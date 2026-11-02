#!/usr/bin/env python3
"""The game resources beside the app: the RomFS image and the startup shaders, in the layout the phone reads them in.

The app carries neither. The phone keeps them in its own Documents folder, in GameData (ios/Sources/main.m), so a new
build of the app installs in minutes and keeps the resources: the image is copied onto the phone in 1 GiB parts
(romfs.bin.000, romfs.bin.001, ...) because one 17 GB file cannot be copied onto a phone reliably, and the shaders go
as one packed stream (shader-seed-<name>.pack.000, ...) because the seed holds 64,000 small files, which a folder copy
drops halfway. The phone unpacks the shaders on its first start.

    python3.14 game_resources.py --romfs <romfs.bin> --seed <shader-seed folder> --out <folder>

The order matters: the app reads romfs.sha256 as the mark of a finished copy, so it is written last.

The shared fonts (the six .bfttf files) are in the app as well: they come from the console's firmware, they never
change, and the game needs them for its text. They are written here too, so the resources folder is the whole game in
one place: the app prefers this copy when the phone holds it (kit/shim/apply_patches.py's patch of ios/Sources/main.m).
"""
import argparse, hashlib, json
from pathlib import Path

PART = 1 << 30          # the part size: a phone's file copy drops on one file of 17 GB
COPY = 8 << 20          # the copy buffer


def split_image(image, out, say=None):
    """The image in parts of PART bytes, the last one shorter (runtime/romfs.c open_chunks reads them in place).

    The runtime reads at most 64 parts (MAX_CHUNKS), so the part size has to be large enough: a 17 GB image in 1 GiB
    parts is 17 of them."""
    size = image.stat().st_size
    parts = (size + PART - 1) // PART
    if parts > 64:
        raise SystemExit(f'{image}: {size / 2**30:.0f} GiB would need {parts} parts of {PART / 2**30:.0f} GiB; the app '
                         'reads at most 64')
    out.mkdir(parents=True, exist_ok=True)
    with image.open('rb') as src:
        for i in range(parts):
            path = out / f'romfs.bin.{i:03d}'
            left = min(PART, size - i * PART)
            with path.open('wb') as dst:
                while left:
                    chunk = src.read(min(COPY, left))
                    if not chunk:
                        raise SystemExit(f'{image}: the image ended early')
                    dst.write(chunk)
                    left -= len(chunk)
            if say:
                say(f'  romfs.bin.{i:03d}: {path.stat().st_size / 2**30:.2f} GiB')
    return parts


def image_sha256(image):
    digest = hashlib.sha256()
    with image.open('rb') as src:
        while True:
            chunk = src.read(COPY)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def pack_seed(seed, out, say=None):
    """The seed's files as one stream in parts of PART bytes, and the marker the app reads.

    The stream: "TOTKPACK1", then per file a u16 name length, the name, a u64 size and the bytes, a zero name length
    last (ios/Sources/main.m seed_unpack reads it back). The fingerprint is the hash of the stream's own bytes: it says
    whether the phone already holds this content, so an unchanged seed is not copied again."""
    names = sorted(p.name for p in seed.iterdir() if p.is_file())
    digest = hashlib.sha256()
    part, handle, written = 0, None, 0

    def roll():
        nonlocal part, handle, written
        if handle:
            handle.close()
            part += 1
        handle = (out / f'.pack.{part:03d}').open('wb')
        written = 0

    def write(data):
        nonlocal written
        digest.update(data)
        while data:
            if written >= PART:
                roll()
            take = min(len(data), PART - written)
            handle.write(data[:take])
            written += take
            data = data[take:]

    roll()
    write(b'TOTKPACK1')
    for name in names:
        raw = name.encode()
        write(len(raw).to_bytes(2, 'little') + raw + (seed / name).stat().st_size.to_bytes(8, 'little'))
        with (seed / name).open('rb') as src:
            while True:
                chunk = src.read(COPY)
                if not chunk:
                    break
                write(chunk)
    write((0).to_bytes(2, 'little'))
    handle.close()
    fingerprint = digest.hexdigest()
    folder = f'shader-seed-{fingerprint[:12]}'
    for part_file in sorted(out.glob('.pack.*'), key=lambda p: int(p.name.rsplit('.', 1)[1])):
        part_file.rename(out / f'{folder}{part_file.name}')
    (out / 'shader-seed.txt').write_bytes(f'{folder}\n{fingerprint}\n'.encode())
    if say:
        say(f'  the shaders: {len(names)} files in {part + 1} part(s), fingerprint {fingerprint}')
    return fingerprint


def copy_fonts(fonts, out, say=None):
    """The six shared fonts into the resources folder.

    The app carries them too (they never change), so this copy is what a player who keeps the game outside the app
    has in one place; the app prefers the phone's copy when it holds all six. The names and the hashes are the
    manifest's: the runtime checks each file against GameData/game-data/shared-fonts.txt when it loads them.
    """
    fonts = Path(fonts)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((fonts / 'manifest.json').read_text())
    if manifest.get('status') != 'pass':
        raise SystemExit(f'{fonts}: the shared font manifest is not a pass')
    for f in manifest['fonts']:
        name = f"{f['type']}-{f['name']}.bfttf"
        src = fonts / name
        if not src.is_file():
            raise SystemExit(f'{fonts}: {name} is missing')
        data = src.read_bytes()
        if len(data) != f['bfttf_bytes'] or hashlib.sha256(data).hexdigest() != f['sha256']:
            raise SystemExit(f'{name}: the shared font does not match the manifest')
        (out / name).write_bytes(data)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if say:
        say(f'  the shared fonts: {len(manifest["fonts"])} fonts ({sum(f["bfttf_bytes"] for f in manifest["fonts"]) / 1048576:.0f} MB)')
    return len(manifest['fonts'])


def write_all(romfs, seed, out, say=None, fonts=None):
    """The resources folder: the image in parts, the shaders as a pack, the shared fonts, and the markers."""
    out.mkdir(parents=True, exist_ok=True)
    parts = split_image(romfs, out, say)
    (out / 'romfs.sha256').write_bytes((image_sha256(romfs) + '\n').encode())
    if seed:
        pack_seed(seed, out, say)
    if fonts:
        copy_fonts(fonts, out / 'shared-fonts', say)
    return parts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--romfs', type=Path, help='the extracted RomFS image (romfs.bin)')
    ap.add_argument('--seed', type=Path, help='the startup shader seed folder')
    ap.add_argument('--fonts', type=Path, help='the shared fonts folder (the six .bfttf files and their manifest)')
    ap.add_argument('--out', type=Path, required=True, help='the folder to write the resources into')
    a = ap.parse_args()
    out = a.out.expanduser().resolve()
    if not a.romfs:
        raise SystemExit('--romfs is needed')
    romfs = a.romfs.expanduser().resolve()
    seed = a.seed.expanduser().resolve() if a.seed else None
    fonts = a.fonts.expanduser().resolve() if a.fonts else None
    parts = write_all(romfs, seed, out, print, fonts)
    print(f'  the image: {parts} part(s)')


if __name__ == '__main__':
    main()
