#!/usr/bin/env python3
"""The home screen icon of the app: the game's own, and never the other game's.

The app's icon has two homes, and both must carry the same game:

  - the asset catalog the shell is built with (Gen/Assets.xcassets -> Assets.car). iOS reads it because the
    Info.plist says CFBundleIconName = AppIcon, and that is the icon the home screen shows.
  - the Icons folder the import tool writes from the player's own dump (kit/tools/extract_app_icon_ios.py): the
    control NCA of the base game carries icon_<language>.dat, a JPEG, which becomes the PNGs the Info.plist's
    CFBundleIconFiles names.

The two kits are separate projects for two different games, but they started from one upstream, and a copy of
the icon file is easy to make by accident: the shell then shows the other game's icon while the game inside is
the right one. So the icon's identity is checked here, by its content, not by the file name:

    app_icon.py <icon.png> --game botw190
    app_icon.py <icon.png> --expect <sha256>
    app_icon.py --selftest
"""
import argparse
import hashlib
import sys
from pathlib import Path

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


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
                         f"Take the icon from this game's own base game (kit/tools/extract_app_icon_ios.py).")
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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('icon', nargs='?', type=Path, help='the icon file to check')
    ap.add_argument('--game', help='the game the icon must belong to (default: this kit\'s game)')
    ap.add_argument('--expect', help='the sha256 the icon must have')
    ap.add_argument('--selftest', action='store_true', help='check the guard itself')
    a = ap.parse_args()
    if a.selftest:
        return 0 if selftest() else 1
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
