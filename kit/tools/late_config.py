#!/usr/bin/env python3
"""The game data folder the app reads at launch (runtime/game_data.c) and the embedded module parts
(ios/tools/gen_embed.py's split).

The app carries no game file: what MacNativeGames' build_ipa.py would compile into the app from the player's files is
read at start from GameData/game-data, the same place upstream's own build writes it:
  - runtime-tables.bin: the module tables of scripts/prepare_runtime.py (analysis/<version>-port/runtime-layout.json),
    in the layout runtime/loader.c load_tables reads (a 64-byte header, one 208-byte record per module, then the
    symbols, relocations and gates, then the symbol names);
  - romfs-config.txt: the RomFS identity of scripts/prepare_romfs_backend.py;
  - shared-fonts.txt: the shared fonts of scripts/prepare_shared_fonts.py;
  - embedded-hashes.txt: gen_embed.py's hashes, which bind the app's contents to the verified rewrites.
"""
import hashlib, json, struct
from pathlib import Path

PG = 0x4000
HEADER, RECORD = 64, 208
MASK = (1 << 64) - 1
NAMES = ('main', 'subsdk0', 'sdk')


def up(n):
    return (n + PG - 1) & ~(PG - 1)


def fixups(path):
    return dict(line[2:].split() for line in Path(path).read_text().splitlines())


def embed_parts(rewritten, name, text):
    """gen_embed.py for one module: the bytes of its sections x0 (__TOTKX), w (__TOTK<name>W) and x1 (__TOTKX) and
    their SHA-256. `text` is the exported x0 (main with the game patches)."""
    data = (Path(rewritten) / f'{name}.patched.bin').read_bytes()
    hdr = fixups(Path(rewritten) / f'{name}.fixups.tsv')
    text_end, patch = int(hdr['TEXT_END'], 16), int(hdr['PATCH_OFF'], 16)
    key = int(hdr['KEY_PAGE_OFF'], 16)
    x0, x1 = up(text_end), up(len(data))
    if len(text) != x0:
        raise ValueError(f'{name}: exported x0 must be exactly {x0:#x} bytes, got {len(text):#x}')
    if patch < 0:
        file_end = int(hdr['FILE_IMAGE_LEN'], 16)
        if file_end % PG or x0 > file_end or key % PG:
            raise ValueError(f'{name}: invalid far patch layout')
        ranges = [(0, x0), (x0, file_end), (file_end, x1)]
    else:
        if patch % PG or x0 > key or key + PG > patch:
            raise ValueError(f'{name}: invalid patch layout')
        ranges = [(0, x0), (x0, patch), (patch, x1)]
    parts = []
    for i, (lo, hi) in enumerate(ranges):
        source = text if i == 0 else data
        chunk = source[lo:min(hi, len(source))] if lo < len(source) else b''
        chunk += bytes(hi - lo - len(chunk))
        parts.append(chunk)
    return parts, [hashlib.sha256(p).hexdigest() for p in parts]


def runtime_tables(modules, version):
    """runtime-tables.bin in the layout runtime/loader.c load_tables reads."""
    strings, arrays, records = bytearray(), bytearray(), []

    def place(blob):
        arrays.extend(bytes(-len(arrays) % 8))
        arrays.extend(blob)
        return HEADER + RECORD * len(modules) + len(arrays) - len(blob)

    for m in modules:
        names = []
        for s in m['symbols']:
            names.append(len(strings))
            strings.extend(s['name'].encode() + b'\0')
        symbols = b''.join(struct.pack('<QQIBBBx', s['value'], s['size'], n, int(s['defined']), s['binding'], s['type'])
                           for s, n in zip(m['symbols'], names))
        relocs = b''.join(struct.pack('<QIIq', r['where'], r['kind'], r['symbol'], r['addend']) for r in m['relocs'])
        gates = b''.join(struct.pack('<QQII', g['ret'], g['original'], int(g['timer']), g['arg']) for g in m['gates'])
        l, t = m['layout'], {int(k): v for k, v in m['tags'].items()}
        records.append(struct.pack('<16s72s13Q4I', m['name'].encode(), m['sha256'].encode(), m['size'], l['TEXT_END'],
                                   l['RO_OFF'], l['DATA_OFF'], l['PATCH_OFF'] % 2**64, l['KEY_PAGE_OFF'], t.get(12, 0),
                                   m['ctor_flag'], t.get(25, 0), t.get(27, 0), place(symbols), place(relocs), place(gates),
                                   len(m['symbols']), len(m['relocs']), len(m['gates']), 0))
    arrays.extend(bytes(-len(arrays) % 8))
    strings_offset = HEADER + RECORD * len(modules) + len(arrays)
    size = strings_offset + len(strings)
    header = struct.pack('<8s8sIIQQQQQ', b'TOTKTAB1', version.encode(), len(modules), 1, modules[0]['probe_plt'],
                         modules[0]['probe_slot'], strings_offset, len(strings), size)
    if len(header) != HEADER or any(len(r) != RECORD for r in records):
        raise ValueError('runtime-tables.bin layout')
    return bytes(header) + b''.join(records) + bytes(arrays) + bytes(strings)


def write(out, layout, romfs_folder, fonts_folder, embed_hashes, version='v143'):
    """Writes the game data folder: runtime-tables.bin, romfs-config.txt, shared-fonts.txt and embedded-hashes.txt.

    layout: runtime-layout.json; romfs_folder: extracted/<version>/romfs (index.json, runtime-index.bin);
    fonts_folder: extracted/firmware/shared-fonts (manifest.json); embed_hashes: {name: [x0, w, x1]}."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    modules = json.loads(Path(layout).read_text())
    if [m['name'] for m in modules] != list(NAMES):
        raise ValueError('module order')
    romfs = json.loads((Path(romfs_folder) / 'index.json').read_text())
    index_sha = hashlib.sha256((Path(romfs_folder) / 'runtime-index.bin').read_bytes()).hexdigest()
    fonts = json.loads((Path(fonts_folder) / 'manifest.json').read_text())
    if fonts.get('status') != 'pass' or [f['type'] for f in fonts['fonts']] != list(range(6)):
        raise ValueError('shared font manifest')

    (out / 'runtime-tables.bin').write_bytes(runtime_tables(modules, version))
    (out / 'romfs-config.txt').write_text(
        f'ROMFS_IMAGE_SIZE {romfs["romfs_size"]}\nROMFS_IMAGE_SHA256 {romfs["romfs_sha256"]}\n'
        f'ROMFS_INDEX_SHA256 {index_sha}\n')

    lines = []
    for f in fonts['fonts']:
        name = f"{f['type']}-{f['name']}.bfttf"
        if (Path(fonts_folder) / name).stat().st_size != f['bfttf_bytes']:
            raise ValueError(f'shared font {name} size')
        lines.append(f'FONT{f["type"]}_FILE {name}\nFONT{f["type"]}_FILE_BYTES {f["bfttf_bytes"]}\n'
                     f'FONT{f["type"]}_FONT_BYTES {f["font_bytes"]}\nFONT{f["type"]}_SHA256 {f["sha256"]}\n')
    (out / 'shared-fonts.txt').write_text(''.join(lines))

    embedded = []
    for name in NAMES:
        x0, w, x1 = embed_hashes[name]
        embedded.append(f'{name}_X0 {x0}\n{name}_W {w}\n{name}_X1 {x1}\n')
    (out / 'embedded-hashes.txt').write_text(''.join(embedded))

    return sum(f.stat().st_size for f in out.iterdir() if f.is_file())
