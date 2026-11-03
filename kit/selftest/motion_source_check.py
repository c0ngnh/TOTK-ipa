#!/usr/bin/env python3
"""The motion source's gate (the user's request, 2026-11-03): the game has one six-axis device, and the player picks
which sensor drives it -- the iPhone's own, a Bluetooth controller's, or automatic.

The test builds the kit's own test (kit/selftest/motion_source_test.c) against the real runtime/motion_fusion.c of a
patched tree and runs it: a source that is not in force must not reach the fusion at all, or the two sensors' samples
would be mixed into one orientation.

    usage: motion_source_check.py <MacNativeGames checkout> [--work <folder>]
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
        raise SystemExit('usage: motion_source_check.py <MacNativeGames checkout> [--work <folder>]')
    mng = Path(args[0]).resolve()
    tree = mng / 'games/totk'
    if not (tree / 'runtime/motion_fusion.c').is_file():
        raise SystemExit(f'{tree} is not a MacNativeGames checkout')

    work = Path(tempfile.mkdtemp(prefix='totk-motion-source-'))
    try:
        # A copy of the tree, with the kit's patches in it: the gate is the kit's own addition.
        patched = work / 'totk'
        shutil.copytree(tree, patched, symlinks=True,
                        ignore=shutil.ignore_patterns('prebuilt', 'rewritten', 'analysis'))
        import apply_patches
        apply_patches.main(patched)

        cc = os.environ.get('CC', 'cc')
        exe = work / 'motion_source_test'
        run = subprocess.run([cc, '-std=gnu11', '-O1', '-Wall', '-I', str(patched / 'runtime'),
                              str(KIT / 'selftest/motion_source_test.c'), str(patched / 'runtime/motion_fusion.c'),
                              '-o', str(exe), '-lm', '-lpthread'],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if run.returncode:
            print(run.stdout)
            raise SystemExit('the motion source test did not build')
        done = subprocess.run([str(exe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(done.stdout.strip())
        if done.returncode:
            raise SystemExit('the motion source test failed')
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
