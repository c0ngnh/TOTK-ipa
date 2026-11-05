#!/usr/bin/env python3
"""The home screen icon of the app: the game's own, and never the other game's.

The app's icon has two homes, and both must carry the same game:

  - the asset catalog the shell is built with (Gen/Assets.xcassets -> Assets.car). iOS reads it because the
    Info.plist says CFBundleIconName = AppIcon, and that is the icon the home screen shows.
  - the Icons folder the import tool writes (kit/tools/app_icon.py): the same PNGs under the names the Info.plist's
    CFBundleIconFiles names, so an iOS that reads the older form finds them too.

The icon itself is the kit's own: kit/shim/AppIcon-1024.png holds the game's real icon, the one from its base game's
control NCA (the icon_<language>.dat JPEG), and its sha256 is the one below. The import tool copies it into the app
and scales it to the sizes the Info.plist names, with kit/tools/png_image.py. So the player's machine needs no image
tool for it: not ImageMagick, not ffmpeg, and not Pillow either. That matters on Windows, where none of them is
installed and `convert` is the system's own FAT-to-NTFS converter rather than ImageMagick.

The two kits are separate projects for two different games, but they started from one upstream, and a copy of
the icon file is easy to make by accident: the shell then shows the other game's icon while the game inside is
the right one. So the icon's identity is checked here, by its content, not by the file name:

    app_icon.py <icon.png> --game botw190
    app_icon.py <icon.png> --expect <sha256>
    app_icon.py --selftest
    app_icon.py --install <folder>     # the PNGs the Info.plist names, in the folder
"""
import argparse
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import png_image

# The sha256 of each game's own icon, taken from its base game's control NCA (the icon_<language>.dat JPEG,
# converted to a 1024x1024 PNG). The BOTW kit must carry the BOTW one, the TOTK kit the TOTK one.
GAME_ICONS = {
    'botw190': '30130a3397fe997a3ad7921a617a575622376e6c7c22da07872e6aba35c85259',
    'v143': 'c3d8ead1697a4de0a034a2749a1bf0c246264e8563ab0f942595041c5873cf8d',
}

# Which game each known icon belongs to, so the check can say what it found instead of only that it failed.
ICON_GAMES = {h: g for g, h in GAME_ICONS.items()}
GAME_NAMES = {'botw190': 'Breath of the Wild', 'v143': 'Tears of the Kingdom'}

# The game this kit is for. It is what the shell is built as and what the import tool builds.
THIS_GAME = 'v143'

# The kit's own copy of the icon: the master's 1024x1024 PNG, and the sizes the Info.plist names beside it.
MASTER = Path(__file__).resolve().parent.parent / 'shim' / 'AppIcon-1024.png'

# The PNGs the app's Info.plist names, and the size each one is. AppIcon60x60@3x is the home screen icon
# (60pt at 3x); the two iPad ones are the sizes an older iOS asks for; Icon-1024 is the master itself.
ICON_SIZES = (
    ('AppIcon60x60@3x.png', 180),
    ('AppIcon76x76@2x~ipad.png', 152),
    ('AppIcon83.5x83.5@2x~ipad.png', 167),
    ('Icon-1024.png', 1024),
)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def install(folder, game=THIS_GAME):
    """The app's icon PNGs, written into a folder.

    The master is the kit's own kit/shim/AppIcon-1024.png, whose sha256 is the game's: the icon is checked before it
    is copied, so a kit carrying the other game's icon stops here instead of shipping it.

    The smaller ones are scaled from the master by kit/tools/png_image.py, with the standard library only. The bytes
    depend on nothing but the pixels, so the icon that goes into the app is the same on every machine — which matters,
    because the guard checks a file by its sha256 and an encoder's fingerprint would otherwise decide it.
    """
    folder = Path(folder)
    master = MASTER
    if not master.is_file():
        raise SystemExit(f'the kit is incomplete: the icon is missing: {master}')
    check_icon(master, game)
    width, height, rgb = png_image.read_png(master)
    folder.mkdir(parents=True, exist_ok=True)
    for name, size in ICON_SIZES:
        target = folder / name
        if size == width and height == size:
            shutil.copy2(master, target)
        else:
            png_image.write_png(target, size, size, png_image.resize(width, height, rgb, size, size))
    return folder


def check_icon(path, game):
    """The icon file must be the game's own; say which game's it is when it is not."""
    want = GAME_ICONS.get(game)
    if want is None:
        raise SystemExit(f'unknown game {game!r}; known: {", ".join(sorted(GAME_ICONS))}')
    path = Path(path)
    if not path.is_file():
        raise SystemExit(f'the app icon is missing: {path}')
    got = sha256(path)
    if got == want:
        return got
    other = ICON_GAMES.get(got)
    if other:
        raise SystemExit(f'{path} is the icon of {GAME_NAMES[other]}, not of this game ({game}). '
                         f"Take the icon from this game's own base game and put it at kit/shim/AppIcon-1024.png.")
    raise SystemExit(f'{path} is not the icon of this game ({game}): its sha256 is {got}, expected {want}.')


def selftest():
    """The guard itself: this kit's icon is this game's, and is refused for the other game."""
    ok = True
    icon = Path(__file__).resolve().parent.parent / 'shim' / 'AppIcon-1024.png'
    if not icon.is_file():
        print(f'  [FAIL] the icon is missing: {icon}')
        return False
    try:
        check_icon(icon, THIS_GAME)
        print(f'  [OK] {THIS_GAME}: {icon.name} is this game\'s icon')
    except SystemExit as e:
        ok = False
        print(f'  [FAIL] {THIS_GAME}: {e}')
    for other in GAME_ICONS:
        if other == THIS_GAME:
            continue
        try:
            check_icon(icon, other)
            ok = False
            print(f'  [FAIL] {THIS_GAME}: its own icon was accepted as the {other} icon')
        except SystemExit as e:
            print(f'  [OK] {THIS_GAME}: refused as the {other} icon ({str(e)[:70]}...)')
    return ok


def check_install(tmp):
    """The installed icons: the master keeps its bytes, the others are the right size, and all are this game's.

    The master is copied, so its sha256 is the game's own and the guard passes on the installed file too. That is
    what the import tool checks, so it is checked here: an install that produced a different file would fail the
    player's build at the last step.
    """
    ok = True
    folder = Path(tmp) / 'Icons'
    install(folder, THIS_GAME)
    for name, size in ICON_SIZES:
        path = folder / name
        if not path.is_file():
            print(f'  [FAIL] the icon {name} was not written')
            ok = False
            continue
        width, height, _rgb = png_image.read_png(path)
        if (width, height) != (size, size):
            print(f'  [FAIL] the icon {name} is {width}x{height}, not {size}x{size}')
            ok = False
            continue
        print(f'  [OK] {name}: {width}x{height}')
    try:
        check_icon(folder / 'Icon-1024.png', THIS_GAME)
        print(f'  [OK] {THIS_GAME}: the installed Icon-1024.png is this game\'s icon')
    except SystemExit as e:
        ok = False
        print(f'  [FAIL] {THIS_GAME}: {e}')
    # The other game's icon must be refused, so a kit carrying it cannot install it.
    other = next(g for g in GAME_ICONS if g != THIS_GAME)
    try:
        check_icon(folder / 'Icon-1024.png', other)
        ok = False
        print(f'  [FAIL] {THIS_GAME}: the installed icon was accepted as the {other} icon')
    except SystemExit as e:
        print(f'  [OK] {THIS_GAME}: the installed icon is refused as the {other} icon ({str(e)[:70]}...)')
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('icon', nargs='?', type=Path, help='the icon file to check')
    ap.add_argument('--game', help='the game the icon must belong to (default: this kit\'s game)')
    ap.add_argument('--expect', help='the sha256 the icon must have')
    ap.add_argument('--selftest', action='store_true', help='check the guard itself')
    ap.add_argument('--install', type=Path, metavar='FOLDER',
                    help='write the icon PNGs the Info.plist names into FOLDER')
    a = ap.parse_args()
    if a.selftest:
        return 0 if selftest() else 1
    if a.install:
        folder = install(a.install, a.game or THIS_GAME)
        print(f'the {a.game or THIS_GAME} icon is in {folder}')
        return 0
    if not a.icon:
        raise SystemExit('an icon file is needed, or --selftest')
    if a.expect:
        got = sha256(a.icon)
        if got != a.expect:
            other = ICON_GAMES.get(got)
            what = f'that is the icon of {GAME_NAMES[other]}' if other else 'an unknown icon'
            raise SystemExit(f'{a.icon} is {what}, expected {a.expect}.')
        print(f'{a.icon}: the expected icon')
        return 0
    check_icon(a.icon, a.game or THIS_GAME)
    print(f'{a.icon}: the {(a.game or THIS_GAME)} icon')
    return 0


if __name__ == '__main__':
    sys.exit(main())
