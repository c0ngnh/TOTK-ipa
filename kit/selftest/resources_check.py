#!/usr/bin/env python3
"""The game resources beside the app: the RomFS image in parts and the startup shaders as a packed stream.

Checks that the parts add up to the image and are read back in the order the runtime reads them
(runtime/romfs.c open_chunks), that the packed stream is the one the app unpacks (ios/Sources/main.m seed_unpack), and
that the markers the app reads name what is there.

    usage: resources_check.py"""
import hashlib, struct, sys, tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / 'tools'))
import game_resources


def read_parts(folder):
    """The image the runtime reads: the parts in order, as one stream."""
    out = b''
    for part in sorted(folder.glob('romfs.bin.*')):
        out += part.read_bytes()
    return out


def unpack_seed(folder):
    """The stream the app unpacks (ios/Sources/main.m seed_unpack): "TOTKPACK1", then per file a u16 name length, the
    name, a u64 size and the bytes, a zero name length last."""
    data = b''
    for part in sorted(folder.glob('shader-seed-*.pack.*')):
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


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        image = root / 'romfs.bin'
        body = bytes(range(256)) * 4096 + b'the end'
        image.write_bytes(body)
        seed = root / 'seed'
        seed.mkdir()
        (seed / 'seed-manifest.json').write_text('{"chain":"c"}')
        (seed / 'shader_map.tsv').write_text('# TOTK control-code-sha256-v1\n')
        (seed / 'pso_title.tsv').write_text('# list\n')
        (seed / 'a.metal').write_text('kernel void k() {}')
        out = root / 'resources'
        parts = game_resources.write_all(image, seed, out)
        assert parts == 1, parts
        # The image: the parts are read back in order and are the image itself.
        assert read_parts(out) == body, 'the parts are not the image'
        assert (out / 'romfs.sha256').read_text().strip() == hashlib.sha256(body).hexdigest()
        # The shaders: the pack unpacks to the seed's files.
        files = unpack_seed(out)
        assert set(files) == {'seed-manifest.json', 'shader_map.tsv', 'pso_title.tsv', 'a.metal'}, sorted(files)
        assert files['a.metal'] == b'kernel void k() {}'
        assert files['pso_title.tsv'] == b'# list\n'
        # The marker the app reads: the folder name and the fingerprint (64 hex characters).
        mark = (out / 'shader-seed.txt').read_text().splitlines()
        assert len(mark) == 2 and len(mark[1]) == 64, mark
        assert mark[0].startswith('shader-seed-'), mark
        assert (out / f'{mark[0]}.pack.000').is_file(), 'the pack the marker names is not there'
        # A second run over the same seed gives the same fingerprint: the phone keeps the content it already has.
        again = root / 'again'
        game_resources.write_all(image, seed, again)
        assert (again / 'shader-seed.txt').read_text() == (out / 'shader-seed.txt').read_text()
        print(f'resources checked: {parts} image part(s), {len(files)} shader file(s) in the pack')


if __name__ == '__main__':
    main()
