#!/usr/bin/env python3
"""TOTK-ipa: the kit's own fixes to the upstream build scripts (games/totk/scripts).

These are checked edits of the upstream scripts, like kit/shim/apply_patches.py is for the runtime and the app: the
text to find must be there exactly once, or the build stops with a message (the upstream code changed; the fix needs to
be written again).

    patch_scripts.py <work folder>     the work folder holds totk/ (the import tool's layout)
"""
import sys
from pathlib import Path


def replace_once(path, old, new, note):
    text = path.read_text(encoding='utf-8')
    if text.count(old) == 1:
        path.write_text(text.replace(old, new), encoding='utf-8')
        print(f'  patched {path.name}: {note}', flush=True)
        return
    if text.count(new) == 1:
        print(f'  {path.name}: {note} is already in place', flush=True)
        return
    raise SystemExit(f'{path.name}: {note}: expected exactly one "{old.strip()[:60]}" '
                     f'(MacNativeGames changed; update kit/shim/patch_scripts.py)')


def main(work):
    work = Path(work)

    # --- the ACID signature is not a data failure ---
    # hactool verifies the NCA's fixed-key signature, the NPDM signature and the ACID signature. All three need
    # Nintendo's public keys, which a player's dump does not carry, so hactool always prints those three lines as
    # (FAIL). They say nothing about the content: the merge is decided by the FS header hashes and all six IVFC levels,
    # which hactool verifies with the content keys it does have. Upstream's games/totk/scripts only tolerates the first
    # two, so a base game whose Program NCA is in title-key crypto (the usual case for an NSP) fails the merge on the
    # ACID line alone. Every other line stays strict.
    for script, note in (('totk/scripts/extract_update_romfs.py', 'the update merge'),):
        path = work / script
        if not path.is_file():
            continue
        # The line that drops the two known failures takes the ACID one too.
        replace_once(path,
                     "        unsigned = re.compile(r'\\s*(?:Fixed-Key Signature|NPDM Signature) \\(FAIL\\)')\n",
                     "        unsigned = re.compile(r'\\s*(?:Fixed-Key Signature|NPDM Signature|Signature) \\(FAIL\\)')\n",
                     f'the ACID signature in {note}')

    # --- the report's keys are paths, and a path is not a string ---
    # The loader binds itself to the rewritten modules by their SHA-256, and the report that carries those digests
    # (analysis/<version>-port/phase12-validation.json, written by build_app.py) keys them by the module's path
    # relative to the game tree: "rewritten/v143/main.patched.bin". The script that reads the report back built the
    # key with str(Path.relative_to(ROOT)), which on Windows joins the parts with a backslash:
    # "rewritten\v143\main.patched.bin". The two never match, so the lookup raises KeyError and the build stops —
    # on the player's Windows machine only; on Linux and macOS the separator is a forward slash and it works.
    # as_posix() is the platform-independent spelling, and it is what build_app.py writes.
    for script, note in (('totk/scripts/prepare_runtime.py', 'the loader\'s binding to the rewritten modules'),):
        path = work / script
        if not path.is_file():
            continue
        replace_once(path,
                     "    assert digest == report['module_file_sha256'][str(path.relative_to(ROOT))], 'Unverified rewrite'\n",
                     "    assert digest == report['module_file_sha256'][path.relative_to(ROOT).as_posix()], 'Unverified rewrite'\n",
                     f'the report\'s path keys in {note}')

    print('the kit\'s script fixes are in place', flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
