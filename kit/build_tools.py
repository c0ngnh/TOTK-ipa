#!/usr/bin/env python3
"""Build the import tool's helper programs for this computer (Linux, macOS or Windows), from MacNativeGames' pinned sources:

  hactool      the update merge (build_app.build_hactool's pinned commit and patches; on Linux the bounded base-file
               view uses glibc's fopencookie instead of BSD funopen, on Windows - MSYS2 MinGW-w64, no stdio cookies - it
               is a temporary copy that is deleted when closed)
  spirv-cross  SPIRV-Cross at build_app.SPIRV_CROSS with its Release flags
  totk_xlate   the shader translator (games/totk/tools/totk_xlate, NativeAOT) - on macOS arm64 the repository's prebuilt

    build_tools.py <MacNativeGames checkout> <output folder> [--dotnet dotnet]
"""
import argparse, concurrent.futures, os, platform, shutil, subprocess, sys
from pathlib import Path

LINUX_SEEK = [
    ('static int mng_base_read(void *cookie, char *buffer, int count) {',
     'static ssize_t mng_base_read(void *cookie, char *buffer, size_t count) {'),
    ('    if (left < count) count = (int)left;', '    if (left < (off_t)count) count = (size_t)left;'),
    ('static fpos_t mng_base_seek(void *cookie, fpos_t offset, int whence) {',
     'static int mng_base_seek(void *cookie, off64_t *where, int whence) {\n    off64_t offset = *where;'),
    ('return (fpos_t)-1;', 'return -1;'),
    ('    return (fpos_t)(range->position = base + offset);', '    *where = range->position = base + offset;\n    return 0;'),
    ('    FILE *view = funopen(range, mng_base_read, NULL, mng_base_seek, mng_base_close);',
     '    FILE *view = fopencookie(range, "rb", (cookie_io_functions_t){ .read = mng_base_read, .write = NULL, '
     '.seek = mng_base_seek, .close = mng_base_close });'),
    ('#define _DARWIN_C_SOURCE 1\n', '#define _GNU_SOURCE 1\n#define _DARWIN_C_SOURCE 1\n'),
]


# Windows: build_app's funopen view of the base program NCA (from its typedef to the end of mng_open_base) becomes this
WINDOWS_BASE = r'''
/* TOTK-ipa (Windows): MinGW has no stdio cookie streams, so the bounded view is a temporary copy of the range, in TMP,
   deleted when hactool closes it ("D"). */
static FILE *mng_open_base(const char *path) {
    const char *start = getenv("MNG_BASE_RANGE_OFFSET"), *size = getenv("MNG_BASE_RANGE_SIZE");
    if (!start && !size) return fopen(path, "rb");
    if (!start || !size) return NULL;
    char *end1, *end2;
    unsigned long long a = strtoull(start, &end1, 10), n = strtoull(size, &end2, 10);
    if (!*start || !*size || *end1 || *end2 || !n) return NULL;
    FILE *in = fopen(path, "rb");
    if (!in) return NULL;
    char *name = _tempnam(NULL, "mngbase");
    FILE *out = name ? fopen(name, "w+bD") : NULL;
    free(name);
    if (!out || fseeko64(in, (off64_t)a, SEEK_SET)) { if (out) fclose(out); fclose(in); return NULL; }
    static unsigned char buffer[1 << 20];
    while (n) {
        size_t want = n < sizeof buffer ? (size_t)n : sizeof buffer;
        if (fread(buffer, 1, want, in) != want || fwrite(buffer, 1, want, out) != want) { fclose(out); fclose(in); return NULL; }
        n -= want;
    }
    fclose(in);
    if (fflush(out) || fseeko64(out, 0, SEEK_SET)) { fclose(out); return NULL; }
    return out;
}
'''


def sh(args, cwd=None, env=None):
    print('+', ' '.join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], cwd=cwd, check=True, env=env)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mng', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--dotnet', default='dotnet')
    a = ap.parse_args()
    mng, out = a.mng.resolve(), a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(mng))
    import build_app as B
    work = out.parent / 'tools-work'
    tree = work / 'totk'
    (tree).mkdir(parents=True, exist_ok=True)
    logs = work / 'logs'
    logs.mkdir(exist_ok=True)
    linux = sys.platform.startswith('linux')
    windows = sys.platform == 'win32'
    exe = '.exe' if windows else ''

    # hactool: build_app's own fetch and patches; the Linux / Windows file view is swapped in just before make
    real_run = B.run
    def run(cmd, log, cwd=None, env=None, quiet=True):
        if (linux or windows) and cmd and cmd[0] == 'make':
            main_c = Path(cwd) / 'main.c'
            text = main_c.read_text(encoding='utf-8')
            if linux and 'fopencookie(' not in text:
                for old, new in LINUX_SEEK:
                    if text.count(old) != 1:
                        raise SystemExit(f'hactool main.c: expected one "{old}" (MacNativeGames changed its hactool patch)')
                    text = text.replace(old, new)
            if windows and '_tempnam(' not in text:
                first = text.find('typedef struct { FILE *file; off_t start, size, position; } mng_base_range;')
                last = text.find('int main(int argc, char **argv)')
                if first < 0 or last < first or 'static FILE *mng_open_base(const char *path)' not in text[first:last]:
                    raise SystemExit('hactool main.c: build_app\'s base-file view changed; update kit/build_tools.py')
                text = text[:first] + WINDOWS_BASE + '\n' + text[last:]
            main_c.write_text(text)
            if windows:   # MinGW-w64: gcc, hactool.exe, no runtime DLLs
                cmd = [c for c in cmd if not str(c).startswith('CC=')] + [
                    'CC=gcc', 'EXEEXT=.exe', 'LDFLAGS=-static -lmbedtls -lmbedx509 -lmbedcrypto']
        try:
            return real_run(cmd, log, cwd=cwd, env=env, quiet=quiet)
        except B.BuildError:
            print(Path(log).read_text(errors='replace')[-4000:])
            raise
    B.run = run
    built = B.build_hactool(tree, logs)
    shutil.copy2(built.with_name(built.name + exe), out / f'hactool{exe}')

    # SPIRV-Cross with build_app's pinned commit and Release flags
    src = work / 'src/SPIRV-Cross'
    B.git_fetch(*B.SPIRV_CROSS, src, logs / 'fetch-spirv-cross.log')
    flags = [f for f in B.SPIRV_CROSS_FLAGS if f not in ('-arch', 'arm64')]
    objs = work / 'spirv-obj'
    objs.mkdir(exist_ok=True)
    cxx = 'g++' if windows else 'clang++' if shutil.which('clang++') else 'c++'
    with concurrent.futures.ThreadPoolExecutor(os.cpu_count() or 4) as pool:
        list(pool.map(lambda n: sh([cxx, *flags, '-c', src / n, '-o', objs / (n + '.o')]), B.SPIRV_CROSS_SOURCES))
    sh([cxx, *[objs / (n + '.o') for n in B.SPIRV_CROSS_SOURCES], *(['-static'] if windows else []), '-o', out / f'spirv-cross{exe}'])

    # The translator links SPIRV-Cross in (publish_native.sh builds the library; Service.cs calls it), so it needs
    # the library beside it. Without it the service cannot start at all. The library is built from the same pinned
    # sources as the program, plus the small wrapper the service's entry point is in.
    spvc = work / 'spvc'
    spvc.mkdir(exist_ok=True)
    for n in B.SPIRV_CROSS_SOURCES:
        sh([cxx, *flags, '-fPIC', '-c', src / n, '-o', spvc / (n + '.o')])
    sh([cxx, *flags, '-fPIC', '-I', src, '-c', mng / 'games/totk/tools/totk_xlate/spirv_cross_inproc.cpp',
        '-o', spvc / 'spirv_cross_inproc.o'])
    # Windows: the service's DllImport("totk_spirv_cross") needs a library of that name, and the NativeAOT link
    # needs an import library for it. A MinGW shared library exports every symbol it defines, so the DLL would
    # carry the C++ symbols of SPIRV-Cross as well. A .def file names the two entry points the service calls and
    # nothing else, and the import library is made from it (dlltool). The library is named totk_spirv_cross.dll,
    # the name the service loads.
    if windows:
        def_file = work / 'totk_spirv_cross.def'
        def_file.write_text('LIBRARY totk_spirv_cross\n'
                            'EXPORTS\n'
                            '    totk_spirv_cross_msl\n'
                            '    totk_spirv_cross_free\n')
        sh([cxx, '-shared', '-fPIC', *[spvc / (n + '.o') for n in B.SPIRV_CROSS_SOURCES],
            spvc / 'spirv_cross_inproc.o', '-o', str(out / 'totk_spirv_cross.dll'), str(def_file)])
        # The import library is made from the .def file: dlltool's -d is the def file it reads, -l the library it writes.
        sh(['dlltool', '-d', str(def_file), '-l', str(out / 'totk_spirv_cross.lib')])
    else:
        sh([cxx, '-shared', '-fPIC', *[spvc / (n + '.o') for n in B.SPIRV_CROSS_SOURCES],
            spvc / 'spirv_cross_inproc.o', '-o', out / 'libtotk_spirv_cross.so'])

    # the shader translator
    prebuilt = mng / 'games/totk/prebuilt/macos-arm64/totk_xlate'
    if sys.platform == 'darwin' and platform.machine() == 'arm64':
        if B.sha256(prebuilt) != (prebuilt.parent / 'totk_xlate.sha256').read_text(encoding='utf-8').strip():
            raise SystemExit('the prebuilt translator does not match its .sha256')
        shutil.copy2(prebuilt, out / 'totk_xlate')
    else:
        rid = {('linux', 'x86_64'): 'linux-x64', ('linux', 'aarch64'): 'linux-arm64', ('win32', 'AMD64'): 'win-x64'}[
            ('linux' if linux else sys.platform, platform.machine())]
        here = mng / 'games/totk/tools/totk_xlate'
        x = work / 'xlate'
        if x.exists():
            shutil.rmtree(x)
        shutil.copytree(mng / 'vendor/ryujinx', x / 'ryujinx-src')
        for d in (x / 'ryujinx-src/src').glob('*/'):
            for sub in ('obj', 'bin'):
                shutil.rmtree(d / sub, ignore_errors=True)
        for p in sorted((here / 'patches').glob('*.patch')):   # git apply: the same on every system (publish_native.sh uses patch)
            # outside any repository (else git apply takes the paths relative to the enclosing checkout)
            sh(['git', 'apply', '-p1', '--whitespace=nowarn', p], cwd=x / 'ryujinx-src',
               env=dict(os.environ, GIT_CEILING_DIRECTORIES=str(x)))
        (x / 'app').mkdir()
        for f in list(here.glob('*.cs')) + [here / 'totk_xlate.csproj']:
            shutil.copy2(f, x / 'app' / f.name)
        # The project links the C++ runtime as -lc++ (macOS). Linux and Windows name it differently, so the flag
        # is replaced with the one of this system (the C# code itself is the same on every system).
        proj = x / 'app/totk_xlate.csproj'
        text = proj.read_text(encoding='utf-8')
        if '<LinkerArg Include="-lc++" />' in text:
            cxx_arg = '-lc++' if sys.platform == 'darwin' else '-lstdc++' if linux else ''
            if cxx_arg:
                text = text.replace('<LinkerArg Include="-lc++" />', f'<LinkerArg Include="{cxx_arg}" />')
            else:
                text = text.replace('    <LinkerArg Include="-lc++" />\n', '')
            proj.write_text(text)
        sh([a.dotnet, 'publish', x / 'app/totk_xlate.csproj', '-c', 'Release', '-r', rid, '-p:PublishAot=true',
            '-p:InvariantGlobalization=true', f'-p:RyuSrc={x / "ryujinx-src"}',
            f'-p:TotkSpirvCrossLib={out / ("totk_spirv_cross.lib" if windows else "libtotk_spirv_cross.so")}',
            '-o', x / 'out'])
        shutil.copy2(x / f'out/totk_xlate{exe}', out / f'totk_xlate{exe}')
        # The translator must carry the fixes its sources describe: a translator that ignores the job's
        # early_fragment_tests flag (the chain v8 fix, 2026-10-22) silently drops [[early_fragment_tests]] from
        # the MSL, and the game then tests depth after the shader (the dotted lattice of the Great Sky Island).
        # The flag's name is in the binary when it is read (.NET keeps its string literals as UTF-16), so its
        # absence means the binary is older than the sources it was built from. The kit builds the translator
        # from the sources it ships, so this must hold.
        built = (out / f'totk_xlate{exe}').read_bytes()
        if not any(b'early_fragment_tests' in enc for enc in
                   (b'early_fragment_tests', 'early_fragment_tests'.encode('utf-16-le'))):
            raise SystemExit('the built translator does not read early_fragment_tests: it is older than the '
                             'sources it was built from; the shaders would lose [[early_fragment_tests]]')
    for name in ('hactool', 'spirv-cross', 'totk_xlate'):
        (out / (name + exe)).chmod(0o755)
    print('tools ready:', ', '.join(sorted(p.name for p in out.iterdir())))


if __name__ == '__main__':
    main()
