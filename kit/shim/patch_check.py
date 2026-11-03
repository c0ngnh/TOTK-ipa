#!/usr/bin/env python3
"""TOTK-ipa: the check of the kit's own patches (kit/shim/apply_patches.py).

The patches are edits of the upstream tree, so every one of them must still find exactly its text, and the result must
hold what the patch says it does. The check needs no game file and no key: it reads the patched tree only.

    patch_check.check(tree)     the tree is games/totk of a MacNativeGames checkout, already patched
"""
import plistlib
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent


def check(tree):
    tree = Path(tree)

    # #1: the frame rate is the display's rate, not a hard 60.
    shell = (KIT / 'build_shell.py').read_text(encoding='utf-8')
    assert 'TOTK_UNCAPPED_HZ","display"' in shell, 'the uncapped clock must follow the display'
    assert 'TOTK_UNCAPPED_HZ","60"' not in shell, 'the hard 60 ceiling must be gone'

    # #2: the controller's Home and Capture buttons are the system's no more.
    gamepad = (tree / 'runtime/gamepad.m').read_text(encoding='utf-8')
    assert 'pad_keep_system_buttons' in gamepad, 'the system gestures are not disabled'
    assert 'preferredSystemGestureState = GCSystemGestureStateDisabled' in gamepad, 'the gesture state is not set'
    assert 'GCInputButtonHome' in gamepad and 'GCInputButtonShare' in gamepad, 'Home and Share must both be taken'
    assert gamepad.count('pad_keep_system_buttons(controller);') == 1, 'the buttons are taken once, when a pad attaches'

    # #4: the split image is mapped in memory, part by part.
    romfs = (tree / 'runtime/romfs.c').read_text(encoding='utf-8')
    assert 'image_maps' in romfs, 'the parts are not mapped'
    assert 'image_mapped_read' in romfs, 'the read path does not use the mappings'
    assert 'if(!nchunks&&getenv("TOTK_ROMFS_MMAP")' not in romfs, 'the fast path must not be limited to a single file'
    assert 'mmap(NULL,(size_t)len,PROT_READ,MAP_PRIVATE,chunk_fds[c],0)' in romfs, 'the parts are not mapped'
    # The mapping is only useful if the read path prefers it.
    read_at = romfs.index('image_mapped_read(buffer')
    assert read_at < romfs.index('src_pread(fd,(uint8_t *)buffer+done'), 'the mappings must come before pread'

    # #3 and #6: the phone's own settings are in the app.
    settings = (tree / 'ios/Sources/phone_extra.m').read_text(encoding='utf-8')
    assert 'NSProcessInfoThermalStateDidChangeNotification' in settings, 'the thermal state is not watched'
    assert 'NSProcessInfoPowerStateDidChangeNotification' in settings, 'Low Power Mode is not watched'
    assert 'lowPowerModeEnabled' in settings, 'Low Power Mode is not read'
    assert 'os_proc_available_memory' in settings, 'the memory is not read'
    assert 'runtime_phone_fps_set' in settings, 'the frame cap is not lowered'
    main_m = (tree / 'ios/Sources/main.m').read_text(encoding='utf-8')
    assert 'phone_settings_start();' in main_m, 'the watcher does not start'
    assert 'developerHUDProperties' in main_m, 'the Metal HUD is not turned on'
    start = (tree / 'ios/Sources/start_screen.m').read_text(encoding='utf-8')
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
    assert 'getenv("TOTK_MFX")' in (tree / 'third_party/d2r_gfx/gfx/nvn/totk_mfx.m').read_text(encoding='utf-8'), \
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
    assert 'totk_phone_setting_enabled' in upstream_settings.read_text(encoding='utf-8'), 'the game\'s own header changed'

    # The pane's rows are bilingual, so the game's own localisation can split them.
    for spec in root_plist['PreferenceSpecifiers']:
        for field in ('Title', 'FooterText'):
            text = spec.get(field)
            if text and ('帧' in text or '補' in text or '内存' in text):
                assert ' · ' in text, f'{field} of {spec.get("Key")} is not bilingual: {text}'

    # #8: the shared fonts come from the phone's GameData when it holds them.
    main_fonts = (tree / 'ios/Sources/main.m').read_text(encoding='utf-8')
    assert 'phoneFonts' in main_fonts, 'the phone\'s shared fonts are not read'
    assert 'appFonts' in main_fonts, 'the app\'s own shared fonts are not the fallback'
    assert 'setenv("TOTK_SHARED_FONTS",(phoneHasFonts ? phoneFonts : appFonts).fileSystemRepresentation,1);' in main_fonts, \
        'the phone\'s fonts are not preferred'
    # Every font the manifest names is checked: the runtime ends the game on a font it cannot open.
    assert 'fontList.count' in main_fonts, 'the font list is not read'
    assert 'phoneHasFonts = NO; break;' in main_fonts, 'a missing font does not fall back to the app\'s copy'
    assert '@"fonts"' in main_fonts, 'the manifest\'s font rows are not read'

    # The rows the kit adds must not disturb the pane's own order.
    assert keys.index('TOTK_MFX') > keys.index('TOTK_TAA'), 'the interpolation row must follow the MetalFX group'
    assert keys.index('TOTK_METAL_HUD') > keys.index('TOTK_FPS_OVERLAY'), 'the HUD row belongs to the interface group'
    assert keys.index('TOTK_FACE_SWAP') > keys.index('TOTK_GYRO'), 'the swap row belongs to the controller group'
    # The kit's own rows carry no TOTKApp mark: that mark is the upstream's list of what Breath of the Wild must not
    # show (build_ipa.py settings_without_totk drops every row marked TOTKApp=totk), so a marked kit row would be
    # stripped from the pane again and the player could never reach it.
    for key in ('TOTK_MFX', 'TOTK_METAL_HUD', 'TOTK_FACE_SWAP'):
        kit_row = next(s for s in root_plist['PreferenceSpecifiers'] if s.get('Key') == key)
        assert kit_row.get('TOTKApp') is None, f'{key} is marked TOTKApp, so the pane filter would drop it'

    # #9: the player picks which sensor feeds the game's single six-axis device (the user's request, 2026-11-03).
    runtime_h = (tree / 'runtime/runtime.h').read_text(encoding='utf-8')
    assert 'RUNTIME_MOTION_SOURCE_AUTO' in runtime_h, 'the motion sources are not named'
    assert 'RUNTIME_MOTION_SOURCE_PHONE' in runtime_h, 'the phone\'s own sensor is not one of the sources'
    assert 'RUNTIME_MOTION_SOURCE_CONTROLLER' in runtime_h, 'the controller\'s sensor is not one of the sources'
    assert 'void runtime_motion_source(int source);' in runtime_h, 'the runtime does not take the choice'
    assert 'void runtime_motion_feed_phone(' in runtime_h, 'the phone\'s samples have no door of their own'
    fusion = (tree / 'runtime/motion_fusion.c').read_text(encoding='utf-8')
    assert 'source_allows' in fusion, 'the fusion does not gate the sources'
    # Only the source in force is let through: the gate has to name both the phone and the controller.
    gate = fusion.split('static int source_allows(int who) {', 1)[1].split('}', 1)[0]
    assert 'RUNTIME_MOTION_SOURCE_PHONE' in gate, 'the phone\'s source is not gated'
    assert 'RUNTIME_MOTION_SOURCE_CONTROLLER' in gate, 'the controller\'s source is not gated'
    assert 'feed_source(0, raw_acc, raw_gyro, now)' in fusion, 'the controller does not feed through the gate'
    assert 'feed_source(1, raw_acc, raw_gyro, now)' in fusion, 'the phone does not feed through the gate'
    # The controller's sensors follow the choice, so the two sensors never report at once.
    feedback = (tree / 'runtime/gamepad_feedback.m').read_text(encoding='utf-8')
    assert feedback.count('runtime_motion_source_get() == RUNTIME_MOTION_SOURCE_PHONE') == 2, \
        'the controller\'s sensors must follow the choice, both when they are attached and when the app returns'
    # The app's own API (the on-screen pad's button).
    device_h = (tree / 'ios/Sources/device_motion.h').read_text(encoding='utf-8')
    assert 'totk_device_motion_set_source' in device_h, 'the app has no motion source API'
    assert 'totk_device_motion_source' in device_h, 'the app cannot tell which source is in force'
    phone = (tree / 'ios/Sources/phone_motion.m').read_text(encoding='utf-8')
    assert 'runtime_motion_feed_phone(acc, gyro, runtime_now_ns())' in phone, 'the phone\'s samples do not use their own door'
    assert 'chosen_source' in phone, 'the phone does not remember the choice'
    assert 'TOTK_MOTION_SOURCE' in phone, 'the choice is not kept between launches'
    # A chosen source stands: a touch on the screen must not take the aiming away from it.
    note = phone.split('void totk_device_motion_note_touch(void)', 1)[1].split('}', 1)[0]
    assert 'RUNTIME_MOTION_SOURCE_AUTO' in note, 'a chosen source is still taken away by a touch'
    # The on-screen pad's button: it must be there, next to the pad's own button, and it must reach the app.
    pad = (KIT / 'shim/touch_pad_botw.m').read_text(encoding='utf-8')
    assert 'inMotion:' in pad, 'the pad has no motion source button'
    assert 'switchMotionSource' in pad, 'the motion source button does nothing'
    assert 'totk_device_motion_set_source(next)' in pad, 'the button does not reach the app'
    assert 'TOTK_MOTION_SOURCE' in pad, 'the choice is not kept between launches'

    # #10: the face buttons swapped, so the game sees the Nintendo arrangement (the user's request, 2026-11-03).
    layout_h = (tree / 'runtime/gamepad_layout.h').read_text(encoding='utf-8')
    assert 'gamepad_face_swap' in layout_h, 'the face buttons cannot be swapped'
    assert 'TOTK_FACE_SWAP' in layout_h, 'the swap has no switch of its own'
    swap = layout_h.split('static inline uint64_t gamepad_face_positions_swapped', 1)[1].split('}', 1)[0]
    # The swap exchanges the two pairs: A with B, and X with Y.
    assert 'gamepad_face_positions(b, a, y, x' in swap, 'the swap does not exchange A with B and X with Y'
    gamepad = (tree / 'runtime/gamepad.m').read_text(encoding='utf-8')
    assert 'gamepad_face_positions_swapped(pad.buttonA' in gamepad, 'the controller\'s buttons do not go through the swap'

    # #11: the on-screen pad's own button changes the swap while the game runs (the user's request, 2026-11-03).
    assert 'void runtime_gamepad_face_swap_set(int on);' in runtime_h, 'the runtime does not take the swap'
    assert 'int runtime_gamepad_face_swap(void);' in runtime_h, 'the app cannot tell which swap is in force'
    assert 'runtime_gamepad_face_swap_set(_faceSwap)' in pad, 'the button does not reach the runtime'
    assert 'gamepad_face_swap_set' in layout_h, 'the swap in force is not held by the runtime'
    assert 'TOTK_FACE_SWAP' in pad, 'the choice is not kept between launches'

    # #12: the phone's frame rate has three settings: 30, 60 and uncapped (the user's request, 2026-11-03).
    hle = (tree / 'third_party/d2r_gfx/gfx/nvn/hle_nvn.c').read_text(encoding='utf-8')
    assert 'int runtime_phone_fps(void);' in runtime_h, 'the runtime does not tell the app the rate'
    assert '0 (uncapped)' in runtime_h, 'the runtime does not name the uncapped rate'
    # The rate in force is one number, so the button's cycle and the runtime agree.
    rate = hle.split('int runtime_phone_fps(void) {', 1)[1].split('\n}\n', 1)[0]
    assert 'v == 0 ? 0' in rate, 'the uncapped rate is not one of the runtime\'s rates'
    setter = hle.split('void runtime_phone_fps_set(int fps) {', 1)[1].split('\n}\n', 1)[0]
    assert 'fps != 0' in setter, 'the runtime does not take the uncapped rate'
    # The uncapped setting raises the ceiling above the display's rate.
    assert 'PHONE_UNCAPPED_HZ' in hle, 'the phone\'s uncapped ceiling is missing'
    assert 'effective_hz()' in hle, 'the rate the game is paced at does not follow the setting'
    # The held rate still wins over the uncapped one.
    assert 'game_hold_fps()' in hle.split('static int effective_hz(void) {', 1)[1].split('\n}\n', 1)[0], \
        'the uncapped setting would overrule the held rate'

    # #13: the Settings pane's frame-rate rows know the third setting.
    preset = next(s for s in root_plist['PreferenceSpecifiers'] if s.get('Key') == 'TOTK_PHONE_FPS')
    assert 'uncapped' in preset['Values'], 'the preset row does not offer the uncapped setting'
    cap = next(s for s in root_plist['PreferenceSpecifiers'] if s.get('Key') == 'TOTK_FPS_CAP')
    assert 'uncapped' in cap['Values'], 'the custom row does not offer the uncapped setting'
    settings_map = (tree / 'ios/Sources/settings_map.c').read_text(encoding='utf-8')
    assert 'totk_frame_button_target(int current)' in settings_map, 'the button\'s cycle is not three-way'
    cycle = settings_map.split('int totk_frame_button_target(int current) {', 1)[1].split('\n}\n', 1)[0]
    assert 'if (current == 30) return 60;' in cycle, 'the cycle does not go 30 → 60'
    assert 'if (current == 60) return 0;' in cycle, 'the cycle does not go 60 → uncapped'
    assert 'return 30;' in cycle, 'the cycle does not come back to 30'
    # The button's three settings are what the runtime knows.
    assert 'totk_frame_button_target(runtime_phone_fps())' in pad, 'the button does not cycle the runtime\'s rate'

    # #16: the stick clicks (L3 / R3) are on the pad, outboard of the shoulders (the user's request, 2026-11-04).
    # The enum's B_LS / B_RS are the Npad's L3 / R3 (bits 4 and 5), so the buttons reach the game as the right ones.
    assert 'B_LS' in pad and 'B_RS' in pad, 'the stick clicks are not in the pad\'s button list'
    assert '@"L3"' in pad and '@"R3"' in pad, 'the stick clicks carry no label'
    # They must be drawn: the loop over the locked keys never reaches them, so they need their own.
    assert 'for (int b = B_LS; b <= B_RS; b++)' in pad, 'the stick clicks are never drawn'
    # And they must be hit: a tap on one is a button press, not a missed touch.
    assert '- (int)clickAt:(CGPoint)p' in pad, 'the stick clicks cannot be hit'
    assert 'int click = [self clickAt:p];' in pad, 'a tap on a stick click is not handled'
    assert 'C_BTN | (click << 8)' in pad, 'a tap on a stick click does not press the button'
    # They sit outboard of the shoulders, so the shoulders must not steal their touches, and the other way round.
    assert 'overClick' in pad, 'the shoulders and the stick clicks can claim the same touch'
    assert '![self overClick:p]' in pad, 'the shoulders do not give the stick clicks priority'
    # The layout: L3 is left of ZL, R3 right of ZR.
    click_x = int(pad.split('K_CLICK_X = ')[1].split(',')[0])
    zl_x = int(pad.split('K_ZL_X = ')[1].split(',')[0])
    assert click_x < zl_x, 'L3 is not outboard of ZL'

    # #15: the phone's GameData folder is made for the player (the user's request, 2026-11-04).
    main_data = (tree / 'ios/Sources/main.m').read_text(encoding='utf-8')
    assert 'createDirectoryAtPath:gameData' in main_data, 'the phone\'s GameData folder is not made for the player'
    # It must be made before the folder is looked in, or the first launch would still say there is no game data.
    assert main_data.index('createDirectoryAtPath:gameData') < main_data.index(
        'fileExistsAtPath:[gameData stringByAppendingPathComponent:@"romfs.bin"]'), \
        'the GameData folder is made after it is looked in'

    print('patches checked: uncapped clock, controller gestures, split image in memory, thermal state, memory readout, '
          'Metal HUD, the frame interpolation row, the shared fonts, the motion source, the face buttons\' swap and the '
          'uncapped frame rate',
          flush=True)


if __name__ == '__main__':
    # The patched tree: apply_patches.main(tree) has already run on it.
    check(Path(sys.argv[1]).resolve())
