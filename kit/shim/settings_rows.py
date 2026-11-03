#!/usr/bin/env python3
"""TOTK-ipa: the rows the kit adds to the Settings pane (the game pane is copied and changed here).

Two rows are added:
  - TOTK_MFX: the MetalFX frame interpolation. The runtime has it (gfx/nvn/totk_mfx.m) and its own settings panel can
    turn it on, but that panel is Mac only (runtime_settings_toggle is empty on iOS), so the row was unreachable on the
    phone. The runtime reads the mode from TOTK_MFX at its start (mfx_init), so the pane's value is handed over as
    that variable like every other row.
  - TOTK_METAL_HUD: Apple's Metal performance HUD over the game (frame rate, frame and GPU time, memory), as Breath
    of the Wild's front end has it (dm/ios/Sources/front_ios.m: developerHUDProperties).

The pane's texts are written "中文 · English" (the game's own rule, settings_strings.py: one language, the device's).

    settings_rows.py <Settings.bundle>
"""
import plistlib
import sys
from pathlib import Path

MFX_VALUES = ['0', 'interp30', 'interpmax']
MFX_TITLES = [
    '关 · Off',
    '30+30（游戏 30 帧，补到 60 帧）· 30+30 (the game at 30 fps, 60 pictures a second)',
    '不限帧（每一帧都补）· Uncapped (every frame interpolated)',
]
MFX_FOOTER = (
    '用 MetalFX 在两帧之间补出中间帧，画面更顺。30+30 让游戏跑 30 帧而屏幕每秒显示 60 幅画面，最省电；'
    '不限帧则让游戏尽量快跑、每一帧都补，GPU 负担最重。重启游戏后生效 · MetalFX makes the frame in between two '
    'game frames, so the picture moves more smoothly. 30+30 runs the game at 30 fps and shows 60 pictures a second, '
    'which is the cheapest; uncapped lets the game run as fast as it can and interpolates every frame, which is the '
    'heaviest. Takes effect after relaunching'
)
HUD_FOOTER = (
    '打开 Apple 的 Metal 性能监视器：帧率、每帧耗时、GPU 时间和内存。用来查性能问题，平时可以关掉。重启游戏后生效 · '
    "Apple's Metal performance HUD over the game: frame rate, frame and GPU time, and memory. Useful when chasing a "
    'performance problem; off the rest of the time. Takes effect after relaunching'
)
# TOTK-ipa (2026-11-03): the frame rate has three settings, not two. The uncapped one is the game's own clock above the
# display's rate: the picture stays at the display's refresh rate (the display link shows the newest finished frame at
# every refresh) while the game itself runs faster, which makes the input and the simulation steadier.
FPS_PRESET_VALUES = ['60', '30', 'uncapped']
FPS_PRESET_TITLES = [
    '最高 60 · Up to 60',
    '鎖 30 · Held at 30',
    '不限帧（游戏跑得比屏幕快）· Uncapped (the game runs faster than the screen)',
]
FPS_CAP_VALUES = ['30', '60', 'uncapped']
FPS_CAP_TITLES = [
    '30 帧（省电，最稳）· 30 fps (coolest, steadiest)',
    '60 帧（推荐）· 60 fps',
    '不限帧（游戏跑得比屏幕快）· Uncapped (the game runs faster than the screen)',
]
FPS_PRESET_FOOTER = (
    '60 是屏幕的刷新率，30 是省电模式，锁定 30 帧。不限帧让游戏按自己的时钟跑（比屏幕快），屏幕每次刷新显示最新的一帧，'
    '游戏速度不变，但按键响应更及时。重启游戏后生效 · 60 is the screen\'s refresh rate, 30 is the power-saving mode, held '
    'at 30 fps. Uncapped lets the game run on its own clock (faster than the screen); the screen shows the newest frame at '
    'every refresh, the game keeps its speed, and the input is answered sooner. Takes effect after relaunching'
)
FPS_CAP_FOOTER = (
    '30 最省电也最稳，长时间不变；60 推荐，发热后可能临时降到 30，冷却后自行回到 60。不限帧让游戏按自己的时钟跑，'
    '发热和耗电都明显更高，不建议长时间使用。重启游戏后生效 · 30 is the coolest and holds steady over time; 60 is '
    'recommended — after the SoC heats up the game may drop to 30 for a while and return to 60 once it cools. Uncapped '
    'lets the game run on its own clock: it heats up and uses more battery, so it is not meant for long sessions. Takes '
    'effect after relaunching'
)
FACE_SWAP_FOOTER = (
    '打开后，蓝牙手柄的 A、B 和 X、Y 互换，游戏里的按键提示就和任天堂手柄一样（A 在右、B 在下、X 在上、Y 在左）。'
    '手柄本身没有改，只是游戏怎么看它。重启游戏后生效 · With this on, a Bluetooth controller\'s A, B and X, Y are '
    'exchanged, so the game\'s button prompts sit where a Nintendo controller\'s are (A right, B bottom, X top, Y left). '
    'The controller itself is not changed, only how the game reads it. Takes effect after relaunching'
)


def add_rows(root):
    specs = root['PreferenceSpecifiers']

    # The kit's own rows carry no TOTKApp mark. That mark is the upstream's list of what Breath of the Wild must not
    # show (build_ipa.py settings_without_totk drops every row marked TOTKApp=totk), so a marked kit row would be
    # stripped from the pane again and the player could never reach it. The kit's rows belong to both games.
    # The MetalFX group (scene upscaling and edge smoothing) keeps its own title; the frame interpolation gets a group
    # of its own, right after it.
    mfx_group = {
        'Type': 'PSGroupSpecifier',
        'Title': '補幀 · Frame interpolation',
    }
    mfx_row = {
        'Type': 'PSRadioGroupSpecifier',
        'Key': 'TOTK_MFX',
        'TOTKPhone': True,
        'Title': '補幀 · Frame interpolation',
        'DefaultValue': '0',
        'Values': MFX_VALUES,
        'Titles': MFX_TITLES,
        'FooterText': MFX_FOOTER,
    }
    # The HUD goes with the interface: the status line and the shader overlay are there.
    hud_row = {
        'Type': 'PSToggleSwitchSpecifier',
        'Key': 'TOTK_METAL_HUD',
        'TOTKPhone': True,
        'Title': 'Metal 性能監視器 · Metal performance HUD',
        'DefaultValue': False,
        'FooterText': HUD_FOOTER,
    }
    # The face buttons' swap goes with the controller: it is about how a controller's buttons are read.
    face_swap_row = {
        'Type': 'PSToggleSwitchSpecifier',
        'Key': 'TOTK_FACE_SWAP',
        'TOTKPhone': True,
        'Title': '手柄按键互换（A/B、X/Y）· Swap the controller\'s A, B and X, Y',
        'DefaultValue': False,
        'FooterText': FACE_SWAP_FOOTER,
    }

    # The place of the MetalFX group: after the last of its own rows (the edge smoothing switch).
    insert_at = len(specs)
    for i, spec in enumerate(specs):
        if spec.get('Key') == 'TOTK_TAA':
            insert_at = i + 1
    specs[insert_at:insert_at] = [mfx_group, mfx_row]

    # The HUD: after the status line, in the interface group.
    insert_at = len(specs)
    for i, spec in enumerate(specs):
        if spec.get('Key') == 'TOTK_FPS_OVERLAY':
            insert_at = i + 1
    specs[insert_at:insert_at] = [hud_row]

    # The face buttons' swap: after the controller's own rows (the rumble and the gyro switches).
    insert_at = len(specs)
    for i, spec in enumerate(specs):
        if spec.get('Key') == 'TOTK_GYRO':
            insert_at = i + 1
    specs[insert_at:insert_at] = [face_swap_row]

    # TOTK-ipa (2026-11-03): the frame-rate rows get the third setting, the uncapped one. The rows the game ships with
    # offer 30 and 60; the button on the pad has three settings (30, 60, uncapped), and a player who used the button
    # would find the pane offering only two, so the pane and the button would disagree. The rows are changed in place,
    # so the game's own order and keys stay.
    for spec in specs:
        key = spec.get('Key')
        if key == 'TOTK_PHONE_FPS':
            spec['Values'] = list(FPS_PRESET_VALUES)
            spec['Titles'] = list(FPS_PRESET_TITLES)
            spec['FooterText'] = FPS_PRESET_FOOTER
        elif key == 'TOTK_FPS_CAP':
            spec['Values'] = list(FPS_CAP_VALUES)
            spec['Titles'] = list(FPS_CAP_TITLES)
            spec['FooterText'] = FPS_CAP_FOOTER
    return root


def main(bundle):
    bundle = Path(bundle)
    path = bundle / 'Root.plist'
    root = plistlib.loads(path.read_bytes())
    root = add_rows(root)
    path.write_bytes(plistlib.dumps(root, sort_keys=False))
    print(f'  the Settings pane has the frame interpolation, the Metal HUD and the face buttons\' swap rows: {path}',
          flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
