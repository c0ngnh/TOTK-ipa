#!/usr/bin/env python3
"""TOTK-ipa: the check of the kit's own patches (kit/shim/apply_patches.py).

The patches are edits of the upstream tree, so every one of them must still find exactly its text, and the result must
hold what the patch says it does. The check needs no game file and no key: it reads the patched tree only.

    patch_check.check(tree)     the tree is games/totk of a MacNativeGames checkout, already patched
"""
import plistlib
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent


def check(tree):
    tree = Path(tree)

    # #1: the frame rate is the display's rate, not a hard 60.
    shell = (KIT / 'build_shell.py').read_text()
    assert 'TOTK_UNCAPPED_HZ","display"' in shell, 'the uncapped clock must follow the display'
    assert 'TOTK_UNCAPPED_HZ","60"' not in shell, 'the hard 60 ceiling must be gone'

    # #2: the controller's Home and Capture buttons are the system's no more.
    gamepad = (tree / 'runtime/gamepad.m').read_text()
    assert 'pad_keep_system_buttons' in gamepad, 'the system gestures are not disabled'
    assert 'preferredSystemGestureState = GCSystemGestureStateDisabled' in gamepad, 'the gesture state is not set'
    assert 'GCInputButtonHome' in gamepad and 'GCInputButtonShare' in gamepad, 'Home and Share must both be taken'
    assert gamepad.count('pad_keep_system_buttons(controller);') == 1, 'the buttons are taken once, when a pad attaches'

    # #4: the split image is mapped in memory, part by part.
    romfs = (tree / 'runtime/romfs.c').read_text()
    assert 'image_maps' in romfs, 'the parts are not mapped'
    assert 'image_mapped_read' in romfs, 'the read path does not use the mappings'
    assert 'if(!nchunks&&getenv("TOTK_ROMFS_MMAP")' not in romfs, 'the fast path must not be limited to a single file'
    assert 'mmap(NULL,(size_t)len,PROT_READ,MAP_PRIVATE,chunk_fds[c],0)' in romfs, 'the parts are not mapped'
    # The mapping is only useful if the read path prefers it.
    read_at = romfs.index('image_mapped_read(buffer')
    assert read_at < romfs.index('src_pread(fd,(uint8_t *)buffer+done'), 'the mappings must come before pread'

    # #3 and #6: the phone's own settings are in the app.
    settings = (tree / 'ios/Sources/phone_extra.m').read_text()
    assert 'NSProcessInfoThermalStateDidChangeNotification' in settings, 'the thermal state is not watched'
    assert 'NSProcessInfoPowerStateDidChangeNotification' in settings, 'Low Power Mode is not watched'
    assert 'lowPowerModeEnabled' in settings, 'Low Power Mode is not read'
    assert 'os_proc_available_memory' in settings, 'the memory is not read'
    assert 'runtime_phone_fps_set' in settings, 'the frame cap is not lowered'
    main_m = (tree / 'ios/Sources/main.m').read_text()
    assert 'phone_settings_start();' in main_m, 'the watcher does not start'
    assert 'developerHUDProperties' in main_m, 'the Metal HUD is not turned on'
    start = (tree / 'ios/Sources/start_screen.m').read_text()
    assert 'phone_available_memory()' in start, 'the memory is not on the start screen'
    assert 'memory, _start' in start, 'the memory readout is not on the screen'

    # #7: the frame interpolation is in the Settings pane.
    root_plist = plistlib.loads((tree / 'ios/Settings.bundle/Root.plist').read_bytes())
    keys = [s.get('Key') for s in root_plist['PreferenceSpecifiers']]
    assert 'TOTK_MFX' in keys, 'the frame interpolation row is missing'
    assert 'TOTK_METAL_HUD' in keys, 'the Metal HUD row is missing'
    row = next(s for s in root_plist['PreferenceSpecifiers'] if s.get('Key') == 'TOTK_MFX')
    assert row['DefaultValue'] == '0', 'the interpolation is off by default'
    assert set(row['Values']) <= {'0', 'interp30', 'interp40', 'interp50', 'interpmax', 'interp60'}, row['Values']
    # The runtime reads the mode from TOTK_MFX, so the pane's value reaches it as that variable.
    assert 'getenv("TOTK_MFX")' in (tree / 'third_party/d2r_gfx/gfx/nvn/totk_mfx.m').read_text(), \
        'the runtime does not read TOTK_MFX'

    # The kit's own files must not shadow an upstream one: the app's sources are compiled together, and two
    # headers of the same name in the same folder means one of them silently wins (the kit's phone_extra.h once
    # replaced the game's own phone_settings.h, and the build failed on the missing totk_phone_setting_enabled).
    for name in ('phone_extra.h', 'phone_extra.m'):
        for folder in (tree / 'ios/Sources', tree / 'runtime'):
            for other in folder.iterdir() if folder.is_dir() else []:
                assert other.name != name or folder == tree / 'ios/Sources', \
                    f'{name} shadows the upstream {folder.name}/{other.name}'
    upstream_settings = tree / 'ios/Sources/phone_settings.h'
    assert upstream_settings.is_file(), 'the game\'s own phone_settings.h must still be there'
    assert 'totk_phone_setting_enabled' in upstream_settings.read_text(), 'the game\'s own header changed'

    # The pane's rows are bilingual, so the game's own localisation can split them.
    for spec in root_plist['PreferenceSpecifiers']:
        for field in ('Title', 'FooterText'):
            text = spec.get(field)
            if text and ('帧' in text or '補' in text or '内存' in text):
                assert ' · ' in text, f'{field} of {spec.get("Key")} is not bilingual: {text}'

    # The rows the kit adds must not disturb the pane's own order.
    assert keys.index('TOTK_MFX') > keys.index('TOTK_TAA'), 'the interpolation row must follow the MetalFX group'
    assert keys.index('TOTK_METAL_HUD') > keys.index('TOTK_FPS_OVERLAY'), 'the HUD row belongs to the interface group'

    print('patches checked: uncapped clock, controller gestures, split image in memory, thermal state, memory readout, '
          'Metal HUD and the frame interpolation row', flush=True)
