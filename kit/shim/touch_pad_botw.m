#import "touch_pad.h"
#import "device_motion.h"
#import "phone_settings.h"
#import <GameController/GameController.h>
#import <CoreText/CoreText.h>
#include <math.h>
#include <stdlib.h>
#include "runtime.h"
#include "settings_map.h"

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
    K_STICK_X = 81, K_STICK_R = 77, K_KNOB_R = 30,  // the left stick: mirrors the diamond, the ring as large as the whole diamond
    K_STICK_GRAB = 1.4,                             // how near the ring's centre a touch-down grabs a stick
    K_FULL = 0.8,                                   // full tilt at this fraction of the ring radius
    K_DEAD = 0.1,                                   // the stick's dead zone (times the ring radius)
    K_LOW_X = 231, K_LOW_Y = 64,                    // the D-pad's centre from the outer edge and the bottom
    K_DPAD_R = 48, K_ARM_W = 17, K_ARM_IN = 11,     // the D-pad: arm outer edge from the centre, half-width, tip from the centre
    K_DPAD_GRAB = 1.3,                              // the D-pad's grab radius (times the outer edge)
    K_RSTICK_R = 60,                                // the right stick (not drawn): the radius around its centre
    K_RSWIPE = 1.0 / 3,                             // the right stick's area: this fraction of the width from the right edge
    K_CLICK_X = 102, K_CLICK_R = 17;                // L3 / R3: centre from the outer edge, radius

static UIColor *k_idle, *k_on, *k_line, *k_ringFill, *k_text, *k_textOn;

@implementation TOTKTouchPad {
    NSMapTable<UITouch *, NSValue *> *points;
    NSMapTable<UITouch *, NSValue *> *leftOrigins;    // where each left-stick touch went down
    NSMapTable<UITouch *, NSValue *> *rightOrigins;   // the same for the camera stick
    NSMapTable<UITouch *, NSNumber *> *owner;         // touch → the control it holds (the key for C_BTN, << 8)
    BOOL gamepad, concealed;                          // a controller is connected; the layer is hidden for it
    NSTimer *hideTimer;
    CAShapeLayer *_key[B_N]; CATextLayer *_label[B_N];
    CAShapeLayer *_ring, *_knob;
    CAShapeLayer *_fps; CATextLayer *_fpsLabel; BOOL _fpsHeld;
    UIImpactFeedbackGenerator *_touchFeedback;        // one short feedback per press edge
    unsigned _hapticSticks;
    BOOL _stickShown;
    uint64_t _faceBits, _btnBits;
}

enum { C_NONE = 0, C_STICK, C_DPAD, C_BTN, C_FACE, C_FPS };

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
        leftOrigins = [NSMapTable strongToStrongObjectsMapTable];
        rightOrigins = [NSMapTable strongToStrongObjectsMapTable];
        owner = [NSMapTable strongToStrongObjectsMapTable];
        CAShapeLayer *controls = [CAShapeLayer layer]; [self.layer addSublayer:controls];
        _ring = shape(controls); _ring.fillColor = k_ringFill.CGColor;
        _knob = shape(controls);
        CAShapeLayer *in = [CAShapeLayer layer]; in.fillColor = nil; in.strokeColor = k_line.CGColor; in.lineWidth = 1.5;
        [_knob addSublayer:in];
        static NSString *const names[B_N] = {@"A", @"B", @"X", @"Y", @"L3", @"R3", @"L", @"R", @"ZL", @"ZR", @"+", @"−"};
        for (int b = 0; b < B_N; b++) {
            _key[b] = shape(controls);
            if (names[b]) _label[b] = label(_key[b], names[b]);   // the D-pad arms carry no label
        }
        _fps = shape(controls); _fpsLabel = label(_fps, @"60");
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
    if (gamepad) [self conceal]; else { concealed = NO; [self setNeedsLayout]; }
}

- (void)conceal {
    concealed = YES;
    /* Fingers on the screen when it hides would otherwise hold their buttons and sticks. */
    [points removeAllObjects]; [leftOrigins removeAllObjects]; [rightOrigins removeAllObjects]; [owner removeAllObjects];
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
- (CGFloat)stickR { return K_STICK_R * self.u; }
- (CGFloat)rightStickR { return K_RSTICK_R * self.u; }
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

static CGFloat dist(CGPoint a, CGPoint b) { return hypot(a.x - b.x, a.y - b.y); }

/* The keys locked at touch-down: the shoulders and the − / + pills. (The enum's order is the Npad's bit order, so L
   and R come before ZL and ZR: the loops below name the keys instead of ranging over them.) */
static const int k_lockedKeys[] = {B_ZL, B_ZR, B_L, B_R, B_PLUS, B_MINUS};
- (int)lockedAt:(CGPoint)p {
    CGFloat u = self.u;
    for (size_t i = 0; i < sizeof(k_lockedKeys) / sizeof(k_lockedKeys[0]); i++) {
        int b = k_lockedKeys[i];
        BOOL hit = isDrop(b) ? dist(p, [self dropCenter:b]) <= [self dropR:b] * 1.35
                 : CGRectContainsPoint(CGRectInset([self pillRect:b], -8 * u, -8 * u), p);
        if (hit) return b;
    }
    return -1;
}
- (BOOL)inFps:(CGPoint)p { return dist(p, self.fpsCenter) <= K_FPS_R * self.u * 1.6; }
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
    uint64_t face = 0, btn = 0; BOOL fps = NO;
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
        }
    }
    int32_t lx = 0, ly = 0, rx = 0, ry = 0;
    CGFloat R = self.stickR;
    for (UITouch *t in leftOrigins.keyEnumerator) {
        CGPoint o = [leftOrigins objectForKey:t].CGPointValue, p = [points objectForKey:t].CGPointValue;
        CGFloat dx = p.x - o.x, dy = o.y - p.y, d = hypot(dx, dy);
        if (d > R) { dx *= R / d; dy *= R / d; }
        CGFloat dz = R * K_DEAD;
        if (d <= dz) continue;
        CGFloat m = fmin((d - dz) / (R * K_FULL - dz), 1) / d;
        lx = (int32_t)lrint(dx * m * 32767); ly = (int32_t)lrint(dy * m * 32767);
    }
    for (UITouch *t in rightOrigins.keyEnumerator) {
        CGPoint o = [rightOrigins objectForKey:t].CGPointValue, p = [points objectForKey:t].CGPointValue;
        CGFloat dx = p.x - o.x, dy = o.y - p.y, d = hypot(dx, dy);
        CGFloat RR = self.rightStickR;
        if (d > RR) { dx *= RR / d; dy *= RR / d; }
        CGFloat dz = RR * K_DEAD;
        if (d <= dz) continue;
        CGFloat m = fmin((d - dz) / (RR * K_FULL - dz), 1) / d;
        rx = (int32_t)lrint(dx * m * 32767); ry = (int32_t)lrint(dy * m * 32767);
    }
    BOOL changed = face != _faceBits || btn != _btnBits || fps != _fpsHeld;
    uint64_t pressed = (face | btn) & ~(_faceBits | _btnBits);
    unsigned gripping = (leftOrigins.count ? 1u : 0) | (rightOrigins.count ? 2u : 0);
    if (pressed || (fps && !_fpsHeld) || (gripping & ~_hapticSticks)) {
        [_touchFeedback impactOccurredWithIntensity:0.6]; [_touchFeedback prepare];
    }
    _hapticSticks = gripping;
    _faceBits = face; _btnBits = btn; _fpsHeld = fps;
    RuntimeGamepadState s = {.connected = 1, .buttons = face | btn, .lx = lx, .ly = ly, .rx = rx, .ry = ry};
    runtime_touch_pad_set(&s);
    BOOL stick = leftOrigins.count > 0;
    if (changed || stick || _stickShown) [self refresh];
    _stickShown = stick;
}

/* ---- Touch ---- */
- (void)touchesBegan:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event {
    (void)event; concealed = NO; [hideTimer invalidate]; hideTimer = nil;
    totk_device_motion_note_touch();   // a finger on the screen takes the aiming from a controller's gyro (phone_motion.m)
    for (UITouch *t in touches) {
        CGPoint p = [t locationInView:self]; NSValue *v = [NSValue valueWithCGPoint:p]; [points setObject:v forKey:t];
        if ([self inFps:p]) {
            [owner setObject:@(C_FPS) forKey:t];
            [self switchFrameRate];   /* toggles the cap on touch-down, like the upstream button */
            continue;
        }
        int locked = [self lockedAt:p];
        if (locked >= 0) { [owner setObject:@(C_BTN | (locked << 8)) forKey:t]; continue; }
        /* The face buttons, the D-pad and the sticks: the nearest one takes the touch. */
        uint64_t face = [self faceAt:p];
        CGFloat faceD = face ? MIN(dist(p, [self facePos:B_A]), dist(p, [self facePos:B_B])) : CGFLOAT_MAX;
        CGPoint dc = self.dpadCenter; CGFloat dpadD = dist(p, dc);
        BOOL dpadHit = dpadD <= self.dpadR * K_DPAD_GRAB;
        CGPoint home = self.stickHome; CGFloat stickD = dist(p, home);
        BOOL stickHit = stickD <= self.stickR * K_STICK_GRAB;
        if (face && (!dpadHit || faceD <= dpadD) && (!stickHit || faceD <= stickD)) {
            [owner setObject:@(C_FACE) forKey:t];   /* the face bits are recomputed from the finger's position */
            continue;
        }
        if (dpadHit && (!stickHit || dpadD <= stickD)) { [owner setObject:@(C_DPAD) forKey:t]; continue; }
        if ([self inRightArea:p]) { [rightOrigins setObject:v forKey:t]; continue; }
        [leftOrigins setObject:v forKey:t];
    }
    [self recompute];
}
- (void)touchesMoved:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event {
    (void)event;
    for (UITouch *t in touches) [points setObject:[NSValue valueWithCGPoint:[t locationInView:self]] forKey:t];
    [self recompute];
}
- (void)touchesEnded:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event {
    (void)event;
    for (UITouch *t in touches) {
        [points removeObjectForKey:t]; [leftOrigins removeObjectForKey:t]; [rightOrigins removeObjectForKey:t];
        [owner removeObjectForKey:t];
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
    setPath(_ring, circlePath(self.stickHome, self.stickR));
    CGFloat k = K_KNOB_R * u; _knob.bounds = CGRectMake(0, 0, 2 * k, 2 * k);
    setPath(_knob, circlePath(CGPointMake(k, k), k));
    CAShapeLayer *in = (CAShapeLayer *)_knob.sublayers.firstObject; CGPathRef ip = circlePath(CGPointMake(k, k), k * 0.62);
    in.frame = _knob.bounds; in.path = ip; CGPathRelease(ip);
    [CATransaction commit];
    [self refresh];
}

- (void)refresh {   /* the pressed state → the fill, the stick → the knob's position */
    uint64_t all = _faceBits | _btnBits;
    [CATransaction begin]; [CATransaction setDisableActions:YES];
    for (int b = 0; b < B_N; b++) {
        BOOL on = (all >> b) & 1;
        _key[b].fillColor = (on ? k_on : k_idle).CGColor;
        _label[b].foregroundColor = (on ? k_textOn : k_text).CGColor;
    }
    _fps.fillColor = (_fpsHeld ? k_on : k_idle).CGColor;
    _fpsLabel.foregroundColor = (_fpsHeld ? k_textOn : k_text).CGColor;
    CGPoint home = self.stickHome;
    CGPoint knob = home;
    for (UITouch *t in leftOrigins.keyEnumerator) {
        CGPoint o = [leftOrigins objectForKey:t].CGPointValue, p = [points objectForKey:t].CGPointValue;
        CGFloat dx = p.x - o.x, dy = p.y - o.y, d = hypot(dx, dy), R = self.stickR;
        if (d > R) { dx *= R / d; dy *= R / d; }
        knob = CGPointMake(o.x + dx, o.y + dy);
        break;
    }
    _knob.position = knob; _knob.fillColor = (leftOrigins.count ? k_on : k_idle).CGColor;
    [CATransaction commit];
}

/* The frame rate button: it switches the game between 60 and 30 as it is held. */
- (void)switchFrameRate {
    BOOL custom = [NSUserDefaults.standardUserDefaults boolForKey:@"TOTK_CUSTOM_PICTURE"];
    int fps = totk_frame_button_target(runtime_phone_fps() == 30);
    /* TOTK-ipa: through phone_settings.m, so the phone's heat and its Low Power Mode still have the last word (the
       button's choice is the player's; a hot phone holds 30 until it cools). */
    phone_frame_cap_set(fps);
    const char *key = totk_frame_button_key(custom);
    if (key) [NSUserDefaults.standardUserDefaults setObject:fps == 30 ? @"30" : @"60" forKey:@(key)];
    _fpsLabel.string = fps == 30 ? @"30" : @"60";
    [self refresh];
}

- (void)drawRect:(CGRect)rect { (void)rect; }   /* the controls are layers, not drawing */
@end
