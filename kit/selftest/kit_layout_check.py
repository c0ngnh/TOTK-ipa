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

# The built tools the import tool runs, and the names they are looked for by.
# The import tool's tool_dir() resolves bin/<system>-<arch>/ and names these three.
TOOL_BINARIES = ('hactool', 'spirv-cross', 'totk_xlate')

# The shared library the shader translator loads by name (the service's DllImport("totk_spirv_cross")), and the
# MinGW-w64 runtime DLLs it would want if it were not linked with the runtime inside it. The player's Windows has
# no MinGW, so a library that wants them cannot load: the build dies with "libgcc_s_seh-1.dll was not found".
WINDOWS_LIBRARIES = ('totk_spirv_cross.dll', 'libgcc_s_seh-1.dll', 'libstdc++-6.dll', 'libwinpthread-1.dll')

# The helper modules the import tool imports by name (kit/tools is on its path), per kit. The two kits import
# different ones: the TOTK import tool imports export_v143 (the 1.4.3 export) and late_config (the late config
# table), the BOTW one imports export_botw190 (the 1.9.0 export) and game_data (the game-data tables).
TOOL_MODULES = {
    'totk_import.py': ('export_v143', 'late_config', 'macho', 'game_resources', 'app_icon'),
    'botw_import.py': ('export_botw190', 'game_data', 'macho', 'game_resources', 'app_icon'),
}

# The upstream script the import tool runs to prepare the shader seed, per game.
# The kit ships both games' trees; the import tool needs its own game's script.
UPSTREAM_SCRIPTS = {
    'totk_import.py': ('totk/scripts/prepare_shader_seed.py',),
    'botw_import.py': ('totk/scripts/prepare_shader_seed.py', 'botw/scripts/prepare_shader_seed.py'),
}


def check(kit):
    """The problems the kit folder has. An empty list means the kit can build."""
    problems = []

    tools = [name for name in IMPORT_TOOLS if (kit / name).is_file()]
    if not tools:
        problems.append(f'no import tool in {kit} (one of {", ".join(IMPORT_TOOLS)})')
    elif len(tools) > 1:
        problems.append(f'{kit} holds more than one import tool: {", ".join(tools)}')

    # The helper modules the import tool imports by name (kit/tools is on its path).
    for name in TOOL_MODULES.get(tools[0] if tools else '', ()):
        if not (kit / 'tools' / f'{name}.py').is_file():
            problems.append(f'tools/{name}.py is missing (the import tool imports it)')

    # The kit's own fix to the upstream build scripts: the import tool reads this when the build starts.
    if not (kit / 'shim/patch_scripts.py').is_file():
        problems.append('shim/patch_scripts.py is missing (the import tool reads it when the build starts)')

    # The upstream sources the kit copies into the work folder and patches.
    mng = kit / 'MacNativeGames'
    if not (mng / 'build_app.py').is_file():
        problems.append('MacNativeGames/build_app.py is missing')
    if not (mng / '.kit-commit').is_file():
        problems.append('MacNativeGames/.kit-commit is missing (the work folder is copied only once per upstream)')
    # The upstream script the import tool runs to prepare the shader seed.
    for rel in UPSTREAM_SCRIPTS.get(tools[0] if tools else '', ()):
        if not (mng / 'games' / rel).is_file():
            problems.append(f'MacNativeGames/games/{rel} is missing (the shader seed is prepared by it)')
    if not (mng / 'games/totk/requirements.txt').is_file():
        problems.append('MacNativeGames/games/totk/requirements.txt is missing (the venv is built from it)')

    # The app shell: the game goes into its reserved sections.
    shells = list((kit / 'shell').glob('*/*.app/TOTK'))
    if not shells:
        problems.append('shell/*/*.app/TOTK is missing (the app shell the game goes into)')

    # The built tools: hactool, SPIRV-Cross, the shader translator. The import tool's tool_dir()
    # resolves bin/<system>-<arch>/ and names these three; a missing one stops the player's build.
    bin_dir = kit / 'bin'
    folders = [d for d in bin_dir.iterdir() if d.is_dir()] if bin_dir.is_dir() else []
    if not folders:
        problems.append('bin/ holds no tool folder (hactool, SPIRV-Cross, the shader translator)')
    else:
        for name in TOOL_BINARIES:
            found = any((folder / name).is_file() or (folder / f'{name}.exe').is_file()
                        for folder in folders)
            if not found:
                problems.append(f'bin/ holds no {name} (the build needs it)')
        # The Windows tools: the translator loads the shared library by name, so the library must be beside it,
        # and the library must not want a MinGW runtime DLL the player's machine does not have.
        windows = [folder for folder in folders if folder.name.startswith('windows-')]
        if windows:
            for name in WINDOWS_LIBRARIES:
                if not any((folder / name).is_file() for folder in windows):
                    problems.append(f'bin/ holds no {name} (the Windows translator loads it, or needs it)')

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
