#!/usr/bin/env python3
"""The face buttons' swap (the user's request, 2026-11-03): the game has one set of A, B, X, Y prompts, and a
Bluetooth controller that is not a Nintendo one is read by position, so the letters land where the player does not
expect them. With the swap on, the game sees the Nintendo arrangement.

The test builds the kit's own test (kit/selftest/face_swap_test.c) against the real runtime/gamepad_layout.h of a
patched tree and runs it: without the switch nothing is swapped (the game keeps what it had), and with it the two
pairs change hands (A with B, X with Y).

    usage: face_swap_check.py <MacNativeGames checkout> [--work <folder>]
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / 'shim'))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 1:
        raise SystemExit('usage: face_swap_check.py <MacNativeGames checkout> [--work <folder>]')
    mng = Path(args[0]).resolve()
    tree = mng / 'games/totk'
    if not (tree / 'runtime/gamepad_layout.h').is_file():
        raise SystemExit(f'{tree} is not a MacNativeGames checkout')

    work = Path(tempfile.mkdtemp(prefix='totk-face-swap-'))
    try:
        # A copy of the tree, with the kit's patches in it: the swap is the kit's own addition.
        patched = work / 'totk'
        shutil.copytree(tree, patched, symlinks=True,
                        ignore=shutil.ignore_patterns('prebuilt', 'rewritten', 'analysis', 'extracted'))
        import apply_patches
        apply_patches.main(patched)

        cc = os.environ.get('CC', 'cc')
        exe = work / 'face_swap_test'
        run = subprocess.run([cc, '-std=gnu11', '-O1', '-Wall', '-I', str(patched / 'runtime'),
                              str(KIT / 'selftest/face_swap_test.c'), '-o', str(exe)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if run.returncode:
            print(run.stdout)
            raise SystemExit('the face buttons\' swap test did not build')
        done = subprocess.run([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(done.stdout.strip())
        if done.returncode:
            raise SystemExit('the face buttons\' swap test failed')
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
