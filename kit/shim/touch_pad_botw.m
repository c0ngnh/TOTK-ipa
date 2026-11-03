#import "touch_pad.h"
#import "device_motion.h"
#import "phone_extra.h"
#import <GameController/GameController.h>
#import <CoreText/CoreText.h>
#include <math.h>
#include <stdlib.h>
#include "runtime.h"
#include "settings_map.h"
#include "totk_ui_lang.h"

/* The on-screen controller, drawn in Breath of the Wild's style: one CAShapeLayer per control, the shoulder buttons as
   teardrops whose tip points at the screen corner, the face buttons as a diamond and the D-pad as four arms, all with
   a soft shadow and a light touch on every press. The layout is a Switch controller's: ZL above L at the top left, ZR
   above R at the top right, − and + beside each other at the top centre, the left stick and the D-pad on the left, the
   A/B/X/Y diamond and the right stick on the right, L3 / R3 in the bottom corners.

   The state goes to the runtime through runtime_touch_pad_set (runtime/gamepad.m), which merges it with any physical
   controller. The button bits are the guest's Npad ones: A 1, B 2, X 4, Y 8, L3 16, R3 32, L 64, R 128, ZL 256, ZR 512,
   + 1024, − 2048, left 4096, up 8192, right 16384, down 32768 (runtime/input.c's button()).

   The touch controls' frame-rate button (between − and +) switches the game between 60 and 30 as it is held; with the
   custom layer off it saves the choice in the pane's preset row (TOTK_PHONE_FPS) for the next start, with it on the
   pane owns the cap, so the button only holds 30 until the next launch.

   The pad's own button (top row, out past the + pill) shows and hides the whole overlay, so a player who brings a
   Bluetooth controller can get the picture clear; the choice is kept in NSUserDefaults (TOTK_PAD_HIDDEN).

   The physical controllers are the runtime's own (runtime/gamepad.m reads them); the touch layer is hidden while one is
   connected, and comes back when it is removed. */
typedef struct { CGPoint at; uint64_t bit; NSString *label; CGFloat size; } TouchButton;
enum { kButtonCount = 16 };
enum { B_A = 0, B_B, B_X, B_Y, B_LS, B_RS, B_L, B_R, B_ZL, B_ZR, B_PLUS, B_MINUS, B_LEFT, B_UP, B_RIGHT, B_DOWN, B_N };

/* Layout constants in points, scaled with the screen (u = 1 on a 430-point-tall landscape iPhone). */
static const CGFloat
    K_ZL_X = 44, K_ZL_Y = 40, K_ZL_R = 26,          // ZL / ZR: centre from the outer edge and the top, radius
    K_L_X = 44, K_L_Y = 108, K_L_R = 24,            // L / R: the same column as ZL / ZR
    K_DROP_TIP = 1.45,                              // the teardrop's tip distance from the centre (times the radius)
    K_CORNER_IN = 0.5,                              // how far the bottom-corner controls reach into the side inset
    K_FACE_X = 81, K_PAD_Y = 82,                    // the diamond's centre from the outer edge, the diamond's and the stick's from the bottom
    K_FACE_GAP = 50, K_FACE_R = 27,                 // the diamond: the key distance from the centre, the key radius
    K_PILL_DX = 52, K_PILL_Y = 22, K_PILL_W = 50, K_PILL_H = 28,   // − / +: from the screen's midline and the top, size
    K_FPS_R = 15,                                   // the frame-rate button: top centre, level with − / +
    K_PAD_TOGGLE_GAP = 30, K_PAD_TOGGLE_R = 13,       // the pad's own button: the gap past the + pill, radius
    K_MOTION_GAP = 30, K_MOTION_W = 68, K_MOTION_R = 13,   // the motion source's button: the gap past the pad's own button, its width and radius
    K_SWAP_GAP = 26, K_SWAP_R = 13,                        // the face buttons' swap: the gap past the motion source's button, its radius
    K_STICK_X = 81, K_STICK_R = 77, K_KNOB_R = 30,  // the left stick: mirrors the diamond, the ring as large as the whole diamond
    K_STICK_GRAB = 1.4,                             // how near the ring's centre a touch-down grabs a stick
    K_FULL = 0.8,                                   // full tilt at this fraction of the ring radius
    K_DEAD = 0.1,                                   // the stick's dead zone (times the ring radius)
    K_LOW_X = 231, K_LOW_Y = 64,                    // the D-pad's centre from the outer edge and the bottom
    K_DPAD_R = 48, K_ARM_W = 17, K_ARM_IN = 11,     // the D-pad: arm outer edge from the centre, half-width, tip from the centre
    K_DPAD_GRAB = 1.3,                              // the D-pad's grab radius (times the outer edge)
    K_RSTICK_R = 60, K_RKNOB_R = 24,                // the right stick: ring and knob radius
    K_RSWIPE = 1.0 / 3,                             // the right stick's area: this fraction of the width from the right edge
    K_CLICK_X = 102, K_CLICK_R = 17;                // L3 / R3: centre from the outer edge, radius

static UIColor *k_idle, *k_on, *k_line, *k_ringFill, *k_text, *k_textOn;

@implementation TOTKTouchPad {
    NSMapTable<UITouch *, NSValue *> *points;         // touch → where it is now
    NSMapTable<UITouch *, NSNumber *> *owner;         // touch → the control it holds (the key for C_BTN, the stick for C_STICK, << 8)
    UITouch *_stick[2];                                // the touch holding each stick (0 left, 1 right)
    CGPoint _centre[2];                               // each stick's centre: its home, or where the finger landed
    CGPoint _drawn[2];                                // the centre each ring was last drawn at
    BOOL _dynamic[2];                                 // the stick follows the finger (it was grabbed away from its home)
    BOOL gamepad, padHidden, padForced;               // a controller is connected; the player hid the overlay; the player showed it over a controller
    NSTimer *hideTimer;
    CAShapeLayer *_key[B_N]; CATextLayer *_label[B_N];
    CAShapeLayer *_ring[2], *_knob[2];                // the left and the right stick's ring and knob
    CAShapeLayer *_controls;                          // every control layer: hidden together by the pad's own button
    CAShapeLayer *_fps; CATextLayer *_fpsLabel; BOOL _fpsHeld;
    CAShapeLayer *_toggle; CATextLayer *_toggleLabel; BOOL _toggleHeld;
    CAShapeLayer *_motion; CATextLayer *_motionLabel; BOOL _motionHeld;
    CAShapeLayer *_swap; CATextLayer *_swapLabel; BOOL _swapHeld;
    BOOL _faceSwap;                                      // the Bluetooth controller's A/B and X/Y swapped
    int _motionSource;                               // the source in force: TOTK_MOTION_SOURCE_AUTO / _PHONE / _CONTROLLER
    UIImpactFeedbackGenerator *_touchFeedback;        // one short feedback per press edge
    unsigned _hapticSticks;
    BOOL _stickShown;
    uint64_t _faceBits, _btnBits;
}

enum { C_NONE = 0, C_STICK, C_DPAD, C_BTN, C_FACE, C_FPS, C_TOGGLE, C_MOTION, C_SWAP };

static CAShapeLayer *shape(CALayer *parent) {
    CAShapeLayer *l = [CAShapeLayer layer];
    l.fillColor = k_idle.CGColor; l.strokeColor = k_line.CGColor; l.lineWidth = 1.5;
    l.shadowColor = UIColor.blackColor.CGColor; l.shadowOpacity = 0.2; l.shadowRadius = 3; l.shadowOffset = CGSizeMake(0, 1);
    [parent addSublayer:l]; return l;
}
static CATextLayer *label(CALayer *parent, NSString *s) {
    CATextLayer *t = [CATextLayer layer];
    t.string = s; t.alignmentMode = kCAAlignmentCenter; t.foregroundColor = k_text.CGColor; t.contentsScale = UIScreen.mainScreen.scale;
    [parent addSublayer:t]; return t;
}
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) {
        self.multipleTouchEnabled = YES; self.opaque = NO; self.backgroundColor = UIColor.clearColor;
        self.contentMode = UIViewContentModeRedraw;
        static dispatch_once_t once;
        dispatch_once(&once, ^{
            /* Each colour carries its own low opacity instead of lowering the whole view's alpha: that would add an
               off-screen pass for the full-screen layer. */
            k_idle = [UIColor colorWithWhite:1 alpha:0.14]; k_on = [UIColor colorWithWhite:1 alpha:0.45];
            k_line = [UIColor colorWithWhite:1 alpha:0.38]; k_ringFill = [UIColor colorWithWhite:1 alpha:0.06];
            k_text = [UIColor colorWithWhite:1 alpha:0.6]; k_textOn = [UIColor colorWithWhite:0 alpha:0.7];
        });
        const char *feedback = getenv("TOTK_TOUCH_HAPTICS");
        if (!feedback || atoi(feedback)) {
            _touchFeedback = [[UIImpactFeedbackGenerator alloc] initWithStyle:UIImpactFeedbackStyleLight];
            [_touchFeedback prepare];
        }
        points = [NSMapTable strongToStrongObjectsMapTable];
        owner = [NSMapTable strongToStrongObjectsMapTable];
        /* The player's choice (the pad's own button) is kept between launches. */
        padHidden = [NSUserDefaults.standardUserDefaults boolForKey:@"TOTK_PAD_HIDDEN"];
        /* The controls live in one layer, so the pad's own button can hide them all at once; the button itself is on
           the view's own layer, so it stays visible and can bring them back. */
        CAShapeLayer *controls = [CAShapeLayer layer]; [self.layer addSublayer:controls];
        _controls = controls;
        for (int i = 0; i < 2; i++) {
            _ring[i] = shape(controls); _ring[i].fillColor = k_ringFill.CGColor;
            _knob[i] = shape(controls);
            CAShapeLayer *in = [CAShapeLayer layer]; in.fillColor = nil; in.strokeColor = k_line.CGColor; in.lineWidth = 1.5;
            [_knob[i] addSublayer:in];
        }
        static NSString *const names[B_N] = {@"A", @"B", @"X", @"Y", @"L3", @"R3", @"L", @"R", @"ZL", @"ZR", @"+", @"−"};
        for (int b = 0; b < B_N; b++) {
            _key[b] = shape(controls);
            if (names[b]) _label[b] = label(_key[b], names[b]);   // the D-pad arms carry no label
        }
        _fps = shape(controls); _fpsLabel = label(_fps, [self frameRateLabel:runtime_phone_fps()]);
        _toggle = shape(self.layer); _toggleLabel = label(_toggle, padHidden ? @"⊘" : @"⊙");
        /* The motion source's button: on the view's own layer, so it stays on screen even when the overlay is hidden
           (a player with a Bluetooth controller may still want to aim with the phone, or with the controller). */
        _motion = shape(self.layer);
        _motionSource = totk_device_motion_source();
        _motionLabel = label(_motion, [self motionLabelFor:_motionSource]);
        /* The face buttons' swap: on the view's own layer, next to the motion source's button, so it stays on screen even
           when the overlay is hidden (a player with a Bluetooth controller may still want to turn the swap on or off).
           The choice is the runtime's, so the button shows what the runtime says (the Settings pane's row is the choice
           at the launch; the button then changes it while the game runs). */
        _swap = shape(self.layer);
        _faceSwap = runtime_gamepad_face_swap() != 0;
        _swapLabel = label(_swap, [self swapLabel]);
        NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
        [center addObserver:self selector:@selector(controllersChanged:) name:GCControllerDidConnectNotification object:nil];
        [center addObserver:self selector:@selector(controllersChanged:) name:GCControllerDidDisconnectNotification object:nil];
        [center addObserver:self selector:@selector(controllersChanged:) name:GCKeyboardDidConnectNotification object:nil];
        [center addObserver:self selector:@selector(controllersChanged:) name:GCKeyboardDidDisconnectNotification object:nil];
        [self controllersChanged:nil];
    }
    return self;
}

- (void)controllersChanged:(NSNotification *)note {
    BOOL connected = NO;
    for (GCController *controller in GCController.controllers)
        if (controller.extendedGamepad && !([note.name isEqualToString:GCControllerDidDisconnectNotification] && controller == note.object)) connected = YES;
    GCKeyboard *keyboard = [note.name isEqualToString:GCKeyboardDidConnectNotification] && [note.object isKindOfClass:GCKeyboard.class]
                         ? note.object : GCKeyboard.coalescedKeyboard;
    const char *keyboardMode = getenv("TOTK_KEYBOARD");
    BOOL keyboardOn = !(keyboardMode && (!strcmp(keyboardMode, "off") || !strcmp(keyboardMode, "0"))) && keyboard != nil;
    const char *touchWithKeyboard = getenv("TOTK_TOUCH_WITH_KEYBOARD");
    BOOL keepTouch = touchWithKeyboard && !strcmp(touchWithKeyboard, "1");
    BOOL hidden = connected || (keyboardOn && !keepTouch);
    if ([note.name isEqualToString:GCKeyboardDidDisconnectNotification])
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
            [self controllersChanged:nil];
        });
    if (hidden == gamepad) return;
    gamepad = hidden; [hideTimer invalidate]; hideTimer = nil;
    if (gamepad) [self conceal]; else [self setNeedsLayout];
    [self applyVisibility];
}

/* The overlay's visibility: hidden while a controller is connected and hidden when the player turned it off with the
   pad's own button. The button itself stays on screen either way: it is how the overlay comes back. */
- (void)applyVisibility {
    _controls.hidden = (gamepad && !padForced) || padHidden;
    _toggle.hidden = NO;
}

- (void)conceal {
    /* Fingers on the screen when it hides would otherwise hold their buttons and sticks. */
    [points removeAllObjects]; [owner removeAllObjects];
    _stick[0] = _stick[1] = nil; _dynamic[0] = _dynamic[1] = NO;
    [self recompute];
}

- (void)hideLater {
    [hideTimer invalidate]; hideTimer = nil;
    if (!gamepad || points.count) return;
    __weak TOTKTouchPad *weakSelf = self;
    hideTimer = [NSTimer scheduledTimerWithTimeInterval:3 repeats:NO block:^(NSTimer *timer) {
        (void)timer; TOTKTouchPad *pad = weakSelf; if (pad) [pad concealIfIdle];
    }];
}
- (void)concealIfIdle { if (gamepad && !points.count) [self conceal]; }

/* The pad's own button: it shows or hides the whole overlay, so a player with a Bluetooth controller can have the
   picture to itself. The choice is kept between launches. */
- (void)togglePad {
    /* With a controller connected the overlay is hidden on its own; the button then brings it back for as long as the
       controller stays (the player may want both), and hides it again after. */
    if (gamepad && !padForced) {
        padForced = YES;
        _toggleLabel.string = @"⊘";
        [self applyVisibility];
        return;
    }
    padForced = NO;
    padHidden = !padHidden;
    [NSUserDefaults.standardUserDefaults setBool:padHidden forKey:@"TOTK_PAD_HIDDEN"];
    /* Fingers on the screen when the pad goes would otherwise hold its buttons and sticks. */
    if (padHidden) [self conceal];
    _toggleLabel.string = padHidden ? @"⊘" : @"⊙";
    [self applyVisibility];
}

/* The motion source's button: it shows which sensor feeds the game's six-axis device, and a tap picks the next one
   (auto → the phone → the controller → auto). The choice is kept between launches (NSUserDefaults), and it reaches
   the runtime through phone_motion.m, which starts and stops the sensors to match. */
- (NSString *)motionLabelFor:(int)source {
    switch (source) {
        case TOTK_MOTION_SOURCE_PHONE: return TOTK_UI(@"手机", @"Phone");
        case TOTK_MOTION_SOURCE_CONTROLLER: return TOTK_UI(@"手柄", @"Pad");
        default: return TOTK_UI(@"自动", @"Auto");
    }
}
- (void)switchMotionSource {
    /* The three sources in the order the button cycles them. */
    static const int order[] = {TOTK_MOTION_SOURCE_AUTO, TOTK_MOTION_SOURCE_PHONE, TOTK_MOTION_SOURCE_CONTROLLER};
    int next = TOTK_MOTION_SOURCE_AUTO;
    for (size_t i = 0; i < sizeof(order) / sizeof(order[0]); i++)
        if (order[i] == _motionSource) { next = order[(i + 1) % (sizeof(order) / sizeof(order[0]))]; break; }
    _motionSource = next;
    /* The runtime takes the choice: it drops the other source's samples and re-aligns the frame for the new one. */
    totk_device_motion_set_source(next);
    [NSUserDefaults.standardUserDefaults setInteger:next forKey:@"TOTK_MOTION_SOURCE"];
    _motionLabel.string = [self motionLabelFor:next];
    [self refresh];
}

/* The face buttons' swap button: it shows whether the swap is on, and a tap turns it on or off. The runtime holds the
   choice (runtime_gamepad_face_swap_set), so the change reaches the game at once, without a restart. */
- (NSString *)swapLabel { return _faceSwap ? TOTK_UI(@"已换", @"On") : TOTK_UI(@"原样", @"Off"); }
- (void)switchFaceSwap {
    _faceSwap = !_faceSwap;
    /* The runtime takes the choice at once: the controller's buttons are read through it on the next frame. */
    runtime_gamepad_face_swap_set(_faceSwap);
    /* The choice is kept between launches, like the pad's own button's and the motion source's. The Settings pane's row
       (TOTK_FACE_SWAP) is the choice at the launch; the button's own choice is the one that counts from now on. */
    [NSUserDefaults.standardUserDefaults setBool:_faceSwap forKey:@"TOTK_FACE_SWAP"];
    _swapLabel.string = [self swapLabel];
    [self refresh];
}

/* ---- Layout ---- */
- (CGRect)safe { return UIEdgeInsetsInsetRect(self.bounds, self.safeAreaInsets); }
- (CGRect)corner {
    UIEdgeInsets i = self.safeAreaInsets; i.left *= K_CORNER_IN; i.right *= K_CORNER_IN;
    return UIEdgeInsetsInsetRect(self.bounds, i);
}
- (CGFloat)u { return MIN(self.bounds.size.height / 430.0, 1.3); }
static CGPoint side(CGRect s, int right, CGFloat dx, CGFloat y) { return CGPointMake(right ? CGRectGetMaxX(s) - dx : CGRectGetMinX(s) + dx, y); }
- (CGPoint)faceCenter { CGRect s = self.corner; CGFloat u = self.u; return side(s, 1, K_FACE_X * u, CGRectGetMaxY(s) - K_PAD_Y * u); }
- (CGFloat)faceGap { return K_FACE_GAP * self.u; }
- (CGFloat)faceR { return K_FACE_R * self.u; }
- (CGPoint)facePos:(int)b {
    CGPoint c = self.faceCenter; CGFloat g = self.faceGap;
    switch (b) { case B_A: return CGPointMake(c.x + g, c.y); case B_B: return CGPointMake(c.x, c.y + g);
                  case B_X: return CGPointMake(c.x, c.y - g); default: return CGPointMake(c.x - g, c.y); }
}
- (CGPoint)stickHome { CGRect s = self.corner; return side(s, 0, K_STICK_X * self.u, CGRectGetMaxY(s) - K_PAD_Y * self.u); }
/* The right stick's home: inward of and below the A/B/X/Y diamond, as on a Pro Controller. Its ring is drawn at rest,
   like Breath of the Wild's (the ring at the bottom right of the game picture). */
- (CGPoint)rightStickHome { CGRect s = self.corner; return side(s, 1, K_LOW_X * self.u, CGRectGetMaxY(s) - K_LOW_Y * self.u); }
- (CGFloat)stickR { return K_STICK_R * self.u; }
- (CGFloat)rightStickR { return K_RSTICK_R * self.u; }
- (CGFloat)stickR:(int)i { return (i ? K_RSTICK_R : K_STICK_R) * self.u; }
/* The right stick's centre: its home, unless a finger grabbed it away from the home (a swipe in the right third), in
   which case the ring follows the finger. */
- (CGPoint)stickCentre:(int)i { return _dynamic[i] ? _centre[i] : (i ? self.rightStickHome : self.stickHome); }
/* The knob's offset from the stick's centre, clamped to the ring. */
- (CGPoint)stickOffset:(int)i {
    if (!_stick[i]) return CGPointZero;
    CGPoint h = [self stickCentre:i];
    CGPoint now = [points objectForKey:_stick[i]].CGPointValue;
    CGFloat dx = now.x - h.x, dy = now.y - h.y, d = hypot(dx, dy), R = [self stickR:i];
    if (d > R) { dx *= R / d; dy *= R / d; }
    return CGPointMake(dx, dy);
}
- (BOOL)inRightArea:(CGPoint)p { CGRect b = self.bounds; return p.x >= CGRectGetMaxX(b) - b.size.width * K_RSWIPE; }
- (CGPoint)dpadCenter { CGRect s = self.corner; CGFloat u = self.u; return side(s, 0, K_LOW_X * u, CGRectGetMaxY(s) - K_LOW_Y * u); }
- (CGFloat)dpadR { return K_DPAD_R * self.u; }
static BOOL isDrop(int b) { return b == B_ZL || b == B_L || b == B_ZR || b == B_R; }
static BOOL isClick(int b) { return b == B_LS || b == B_RS; }
- (CGPoint)dropCenter:(int)b {
    CGRect s = self.safe; CGFloat u = self.u; BOOL z = b == B_ZL || b == B_ZR;
    return side(s, b == B_ZR || b == B_R, (z ? K_ZL_X : K_L_X) * u, CGRectGetMinY(s) + (z ? K_ZL_Y : K_L_Y) * u);
}
- (CGFloat)dropR:(int)b { return (b == B_ZL || b == B_ZR ? K_ZL_R : K_L_R) * self.u; }
- (CGPoint)clickCenter:(int)b { CGRect s = self.safe; return side(s, b == B_RS, K_CLICK_X * self.u, CGRectGetMinY(s) + K_ZL_Y * self.u); }
- (CGRect)pillRect:(int)b {
    CGRect s = self.safe; CGFloat u = self.u, w = K_PILL_W * u, h = K_PILL_H * u;
    CGPoint c = CGPointMake(CGRectGetMidX(s) + (b == B_PLUS ? K_PILL_DX : -K_PILL_DX) * u, CGRectGetMinY(s) + K_PILL_Y * u);
    return CGRectMake(c.x - w / 2, c.y - h / 2, w, h);
}
- (CGPoint)fpsCenter { CGRect s = self.safe; return CGPointMake(CGRectGetMidX(s), CGRectGetMinY(s) + K_PILL_Y * self.u); }
/* The pad's own button: out past the + pill, so it neither covers the + button nor steals its touches. The gap is
   measured from the pill's outer edge, so the two stay apart whatever the screen's size. */
- (CGPoint)toggleCenter {
    CGRect s = self.safe; CGFloat u = self.u;
    CGFloat pillEdge = (K_PILL_DX + K_PILL_W / 2) * u;   // the + pill's outer edge, from the screen's midline
    return CGPointMake(CGRectGetMidX(s) + pillEdge + K_PAD_TOGGLE_GAP * u, CGRectGetMinY(s) + K_PILL_Y * u);
}
/* The motion source's button: out past the pad's own button, so it neither covers it nor steals its touches. Its
   centre is measured from the pad's own button's centre, so the two stay apart whatever the screen's size. */
- (CGPoint)motionCenter {
    CGPoint t = self.toggleCenter; CGFloat u = self.u;
    return CGPointMake(t.x + (K_PAD_TOGGLE_R + K_MOTION_GAP + K_MOTION_R) * u, t.y);
}
/* The face buttons' swap button: out past the motion source's button, so it neither covers it nor steals its touches.
   Its centre is measured from the motion source's button's centre, so the two stay apart whatever the screen's size. */
- (CGPoint)swapCenter {
    CGPoint m = self.motionCenter; CGFloat u = self.u;
    return CGPointMake(m.x + (K_MOTION_R + K_SWAP_GAP + K_SWAP_R) * u, m.y);
}

static CGFloat dist(CGPoint a, CGPoint b) { return hypot(a.x - b.x, a.y - b.y); }

/* The keys locked at touch-down: the shoulders and the − / + pills. (The enum's order is the Npad's bit order, so L
   and R come before ZL and ZR: the loops below name the keys instead of ranging over them.) */
static const int k_lockedKeys[] = {B_ZL, B_ZR, B_L, B_R, B_PLUS, B_MINUS};
- (int)lockedAt:(CGPoint)p {
    for (size_t i = 0; i < sizeof(k_lockedKeys) / sizeof(k_lockedKeys[0]); i++) {
        int b = k_lockedKeys[i];
        BOOL hit = isDrop(b) ? dist(p, [self dropCenter:b]) <= [self dropR:b] * 1.35
                 : CGRectContainsPoint([self pillTouchRect:b], p);
        if (hit) return b;
    }
    return -1;
}
/* The − / + pills' touch area: their own rect, grown by the margin a finger needs. */
- (CGRect)pillTouchRect:(int)b { return CGRectInset([self pillRect:b], -8 * self.u, -8 * self.u); }
/* The two small buttons at the top (the frame rate and the pad's own) sit between the pills and the screen's middle, so
   their grab circles reach into the pills' margins. The game buttons win there: a tap on the + pill is a + press, never
   a frame-rate or a hide/show. */
- (BOOL)overPill:(CGPoint)p { return CGRectContainsPoint([self pillTouchRect:B_PLUS], p) || CGRectContainsPoint([self pillTouchRect:B_MINUS], p); }
- (BOOL)inFps:(CGPoint)p { return dist(p, self.fpsCenter) <= K_FPS_R * self.u * 1.6 && ![self overPill:p]; }
/* The pad's own button's touch area: out past the + pill, so it neither covers the + button nor steals its touches. */
- (BOOL)inToggle:(CGPoint)p { return dist(p, self.toggleCenter) <= K_PAD_TOGGLE_R * self.u * 1.6 && ![self overPill:p]; }
/* The motion source's button's touch area: out past the pad's own button, and clear of it (the two circles must not
   overlap, or a tap near the boundary would pick the wrong one). */
- (BOOL)inMotion:(CGPoint)p {
    if (dist(p, self.toggleCenter) <= (K_PAD_TOGGLE_R * 1.6 + K_MOTION_R * 1.6) * self.u) return NO;
    return dist(p, self.motionCenter) <= K_MOTION_R * self.u * 1.6 && ![self overPill:p];
}
/* The face buttons' swap button's touch area: out past the motion source's button, and clear of it (the two circles must
   not overlap, or a tap near the boundary would pick the wrong one). */
- (BOOL)inSwap:(CGPoint)p {
    if (dist(p, self.motionCenter) <= (K_MOTION_R * 1.6 + K_SWAP_R * 1.6) * self.u) return NO;
    if (dist(p, self.toggleCenter) <= (K_PAD_TOGGLE_R * 1.6 + K_SWAP_R * 1.6) * self.u) return NO;
    return dist(p, self.swapCenter) <= K_SWAP_R * self.u * 1.6 && ![self overPill:p];
}
- (uint64_t)faceAt:(CGPoint)p {
    uint64_t m = 0; CGFloat r = self.faceR * 1.25;
    for (int b = B_A; b <= B_Y; b++) if (dist(p, [self facePos:b]) <= r) m |= 1ull << b;
    return m;
}
- (uint64_t)dpadAt:(CGPoint)p {
    CGPoint c = self.dpadCenter; CGFloat dx = p.x - c.x, dy = p.y - c.y;
    if (hypot(dx, dy) < self.dpadR * 0.25) return 0;
    double a = atan2(-dy, dx) * 180 / M_PI; uint64_t m = 0;
    if (a > -67.5 && a < 67.5) m |= 1ull << B_RIGHT;
    if (a > 22.5 && a < 157.5) m |= 1ull << B_UP;
    if (a > 112.5 || a < -112.5) m |= 1ull << B_LEFT;
    if (a < -22.5 && a > -157.5) m |= 1ull << B_DOWN;
    return m;
}

/* ---- State ---- */
- (void)recompute {
    uint64_t face = 0, btn = 0; BOOL fps = NO, toggle = NO, motion = NO, swap = NO;
    for (UITouch *t in owner.keyEnumerator) {
        uint64_t v = [owner objectForKey:t].unsignedLongLongValue; int c = (int)(v & 0xff);
        if (c == C_FACE) {
            /* The face buttons follow the finger: every key under it counts, so sliding between two presses both. */
            face |= [self faceAt:[t locationInView:self]];
        } else if (c == C_BTN) {
            btn |= 1ull << (int)(v >> 8);
        } else if (c == C_DPAD) {
            face |= [self dpadAt:[t locationInView:self]];
        } else if (c == C_FPS) {
            fps = YES;
        } else if (c == C_TOGGLE) {
            toggle = YES;
        } else if (c == C_MOTION) {
            motion = YES;
        } else if (c == C_SWAP) {
            swap = YES;
        }
    }
    int32_t ax[4] = {0, 0, 0, 0};
    for (int i = 0; i < 2; i++) {
        CGPoint o = [self stickOffset:i]; CGFloat R = [self stickR:i], d = hypot(o.x, o.y), dz = R * K_DEAD;
        if (d <= dz) continue;
        /* Outside the dead zone: 0 rising to full at the full-tilt radius. Up is positive, as the host wants it. */
        CGFloat m = fmin((d - dz) / (R * K_FULL - dz), 1) / d;
        ax[i * 2] = (int32_t)lrint(o.x * m * 32767); ax[i * 2 + 1] = (int32_t)lrint(-o.y * m * 32767);
    }
    BOOL changed = face != _faceBits || btn != _btnBits || fps != _fpsHeld || toggle != _toggleHeld ||
                   motion != _motionHeld || swap != _swapHeld;
    uint64_t pressed = (face | btn) & ~(_faceBits | _btnBits);
    unsigned gripping = (_stick[0] ? 1u : 0) | (_stick[1] ? 2u : 0);
    if (pressed || (fps && !_fpsHeld) || (motion && !_motionHeld) || (swap && !_swapHeld) || (gripping & ~_hapticSticks)) {
        [_touchFeedback impactOccurredWithIntensity:0.6]; [_touchFeedback prepare];
    }
    _hapticSticks = gripping;
    _faceBits = face; _btnBits = btn; _fpsHeld = fps; _toggleHeld = toggle; _motionHeld = motion; _swapHeld = swap;
    RuntimeGamepadState s = {.connected = 1, .buttons = face | btn, .lx = ax[0], .ly = ax[1], .rx = ax[2], .ry = ax[3]};
    runtime_touch_pad_set(&s);
    BOOL stick = _stick[0] || _stick[1];
    if (changed || stick || _stickShown) [self refresh];   /* also on the release, so the knob returns to the centre */
    _stickShown = stick;
}

/* ---- Touch ---- */
- (void)touchesBegan:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event {
    (void)event; [hideTimer invalidate]; hideTimer = nil;
    totk_device_motion_note_touch();   // a finger on the screen takes the aiming from a controller's gyro (phone_motion.m)
    for (UITouch *t in touches) {
        CGPoint p = [t locationInView:self]; [points setObject:[NSValue valueWithCGPoint:p] forKey:t];
        if ([self inToggle:p]) {
            [owner setObject:@(C_TOGGLE) forKey:t];
            [self togglePad];   /* shows or hides the overlay, like the upstream button */
            continue;
        }
        if ([self inMotion:p]) {
            [owner setObject:@(C_MOTION) forKey:t];
            [self switchMotionSource];   /* picks the next motion source, like the upstream button */
            continue;
        }
        if ([self inSwap:p]) {
            [owner setObject:@(C_SWAP) forKey:t];
            [self switchFaceSwap];   /* turns the controller's face buttons' swap on or off */
            continue;
        }
        if ([self inFps:p]) {
            [owner setObject:@(C_FPS) forKey:t];
            [self switchFrameRate];   /* toggles the cap on touch-down, like the upstream button */
            continue;
        }
        int locked = [self lockedAt:p];
        if (locked >= 0) { [owner setObject:@(C_BTN | (locked << 8)) forKey:t]; continue; }
        /* The face buttons, the D-pad and the two sticks: the nearest one takes the touch. Each stick is grabbed by a
           touch inside its own ring (the grab circle is a little wider than the ring), so a finger lands on the stick
           the player sees, not on whichever one happens to be nearer. */
        uint64_t face = [self faceAt:p];
        CGFloat faceD = face ? MIN(dist(p, [self facePos:B_A]), dist(p, [self facePos:B_B])) : CGFLOAT_MAX;
        CGPoint dc = self.dpadCenter; CGFloat dpadD = dist(p, dc);
        BOOL dpadHit = dpadD <= self.dpadR * K_DPAD_GRAB;
        CGPoint home = self.stickHome; CGFloat stickD = dist(p, home);
        BOOL stickHit = stickD <= self.stickR * K_STICK_GRAB;
        CGPoint rhome = self.rightStickHome; CGFloat rstickD = dist(p, rhome);
        BOOL rstickHit = rstickD <= self.rightStickR * K_STICK_GRAB;
        if (face && (!dpadHit || faceD <= dpadD) && (!stickHit || faceD <= stickD) && (!rstickHit || faceD <= rstickD)) {
            [owner setObject:@(C_FACE) forKey:t];   /* the face bits are recomputed from the finger's position */
            continue;
        }
        if (dpadHit && (!stickHit || dpadD <= stickD) && (!rstickHit || dpadD <= rstickD)) {
            [owner setObject:@(C_DPAD) forKey:t]; continue;
        }
        /* The two sticks: the nearer ring wins, so a touch between them takes the closer one. A touch on a stick's
           ring holds it at its home, so the knob sits where the finger is. */
        if (stickHit || rstickHit) {
            int idx = (stickHit && rstickHit) ? (stickD <= rstickD ? 0 : 1) : (stickHit ? 0 : 1);
            _stick[idx] = t; [owner setObject:@(C_STICK | ((uint64_t)idx << 8)) forKey:t];
            _dynamic[idx] = NO; _centre[idx] = idx ? rhome : home;
            continue;
        }
        /* A touch on no control in the right third holds the right stick, centred where it lands (Breath of the
           Wild's camera stick): the ring follows the finger, so the stick can be used without looking at it. */
        if ([self inRightArea:p]) {
            _stick[1] = t; [owner setObject:@(C_STICK | (1ull << 8)) forKey:t];
            _dynamic[1] = YES; _centre[1] = p;
            continue;
        }
        /* Anywhere else on the left half: the left stick, also centred where the finger lands. */
        _stick[0] = t; [owner setObject:@(C_STICK) forKey:t];
        _dynamic[0] = YES; _centre[0] = p;
    }
    [self recompute];
}
- (void)touchesMoved:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event {
    (void)event;
    for (UITouch *t in touches) {
        CGPoint p = [t locationInView:self];
        [points setObject:[NSValue valueWithCGPoint:p] forKey:t];
        /* A stick's centre follows a finger past its radius, so turning back responds at once. */
        for (int i = 0; i < 2; i++) {
            if (!_stick[i] || _stick[i] != t || !_dynamic[i]) continue;
            CGFloat d = dist(p, _centre[i]), R = [self stickR:i];
            if (d > R) _centre[i] = CGPointMake(p.x - (p.x - _centre[i].x) * R / d, p.y - (p.y - _centre[i].y) * R / d);
        }
    }
    [self recompute];
}
- (void)touchesEnded:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event {
    (void)event;
    for (UITouch *t in touches) {
        [points removeObjectForKey:t];
        [owner removeObjectForKey:t];
        for (int i = 0; i < 2; i++) if (_stick[i] == t) { _stick[i] = nil; _dynamic[i] = NO; }
    }
    [self recompute]; [self hideLater];
}
- (void)touchesCancelled:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event { [self touchesEnded:touches withEvent:event]; }
- (void)safeAreaInsetsDidChange { [super safeAreaInsetsDidChange]; [self setNeedsLayout]; }

/* ---- Shapes ---- */
static CGPathRef circlePath(CGPoint c, CGFloat r) { return CGPathCreateWithEllipseInRect(CGRectMake(c.x - r, c.y - r, 2 * r, 2 * r), NULL); }
static CGPathRef dropPath(CGPoint c, CGFloat r, CGFloat tipAngle, CGFloat round) {
    CGFloat d = r * K_DROP_TIP, th = acos(r / d);
    CGPoint tip = CGPointMake(c.x + d * cos(tipAngle), c.y + d * sin(tipAngle));
    CGPoint p1 = CGPointMake(c.x + r * cos(tipAngle + th), c.y + r * sin(tipAngle + th));
    CGPoint p2 = CGPointMake(c.x + r * cos(tipAngle - th), c.y + r * sin(tipAngle - th));
    CGMutablePathRef p = CGPathCreateMutable();
    CGPathMoveToPoint(p, NULL, p2.x, p2.y);
    CGPathAddArcToPoint(p, NULL, tip.x, tip.y, p1.x, p1.y, round);
    CGPathAddArc(p, NULL, c.x, c.y, r, tipAngle + th, tipAngle - th + 2 * M_PI, false);
    CGPathCloseSubpath(p); return p;
}
static CGPathRef armPath(CGPoint c, CGFloat R, CGFloat w, CGFloat in, CGFloat angle, CGFloat round) {
    CGPoint v[5] = {{-w, -R}, {w, -R}, {w, -(in + w)}, {0, -in}, {-w, -(in + w)}};
    CGFloat cs = cos(angle), sn = sin(angle);
    for (int i = 0; i < 5; i++) v[i] = CGPointMake(c.x + v[i].x * cs - v[i].y * sn, c.y + v[i].x * sn + v[i].y * cs);
    CGMutablePathRef p = CGPathCreateMutable();
    CGPathMoveToPoint(p, NULL, (v[4].x + v[0].x) / 2, (v[4].y + v[0].y) / 2);
    for (int i = 0; i < 5; i++) CGPathAddArcToPoint(p, NULL, v[i].x, v[i].y, v[(i + 1) % 5].x, v[(i + 1) % 5].y, round);
    CGPathCloseSubpath(p); return p;
}
static void setPath(CAShapeLayer *l, CGPathRef p) { l.path = p; l.shadowPath = p; CGPathRelease(p); }
static void placeLabel(CATextLayer *t, CGPoint c, CGFloat fs) {
    CTFontRef f = CTFontCreateUIFontForLanguage(kCTFontUIFontEmphasizedSystem, fs, NULL);
    t.font = f; t.fontSize = fs;
    CGFloat h = CTFontGetAscent(f) + CTFontGetDescent(f) + CTFontGetLeading(f), w = fs * 3;
    t.frame = CGRectMake(c.x - w / 2, c.y - h / 2, w, h);
    CFRelease(f);
}

- (void)layoutSubviews {
    [super layoutSubviews];
    CGFloat u = self.u;
    [CATransaction begin]; [CATransaction setDisableActions:YES];
    for (int b = B_A; b <= B_Y; b++) { CGPoint c = [self facePos:b]; setPath(_key[b], circlePath(c, self.faceR)); placeLabel(_label[b], c, 20 * u); }
    for (size_t i = 0; i < sizeof(k_lockedKeys) / sizeof(k_lockedKeys[0]); i++) {
        int b = k_lockedKeys[i];
        if (b == B_PLUS || b == B_MINUS) {
            CGRect rc = [self pillRect:b];
            setPath(_key[b], CGPathCreateWithRoundedRect(rc, rc.size.height / 2, rc.size.height / 2, NULL));
            placeLabel(_label[b], CGPointMake(CGRectGetMidX(rc), CGRectGetMidY(rc)), 18 * u);
        } else if (isDrop(b)) {
            BOOL right = b == B_ZR || b == B_R; CGPoint c = [self dropCenter:b];
            setPath(_key[b], dropPath(c, [self dropR:b], right ? -M_PI_4 : -3 * M_PI_4, 4 * u));
            placeLabel(_label[b], c, 16 * u);
        } else if (isClick(b)) {
            CGPoint c = [self clickCenter:b]; setPath(_key[b], circlePath(c, K_CLICK_R * u));
            placeLabel(_label[b], c, 13 * u);
        }
    }
    static const struct { int b; CGFloat angle; } arms[] = {{B_UP, 0}, {B_RIGHT, M_PI_2}, {B_DOWN, M_PI}, {B_LEFT, -M_PI_2}};
    for (int i = 0; i < 4; i++) setPath(_key[arms[i].b], armPath(self.dpadCenter, self.dpadR, K_ARM_W * u, K_ARM_IN * u, arms[i].angle, 6 * u));
    CGPoint fc = self.fpsCenter; setPath(_fps, circlePath(fc, K_FPS_R * u)); placeLabel(_fpsLabel, fc, 12 * u);
    CGPoint tc = self.toggleCenter; setPath(_toggle, circlePath(tc, K_PAD_TOGGLE_R * u)); placeLabel(_toggleLabel, tc, 13 * u);
    /* The motion source's button: a rounded pill, wider than the pad's own button, as it carries two words. */
    CGPoint mc = self.motionCenter;
    CGRect mr = CGRectMake(mc.x - K_MOTION_W * u / 2, mc.y - K_MOTION_R * u, K_MOTION_W * u, K_MOTION_R * u * 2);
    setPath(_motion, CGPathCreateWithRoundedRect(mr, mr.size.height / 2, mr.size.height / 2, NULL));
    placeLabel(_motionLabel, mc, 11 * u);
    /* The face buttons' swap button: a small circle, like the pad's own button. */
    CGPoint sc = self.swapCenter; setPath(_swap, circlePath(sc, K_SWAP_R * u)); placeLabel(_swapLabel, sc, 11 * u);
    /* Both sticks' rings: the left one at its home, the right one at its home too (it follows the finger only while a
       swipe holds it away from there). */
    for (int i = 0; i < 2; i++) {
        CGPoint c = i ? self.rightStickHome : self.stickHome;
        setPath(_ring[i], circlePath(c, [self stickR:i]));
        _drawn[i] = c;
        CGFloat k = (i ? K_RKNOB_R : K_KNOB_R) * u; _knob[i].bounds = CGRectMake(0, 0, 2 * k, 2 * k);
        setPath(_knob[i], circlePath(CGPointMake(k, k), k));
        CAShapeLayer *in = (CAShapeLayer *)_knob[i].sublayers.firstObject; CGPathRef ip = circlePath(CGPointMake(k, k), k * 0.62);
        in.frame = _knob[i].bounds; in.path = ip; CGPathRelease(ip);
    }
    [CATransaction commit];
    [self applyVisibility];
    [self refresh];
}

- (void)refresh {   /* the pressed state → the fill, the sticks → the knob's position */
    uint64_t all = _faceBits | _btnBits;
    [CATransaction begin]; [CATransaction setDisableActions:YES];
    for (int b = 0; b < B_N; b++) {
        BOOL on = (all >> b) & 1;
        _key[b].fillColor = (on ? k_on : k_idle).CGColor;
        _label[b].foregroundColor = (on ? k_textOn : k_text).CGColor;
    }
    _fps.fillColor = (_fpsHeld ? k_on : k_idle).CGColor;
    _fpsLabel.foregroundColor = (_fpsHeld ? k_textOn : k_text).CGColor;
    _toggle.fillColor = (_toggleHeld ? k_on : k_idle).CGColor;
    _motion.fillColor = (_motionHeld ? k_on : k_idle).CGColor;
    _motionLabel.foregroundColor = (_motionHeld ? k_textOn : k_text).CGColor;
    /* The swap button's fill shows the choice (on or off), like its text does; the press itself is felt through the
       haptic feedback, as the other buttons' presses are. */
    _swap.fillColor = (_faceSwap ? k_on : k_idle).CGColor;
    _swapLabel.foregroundColor = (_faceSwap ? k_textOn : k_text).CGColor;
    for (int i = 0; i < 2; i++) {
        CGPoint h = [self stickCentre:i];
        CGPoint o = [self stickOffset:i];
        _knob[i].position = CGPointMake(h.x + o.x, h.y + o.y); _knob[i].fillColor = (_stick[i] ? k_on : k_idle).CGColor;
        /* A stick's ring follows its centre while a swipe holds it away from the home. */
        if (!CGPointEqualToPoint(h, _drawn[i])) {
            setPath(_ring[i], circlePath(h, [self stickR:i]));
            _drawn[i] = h;
        }
    }
    [CATransaction commit];
}

/* The frame rate button: it cycles the game through 30, 60 and uncapped as it is held (the user's request,
   2026-11-03). The runtime's rates are 30 (held), 60 (the display's rate) and 0 (uncapped). */
- (void)switchFrameRate {
    BOOL custom = [NSUserDefaults.standardUserDefaults boolForKey:@"TOTK_CUSTOM_PICTURE"];
    int fps = totk_frame_button_target(runtime_phone_fps());
    /* TOTK-ipa: through phone_settings.m, so the phone's heat and its Low Power Mode still have the last word (the
       button's choice is the player's; a hot phone holds 30 until it cools). */
    phone_frame_cap_set(fps);
    const char *key = totk_frame_button_key(custom);
    if (key) [NSUserDefaults.standardUserDefaults setObject:[self frameRateName:fps] forKey:@(key)];
    _fpsLabel.string = [self frameRateLabel:fps];
    [self refresh];
}

/* The rate's name in the pane's row: the same words the Settings pane offers, so the two mean the same thing. */
- (NSString *)frameRateName:(int)fps { return fps == 30 ? @"30" : fps == 0 ? @"uncapped" : @"60"; }
/* What the button shows: the rate, and the uncapped one as the sign for "no limit" (the button is small). */
- (NSString *)frameRateLabel:(int)fps { return fps == 30 ? @"30" : fps == 0 ? @"∞" : @"60"; }

- (void)drawRect:(CGRect)rect { (void)rect; }   /* the controls are layers, not drawing */
@end
