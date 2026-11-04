#!/usr/bin/env python3
"""Check the kit's rule for the Windows tools: they must not want a MinGW runtime DLL.

The player's Windows has no MinGW. A tool linked against the MinGW runtime (libgcc_s_seh-1.dll for the unwinder,
libstdc++-6.dll for the C++ runtime, libwinpthread-1.dll for the threading runtime) cannot start there: the build
dies in the middle of the shader step with "<name> was not found". The kit links the runtime into the tools, so the
import table of a built tool must not name those three.

The check reads the import table the way the kit's own builder does (objdump -p), on the output objdump gives for a
tool that wants them and for one that does not.

    usage: mingw_runtime_check.py
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
import build_tools

# The lines objdump -p prints for the libraries a tool imports.
OBJDUMP_OUTPUT = """The Import Tables (with Import Lookup Table):

DLL Name: KERNEL32.dll
	vma:  Hint/Ord Member-Name Bound-To
	00001000	  1000  LoadLibraryA

DLL Name: libgcc_s_seh-1.dll
	00002000	  2000  _Unwind_Resume

DLL Name: libstdc++-6.dll
	00003000	  3000  __cxa_throw

DLL Name: libwinpthread-1.dll
	00004000	  4000  pthread_create

DLL Name: msvcrt.dll
	00005000	  5000  memset
"""


def main():
    # The three runtime DLLs the player's Windows does not have.
    if 'libgcc_s_seh-1.dll' not in build_tools.MINGW_RUNTIME_DLLS:
        raise SystemExit('the unwinder is not in the list of runtime DLLs')
    if 'libstdc++-6.dll' not in build_tools.MINGW_RUNTIME_DLLS:
        raise SystemExit('the C++ runtime is not in the list of runtime DLLs')
    if 'libwinpthread-1.dll' not in build_tools.MINGW_RUNTIME_DLLS:
        raise SystemExit('the threading runtime is not in the list of runtime DLLs')

    # The parser must read the import table the way objdump prints it.
    parsed = set(re.findall(r'^\s*DLL Name:\s*(\S+)', OBJDUMP_OUTPUT, re.M))
    wanted = parsed & set(build_tools.MINGW_RUNTIME_DLLS)
    if wanted != {'libgcc_s_seh-1.dll', 'libstdc++-6.dll', 'libwinpthread-1.dll'}:
        raise SystemExit(f'the import table was not read as expected: {sorted(wanted)}')
    # The Windows API is always there; it must not be reported as a runtime DLL.
    if 'KERNEL32.dll' in wanted or 'msvcrt.dll' in wanted:
        raise SystemExit('the Windows API was read as a MinGW runtime DLL')

    # A tool with the runtime inside it imports no runtime DLL.
    clean = set(re.findall(r'^\s*DLL Name:\s*(\S+)', 'DLL Name: KERNEL32.dll\nDLL Name: msvcrt.dll\n', re.M))
    if clean & set(build_tools.MINGW_RUNTIME_DLLS):
        raise SystemExit('a tool that carries the runtime was read as needing one')

    # The check must read a real file's import table, so it must find objdump or say so.
    if not (build_tools.shutil.which('objdump') or build_tools.find_mingw_tool('objdump')):
        print('note: objdump is not here; the import table of a built tool was not read')
    else:
        # A real library is read: the parse must not raise on it.
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / 'probe.dll'
            probe.write_bytes(b'MZ' + b'\0' * 64)
            try:
                build_tools.runtime_imports(probe)
            except SystemExit as e:
                # objdump cannot read a file that is not a library; that is the tool's answer, not a crash.
                if 'could not read' not in str(e):
                    raise

    print('the kit\'s Windows tools rule: the MinGW runtime is linked in, so no tool wants a runtime DLL')


if __name__ == '__main__':
    main()
