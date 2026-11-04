#!/usr/bin/env python3
"""Check the kit's own fix to the upstream build scripts (kit/shim/patch_scripts.py).

The fix lets the update's RomFS merge pass when hactool reports the ACID signature as (FAIL). That line needs
Nintendo's public keys, which a player's dump does not carry, so it is (FAIL) for every dump; the merge itself is
decided by the FS header hashes and all six IVFC levels, which hactool verifies with the content keys it has.

The check runs the patched script's own logic on a real hactool log (the one a merge writes) and on the logs that
must still fail.

    usage: patch_scripts_check.py <MacNativeGames checkout>
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
MNG = Path(sys.argv[1])

# The real lines hactool prints for the three signatures it cannot verify without Nintendo's public keys.
SIG_LINES = [
    'Fixed-Key Signature (FAIL):         16BAEAE70EB03A728955F7AF658159990C2E6019F05D1F2123C3FBB801183578',
    'NPDM Signature (FAIL):              43B5FDC0AD76625C0CDDC82182E537AD8ECA933E9F28A9CCC16A3BF4F1ABF057',
    '        Signature (FAIL):           044FEE4930BC7CB71BC9280EA2E16B04DF510B93F5EBDE349E88A41D2E2B53E5',
]
IVFC = ''.join(f'        Level {i} (GOOD):\n            Data Size:              0x000000001000\n' for i in range(6))


def patched_logic(text):
    """The logic the patched script runs: the three signature lines are removed, everything else is checked."""
    stripped = re.sub(r'^\s*(?:Fixed-Key Signature|NPDM Signature|Signature) \(FAIL\).*$', '', text, flags=re.M)
    return re.search(r'\(FAIL\)|\(INVALID\)|Failed to|Error:', stripped)


def main():
    sys.path.insert(0, str(KIT / 'shim'))
    import patch_scripts

    # The upstream script, copied and patched by the kit's own code.
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / 'totk/scripts').mkdir(parents=True)
        shutil.copy2(MNG / 'games/totk/scripts/extract_update_romfs.py', work / 'totk/scripts/extract_update_romfs.py')
        patch_scripts.main(work)
        src = (work / 'totk/scripts/extract_update_romfs.py').read_text(encoding='utf-8')

        # The script must still read its own logic: pull the statement out and run it on a real log.
        unsigned = re.search(r"unsigned = re\.compile\((r'.*?')\)", src, re.S)
        if not unsigned:
            raise SystemExit('the unsigned line is not where the kit\'s fix put it')
        if 'Signature' not in unsigned.group(1):
            raise SystemExit(f'the unsigned line does not tolerate the ACID signature: {unsigned.group(1)}')
        checked = re.search(r"checked = '\\n'\.join\(line for line in log\.splitlines\(\) if not unsigned\.match\(line\)\)", src)
        if not checked:
            raise SystemExit('the checked line is not where the kit\'s fix put it')

        # The pattern the patched script uses, read from the file itself.
        pattern = re.compile(unsigned.group(1)[2:-1])   # the raw string literal, without its r'...'
        if not pattern.match('        Signature (FAIL):           044FEE4930BC7CB71BC9280EA2E16B04DF510B93F5EBDE349E88A41D2E2B53E5'):
            raise SystemExit(f'the patched pattern does not match the ACID signature line: {unsigned.group(1)}')

        # A log with only the three signature lines and the six IVFC levels passes.
        good = '\n'.join(SIG_LINES) + '\n' + IVFC + 'Done!\n'
        if re.search(r'\(FAIL\)|\(INVALID\)|Failed to|Error:', '\n'.join(l for l in good.splitlines() if not pattern.match(l))):
            raise SystemExit('a clean merge log is still read as a failure')

        # A log with any other failure is still a failure.
        for extra in ('        Level 2 (INVALID):', 'Failed to open the file', 'Error: bad key',
                      '        Level 3 (FAIL):'):
            if not patched_logic(good + extra + '\n'):
                raise SystemExit(f'the failure {extra!r} is not caught any more')

    print('the kit\'s script fix: the ACID signature passes, every other failure is still caught')


if __name__ == '__main__':
    main()
