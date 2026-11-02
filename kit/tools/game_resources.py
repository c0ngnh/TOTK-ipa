#!/usr/bin/env python3
"""The game resources beside the app: the RomFS image and the startup shaders, in the layout the phone reads them in.

The app carries neither. The phone keeps them in its own Documents folder, in GameData (ios/Sources/main.m), so a new
build of the app installs in minutes and keeps the resources: the image is copied onto the phone in 1 GiB parts
(romfs.bin.000, romfs.bin.001, ...) because one 17 GB file cannot be copied onto a phone reliably, and the shaders go
as one packed stream (shader-seed-<name>.pack.000, ...) because the seed holds 64,000 small files, which a folder copy
drops halfway. The phone unpacks the shaders on its first start.

    python3.14 game_resources.py --romfs <romfs.bin> --seed <shader-seed folder> --out <folder>

The order matters: the app reads romfs.sha256 as the mark of a finished copy, so it is written last.
"""
import argparse, hashlib
from pathlib import Path

PART = 1 << 30          # the part size: a phone's file copy drops on one file of 17 GB
COPY = 8 << 20          # the copy buffer


def split_image(image, out, say=None):
    """The image in parts of PART bytes, the last one shorter (runtime/romfs.c open_chunks reads them in place)."""
    size = image.stat().st_size
    parts = (size + PART - 1) // PART
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
    for part_file in sorted(out.glob('.pack.*')):
        part_file.rename(out / f'{folder}{part_file.name}')
    (out / 'shader-seed.txt').write_text(f'{folder}\n{fingerprint}\n')
    if say:
        say(f'  the shaders: {len(names)} files in {part + 1} part(s), fingerprint {fingerprint}')
    return fingerprint


def write_all(romfs, seed, out, say=None):
    """The resources folder: the image in parts, the shaders as a pack, and the markers."""
    out.mkdir(parents=True, exist_ok=True)
    parts = split_image(romfs, out, say)
    (out / 'romfs.sha256').write_text(image_sha256(romfs) + '\n')
    if seed:
        pack_seed(seed, out, say)
    return parts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--romfs', type=Path, help='the extracted RomFS image (romfs.bin)')
    ap.add_argument('--seed', type=Path, help='the startup shader seed folder')
    ap.add_argument('--out', type=Path, required=True, help='the folder to write the resources into')
    a = ap.parse_args()
    out = a.out.expanduser().resolve()
    if not a.romfs:
        raise SystemExit('--romfs is needed')
    romfs = a.romfs.expanduser().resolve()
    seed = a.seed.expanduser().resolve() if a.seed else None
    parts = write_all(romfs, seed, out, print)
    print(f'  the image: {parts} part(s)')


if __name__ == '__main__':
    main()
