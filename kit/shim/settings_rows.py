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
FACE_SWAP_FOOTER = (
    '打开后，蓝牙手柄的 A、B 和 X、Y 互换，游戏里的按键提示就和任天堂手柄一样（A 在右、B 在下、X 在上、Y 在左）。'
    '手柄本身没有改，只是游戏怎么看它。重启游戏后生效 · With this on, a Bluetooth controller\'s A, B and X, Y are '
    'exchanged, so the game\'s button prompts sit where a Nintendo controller\'s are (A right, B bottom, X top, Y left). '
    'The controller itself is not changed, only how the game reads it. Takes effect after relaunching'
)


def add_rows(root):
    specs = root['PreferenceSpecifiers']

    # The MetalFX group (scene upscaling and edge smoothing) keeps its own title; the frame interpolation gets a group
    # of its own, right after it.
    mfx_group = {
        'Type': 'PSGroupSpecifier',
        'Title': '補幀 · Frame interpolation',
    }
    mfx_row = {
        'Type': 'PSRadioGroupSpecifier',
        'Key': 'TOTK_MFX',
        'TOTKApp': 'totk',
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
        'TOTKApp': 'totk',
        'TOTKPhone': True,
        'Title': 'Metal 性能監視器 · Metal performance HUD',
        'DefaultValue': False,
        'FooterText': HUD_FOOTER,
    }
    # The face buttons' swap goes with the controller: it is about how a controller's buttons are read.
    face_swap_row = {
        'Type': 'PSToggleSwitchSpecifier',
        'Key': 'TOTK_FACE_SWAP',
        'TOTKApp': 'totk',
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
