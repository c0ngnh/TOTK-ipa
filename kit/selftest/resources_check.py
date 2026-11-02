#!/usr/bin/env python3
"""The game resources beside the app: the RomFS image in parts, the startup shaders as a packed stream and the shared
fonts.

Checks that the parts add up to the image and are read back in the order the runtime reads them
(runtime/romfs.c open_chunks), that the packed stream is the one the app unpacks (ios/Sources/main.m seed_unpack), that
the markers the app reads name what is there, and that the shared fonts are the ones the manifest names.

    usage: resources_check.py"""
import hashlib, json, struct, sys, tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / 'tools'))
import game_resources


def read_parts(folder):
    """The image the runtime reads: the parts in order, as one stream. The runtime names them by index
    (romfs.bin.%03u, runtime/romfs.c open_chunks), so they are read in numeric order, not by name."""
    out = b''
    for part in sorted(folder.glob('romfs.bin.*'), key=lambda p: int(p.name.rsplit('.', 1)[1])):
        out += part.read_bytes()
    return out


def unpack_seed(folder):
    """The stream the app unpacks (ios/Sources/main.m seed_unpack): "TOTKPACK1", then per file a u16 name length, the
    name, a u64 size and the bytes, a zero name length last."""
    data = b''
    for part in sorted(folder.glob('shader-seed-*.pack.*'), key=lambda p: int(p.name.rsplit('.', 1)[1])):
        data += part.read_bytes()
    assert data[:9] == b'TOTKPACK1', 'the pack has no magic'
    at, files = 9, {}
    while True:
        (nl,) = struct.unpack_from('<H', data, at)
        at += 2
        if not nl:
            break
        name = data[at:at + nl].decode()
        at += nl
        (size,) = struct.unpack_from('<Q', data, at)
        at += 8
        files[name] = data[at:at + size]
        at += size
    return files


def check_parts():
    """The resources, written and read back: the image in parts and the shaders as a pack."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = root / 'romfs.bin'
        body = bytes(range(256)) * 4096 + b'the end'
        image.write_bytes(body)
        seed = root / 'seed'
        seed.mkdir()
        # The files are written in bytes, not in text: on Windows a text write turns the newline into two characters,
        # and the pack holds the bytes as they are (game_resources.pack_seed reads them raw).
        (seed / 'seed-manifest.json').write_bytes(b'{"chain":"c"}')
        (seed / 'shader_map.tsv').write_bytes(b'# TOTK control-code-sha256-v1\n')
        (seed / 'pso_title.tsv').write_bytes(b'# list\n')
        (seed / 'pso_list.tsv').write_bytes(b'# pipelines\n')
        (seed / 'a.metal').write_bytes(b'kernel void k() {}')
        out = root / 'resources'
        parts = game_resources.write_all(image, seed, out)
        assert parts == 1, parts
        # The image: the parts are read back in order and are the image itself.
        assert read_parts(out) == body, 'the parts are not the image'
        assert (out / 'romfs.sha256').read_text().strip() == hashlib.sha256(body).hexdigest()
        # The shaders: the pack unpacks to the seed's files.
        files = unpack_seed(out)
        assert set(files) == {'seed-manifest.json', 'shader_map.tsv', 'pso_title.tsv', 'pso_list.tsv', 'a.metal'}, sorted(files)
        assert files['a.metal'] == b'kernel void k() {}'
        assert files['pso_title.tsv'] == b'# list\n'
        # The pipelines list: the runtime reads it beside the shader map (nvn_mtl.m warm_start).
        assert files['pso_list.tsv'] == b'# pipelines\n'
        # The marker the app reads: the folder name and the fingerprint (64 hex characters).
        mark = (out / 'shader-seed.txt').read_text().splitlines()
        assert len(mark) == 2 and len(mark[1]) == 64, mark
        assert mark[0].startswith('shader-seed-'), mark
        assert (out / f'{mark[0]}.pack.000').is_file(), 'the pack the marker names is not there'
        # A second run over the same seed gives the same fingerprint: the phone keeps the content it already has.
        again = root / 'again'
        game_resources.write_all(image, seed, again)
        assert (again / 'shader-seed.txt').read_text() == (out / 'shader-seed.txt').read_text()
        # More than one part: all but the last have the same size (runtime/romfs.c open_chunks). The runtime reads at
        # most 64 parts (MAX_CHUNKS), so the parts are 1 GiB for a 17 GB image.
        many = root / 'many'
        old, game_resources.PART = game_resources.PART, 100000
        try:
            parts = game_resources.split_image(image, many)
        finally:
            game_resources.PART = old
        assert parts > 1, parts
        sizes = [p.stat().st_size for p in sorted(many.glob('romfs.bin.*'), key=lambda p: int(p.name.rsplit('.', 1)[1]))]
        assert sizes[:-1] == [sizes[0]] * (len(sizes) - 1), sizes
        assert sum(sizes) == len(body)
        assert read_parts(many) == body, 'the parts do not rejoin'
        print(f'resources checked: {parts} image part(s), {len(files)} shader file(s) in the pack')


def check_fonts():
    """The shared fonts: the six files the manifest names, each with its size and hash, and the manifest itself."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fonts = root / 'fonts'
        fonts.mkdir()
        rows = []
        for t in range(6):
            data = bytes(range(256)) * (t + 1)
            (fonts / f'{t}-font{t}.bfttf').write_bytes(data)
            rows.append(dict(type=t, name=f'font{t}', bfttf_bytes=len(data), font_bytes=len(data) - 8,
                             sha256=hashlib.sha256(data).hexdigest()))
        (fonts / 'manifest.json').write_text(json.dumps(dict(status='pass', fonts=rows)))
        out = root / 'resources'
        n = game_resources.copy_fonts(fonts, out / 'shared-fonts')
        assert n == 6, n
        for r in rows:
            p = out / 'shared-fonts' / f"{r['type']}-{r['name']}.bfttf"
            data = p.read_bytes()
            assert len(data) == r['bfttf_bytes'], r
            assert hashlib.sha256(data).hexdigest() == r['sha256'], r
        assert json.loads((out / 'shared-fonts' / 'manifest.json').read_text())['status'] == 'pass'
        # A font that does not match the manifest is refused, not copied.
        (fonts / '0-font0.bfttf').write_bytes(b'wrong')
        try:
            game_resources.copy_fonts(fonts, root / 'bad')
        except SystemExit:
            pass
        else:
            raise AssertionError('a font that does not match the manifest was copied')
        print(f'fonts checked: {n} shared font(s), each against the manifest')


def main():
    check_parts()
    check_fonts()


if __name__ == '__main__':
    main()
