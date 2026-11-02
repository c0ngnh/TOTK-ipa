#!/usr/bin/env python3
"""Convert the game files between the formats the Switch stores them in.

The Switch stores a game as an XCI (card image) or as an NSP (a set of NCAs). A downloaded update
is usually an NSZ (a compressed NSP). The kit's import tool accepts an XCI or an NSP as the base
game and an NSP or an NSZ as the update; this script converts between them so you can prepare the
files once and reuse them.

    # an NSZ update -> an NSP (decompress, and verify the NCA hashes)
    python3 convert_game.py update update.nsz --keys prod.keys --output-dir ~/Games

    # list what is inside a game file (title id, content type, size)
    python3 convert_game.py info base.nsp --keys prod.keys

    # the NSZ decompressor (nsz==5.0.0) comes from the kit's Python environment:
    #   python -m pip install nsz==5.0.0

What each format is:

    XCI  a card image: the game exactly as it is on a game card. One file, and it carries the
         system update the game needs (shared fonts included).
    NSP  the game split into its NCAs, packed as an HFS0 archive. One file. No system fonts.
    NSZ  an NSP whose NCAs are compressed (with the Nintendo/HAC standard compression). It is
         decompressed with hash verification: every NCA's hash is checked against the ticket.

Everything here works on Linux and Windows too; nothing needs a Switch or a Mac.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# The title ID of the base game, used to recognise the add-on content packs.
TOTK_BASE_TITLE = '0100f2c0115b6000'


def find_tool(name, extra_dirs=()):
    """A helper binary: the kit's own build first, then the PATH."""
    here = Path(__file__).resolve().parent
    # The script sits in the kit's tools/ folder: the binaries are in the kit's bin/, and in a checkout of the
    # repository the kit itself is in kit/, so both layouts are looked at.
    dirs = [here.parent / 'bin/linux-x64', here.parent / 'bin/windows-x64',
            here.parent.parent / 'kit/bin/linux-x64', here.parent.parent / 'kit/bin/windows-x64']
    dirs += list(extra_dirs)
    for d in dirs:
        for cand in (d / name, d / f'{name}.exe'):
            if cand.is_file():
                return cand
    found = shutil.which(name)
    return Path(found) if found else None


def run(cmd, **kw):
    print('$', ' '.join(str(c) for c in cmd), file=sys.stderr)
    rc = subprocess.run(cmd, **kw).returncode
    if rc:
        raise SystemExit(f'failed ({rc}): {cmd[0]}')


def nsz_tool(venv: Path):
    """The NSZ decompressor, from the kit's Python environment (nsz==5.0.0, a PyPI package)."""
    for cand in (venv / 'bin/nsz', venv / 'Scripts/nsz.exe'):
        if cand.is_file():
            return cand
    return None


def decompress_nsz(nsz_file: Path, keys: Path, out_dir: Path, venv: Path = None):
    """NSZ -> NSP, with the NCA hash verification NSZ does."""
    if nsz_file.suffix.lower() != '.nsz':
        # Already an NSP: nothing to decompress, but the file may still be named .nsp.
        if nsz_file.suffix.lower() == '.nsp':
            print(f'{nsz_file.name} is already an NSP; nothing to decompress.')
            return nsz_file
        raise SystemExit(f'expected an .nsz update, got {nsz_file.name}')
    here = Path(__file__).resolve().parent
    # The kit's import tool creates the environment with nsz installed; reuse it if it is there. The import tool's
    # work folder is next to the game file, so the kit folder and the current folder are both looked at.
    candidates = []
    if venv:
        candidates.append(venv)
    candidates += [here.parent / 'TOTK_ipa_build/venv', here.parent.parent / 'TOTK_ipa_build/venv',
                   Path.cwd() / 'TOTK_ipa_build/venv', Path.cwd() / 'venv']
    tool = None
    for v in candidates:
        tool = nsz_tool(v)
        if tool:
            break
    if not tool:
        raise SystemExit(
            'no NSZ decompressor found.\n'
            'The kit installs one (nsz==5.0.0) when it runs. Run the import tool once first,\n'
            'or install it yourself:  python -m pip install nsz==5.0.0\n'
            'or point at it with --venv <the kit\'s Python environment>')
    out_dir.mkdir(parents=True, exist_ok=True)
    run([str(tool), '-D', '--keys', str(keys), '-o', str(out_dir), str(nsz_file)])
    produced = out_dir / f'{nsz_file.stem}.nsp'
    if not produced.is_file():
        cands = sorted(out_dir.glob(f'{nsz_file.stem}*.nsp'))
        if not cands:
            raise SystemExit('the decompressor did not produce an NSP')
        produced = cands[0]
    return produced


def load_keys(path):
    """Read a prod.keys / title.keys file into {name: bytes}."""
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


def nca_header(raw, header_key):
    """Decrypt the 3 KiB NCA header of a raw NCA prefix."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    out = b''
    for i in range(6):
        cipher = Cipher(algorithms.AES(header_key), modes.XTS(i.to_bytes(16, 'big')))
        dec = cipher.decryptor()
        out += dec.update(raw[i * 512:(i + 1) * 512]) + dec.finalize()
    return out


def pfs0_entries(f):
    """(name, offset, size) of each file in a PFS0 archive (the NSP format)."""
    import struct
    f.seek(0)
    hdr = f.read(16)
    if hdr[:4] != b'PFS0':
        raise ValueError('not a PFS0 archive (an NSP)')
    count, strings_size = struct.unpack_from('<II', hdr, 4)
    f.seek(16)
    raw = f.read(count * 24 + strings_size)
    strings = raw[count * 24:]
    base = 16 + count * 24 + strings_size
    entries = []
    for i in range(count):
        off, length, nameoff = struct.unpack_from('<QQI', raw, i * 24)
        end = strings.find(b'\0', nameoff)
        entries.append((strings[nameoff:end].decode('utf-8'), base + off, length))
    return entries


def describe(game: Path, keys: Path):
    """Title ID and content type of every NCA in an NSP."""
    import struct
    keyset = load_keys(keys)
    rows = []
    with game.open('rb') as f:
        for name, off, length in pfs0_entries(f):
            if not name.endswith('.nca'):
                continue
            f.seek(off)
            hdr = nca_header(f.read(0xc00), keyset['header_key'])
            if hdr[0x200:0x204] != b'NCA3':
                continue
            title = f'{struct.unpack_from("<Q", hdr, 0x210)[0]:016x}'
            rows.append(dict(file=name, title=title, type=hdr[0x205], size=length))
    for r in rows:
        print(f"{r['title']} type={r['type']} {r['size']:>12} {r['file']}")
    print(f'\n{len(rows)} NCAs in {game.name}')
    if any(r['title'] == TOTK_BASE_TITLE for r in rows):
        print('this is the base game (0100f2c0115b6000)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    d = sub.add_parser('update', help='decompress an NSZ update into an NSP')
    d.add_argument('nsz', type=Path)
    d.add_argument('--keys', type=Path, required=True)
    d.add_argument('--output-dir', type=Path, default=Path('.'))
    d.add_argument('--venv', type=Path, help='the kit\'s Python environment (with nsz installed)')

    i = sub.add_parser('info', help='list the NCAs of an NSP')
    i.add_argument('nsp', type=Path)
    i.add_argument('--keys', type=Path, required=True)

    x = sub.add_parser('xci', help='show what an XCI holds')
    x.add_argument('xci', type=Path)

    args = ap.parse_args()
    if args.cmd == 'update':
        nsp = decompress_nsz(args.nsz, args.keys, args.output_dir, args.venv)
        print(f'\nthe update is now an NSP: {nsp}')
        print('Give it to the import tool with --update')
    elif args.cmd == 'info':
        describe(args.nsp, args.keys)
    elif args.cmd == 'xci':
        print(f'{args.xci} is a card image; the import tool reads it directly')


if __name__ == '__main__':
    main()
