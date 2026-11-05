#!/usr/bin/env python3
"""Check that the app's icon is the kit's own, and that it needs no image tool to install.

The app's home screen icon is the game's own, and the kit carries it: kit/shim/AppIcon-1024.png is the icon from
the game's base game's control NCA, and its sha256 is the one in kit/tools/app_icon.py's GAME_ICONS. The import
tool writes it into the app (kit/tools/app_icon.py) and scales it to the sizes the Info.plist names, with
kit/tools/png_image.py — the standard library only.

That is deliberate, and it replaces what used to be here. The icon used to be extracted from the player's own dump
(the control NCA's icon_<language>.dat, a JPEG) and converted with an image tool, which needed ImageMagick or
ffmpeg or Pillow. A clean Windows has none of them — and `convert` there is not ImageMagick but the system's own
FAT-to-NTFS converter, which prints "Invalid Parameter - -resize" — so the build died at the last step with "no
image tool for the icon: install ImageMagick or ffmpeg". **The 2026-11-05 failure.**

The icon does not come from the dump, but the game's identity is still enforced: identify_game() refuses a dump of
the other game before the build starts, and the sha256 guard refuses the other game's icon.

This check proves what the player's build depends on:

  1. The kit carries the icon, and it is this game's (checked by its sha256).
  2. Installing it writes the PNGs the Info.plist names, at the right sizes.
  3. The installed master is byte-identical to the kit's, so the guard the import tool runs passes on it.
  4. Nothing in the icon path calls an image tool: no ImageMagick, no ffmpeg, no Pillow. The install must work on a
     machine that has none of them, so the check runs the install with all three hidden from the search path.

    usage: icon_venv_check.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / 'tools'))
import app_icon
import png_image

# The tools the icon path must not need. On a clean Windows none of them is installed, and `convert` is the system's
# own FAT-to-NTFS converter rather than ImageMagick, so calling it is worse than calling nothing.
IMAGE_TOOLS = ('magick', 'convert', 'ffmpeg')

# The package the icon path must not need either: the venv does not have Pillow, and the installer's Python has its
# site-packages stripped, so it could not have it.
PACKAGES = ('PIL',)


def check_no_image_tool():
    """The install must work on a machine with no image tool at all.

    The check runs the install in a subprocess whose PATH holds none of the tools and whose import path hides the
    packages, so a fallback that reached for one of them would fail here rather than on the player's Windows.
    """
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / 'probe.py'
        probe.write_text(
            'import sys\n'
            # Only the kit\'s own tools: no Pillow from anywhere.
            f'sys.path.insert(0, {str(KIT / "tools")!r})\n'
            # Hide any package that happens to be installed.
            'sys.modules["PIL"] = None\n'
            'sys.modules["PIL.Image"] = None\n'
            'import app_icon\n'
            f'folder = app_icon.install({str(Path(tmp) / "Icons")!r}, {app_icon.THIS_GAME!r})\n'
            'print("installed", folder)\n', encoding='utf-8')
        # A PATH with nothing on it: no ImageMagick, no ffmpeg, and no `convert` either.
        env = {'PATH': '', 'SYSTEMROOT': '', 'PYTHONPATH': ''}
        proc = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, env=env)
    out = proc.stdout + proc.stderr
    if proc.returncode:
        raise SystemExit(f'the icon install needs an image tool, so it fails on a clean Windows:\n{out}')
    if 'installed' not in out:
        raise SystemExit(f'the icon install did not finish:\n{out}')
    for tool in IMAGE_TOOLS:
        if tool in out:
            raise SystemExit(f'the icon install called {tool}, which a clean Windows does not have:\n{out}')
    return True


def check_sizes(folder):
    """The installed PNGs: the right names, the right sizes, and this game's icon."""
    problems = []
    for name, size in app_icon.ICON_SIZES:
        path = Path(folder) / name
        if not path.is_file():
            problems.append(f'{name} was not written')
            continue
        width, height, _rgb = png_image.read_png(path)
        if (width, height) != (size, size):
            problems.append(f'{name} is {width}x{height}, not {size}x{size}')
    return problems


def main():
    ok = True
    master = app_icon.MASTER
    if not master.is_file():
        print(f'  [FAIL] the kit does not carry the icon: {master}')
        return 1
    try:
        app_icon.check_icon(master, app_icon.THIS_GAME)
        print(f'  [OK] {app_icon.THIS_GAME}: the kit\'s icon is this game\'s own')
    except SystemExit as e:
        print(f'  [FAIL] {app_icon.THIS_GAME}: {e}')
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / 'Icons'
        app_icon.install(folder, app_icon.THIS_GAME)
        problems = check_sizes(folder)
        if problems:
            ok = False
            for problem in problems:
                print(f'  [FAIL] {problem}')
        else:
            print(f'  [OK] the install wrote the {len(app_icon.ICON_SIZES)} PNGs the Info.plist names')
        # The installed master must be byte-identical to the kit's: the import tool's guard checks it by sha256.
        if (folder / 'Icon-1024.png').read_bytes() != master.read_bytes():
            ok = False
            print('  [FAIL] the installed Icon-1024.png is not the kit\'s own bytes')
        else:
            print('  [OK] the installed Icon-1024.png is the kit\'s own bytes, so the guard passes on it')

    try:
        check_no_image_tool()
        print('  [OK] the install needs no image tool and no Pillow (it works on a clean Windows)')
    except SystemExit as e:
        ok = False
        print(f'  [FAIL] {e}')

    if not ok:
        return 1
    print(f'the app icon is the kit\'s own, and it installs without an image tool')
    return 0


if __name__ == '__main__':
    sys.exit(main())
