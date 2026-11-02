# Build the TOTK IPA and the game resources (no Mac needed)

Short guide to make a Tears of the Kingdom IPA for iPhone/iPad and the separate game resources,
on **Linux, Windows or a Mac**.

> **Legal note — read this first.**
> You must supply **your own** game dump and **your own** `prod.keys`. Both are needed to decrypt the
> game; neither is in this repository, and neither may be obtained from it.
> - `prod.keys` are the console's encryption keys. Dump them from **your own Switch**.
> - The base game (1.0.0) and the 1.4.3 update must be dumped from **your own** cartridge or your own
>   installed game.
> - Doing this for a game you do not own, or distributing the result, is illegal in most countries.
> - The IPA and the resources contain the game itself. **They are for your own use only. Do not share
>   them, and do not upload them anywhere.**
> - This project is not affiliated with or endorsed by Nintendo.

---

## 1. What you need

| | |
|---|---|
| Computer | Linux x64, Windows x64, or an Apple silicon Mac. **No Mac required** (see §5). |
| Kit | `totk-ipa-kit-linux-x64.tar.gz` / `totk-ipa-kit-macos-arm64.tar.gz` from Releases, or `TOTK-ipa-Setup.exe` on Windows. |
| Base game | 1.0.0 as `.xci` **or** `.nsp`, dumped from your own Switch. |
| Update | 1.4.3 as `.nsp` or `.nsz` (`.nsz` is decompressed for you). |
| Keys | Your own `prod.keys`, dumped from the same Switch. |
| Fonts | Only if the base game is an `.nsp`: your console's **firmware** dump, or the six `.bfttf` files extracted from it. An `.xci` carries them already. |
| Python | 3.14+ on Linux/Mac (`uv python install 3.14`). The Windows installer brings its own. |
| Disk | ~60 GB free (80 GB on Windows). |
| Phone | iPhone 14+ or a recent iPad, iOS/iPadOS 26, plus a sideloading tool (xtool, Sideloadly, AltStore…). |

---

## 2. Get the kit

**Windows:** run `TOTK-ipa-Setup.exe`. It installs its own Python and opens **TOTK IPA Builder**, which asks
for your game files, your keys, your fonts and the output path, then builds the IPA.

**Linux / Mac:**

```sh
tar xzf totk-ipa-kit-linux-x64.tar.gz
cd totk-ipa-kit-linux-x64
```

---

## 3. Prepare the game files

The kit takes the base game as an `.xci` or an `.nsp` and the update as an `.nsp` or an `.nsz`.

**Convert a compressed update (`.nsz` → `.nsp`)** — the import tool does this on its own, but to do it
separately:

```sh
python3.14 tools/convert_game.py update ~/Games/update.nsz --keys ~/keys/prod.keys --output-dir ~/Games
```

**Check what a game file contains:**

```sh
python3.14 tools/convert_game.py info ~/Games/base.nsp --keys ~/keys/prod.keys
```

**Get the system fonts (only for an `.nsp` base game).** An NSP has no system fonts, so they come from
your console's firmware:

```sh
# 1. check the firmware dump holds them
python3.14 tools/scan_firmware.py <firmware-nca-dir> --keys ~/keys/prod.keys

# 2. extract the six fonts (verifies the NCA headers, all IVFC levels and each BFTTF header)
python3.14 tools/extract_shared_fonts.py --firmware <firmware-nca-dir> \
        --keys ~/keys/prod.keys --output ~/Games/shared-fonts
```

You can pass the firmware directory straight to the import tool with `--firmware <dir>` instead, or the
extracted folder with `--shared-fonts <dir>`.

---

## 4. Build

```sh
python3.14 totk_import.py ~/Games/base.nsp \
    --update ~/Games/update.nsp \
    -k ~/keys/prod.keys \
    --shared-fonts ~/Games/shared-fonts \
    -o ~/Games/TOTK.ipa
```

It verifies every file against the hashes of the supported versions, rewrites the game's code for Apple
chips, decrypts the data (17 GB), translates the startup shaders and writes the IPA (~18 GB).
Re-running the command reuses the finished steps (work folder: `TOTK_ipa_build` next to the game file).

### Keep the game resources out of the IPA

Add `--split-resources`. The IPA drops to ~200 MB; the 17 GB image and the shaders are written
**beside** it, in `TOTK-resources/`, and you copy that folder to the phone yourself.

```sh
python3.14 totk_import.py ~/Games/base.nsp --update ~/Games/update.nsp -k ~/keys/prod.keys \
    --shared-fonts ~/Games/shared-fonts -o ~/Games/TOTK.ipa --split-resources
```

The resources folder holds:

- `romfs.bin.000`, `romfs.bin.001`, … — the game image in 1 GiB parts (a single 17 GB file does not
  copy onto a phone reliably; the app reads the parts in place).
- `romfs.sha256` — the image's hash. The app reads it as the mark of a finished copy, so **copy it
  last**, or the app thinks the copy is still running.
- `shader-seed-<name>.pack.000`, … — the startup shaders as one packed stream (a folder of 64,000
  small files drops halfway on a phone; the app unpacks the pack on first start). The pack also
  carries the warm-up lists: `pso_list.tsv` (the render pipelines the phone compiles ahead of the
  first play, each naming a shader the seed actually carries), `pso_title.tsv` and `pso_manifest.tsv`.
- `shader-seed.txt` — which pack to unpack, and the fingerprint that says whether the phone has it.
- `shared-fonts/` — the six system fonts.

**Copy the contents** of the folder to the phone with the Files app:

```
Files › On My iPhone › Tears of the Kingdom › GameData
```

Then start the game. A later build of the app keeps these, so you only copy them once.

---

## 5. Install

Sign the IPA with your sideloading tool (xtool, Sideloadly, AltStore…) and keep its entitlements: the
game needs the increased memory limit. The IPA is ad-hoc signed, so it needs a jailbroken device or a
sideloading tool.

**The IPA contains the game made from your files. For your own use only — do not share it.**

---

## 5a. The on-screen controller

The pad is drawn in *Breath of the Wild*'s style: the A/B/X/Y diamond, the D-pad, both sticks and the
shoulder buttons.

- **Both sticks are drawn at rest**, so you see where they are before you touch them. A finger inside a
  stick's ring grabs that stick; a finger on a ring's edge is not a "nearest control" contest any more.
- **The right stick follows a swipe.** A touch on no control in the right third of the screen holds the
  right stick where it lands, and the ring follows it, so the camera can be turned without looking at
  the pad.
- **The ⊙ button at the top centre** (next to the frame-rate button) shows and hides the whole overlay.
  With a Bluetooth controller connected the pad hides itself; press ⊙ to bring it back for that session,
  or press it once with no controller to keep the picture clear between launches (the choice is
  remembered).
- **Physical controllers** map by position, as on a Switch controller: bottom = B, right = A,
  left = Y, top = X. A Nintendo controller (Switch Pro, Joy-Con) keeps its own labels instead.
- The **frame-rate button** (the number at the top centre) switches between 60 and 30 as it is held.

---

## 6. Why no Mac is needed

The one step that genuinely needs a Mac is compiling the app shell: Apple's Metal compiler and the iOS
SDK run only on macOS. The kit's GitHub Actions workflow does that step on a **macOS runner** and
publishes the finished shell in the release — so you get a prebuilt shell and only inject your own game
files into it locally.

Because the shell is prebuilt and built on macOS, three things differ from a Mac build:

- **Shaders compile on the phone.** A Mac precompiles them with Apple's Metal compiler; without it,
  each shader compiles on the phone the first time it is used, so the first launches stutter more until
  the phone's shader cache fills. The kit ships a **warm-up list** (`pso_list.tsv` in the shader pack)
  that names, for each render pipeline, the exact shader variants the seed carries, so the phone
  compiles them ahead of the first play instead of during it. The list is *resolved* against the seed
  (`shader_list.py resolve`), not exported from the shared list: an export names 60% of variants the
  seed does not have, and the runtime skips those rows silently.
- **Game data is loaded at startup** from `GameData/totk-late.bin` instead of being compiled in.
- **The game code goes into reserved space** in the executable, which is then signed again (ad hoc).
  The phone still checks every patched instruction and every embedded hash on start.

To build the kit yourself (maintainers), run the **Build TOTK-ipa kit** workflow in Actions. It builds
the shell on macOS, builds hactool / SPIRV-Cross / the shader translator for Linux, macOS and Windows,
packages the Windows installer, runs the self-tests, and publishes the release.

---

## 7. Scripts

In a release kit (`totk-ipa-kit-*.tar.gz`) the scripts sit in `tools/`, next to the import tool. In a
checkout of this repository they sit in `kit/tools/`.

| Script | What it does |
|---|---|
| `totk_import.py` | The build. Extracts, verifies, rewrites, translates the shaders, writes the IPA and (with `--split-resources`) the resources folder. |
| `tools/convert_game.py` | Converts between the game formats (`update` decompresses an `.nsz` update into an `.nsp`; `info` lists the NCAs of an NSP). |
| `tools/scan_firmware.py` | Lists the NCAs of a firmware dump and says whether the shared-font NCAs are all there. |
| `tools/extract_shared_fonts.py` | Extracts and verifies the six shared fonts from a firmware dump. |
| `kit/gui.py` | The Windows builder window. |

Maintainer-only (in this repository, not in the release kit):

| Script | What it does |
|---|---|
| `kit/build_shell.py` | Builds the app shell (needs a Mac). |
| `kit/build_tools.py` | Builds hactool, SPIRV-Cross and the shader translator. |
| `kit/selftest/` | The self-tests the workflow runs. |

The MacNativeGames scripts (ROMFS extraction, the code rewriter, the shader preparation) are fetched by
the workflow into `kit/MacNativeGames/`; the import tool runs them from there.

---

## 8. Troubleshooting

| Message | Cause |
|---|---|
| `an NSP base game has no system fonts` | Pass `--firmware <dir>` or `--shared-fonts <dir>`. |
| `the update is <version>: the iPhone/iPad build needs 1.4.3` | Only 1.4.3 is supported. |
| `needs about 60 GB free` | The work folder needs room for the 17 GB image and its copies. |
| `BKTR verification failed` on the update merge | A dump tool rewrote the ACID block. `hactool` reports `Signature (FAIL)` for every retail dump because its struct has the fields in the wrong order — the merge itself is fine. |
| The game starts but the screen is very dark | The shader translator is older than the `early_fragment_tests` fix. Rebuild it with `kit/build_tools.py` (the build refuses to finish without that flag) and regenerate the seed. |

---

Based on [MacNativeGames](https://github.com/ly05010419/MacNativeGames) (MIT). Not affiliated with
Nintendo. You must own the game.
