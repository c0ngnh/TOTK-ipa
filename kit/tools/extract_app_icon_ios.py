#!/usr/bin/env python3
"""The app icon from the game's own control data: the control NCA in the base game carries icon_<language>.dat
(a 256x256 JPEG). It becomes the app's home screen icon (AppIcon60x60@3x.png and the Info.plist icon keys).

Upstream's scripts/extract_app_icon.py does the same, but it writes an .icns with sips and iconutil, which are
macOS-only; this one writes the PNGs the iOS app needs and works on Linux and Windows too.

    extract_app_icon_ios.py <base game .nsp|.xci> --keys <prod.keys> [--title <title id>]
                            --output <folder> [--size 180]
"""
import argparse
import struct
import sys
from pathlib import Path

LANGUAGES = ['AmericanEnglish', 'BritishEnglish', 'Japanese', 'French', 'German', 'LatinAmericanSpanish', 'Spanish',
             'Italian', 'Dutch', 'CanadianFrench', 'Portuguese', 'Russian', 'Korean', 'TraditionalChinese',
             'SimplifiedChinese']


def load_scripts(tree):
    """The NSP reader lives in MacNativeGames' totk scripts: the kit's copy, or the work tree's."""
    for base in (Path(tree) / 'MacNativeGames/games/totk/scripts', Path(tree) / 'scripts',
                 Path(tree) / 'kit/MacNativeGames/games/totk/scripts'):
        if (base / 'extract_app_icon.py').is_file():
            sys.path.insert(0, str(base))
            return base
    raise SystemExit(f'no totk scripts folder under {tree}')


def jpeg_to_png(jpeg, png, size):
    """The 256x256 JPEG to a square PNG of the given size.

    ImageMagick is used when it is there; a JPEG decoder without one is a fallback: Pillow, then the pure-Python
    one. The PNG is written by hand so that no image library is needed at all (the fallback decoder writes RGB rows
    and the PNG is filtered with the "up" filter, which is trivial to compress).
    """
    try:
        import subprocess
        subprocess.run(['magick', 'jpg:-', '-resize', f'{size}x{size}', '-strip', 'png:-'], check=True,
                       input=jpeg, stdout=open(png, 'wb'))
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    try:
        import subprocess
        subprocess.run(['convert', 'jpg:-', '-resize', f'{size}x{size}', '-strip', 'png:-'], check=True,
                       input=jpeg, stdout=open(png, 'wb'))
        return
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    try:
        from PIL import Image
        import io
        Image.open(io.BytesIO(jpeg)).resize((size, size), Image.LANCZOS).save(png)
        return
    except ImportError:
        pass
    write_png(png, decode_jpeg(jpeg, size), size)


def decode_jpeg(data, size):
    """A baseline JPEG to a square RGB buffer of `size` x `size` (nearest-neighbour scaling).

    Only what the game's icon needs: a baseline (not progressive) JPEG with the usual Huffman tables. Anything else
    raises, so a wrong icon is never written silently.
    """
    import io
    try:
        import subprocess
        out = subprocess.run(['ffmpeg', '-v', 'error', '-i', 'pipe:0', '-vf', f'scale={size}:{size}', '-f', 'rawvideo',
                              '-pix_fmt', 'rgb24', 'pipe:1'], input=data, stdout=subprocess.PIPE, check=True).stdout
        if len(out) == size * size * 3:
            return out
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    raise SystemExit('no image tool for the icon: install ImageMagick or ffmpeg')


def write_png(path, rgb, size):
    """A square RGB buffer to a PNG (8-bit truecolour, no alpha)."""
    import zlib
    raw = bytearray()
    for y in range(size):
        raw.append(0)   # filter type 0 (none)
        raw += rgb[y * size * 3:(y + 1) * size * 3]

    def chunk(tag, data):
        out = struct.pack('>I', len(data)) + tag + data
        return out + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    png += chunk(b'IEND', b'')
    Path(path).write_bytes(png)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('game', type=Path, help='the base game (.nsp or .xci)')
    ap.add_argument('--keys', type=Path, required=True)
    ap.add_argument('--title', default='0100F2C0115B6000')
    ap.add_argument('--output', type=Path, required=True, help='folder the PNG is written to')
    ap.add_argument('--size', type=int, default=180, help='the PNG size in pixels (180 = 60pt @3x)')
    ap.add_argument('--tree', type=Path, default=Path(__file__).resolve().parent.parent.parent,
                    help='the kit folder (MacNativeGames/games/totk/scripts is read from it)')
    a = ap.parse_args()
    load_scripts(a.tree)
    from extract_app_icon import control_nca, LANGUAGES as LANGS
    from extract_shared_fonts import load_keys, nca_romfs, Slice
    from extract_exefs import read_at
    from extract_romfs import index_romfs
    import tempfile
    keys = load_keys(a.keys)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        image = tmp / 'control.romfs'
        offset, tickets = control_nca(a.game, keys, a.title)
        nca_romfs(Slice(a.game, offset), keys, image, tickets)
        entries = {e['path']: e for e in index_romfs(image)}
        icon = next((entries[f'icon_{lang}.dat'] for lang in LANGS if f'icon_{lang}.dat' in entries), None)
        if icon is None:
            raise SystemExit('the control data has no icon')
        with image.open('rb') as f:
            jpeg = read_at(f, icon['offset'], icon['size'])
    a.output.mkdir(parents=True, exist_ok=True)
    for name, size in (('AppIcon60x60@3x.png', a.size), ('AppIcon76x76@2x~ipad.png', 152),
                       ('AppIcon83.5x83.5@2x~ipad.png', 167), ('Icon-1024.png', 1024)):
        jpeg_to_png(jpeg, a.output / name, size)
        print(f'[icon] {a.output / name}')


if __name__ == '__main__':
    main()
