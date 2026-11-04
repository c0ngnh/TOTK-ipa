#!/usr/bin/env python3
"""Check that a kit folder holds everything the import tool loads while it builds.

The workflow assembles the kit from pieces: the import tool, the game-file scripts (kit/tools), the kit's own fix
to the upstream build scripts (kit/shim/patch_scripts.py), the app shell, the built tools and the MacNativeGames
sources. The import tool loads some of them by path while it runs — kit/shim/patch_scripts.py is read when the
build starts — so a kit published without one of them does not fail here, in the workflow, but on the player's
machine, in the middle of their first build.

This check runs on the assembled kit, so a packaging step that forgets a piece fails the build instead.

    usage: kit_layout_check.py <kit folder>
"""
import sys
from pathlib import Path

# The import tool of either kit: the folder holds one of them.
IMPORT_TOOLS = ('totk_import.py', 'botw_import.py')


def check(kit):
    """The problems the kit folder has. An empty list means the kit can build."""
    problems = []

    tools = [name for name in IMPORT_TOOLS if (kit / name).is_file()]
    if not tools:
        problems.append(f'no import tool in {kit} (one of {", ".join(IMPORT_TOOLS)})')
    elif len(tools) > 1:
        problems.append(f'{kit} holds more than one import tool: {", ".join(tools)}')

    # The helper modules the import tool imports (kit/tools is on its path).
    if not list((kit / 'tools').glob('*.py')):
        problems.append('tools/ is missing or empty (the import tool loads its helpers from there)')

    # The kit's own fix to the upstream build scripts: the import tool reads this when the build starts.
    if not (kit / 'shim/patch_scripts.py').is_file():
        problems.append('shim/patch_scripts.py is missing (the import tool reads it when the build starts)')

    # The upstream sources the kit copies into the work folder and patches.
    mng = kit / 'MacNativeGames'
    if not (mng / 'build_app.py').is_file():
        problems.append('MacNativeGames/build_app.py is missing')
    if not (mng / '.kit-commit').is_file():
        problems.append('MacNativeGames/.kit-commit is missing (the work folder is copied only once per upstream)')
    scripts = list((mng / 'games').glob('*/scripts/*.py'))
    if not scripts:
        problems.append('MacNativeGames/games/*/scripts is missing or empty (the upstream build scripts)')

    # The app shell: the game goes into its reserved sections.
    shells = list((kit / 'shell').glob('*/*.app/TOTK'))
    if not shells:
        problems.append('shell/*/*.app/TOTK is missing (the app shell the game goes into)')

    # The built tools (hactool, SPIRV-Cross, the shader translator).
    tools_dirs = [d for d in (kit / 'bin').iterdir() if d.is_dir()] if (kit / 'bin').is_dir() else []
    if not tools_dirs:
        problems.append('bin/ holds no tool folder (hactool, SPIRV-Cross, the shader translator)')

    return problems


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    kit = Path(sys.argv[1]).resolve()
    if not kit.is_dir():
        print(f'  [FAIL] the kit folder does not exist: {kit}')
        return 1
    problems = check(kit)
    for problem in problems:
        print(f'  [FAIL] {problem}')
    if problems:
        print(f'kit layout: {len(problems)} problem(s) — the kit would fail on the player\'s machine')
        return 1
    print(f'kit layout: {kit.name} holds everything the import tool loads')
    return 0


if __name__ == '__main__':
    sys.exit(main())
