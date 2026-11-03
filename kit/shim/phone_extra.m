// TOTK-ipa: the phone's own settings on top of the runtime's.
//
// Three things the runtime has or needs, and the iOS app has to reach:
//   - the thermal state and Low Power Mode (NSProcessInfo): the runtime reads the thermal state for its own logging
//     (dm_thermal_now, frontend_ios.m) but never acts on it, so a phone that heats up loses frames with no reason
//     shown. Here the frame cap follows the phone's state: 30 while it is hot or in Low Power Mode, the player's
//     choice again when it cools;
//   - the MetalFX frame interpolation (gfx/nvn/totk_mfx.m): the runtime's own settings panel is Mac only
//     (runtime_settings_toggle is empty on iOS), so the Settings app's row drives the mode instead. The interpolation
//     is GPU work, so a hot phone leaves it off as well;
//   - the memory the app may still use (os_proc_available_memory), shown on the start screen: the game asks for a
//     3.2 GiB pool, so a player who watches the number fall knows the phone is under pressure.
//
// The file is the kit's own (kit/shim/phone_extra.m); build_shell.py puts it in the tree and adds it to the project.
#import <UIKit/UIKit.h>
#import <Foundation/Foundation.h>
#include <TargetConditionals.h>
#include <os/proc.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "runtime.h"

/* ---- Memory ---- */

/* What the OS would still give this app: the same number the system uses for its kill threshold. Not the device's free
   memory (other apps take that), the memory this process may still claim. */
uint64_t phone_available_memory(void) { return (uint64_t)os_proc_available_memory(); }

/* ---- The phone's heat ---- */

/* The cap the player chose (30, 60 or 0 for uncapped). The thermal rule may lower it for a while; it never raises it
   above the choice. -1 until it is known: the first look at the runtime tells us the player's choice (the Settings app's
   row, through TOTK_PHONE_FPS, or the touch controls' button). */
static _Atomic int g_cap = -1;

/* The value this file last handed to the runtime (-1: none yet). A cap the runtime shows that this file did not make is
   the player's (the touch controls' button), and is taken as the new choice. */
static int g_applied = -1;

int phone_frame_cap(void) { int c = atomic_load(&g_cap); return c < 0 ? 60 : c; }

/* The phone's state now: 0 nominal, 1 fair, 2 serious, 3 critical. */
static int phone_thermal(void) { return (int)NSProcessInfo.processInfo.thermalState; }
static BOOL phone_low_power(void) { return NSProcessInfo.processInfo.lowPowerModeEnabled; }

/* True when the phone is under pressure: hot enough to slow down, or in Low Power Mode (which lowers the CPU's
   clock). Fair is not enough: a phone at "fair" still runs at its best speed for a while. */
static BOOL phone_is_pressed(void) { return phone_thermal() >= 2 || phone_low_power(); }

/* The game holds 30 through its own path (TOTK_PHONE_FPS=30, runtime_phone_fps_set in gfx/nvn/hle_nvn.c): the pacing
   reads it every frame (phone_holds_30), so a change takes effect at once and the game's speed stays right. */
static void push_cap(int fps) {
    if (fps == runtime_phone_fps()) { g_applied = fps; return; }
    runtime_phone_fps_set(fps);
    g_applied = fps;
}

/* The player changes the cap (the Settings app's row, the touch controls' button). The rates are 30, 60 and 0 (the
   game's own clock above the display's rate: the uncapped setting). */
void phone_frame_cap_set(int fps) {
    if (fps != 30 && fps != 60 && fps != 0) return;
    atomic_store(&g_cap, fps);
    push_cap(fps);
}

/* ---- MetalFX frame interpolation ---- */

/* The runtime's interpolation modes (gfx/nvn/totk_mfx_mode.h): the game renders at that rate and MetalFX makes the
   frame in between. The number is the runtime's own enum (MFX_OFF, MFX_30, ...), so the mode is set through the
   runtime's flag interface and not by a name of our own. */
static int mfx_mode_of(const char *name) {
    if (!name || !*name || !strcmp(name, "0")) return 0;   /* off */
    if (!strcmp(name, "interp30")) return 1;                /* the game at 30 fps, 60 pictures a second */
    if (!strcmp(name, "interp40")) return 2;
    if (!strcmp(name, "interp50")) return 3;
    if (!strcmp(name, "interpmax")) return 4;
    if (!strcmp(name, "interp60")) return 5;
    return -1;                                               /* not a mode */
}

/* The mode the player chose: the runtime reads it from TOTK_MFX at its start (mfx_init in gfx/nvn/totk_mfx.m), which
   is the Settings app's row handed over like every other row. */
static int g_mfx_choice = 0;

/* The mode in force now (-1: not known yet). The runtime takes it over at a frame boundary, so a frame is never half
   on (mfx_latch in gfx/nvn/nvn_mtl.m). */
static int g_mfx_live = -1;

/* The mode for the next game frame. */
static void push_mfx(int mode) {
    extern void dm_gfx_set_flag(const char *name, int value);
    dm_gfx_set_flag("mfx_interp", mode);
}

/* ---- The watcher ---- */

/* The phone's state is read every few seconds and the cap and the interpolation follow it. A change of the thermal
   state or of Low Power Mode is logged, so the log says why the frame rate moved. */
static void phone_settings_watch(void) {
    static int lastThermal = -1, lastLowPower = -1;
    int thermal = phone_thermal();
    BOOL low = phone_low_power();
    if (thermal != lastThermal) {
        lastThermal = thermal;
        fprintf(stderr, "[totk] thermal state %d (%s)\n", thermal,
                thermal == 0 ? "nominal" : thermal == 1 ? "fair" : thermal == 2 ? "serious" : "critical");
    }
    if ((int)low != lastLowPower) {
        lastLowPower = (int)low;
        fprintf(stderr, "[totk] Low Power Mode %s\n", low ? "on" : "off");
    }
    /* A cap the runtime shows that this file did not set is the player's: take it as the choice and keep it. */
    int cur = runtime_phone_fps();
    if (cur != g_applied) {
        atomic_store(&g_cap, cur);
        g_applied = cur;
        fprintf(stderr, "[totk] frame cap: %d (the player's choice)\n", cur);
    }
    /* The cap: the player's choice, 30 while the phone is pressed. The uncapped setting (0) is the game's own clock
       above the display's rate: a hot phone holds 30 instead, and the player's choice comes back when it cools. */
    int want = phone_frame_cap();
    if (phone_is_pressed() && want != 30) want = 30;
    if (want != cur) push_cap(want);
    /* The interpolation: off while the phone is pressed (it is GPU work on top of the game's own frames). */
    int mfx = phone_is_pressed() ? 0 : g_mfx_choice;
    if (mfx != g_mfx_live) {
        g_mfx_live = mfx;
        push_mfx(mfx);
    }
}

/* Start the watcher. The phone's state is taken into account at once: a phone that is already hot when the game starts
   should not run a full minute before it notices. */
void phone_settings_start(void) {
    g_mfx_choice = mfx_mode_of(getenv("TOTK_MFX"));
    if (g_mfx_choice < 0) g_mfx_choice = 0;
    g_mfx_live = g_mfx_choice;
    phone_settings_watch();
    NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
    [center addObserverForName:NSProcessInfoThermalStateDidChangeNotification object:nil
                        queue:NSOperationQueue.mainQueue
                   usingBlock:^(NSNotification *n) { (void)n; phone_settings_watch(); }];
    [center addObserverForName:NSProcessInfoPowerStateDidChangeNotification object:nil
                        queue:NSOperationQueue.mainQueue
                   usingBlock:^(NSNotification *n) { (void)n; phone_settings_watch(); }];
    NSTimer *t = [NSTimer scheduledTimerWithTimeInterval:3.0 repeats:YES block:^(NSTimer *timer) {
        (void)timer; phone_settings_watch();
    }];
    [NSRunLoop.mainRunLoop addTimer:t forMode:NSRunLoopCommonModes];
}
