#!/usr/bin/env python3
"""List the title ID and content type of every NCA in an unpacked firmware directory.

An NSP base game carries no system fonts, so the six shared fonts must come from your console's
firmware. This script shows which NCAs in your firmware dump are the fonts (the data NCAs with
the titles 0100000000000810 .. 0100000000000814), so you know the dump is complete before the build.

    python3 scan_firmware.py <firmware-nca-dir> --keys <prod.keys>

Only the NCA headers are read; no game data is decrypted.
"""
import argparse
import json
import struct
import sys
from pathlib import Path

# The system data titles that hold the shared fonts (see extract_shared_fonts.py in the kit).
FONT_TITLES = {f'010000000000081{i}' for i in range(5)}


def load_keys(path):
    keys = {}
    for line in Path(path).read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if '=' in line:
            name, value = line.split('=', 1)
            try:
                keys[name.strip().lower()] = bytes.fromhex(value.strip())
            except ValueError:
                raise ValueError(f'Invalid key encoding: {line}') from None
    return keys


def nca_header(f, header_key):
    """The decrypted 3 KiB NCA header of an open file."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    f.seek(0)
    raw = f.read(0xc00)
    out = b''
    for i in range(6):
        cipher = Cipher(algorithms.AES(header_key), modes.XTS(i.to_bytes(16, 'big')))
        dec = cipher.decryptor()
        out += dec.update(raw[i * 512:(i + 1) * 512]) + dec.finalize()
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('firmware', type=Path, help='unpacked firmware NCA directory')
    ap.add_argument('--keys', type=Path, required=True, help='your prod.keys')
    ap.add_argument('--json', type=Path, help='write the inventory as JSON to this file')
    args = ap.parse_args()

    if not args.firmware.is_dir():
        raise SystemExit(f'not a directory: {args.firmware}')
    keys = load_keys(args.keys)
    if 'header_key' not in keys:
        raise SystemExit('the keys file has no header_key')

    rows = []
    for p in sorted(args.firmware.rglob('*')):
        if not p.is_file():
            continue
        if p.suffix.lower() != '.nca' and p.name != '00':
            continue
        try:
            with p.open('rb') as f:
                hdr = nca_header(f, keys['header_key'])
            if hdr[0x200:0x204] != b'NCA3':
                continue
            title = f'{struct.unpack_from("<Q", hdr, 0x210)[0]:016x}'
            rows.append({'title': title, 'type': hdr[0x205], 'file': str(p.relative_to(args.firmware)),
                         'size': p.stat().st_size})
        except Exception as e:
            print(f'ERR {p.name}: {e}', file=sys.stderr)

    for r in rows:
        # The fonts live in the data NCAs (content type 4); the .cnmt.nca of the same title is only metadata.
        mark = '  <-- shared font (data)' if r['title'] in FONT_TITLES and r['type'] == 4 else ''
        print(f"{r['title']} type={r['type']} {r['size']:>12} {r['file']}{mark}")

    found = {r['title'] for r in rows if r['type'] == 4} & FONT_TITLES
    missing = FONT_TITLES - found
    if missing:
        print(f'\nWARNING: {len(missing)} shared font title(s) missing: {", ".join(sorted(missing))}',
              file=sys.stderr)
        print('The build needs all of them; dump the system data partition too.', file=sys.stderr)
    else:
        print(f'\nall {len(FONT_TITLES)} shared font titles are present', file=sys.stderr)

    if args.json:
        args.json.write_text(json.dumps(rows, indent=1) + '\n')
        print(f'written: {args.json}')


if __name__ == '__main__':
    main()
