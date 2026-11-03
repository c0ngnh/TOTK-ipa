#!/usr/bin/env python3
"""Check the on-screen pad's layout (kit/shim/touch_pad_botw.m): the top row's controls must not overlap each other,
and none of them may steal another's touches.

The pad's own button (⊙) used to sit on top of the + pill, so the + button was unusable and a tap near it hit the
wrong control. The two small buttons at the top (the frame rate and the pad's own) still reach into the pills' touch
margins, so the shim's overPill guard gives the pills priority there; this test models that guard and checks the
result, so the layout cannot silently regress again.

The top row now holds four small controls: the frame rate (fps), the pad's own button (toggle), the motion source's
button (motion) and the face buttons' swap (swap). Each is drawn and hit on its own, so none of them may cover
another one, and a tap near the boundary must pick exactly one of them.

    usage: pad_layout.py [path to touch_pad_botw.m]
"""
import re
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
SHIM = KIT / 'shim/touch_pad_botw.m'

# The screens the pad is drawn on: (name, width, height, left inset, right inset) in points, landscape.
SCREENS = [
    ('iPhone SE 2/3', 667, 375, 0, 0),
    ('iPhone 13 mini', 812, 375, 44, 44),
    ('iPhone 14 Pro', 852, 393, 59, 59),
    ('iPhone 15 Pro Max', 932, 430, 59, 59),
    ('iPhone 16 Pro Max', 956, 440, 62, 62),
    ('iPad 11', 1194, 834, 0, 0),
    ('iPad Pro 12.9', 1366, 1024, 0, 0),
]

# The touch margin a finger needs around a pill (touch_pad_botw.m's pillTouchRect).
PILL_MARGIN = 8
# The grab circle of the small top buttons, as a multiple of their radius (inFps / inToggle / inMotion / inSwap).
SMALL_GRAB = 1.6
# The shoulders' grab radius, as a multiple of their radius (lockedAt).
DROP_GRAB = 1.35

NEEDED = ('K_PILL_DX', 'K_PILL_Y', 'K_PILL_W', 'K_PILL_H', 'K_FPS_R', 'K_PAD_TOGGLE_GAP',
          'K_PAD_TOGGLE_R', 'K_MOTION_GAP', 'K_MOTION_W', 'K_MOTION_R', 'K_SWAP_GAP', 'K_SWAP_R',
          'K_CLICK_X', 'K_CLICK_R', 'K_ZL_X', 'K_ZL_Y', 'K_ZL_R')


def constants(path):
    """The layout constants out of the shim's `static const CGFloat` block."""
    src = path.read_text(encoding='utf-8')
    return {name: float(value) for name, value in re.findall(r'\b(K_[A-Z0-9_]+)\s*=\s*([0-9.]+)', src)}


def overlaps(a, b):
    """Do two (left, top, right, bottom) rectangles touch?"""
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def subtract(rect, hole):
    """The pieces of `rect` that are not in `hole` (axis-aligned rectangles)."""
    l, t, r, b = rect
    hl, ht, hr, hb = hole
    if not overlaps(rect, hole):
        return [rect]
    out = []
    if l < hl:
        out.append((l, t, min(r, hl), b))
    if r > hr:
        out.append((max(l, hr), t, r, b))
    ml, mr = max(l, hl), min(r, hr)
    if ml < mr:
        if t < ht:
            out.append((ml, t, mr, min(b, ht)))
        if b > hb:
            out.append((ml, max(t, hb), mr, b))
    return [p for p in out if p[2] > p[0] and p[3] > p[1]]


def layout(k, width, height, left, right):
    """The top row's rectangles for one screen, in points."""
    u = min(height / 430.0, 1.3)          # the shim's scale: 1 on a 430-point-tall landscape iPhone
    smin, smax = left, width - right
    mid = (smin + smax) / 2
    top = 0
    pill_y = top + k['K_PILL_Y'] * u
    pill_h, pill_w, pill_dx = k['K_PILL_H'] * u, k['K_PILL_W'] * u, k['K_PILL_DX'] * u
    fps_r, tog_r = k['K_FPS_R'] * u, k['K_PAD_TOGGLE_R'] * u
    gap = k['K_PAD_TOGGLE_GAP'] * u
    mot_r, mot_w = k['K_MOTION_R'] * u, k['K_MOTION_W'] * u
    mot_gap = k['K_MOTION_GAP'] * u
    swp_r, swp_gap = k['K_SWAP_R'] * u, k['K_SWAP_GAP'] * u

    def pill(sign):
        c = mid + sign * pill_dx
        return (c - pill_w / 2, pill_y - pill_h / 2, c + pill_w / 2, pill_y + pill_h / 2)

    def grown(r, m):
        return (r[0] - m, r[1] - m, r[2] + m, r[3] + m)

    def circle(cx, r):
        """A circle's bounding box, at the pill row's height."""
        return (cx - r, pill_y - r, cx + r, pill_y + r)

    minus, plus = pill(-1), pill(1)
    fps_c = mid
    tog_c = mid + pill_dx + pill_w / 2 + gap
    # The motion source's button: its centre is measured from the pad's own button's centre (the shim's motionCenter).
    mot_c = tog_c + tog_r + mot_gap + mot_r
    # The face buttons' swap: its centre is measured from the motion source's button's centre (the shim's swapCenter).
    swp_c = mot_c + mot_r + swp_gap + swp_r
    fps = circle(fps_c, fps_r)
    tog = circle(tog_c, tog_r)
    # The motion source's button is drawn as a rounded pill, wider than its radius (it carries two words).
    motion = (mot_c - mot_w / 2, pill_y - mot_r, mot_c + mot_w / 2, pill_y + mot_r)
    swap = circle(swp_c, swp_r)
    r3_c, r3_r = smax - k['K_CLICK_X'] * u, k['K_CLICK_R'] * u
    r3 = (r3_c - r3_r, top + k['K_ZL_Y'] * u - r3_r, r3_c + r3_r, top + k['K_ZL_Y'] * u + r3_r)
    zr_c, zr_r = smax - k['K_ZL_X'] * u, k['K_ZL_R'] * u
    zr = (zr_c - zr_r, top + k['K_ZL_Y'] * u - zr_r, zr_c + zr_r, top + k['K_ZL_Y'] * u + zr_r)

    pill_touch = {'minus': grown(minus, PILL_MARGIN * u), 'plus': grown(plus, PILL_MARGIN * u)}
    # The small buttons reach into the pills' margins; the pills win there (the shim's overPill guard).
    fps_touch = [grown(fps, (SMALL_GRAB - 1) * fps_r)]
    tog_touch = [grown(tog, (SMALL_GRAB - 1) * tog_r)]
    mot_touch = [grown(circle(mot_c, mot_r), (SMALL_GRAB - 1) * mot_r)]
    swp_touch = [grown(circle(swp_c, swp_r), (SMALL_GRAB - 1) * swp_r)]
    for regions in (fps_touch, tog_touch, mot_touch, swp_touch):
        for hole in pill_touch.values():
            regions[:] = [piece for region in regions for piece in subtract(region, hole)]
    # The shim's inMotion / inSwap guards: a button whose grab circle would reach another one's is refused there, so a
    # tap near the boundary picks the nearer button and never both. The shim refuses a tap whose distance to the other
    # button's centre is under the sum of the two grab radii, so that sum is the hole.
    mot_touch[:] = [piece for region in mot_touch
                    for piece in subtract(region, circle(tog_c, (tog_r + mot_r) * SMALL_GRAB))]
    swp_touch[:] = [piece for region in swp_touch
                    for piece in subtract(region, circle(mot_c, (mot_r + swp_r) * SMALL_GRAB))]
    swp_touch[:] = [piece for region in swp_touch
                    for piece in subtract(region, circle(tog_c, (tog_r + swp_r) * SMALL_GRAB))]

    return {
        'visual': {'minus': [minus], 'plus': [plus], 'fps': [fps], 'toggle': [tog], 'motion': [motion],
                   'swap': [swap], 'R3': [r3], 'ZR': [zr]},
        'touch': {
            'minus': [pill_touch['minus']],
            'plus': [pill_touch['plus']],
            'fps': fps_touch,
            'toggle': tog_touch,
            'motion': mot_touch,
            'swap': swp_touch,
            'R3': [grown(r3, 0)],
            'ZR': [grown(zr, (DROP_GRAB - 1) * zr_r)],
        },
    }


def check(path):
    """The layout check itself; raises SystemExit when something overlaps."""
    path = Path(path)
    if not path.is_file():
        raise SystemExit(f'no such file: {path}')
    src = path.read_text(encoding='utf-8')
    k = constants(path)
    for name in NEEDED:
        if name not in k:
            raise SystemExit(f'{path}: the layout constant {name} is missing')

    # The guard this test relies on has to be there.
    if 'overPill' not in src:
        raise SystemExit(f'{path}: the overPill guard is gone')
    for name in ('inFps', 'inToggle', 'inMotion', 'inSwap'):
        body = src.split(f'- (BOOL){name}:', 1)
        if len(body) < 2:
            raise SystemExit(f'{path}: {name} is gone')
        line = body[1].split('\n', 1)[0]
        if 'overPill' not in line and 'overPill' not in body[1].split('}', 1)[0]:
            raise SystemExit(f'{path}: {name} does not give the pills priority any more')

    bad = 0
    for name, width, height, left, right in SCREENS:
        lay = layout(k, width, height, left, right)
        for kind, rects in lay.items():
            names = list(rects)
            for a in names:
                for b in names:
                    if a >= b:
                        continue
                    for ra in rects[a]:
                        for rb in rects[b]:
                            if overlaps(ra, rb):
                                print(f'{name}: the {kind} areas of {a} and {b} overlap')
                                bad += 1
                                break
        # The pad's own button must stay clear of the + pill, or it hides the + button.
        plus, tog = lay['visual']['plus'][0], lay['visual']['toggle'][0]
        if tog[0] <= plus[2]:
            print(f'{name}: the pad\'s own button covers the + button')
            bad += 1
        if tog[2] >= lay['visual']['R3'][0][0]:
            print(f'{name}: the pad\'s own button covers the R3 button')
            bad += 1
        # The same for the motion source's and the swap's buttons: they are further out, so they must not reach the R3
        # button or the ZR teardrop either.
        for key in ('motion', 'swap'):
            rect = lay['visual'][key][0]
            if rect[2] >= lay['visual']['R3'][0][0]:
                print(f'{name}: the {key} button covers the R3 button')
                bad += 1
            if rect[2] >= lay['visual']['ZR'][0][0]:
                print(f'{name}: the {key} button covers the ZR button')
                bad += 1
        # The swap's button must not touch the motion source's button it sits next to.
        if lay['visual']['swap'][0][0] <= lay['visual']['motion'][0][2]:
            print(f'{name}: the swap button covers the motion source\'s button')
            bad += 1

    if bad:
        raise SystemExit(f'pad layout: {bad} problem(s)')
    print(f"pad layout: {len(SCREENS)} screens, no overlap between the top row's controls")


def main():
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else SHIM)


if __name__ == '__main__':
    main()
