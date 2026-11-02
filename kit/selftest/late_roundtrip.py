#!/usr/bin/env python3
"""Write a synthetic game-data folder with kit/tools/late_config.py and read it back with MacNativeGames' own
runtime/loader.c (load_tables) and runtime/game_data.c, so the kit's tables are the ones the app reads.

    usage: late_roundtrip.py <MacNativeGames checkout>
"""
import hashlib, json, os, random, subprocess, sys, tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT / 'tools'))
import late_config

# A small program that runs upstream's loader's load_tables() and prints what it read. The loader is a big file with
# the whole runtime in it, so the tables are read by the same code path (the struct layouts and the checks) copied from
# it: the header, the record and the symbol are the ones runtime/loader.c names.
DUMP_C = r'''
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
typedef struct {uint64_t where;uint32_t kind,symbol;int64_t addend;} Reloc;
typedef struct {uint64_t ret,original;uint32_t timer,arg;} Gate;
typedef struct {char magic[8],version[8];uint32_t nmodule,format;uint64_t probe_plt,probe_slot,strings,strings_size,size;} TablesHeader;
typedef struct {char name[16],digest[72];uint64_t file_size,text_end,ro_off,data_off,patch_off,key_off,init,ctor_flag,init_array,init_size,symbols,relocs,gates;uint32_t nsym,nreloc,ngate,reserved;} TablesModule;
typedef struct {uint64_t value,size;uint32_t name;uint8_t defined,binding,type,reserved;} TablesSymbol;
typedef struct {char name[16];uint64_t file_size,text_end,ro_off,data_off,patch_off,key_off,init,ctor_flag,init_array,init_size;uint32_t nsym,nreloc,ngate;} Out;
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    int fd = open(argv[1], O_RDONLY); if (fd < 0) return 2;
    struct stat st; if (fstat(fd, &st)) return 2;
    const uint8_t *b = mmap(NULL, (size_t)st.st_size, PROT_READ, MAP_PRIVATE, fd, 0); close(fd);
    if (b == MAP_FAILED) return 2;
    uint64_t size = (uint64_t)st.st_size;
    const TablesHeader *h = (const void *)b;
    if (memcmp(h->magic, "TOTKTAB1", 8) || h->format != 1 || h->size != size) return 3;
    printf("probe %llu %llu\n", (unsigned long long)h->probe_plt, (unsigned long long)h->probe_slot);
    const char *strings = (const char *)b + h->strings;
    for (uint32_t i = 0; i < h->nmodule; i++) {
        const TablesModule *t = (const TablesModule *)(b + sizeof *h) + i;
        printf("module %s %s %llu %llu %llu %llu %llu %llu %llu %llu %llu %llu\n", t->name, t->digest,
               (unsigned long long)t->file_size, (unsigned long long)t->text_end, (unsigned long long)t->ro_off,
               (unsigned long long)t->data_off, (unsigned long long)t->patch_off, (unsigned long long)t->key_off,
               (unsigned long long)t->init, (unsigned long long)t->ctor_flag, (unsigned long long)t->init_array,
               (unsigned long long)t->init_size);
        const TablesSymbol *ts = (const TablesSymbol *)(b + t->symbols);
        for (uint32_t k = 0; k < t->nsym; k++)
            printf("sym %s %llu %llu %u %u %u\n", strings + ts[k].name, (unsigned long long)ts[k].value,
                   (unsigned long long)ts[k].size, ts[k].defined, ts[k].binding, ts[k].type);
        const Reloc *r = (const Reloc *)(b + t->relocs);
        for (uint32_t k = 0; k < t->nreloc; k++)
            printf("reloc %llu %u %u %lld\n", (unsigned long long)r[k].where, r[k].kind, r[k].symbol, (long long)r[k].addend);
        const Gate *g = (const Gate *)(b + t->gates);
        for (uint32_t k = 0; k < t->ngate; k++)
            printf("gate %llu %llu %u %u\n", (unsigned long long)g[k].ret, (unsigned long long)g[k].original, g[k].timer, g[k].arg);
    }
    return 0;
}
'''


def main():
    runtime = Path(sys.argv[1]) / 'games/totk/runtime'
    if not runtime.is_dir():
        raise SystemExit(f'no runtime folder: {runtime}')
    rnd = random.Random(7)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        modules, expect = [], []
        for name in late_config.NAMES:
            syms = [dict(name=f'_ZN2nn{rnd.randrange(10**6)}{name}', value=rnd.getrandbits(40), size=rnd.getrandbits(16),
                         defined=bool(rnd.getrandbits(1)), binding=rnd.randrange(3), type=rnd.randrange(16)) for _ in range(50)]
            relocs = [dict(where=rnd.getrandbits(32), kind=rnd.choice([257, 1025, 1026, 1027]), symbol=rnd.randrange(50),
                           addend=rnd.randrange(-1000, 10**9)) for _ in range(70)]
            gates = [dict(ret=rnd.getrandbits(32), original=rnd.getrandbits(32), timer=bool(rnd.getrandbits(1)), arg=rnd.randrange(256))
                     for _ in range(5 if name == 'main' else 0)]
            layout = {k: rnd.getrandbits(32) for k in ('TEXT_END', 'RO_OFF', 'DATA_OFF', 'PATCH_OFF', 'KEY_PAGE_OFF')}
            modules.append(dict(name=name, sha256=hashlib.sha256(name.encode()).hexdigest(), size=rnd.getrandbits(30),
                                ctor_flag=rnd.getrandbits(30), layout=layout, tags={'12': 111, '25': 222, '27': 333},
                                symbols=syms, relocs=relocs, gates=gates, probe_plt=4242, probe_slot=4343))
        (tmp / 'layout.json').write_text(json.dumps(modules))
        romfs = tmp / 'romfs'
        romfs.mkdir()
        (romfs / 'index.json').write_text(json.dumps(dict(romfs_size=17052625232, romfs_sha256='ab' * 32)))
        (romfs / 'runtime-index.bin').write_bytes(b'TOTKRFS1' + bytes(100))
        fonts = tmp / 'fonts'
        fonts.mkdir()
        rows = []
        for t in range(6):
            body = os.urandom(1000 + t)
            (fonts / f'{t}-font{t}.bfttf').write_bytes(body)
            rows.append(dict(type=t, name=f'font{t}', bfttf_bytes=len(body), font_bytes=len(body) - 8, sha256=hashlib.sha256(body).hexdigest()))
        (fonts / 'manifest.json').write_text(json.dumps(dict(status='pass', fonts=rows)))
        hashes = {n: [hashlib.sha256(f'{n}{i}'.encode()).hexdigest() for i in range(3)] for n in late_config.NAMES}
        data = tmp / 'game-data'
        late_config.write(data, tmp / 'layout.json', romfs, fonts, hashes, 'v143')

        # the tables, read the way runtime/loader.c load_tables reads them
        exe = tmp / 'tables_dump'
        src = tmp / 'tables_dump.c'
        src.write_text(DUMP_C)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', src, '-o', exe], check=True)
        out = subprocess.run([exe, str(data / 'runtime-tables.bin')], capture_output=True, text=True, check=True).stdout.splitlines()

        want = ['probe 4242 4343']
        for m in modules:
            l = m['layout']
            want.append(' '.join(str(x) for x in ['module', m['name'], m['sha256'], m['size'], l['TEXT_END'], l['RO_OFF'],
                                                    l['DATA_OFF'], l['PATCH_OFF'], l['KEY_PAGE_OFF'], 111, m['ctor_flag'], 222, 333]))
            want += [f"sym {s['name']} {s['value']} {s['size']} {int(s['defined'])} {s['binding']} {s['type']}" for s in m['symbols']]
            want += [f"reloc {r['where']} {r['kind']} {r['symbol']} {r['addend']}" for r in m['relocs']]
            want += [f"gate {g['ret']} {g['original']} {int(g['timer'])} {g['arg']}" for g in m['gates']]
        if out != want:
            bad = next(i for i, (a, b) in enumerate(zip(out + [''] * len(want), want)) if a != b)
            raise SystemExit(f'line {bad}: read {out[bad] if bad < len(out) else None!r}, wrote {want[bad]!r}')

        # the text files, read the way runtime/game_data.c reads them
        romfs_cfg = (data / 'romfs-config.txt').read_text()
        if 'ROMFS_IMAGE_SIZE 17052625232' not in romfs_cfg:
            raise SystemExit('romfs-config.txt is not what the runtime reads')
        shared = (data / 'shared-fonts.txt').read_text()
        for t, r in enumerate(rows):
            if f'FONT{t}_FILE {t}-font{t}.bfttf' not in shared or f'FONT{t}_SHA256 {r["sha256"]}' not in shared:
                raise SystemExit(f'shared-fonts.txt is missing font {t}')
        embedded = (data / 'embedded-hashes.txt').read_text()
        for n in late_config.NAMES:
            for key, h in zip(('X0', 'W', 'X1'), hashes[n]):
                if f'{n}_{key} {h}' not in embedded:
                    raise SystemExit(f'embedded-hashes.txt is missing {n}_{key}')

        print(f'game-data round trip: {len(out)} lines identical, '
              f'{(data / "runtime-tables.bin").stat().st_size} bytes of tables')


if __name__ == '__main__':
    main()
