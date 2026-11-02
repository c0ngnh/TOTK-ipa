# TOTK-ipa

Build an iPhone/iPad IPA of Tears of the Kingdom from **your own** dump, without a Mac and without uploading your game
anywhere.

GitHub builds a game-free kit: the app shell (MacNativeGames' iOS app with empty space for the game) and the helper
tools. You download the kit and run its import script with your dump and `prod.keys`. The script makes the IPA on your
computer, and you sideload it.

## Start here

**[BUILD_GUIDE.md](BUILD_GUIDE.md)** — the full guide: requirements, the NSP/NSZ conversion scripts, the build commands,
how to keep the game resources out of the IPA, how to copy them to the phone, and the on-screen controller.

- **Windows players:** download `TOTK-ipa-Setup.exe` from Releases and run it. The builder it installs asks for your
  game files and makes the IPA.
- **Linux and Mac players:** download the kit from Releases and follow [kit/README.md](kit/README.md).
- **Maintainers:** run the **Build TOTK-ipa kit** workflow in Actions to build and publish the kit. It builds from the
  MacNativeGames commit in `kit/MNG_COMMIT`; to move to a newer one, change that file and let the self-tests confirm.

## What is in the kit

| | |
|---|---|
| `kit/totk_import.py` | The build: your dump in, an IPA and (with `--split-resources`) the game resources out. |
| `kit/shim/touch_pad_botw.m` | The on-screen controller, in *Breath of the Wild*'s style. |
| `kit/tools/` | The game-file scripts: `convert_game.py`, `scan_firmware.py`, `extract_shared_fonts.py`. |
| `kit/selftest/` | The self-tests the workflow runs. |

The on-screen pad draws both sticks at rest, lets the right stick follow a swipe, and has a ⊙ button at the top
centre that shows and hides the overlay (handy with a Bluetooth controller). Physical controllers map by position, as
on a Switch controller. See [BUILD_GUIDE.md](BUILD_GUIDE.md) §5a.


## Legal

You must provide **your own** game dump and **your own** `prod.keys`, dumped from **your own** Switch. Neither is in this
repository, and neither may be obtained from it. Doing this for a game you do not own, or distributing the result, is
illegal in most countries. The IPA and the resources contain the game itself: **for your own use only — do not share
them, and do not upload them anywhere.**

Based on [MacNativeGames](https://github.com/ly05010419/MacNativeGames) (MIT). Not affiliated with Nintendo. You must
own the game; the IPA you make contains it and is for your own use only.
