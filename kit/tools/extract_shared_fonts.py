#!/usr/bin/env python3
"""Extract the six system shared fonts (BFTTF) from your console's firmware.

Why this is needed: a game card image (XCI) carries the system update the game needs, shared fonts
included. An NSP does not - so if your base game is an NSP, the build cannot get the fonts from it
and you must take them from your console's firmware dump instead.

    python3 extract_shared_fonts.py --firmware <firmware-nca-dir> --keys <prod.keys> --output <dir>

Run scan_firmware.py first to check that the firmware dump holds the font data NCAs
(titles 0100000000000810 .. 0100000000000814).

It is self-contained: it decrypts the NCA headers, verifies the FS header hash and all six IVFC
levels of each NCA it reads, and checks every BFTTF header before writing anything. The fonts stay
in the BFTTF form the hardware places in shared memory; only local copies are written, never printed.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# nn::pl::SharedFontType -> (system data title, BFTTF file name)
FONTS = [
    (0, 'standard', '0100000000000811', 'nintendo_udsg-r_std_003.bfttf'),
    (1, 'chinese-simplified', '0100000000000814', 'nintendo_udsg-r_org_zh-cn_003.bfttf'),
    (2, 'chinese-simplified-extension', '0100000000000814', 'nintendo_udsg-r_ext_zh-cn_003.bfttf'),
    (3, 'chinese-traditional', '0100000000000813', 'nintendo_udjxh-db_zh-tw_003.bfttf'),
    (4, 'korean', '0100000000000812', 'nintendo_udsg-r_ko_003.bfttf'),
    (5, 'nintendo-extension', '0100000000000810', 'nintendo_ext_003.bfttf'),
]
BFTTF_DECODED_MAGIC = 0x7f9a0218


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_keys(path):
    keys = {}
    for line in Path(path).read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if '=' in line:
            name, value = line.split('=', 1)
            try:
                keys[name.strip().lower()] = bytes.fromhex(value.strip())
            except ValueError:
                raise ValueError(f'Invalid key encoding: {line}') from None
    return keys


def aes_ecb_decrypt(key, data):
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return dec.update(data) + dec.finalize()


def nca_header(f, header_key, offset=0):
    """The decrypted 3 KiB NCA header at offset."""
    f.seek(offset)
    raw = f.read(0xc00)
    out = b''
    for i in range(6):
        dec = Cipher(algorithms.AES(header_key), modes.XTS(i.to_bytes(16, 'big'))).decryptor()
        out += dec.update(raw[i * 512:(i + 1) * 512]) + dec.finalize()
    return out


def nca_ctr_key(hdr, keys):
    """The AES-CTR key of an NCA's body, from the key area in the header."""
    generation = max(max(hdr[0x206], hdr[0x220]) - 1, 0)
    require(hdr[0x207] < 3, 'Unsupported NCA key area')
    area = ('application', 'ocean', 'system')[hdr[0x207]]
    keyname = f'key_area_key_{area}_{generation:02x}'
    require(keyname in keys, f'Missing {keyname} in prod.keys')
    return aes_ecb_decrypt(keys[keyname], hdr[0x300:0x340])[32:48]


def nca_romfs(f, offset, length, keys, image_path):
    """Write the verified RomFS image of a data NCA to image_path."""
    hdr = nca_header(f, keys['header_key'], offset)
    require(hdr[0x200:0x204] == b'NCA3', 'Unsupported NCA')
    ctr_key = nca_ctr_key(hdr, keys)
    for i in range(4):
        start, end = struct.unpack_from('<II', hdr, 0x240 + i * 16)
        if not start:
            continue
        fs = hdr[0x400 + 512 * i:0x600 + 512 * i]
        require(hashlib.sha256(fs).digest() == hdr[0x280 + 32 * i:0x2a0 + 32 * i], 'FS header hash')
        if fs[2:5] != bytes([0, 3, 3]):
            continue
        require(fs[8:12] == b'IVFC' and struct.unpack_from('<III', fs, 12) == (0x20000, 32, 7),
                'Unsupported IVFC layout')
        levels = [struct.unpack_from('<QQII', fs, 0x18 + j * 24) for j in range(6)]

        def read(relative, size):
            require(0 <= relative <= relative + size <= (end - start) * 512, 'Section bounds')
            absolute = start * 512 + relative
            aligned = absolute & ~15
            skip = absolute - aligned
            iv = fs[0x140:0x148][::-1] + (aligned // 16).to_bytes(8, 'big')
            dec = Cipher(algorithms.AES(ctr_key), modes.CTR(iv)).decryptor()
            f.seek(offset + aligned)
            data = dec.update(f.read(size + skip)) + dec.finalize()
            return data[skip:]

        parent = fs[0xc8:0xe8]
        image = bytearray()
        for level, (lev_offset, lev_size, power, reserved) in enumerate(levels):
            require(12 <= power <= 24 and reserved == 0, 'IVFC block size')
            block = 1 << power
            data = read(lev_offset, lev_size)
            for index, j in enumerate(range(0, len(data), block)):
                payload = data[j:j + block]
                require(hashlib.sha256(payload + bytes(block - len(payload))).digest()
                        == parent[index * 32:index * 32 + 32], f'IVFC level {level} block {index}')
            parent = data
            if level == 5:
                image = data
        image_path.write_bytes(image)
        return
    raise ValueError('No RomFS in the NCA')


def index_romfs(path):
    """(path -> offset, size) of every file in a RomFS image."""
    with path.open('rb') as f:
        h = struct.unpack('<10Q', f.read(80))
        require(h[0] == 80, 'RomFS header')
        length = path.stat().st_size

        def read_at(off, size):
            f.seek(off)
            return f.read(size)

        for off, size in [(h[1], h[2]), (h[3], h[4]), (h[5], h[6]), (h[7], h[8])]:
            require(off + size <= length, 'RomFS table bounds')
        dirs = read_at(h[3], h[4])
        entries = read_at(h[7], h[8])
        files = {}
        todo = [(0, '')]
        while todo:
            off, parent = todo.pop()
            p, sibling, child, file, hash_next, n = struct.unpack_from('<6I', dirs, off)
            part = dirs[off + 24:off + 24 + n].decode('utf-8')
            prefix = parent + part + '/' if part else parent
            if sibling != 0xffffffff:
                todo.append((sibling, parent))
            if child != 0xffffffff:
                todo.append((child, prefix))
            while file != 0xffffffff:
                p, next_file, data, size, hash_next, n = struct.unpack_from('<IIQQII', entries, file)
                name = entries[file + 32:file + 32 + n].decode('utf-8')
                files[prefix + name] = (h[9] + data, size)
                file = next_file
        return files


def bfttf_size(data):
    """BFTTF: big-endian words XORed with key = word0 ^ 0x7f9a0218; word1 = font size."""
    magic, size = struct.unpack_from('>II', data, 0)
    key = magic ^ BFTTF_DECODED_MAGIC
    decoded = size ^ key
    require(decoded + 8 == len(data), 'BFTTF size does not match file')
    first = struct.unpack_from('>I', data, 8)[0] ^ key
    require(first in (0x00010000, 0x4f54544f), 'BFTTF payload is not a TrueType/OpenType font')
    return decoded


def firmware_data_ncas(folder, keys):
    """The data NCA of each shared-font title in an unpacked firmware directory."""
    wanted = {title for _, _, title, _ in FONTS}
    found = {}
    for path in sorted(folder.rglob('*')):
        if path.is_dir():
            path = path / '00'
        if not path.is_file() or (path.name != '00' and path.suffix.lower() != '.nca'):
            continue
        with path.open('rb') as f:
            hdr = nca_header(f, keys['header_key'])
        require(hdr[0x200:0x204] == b'NCA3', 'Invalid firmware NCA header (check prod.keys)')
        title = f'{struct.unpack_from("<Q", hdr, 0x210)[0]:016x}'
        if hdr[0x205] == 4 and title in wanted:
            require(title not in found, f'Duplicate shared-font title {title} in firmware')
            found[title] = path
    require(wanted <= found.keys(),
            'Firmware is missing shared-font data NCAs: ' + ', '.join(sorted(wanted - found.keys())))
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--firmware', type=Path, help='unpacked firmware NCA directory')
    ap.add_argument('--keys', type=Path, required=True, help='your prod.keys')
    ap.add_argument('--output', type=Path, default=Path('shared-fonts'), help='where to write the fonts')
    args = ap.parse_args()
    if not args.firmware:
        raise SystemExit('--firmware is required (an NSP base game has no system fonts)')
    if args.output.exists():
        raise SystemExit(f'{args.output} already exists; remove it or choose another name')

    keys = load_keys(args.keys)
    ncas = firmware_data_ncas(args.firmware, keys)
    args.output.mkdir(parents=True)
    images = {}
    report = []
    for kind, name, title, filename in FONTS:
        if title not in images:
            image_path = args.output / f'{title}.romfs'
            with ncas[title].open('rb') as f:
                nca_romfs(f, 0, ncas[title].stat().st_size, keys, image_path)
            images[title] = (image_path, index_romfs(image_path))
        image_path, entries = images[title]
        require(filename in entries, f'{filename} missing in {title}')
        offset, size = entries[filename]
        with image_path.open('rb') as f:
            f.seek(offset)
            data = f.read(size)
        font_bytes = bfttf_size(data)
        (args.output / f'{kind}-{name}.bfttf').write_bytes(data)
        report.append(dict(type=kind, name=name, title_id=title, file=filename, bfttf_bytes=len(data),
                           font_bytes=font_bytes, sha256=hashlib.sha256(data).hexdigest()))
    for image_path, _ in images.values():
        image_path.unlink()
    manifest = dict(status='pass',
                    integrity='NCA FS header and six IVFC levels verified per NCA; BFTTF header decodes to an sfnt '
                              'font; RSA not checked',
                    fonts=report)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    print(f'\n6 shared fonts written to {args.output}:')
    for r in report:
        print(f'  {r["type"]}-{r["name"]}.bfttf  {r["font_bytes"]} bytes  {r["sha256"][:16]}...')
    print('\nGive this folder to the import tool with --shared-fonts <folder>')


if __name__ == '__main__':
    try:
        main()
    except ValueError as e:
        raise SystemExit(f'error: {e}') from None
