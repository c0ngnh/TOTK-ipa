#!/usr/bin/env python3
"""Check that the icon extractor runs in the build's venv, and not in the import tool's own Python.

The app's home screen icon comes from the player's own dump: the control NCA of the base game carries
icon_<language>.dat, and kit/tools/extract_app_icon_ios.py turns it into the PNGs the Info.plist names.
That extractor reads the card through MacNativeGames' own NSP reader (extract_exefs.py, extract_romfs.py,
extract_shared_fonts.py), and those import the `cryptography` package to decrypt the NCA.

The `cryptography` package is installed into the build's venv (work/venv, reached as tree/.venv), which is
where every other upstream script runs. The import tool's own Python does not have it — and on Windows it
cannot have it: the installer ships a private Python with its site-packages stripped, so `sys.executable`
there has no third-party package at all. Running the extractor with sys.executable therefore dies with

    ModuleNotFoundError: No module named 'cryptography'

and the build stops at the last step with "the app icon could not be made". The failure is invisible on
Linux and Mac, where the player's Python may happen to have the package installed, so it reaches the
player's Windows machine and nowhere else.

This check does two things:

  1. It reads the import tool and asserts the extractor is started with the venv's Python.
  2. It runs the extractor in a venv that has no `cryptography` and asserts it fails with that very
     ModuleNotFoundError, and in a venv that has it and asserts it gets past the imports. That proves
     the interpreter is what decides, so the check would catch a real regression rather than only the
     shape of the source.

    usage: icon_venv_check.py [MacNativeGames checkout]
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
IMPORT_TOOL = KIT / 'totk_import.py'
EXTRACTOR = KIT / 'tools/extract_app_icon_ios.py'

# The upstream script the extractor reads the card through, and the package it needs.
UPSTREAM_READER = 'extract_exefs.py'
NEEDED_PACKAGE = 'cryptography'


def check_source():
    """The import tool must start the extractor with the venv's Python."""
    text = IMPORT_TOOL.read_text(encoding='utf-8')
    # The line the extractor is started on.
    match = re.search(r'subprocess\.run\(\[([^\]]*extract_app_icon_ios\.py[^\]]*)\]', text, re.S)
    if not match:
        raise SystemExit(f'{IMPORT_TOOL.name} does not start the icon extractor at all')
    command = match.group(1)
    if 'sys.executable' in command:
        raise SystemExit(
            f'{IMPORT_TOOL.name} starts the icon extractor with sys.executable, which has no {NEEDED_PACKAGE} '
            f'package: the build dies with "No module named \'{NEEDED_PACKAGE}\'". Use the venv\'s Python '
            f'(tree/.venv/bin/python), which is where every other upstream script runs.')
    if ".venv/bin/python" not in command:
        raise SystemExit(
            f'{IMPORT_TOOL.name} starts the icon extractor with something that is not the venv\'s Python: {command.strip()}')


def upstream_reader(mng):
    """The upstream NSP reader the extractor imports, and whether it needs the package."""
    for base in (mng / 'games/totk/scripts', mng / 'MacNativeGames/games/totk/scripts', mng / 'scripts'):
        reader = base / UPSTREAM_READER
        if reader.is_file():
            return reader
    return None


def run_extractor(python, tree):
    """The extractor's own answer when it is started with this Python."""
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run([str(python), str(EXTRACTOR), str(Path(tmp) / 'game.nsp'),
                               '--keys', str(Path(tmp) / 'prod.keys'),
                               '--output', str(Path(tmp) / 'out'),
                               '--tree', str(tree)],
                              capture_output=True, text=True)
    return proc.stdout + proc.stderr


def scripts_tree(mng, tmp):
    """A work tree holding the upstream scripts, the way the build copies them."""
    tree = Path(tmp) / 'tree'
    src = mng / 'games/totk/scripts'
    if not src.is_dir():
        src = mng / 'MacNativeGames/games/totk/scripts'
    (tree / 'scripts').mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_file() and item.suffix == '.py':
            (tree / 'scripts' / item.name).write_bytes(item.read_bytes())
    return tree


def check_behaviour(mng):
    """The interpreter decides: without the package the extractor dies, with it the extractor gets on."""
    reader = upstream_reader(mng)
    if reader is None:
        print(f'note: {UPSTREAM_READER} was not found under {mng}; the behaviour was not checked')
        return
    text = reader.read_text(encoding='utf-8')
    if f'import {NEEDED_PACKAGE}' not in text and f'from {NEEDED_PACKAGE}' not in text:
        raise SystemExit(f'{reader} does not need {NEEDED_PACKAGE}; the check no longer proves anything')

    with tempfile.TemporaryDirectory() as tmp:
        tree = scripts_tree(mng, tmp)
        # A venv without the package: the extractor must fail with that very ModuleNotFoundError.
        bare = Path(tmp) / 'bare'
        subprocess.run([sys.executable, '-m', 'venv', str(bare)], check=True, capture_output=True)
        out = run_extractor(bare / 'bin/python', tree)
        if f"No module named '{NEEDED_PACKAGE}'" not in out:
            raise SystemExit(f'the extractor did not fail without {NEEDED_PACKAGE}, so the check proves nothing:\n{out}')

        # A venv with the package: the extractor must get past the imports and reach the game files.
        full = Path(tmp) / 'full'
        subprocess.run([sys.executable, '-m', 'venv', str(full)], check=True, capture_output=True)
        subprocess.run([str(full / 'bin/python'), '-m', 'pip', 'install', '-q', NEEDED_PACKAGE],
                       check=True, capture_output=True)
        out = run_extractor(full / 'bin/python', tree)
        if f"No module named '{NEEDED_PACKAGE}'" in out:
            raise SystemExit(f'the extractor still failed without {NEEDED_PACKAGE}, though it was installed:\n{out}')
        if 'FileNotFoundError' not in out:
            raise SystemExit(f'the extractor did not get as far as reading the game files:\n{out}')


def main():
    check_source()
    mng = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else KIT.parent / 'MacNativeGames'
    if mng.is_dir():
        check_behaviour(mng)
    else:
        print(f'note: {mng} is not here; the behaviour was not checked')
    print(f'the icon extractor runs in the build\'s venv, so it has the {NEEDED_PACKAGE} package')


if __name__ == '__main__':
    main()
