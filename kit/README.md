# TOTK-ipa kit

Make a Tears of the Kingdom IPA for iPhone and iPad from **your own** game dump and keys, on Windows, Linux or a
Mac. The kit is built by GitHub without any game file. Your dump and `prod.keys` stay on your computer.

It is built on [MacNativeGames](https://github.com/ly05010419/MacNativeGames), which does the real work: it rewrites the
game's code for Apple chips and rebuilds its graphics on Metal. This kit only moves the game-specific steps of its iOS
build from a Mac to your computer.

**See [BUILD_GUIDE.md](BUILD_GUIDE.md) for the full guide** (requirements, the NSP/NSZ conversion scripts, the build
commands, how to keep the game resources out of the IPA, and how to copy them to the phone).

> **You must supply your own dump and your own `prod.keys`, both from your own Switch.** Neither is in this kit, and
> neither may be obtained from it. The IPA contains the game made from your files: for your own use only, do not share it.

## Windows

Download **TOTK-ipa-Setup.exe** from this repository's Releases and run it. It needs no administrator rights and
installs its own Python. When it finishes, **TOTK IPA Builder** opens. It asks for:

- your base game,
- the 1.4.3 update,
- your `prod.keys`,
- the system fonts (only for an `.nsp` base game),
- where to save the IPA.

Then press **Build** and watch the log. If something stops the build, fix it and press Build again: finished steps are
reused. You can open the builder again from the Start menu.

## What you need

- On Windows, the installer above. Otherwise, the kit for your computer from this repository's Releases:
  `totk-ipa-kit-linux-x64.tar.gz` (Linux) or `totk-ipa-kit-macos-arm64.tar.gz` (Apple silicon Mac).
- **Base game 1.0.0** (`.xci`, or `.nsp`) **and the 1.4.3 update** (`.nsp` or `.nsz`), dumped from your Switch.
  1.4.3 is the only version MacNativeGames has tested on iPhone and iPad.
- Your `prod.keys`, from the same Switch.
- An NSP base game only: the system fonts, as `--firmware <unpacked firmware NCAs>` or
  `--shared-fonts <folder with the six .bfttf files>`. An XCI has them.
- Linux and Mac: Python 3.14 or newer (`uv python install 3.14` gets it). The Windows installer brings its own.
- About 60 GB of free disk space (80 GB on Windows).
- An iPhone 14 or newer (or a recent iPad) on iOS/iPadOS 26, and a sideloading tool: xtool, Sideloadly, AltStore…

## Make the IPA (Linux and Mac)

```sh
tar xzf totk-ipa-kit-linux-x64.tar.gz
cd totk-ipa-kit-linux-x64
python3.14 totk_import.py ~/Games/totk.xci --update ~/Games/totk-1.4.3.nsp -k ~/keys/prod.keys -o ~/Games/TOTK.ipa
```

The import runs MacNativeGames' own steps on your files:

1. Check every file against the hashes of the supported versions.
2. Rewrite the code and decrypt the data (17 GB).
3. Prepare the startup shaders.

Then it puts the result into the app shell and writes the IPA. The IPA is about 18 GB. Running the command again reuses
the work already done; the work folder is `TOTK_ipa_build` next to the game file.

Sign and install the IPA with your sideloading tool, keeping its entitlements: the game needs the increased memory limit.

**The IPA contains the game made from your files. It is for your own use only: do not share it.**

## The scripts

`tools/` holds the helpers that prepare the game files before the build. They are standalone: they need
`cryptography` (in the kit's Python environment) and nothing else.

| Script | What it does |
|---|---|
| `tools/convert_game.py update <file.nsz> --keys <prod.keys> --output-dir <dir>` | Decompresses a compressed update into an `.nsp`, with the NCA hash verification. The import tool does this on its own too. |
| `tools/convert_game.py info <file.nsp> --keys <prod.keys>` | Lists the NCAs of an NSP: their title ID, content type and size. |
| `tools/scan_firmware.py <firmware-nca-dir> --keys <prod.keys>` | Lists the NCAs of a firmware dump and says whether the shared-font NCAs are all there. |
| `tools/extract_shared_fonts.py --firmware <firmware-nca-dir> --keys <prod.keys> --output <dir>` | Extracts the six shared fonts from a firmware dump, verifying the NCA headers, all six IVFC levels and each BFTTF header. Only needed for an `.nsp` base game. |

## The on-screen controller

The pad is drawn in *Breath of the Wild*'s style: the A/B/X/Y diamond, the D-pad, both sticks and the shoulder buttons.

- **Both sticks are drawn at rest**, so you see where they are before you touch them. A finger inside a stick's ring
  grabs that stick; a finger on a ring's edge is not a "nearest control" contest any more.
- **The right stick follows a swipe.** A touch on no control in the right third of the screen holds the right stick
  where it lands, and the ring follows it, so the camera can be turned without looking at the pad.
- **The ⊙ button at the top right of the + button** shows and hides the whole overlay. With a
  Bluetooth controller connected the pad hides itself; press ⊙ to bring it back for that session, or press it once
  with no controller to keep the picture clear between launches (the choice is remembered).
- **Physical controllers** map by position, as on a Switch controller: bottom = B, right = A, left = Y, top = X. A
  Nintendo controller (Switch Pro, Joy-Con) keeps its own labels instead.
- The **frame-rate button** (the number at the top centre) switches between 60 and 30 as it is held.

## Keeping the game resources out of the IPA

With `--split-resources` the IPA is about 200 MB: the 17 GB game image and the startup shaders are written **beside** it,
in a folder named after the IPA (`Tears of the Kingdom-resources`). You copy that folder to the phone yourself, and the
app reads it from there.

    40|python3.14 totk_import.py ~/Games/totk.xci --update ~/Games/totk-1.4.3.nsp -k ~/keys/prod.keys \
        -o ~/Games/TOTK.ipa --split-resources

The resources folder holds:

- `romfs.bin.000`, `romfs.bin.001`, …: the game image in parts of 1 GiB. A single 17 GB file cannot be copied onto a
  phone reliably, so it is split; the app reads the parts in place.
- `romfs.sha256`: the image's hash. The app reads it as the mark of a finished copy, so copy it **last**, or the app
  thinks the copy is still running.
- `shader-seed-<name>.pack.000`, …: the startup shaders as one packed stream. The seed holds 64,000 small files, which a
  folder copy onto the phone drops halfway; the app unpacks the pack on its first start.
- `shader-seed.txt`: which pack to unpack, and the fingerprint that says whether the phone already has it.

Copy the whole folder into the app's folder on the phone, with the Files app:

    Files › On My iPhone › Tears of the Kingdom › GameData

(The app's folder is named after the app in the Files app: **Tears of the Kingdom**.) Then start the game: it reads the
image and the shaders from there. A later build of the app keeps them, so you only copy them once.

## What is different from building on a Mac

- **Shaders compile on the phone.** A Mac precompiles the startup shaders with Apple's Metal compiler, which runs only on
  Apple systems. Without it, each shader compiles on the phone the first time it is used, so the first launches stutter
  more until the phone's shader cache fills. The kit ships a **warm-up list** (`pso_list.tsv` in the shader pack) that
  names, for each render pipeline, the exact shader variants the seed carries, so the phone compiles them ahead of the
  first play instead of during it. The list is *resolved* against the seed (`shader_list.py resolve`), not exported from
  the shared list: an export names 60% of variants the seed does not have, and the runtime skips those rows silently.
- **Game data is loaded at startup.** The game's tables are read from `GameData/totk-late.bin` when the app starts,
  instead of being compiled into it.
- **The game code goes into reserved space.** It is placed into empty sections the shell reserved for it, and the
  executable is signed again (ad hoc) afterwards.
- **Checks still run on the phone.** The phone checks every patched instruction and the hash of every embedded code
  part when it starts, as it does with a Mac build. A mistake stops the start with a message rather than running wrong
  code.

## Building the kit (maintainers)

The kit is built by the **Build TOTK-ipa kit** workflow (Actions → Run workflow). It builds:

- **App shell:** on a macOS 26 machine it builds MacNativeGames' iOS app with `kit/build_shell.py`.
- **Helper tools:** it builds hactool, SPIRV-Cross and the shader translator for Linux, macOS and Windows with
  `kit/build_tools.py`.
- **Windows installer:** it puts the Windows tools, the Python packages, a private Python 3.14 and the builder window
  (`kit/gui.py`) into `TOTK-ipa-Setup.exe` with Inno Setup (`kit/windows/installer.iss`).
- **Self-tests:** they check that:
  - the Python port of the 1.4.3 code patches writes exactly what MacNativeGames' C code writes;
  - the filled executable passes `codesign --verify`;
  - the tables file round-trips through the app's reader;
  - on Windows, the environment, embedding and IPA writing work on synthetic files, and the builder window's pages and
    checks behave.

It then publishes the installer and the two kits as a release.
