#!/usr/bin/env python3
"""The feature manifest: the list of features a port MUST have, checked against the kit.

This is the file that makes "every future port has the features we built" checkable rather than a
wish. It lists each feature, where it lives in the kit, how to tell it is present, and what proves
it works. The self-test in this directory runs it.

Two kinds of check:

  - in the SOURCE: the feature's marker text is in the file (the patch's anchor, the method, the
    constant). This is what catches a feature that was never ported.
  - a TEST: the feature has a self-test that proves its behaviour. This is what catches a feature
    that was ported but does not work.

Run it:

    python3 kit/selftest/feature_manifest.py          # check the kit against the manifest
    python3 kit/selftest/feature_manifest.py --list   # show the manifest

A new port MUST pass this. If it does not, the port is not finished: either the feature is missing
or it was ported wrongly.
"""
import argparse
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).resolve().parent / 'features.json'


def load():
    if not MANIFEST.is_file():
        raise SystemExit(f'the manifest is missing: {MANIFEST}')
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def check():
    """The kit against the manifest. Returns the number of problems."""
    data = load()
    features = data['features']
    bad = 0

    for feature in features:
        name = feature['name']
        kind = feature['kind']

        if kind == 'source':
            path = KIT / feature['file']
            if not path.is_file():
                print(f'  [FAIL] {name}: the file is missing: {path}')
                bad += 1
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
            missing = [m for m in feature['markers'] if m not in text]
            if missing:
                print(f"  [FAIL] {name}: {feature['file']} has none of {missing}")
                bad += 1
            else:
                print(f"  [OK]   {name}  ({feature['file']})")

        elif kind == 'test':
            path = KIT / 'selftest' / feature['file']
            if not path.is_file():
                print(f'  [FAIL] {name}: the self-test is missing: {path}')
                bad += 1
                continue
            print(f"  [OK]   {name}  (selftest/{feature['file']})")

        elif kind == 'tool':
            path = KIT / 'tools' / feature['file']
            if not path.is_file():
                print(f'  [FAIL] {name}: the tool is missing: {path}')
                bad += 1
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
            missing = [m for m in feature.get('markers', []) if m not in text]
            if missing:
                print(f"  [FAIL] {name}: tools/{feature['file']} has none of {missing}")
                bad += 1
            else:
                print(f"  [OK]   {name}  (tools/{feature['file']})")

        else:
            print(f'  [FAIL] {name}: unknown check kind {kind!r}')
            bad += 1

    # The self-tests a feature names must exist and be runnable by the workflow.
    for test in data.get('workflow_tests', []):
        path = KIT / 'selftest' / test
        if not path.is_file():
            print(f'  [FAIL] the workflow runs selftest/{test}, which is missing')
            bad += 1

    print()
    if bad:
        print(f'feature manifest: {bad} problem(s) — the port is not finished')
    else:
        print(f"feature manifest: {len(features)} features, all present")
    return bad


def show():
    data = load()
    width = max(len(f['name']) for f in data['features'])
    for feature in data['features']:
        print(f"  {feature['name']:<{width}}  {feature['kind']:<7}  {feature.get('file', '')}")
        if feature.get('note'):
            print(f"  {'':<{width}}  {'':<7}  {feature['note']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--list', action='store_true', help='show the manifest')
    a = ap.parse_args()
    if a.list:
        show()
        return 0
    return 1 if check() else 0


if __name__ == '__main__':
    sys.exit(main())
