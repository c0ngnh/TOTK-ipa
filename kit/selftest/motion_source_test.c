/* The motion source's gate (runtime/motion_fusion.c): the game has one six-axis device, and the player's choice
   decides which sensor drives it. A sample from the source that is not in force must not reach the fusion at all,
   or the two sensors' samples would be mixed into one orientation.

   The test drives the real runtime/motion_fusion.c: it feeds one source, reads the states the game would read, and
   checks that a source that is not in force leaves the game with no motion at all.

   Build and run (from the patched tree):
       clang -std=gnu11 -I runtime motion_source_test.c runtime/motion_fusion.c -o motion_source_test -lm -lpthread
       ./motion_source_test
*/
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "runtime.h"

static int failures, checks;
static void check(int ok, const char *what) {
    checks++;
    if (!ok) { failures++; fprintf(stderr, "FAIL: %s\n", what); }
}

/* The runtime's own clock, so the fusion sees the time go by. */
static uint64_t fake_now;
uint64_t runtime_now_ns(void) { return fake_now; }
_Noreturn void runtime_fail(const char *message) { fprintf(stderr, "runtime_fail: %s\n", message); exit(2); }
void runtime_hid_feedback_stats(uint64_t *values, uint64_t *motion_reads) { *values = 0; *motion_reads = 0; }

/* Feed a source a sample with a clear rate, so a sample that slips through would show in the states. */
#define SAMPLE_RATE 0.5   /* rad/s */
static void feed(int who) {
    const double acc[3] = {0, 0, -1}, gyro[3] = {SAMPLE_RATE, 0, 0};
    fake_now += 10000000ull;   /* ten milliseconds between the samples */
    if (who == 0) runtime_motion_feed(acc, gyro, fake_now);
    else runtime_motion_feed_phone(acc, gyro, fake_now);
}

/* How many states the game would read now. */
static int states(void) {
    RuntimeMotionState s[8];
    return runtime_motion_read(s, 8);
}

/* Is the sample's rate in the states the game reads? The states hold revolutions a second. */
static int rate_in_states(void) {
    RuntimeMotionState s[8];
    int n = runtime_motion_read(s, 8), found = 0;
    double rps = SAMPLE_RATE / (2 * M_PI);
    for (int i = 0; i < n; i++) if (fabs(s[i].gyro[0] - rps) < 1e-4) found = 1;
    return found;
}

/* The motion the game sees goes stale when no sample reaches the fusion for a while (200 ms). */
#define STALE_AFTER 300000000ull

int main(void) {
    /* --- the automatic mode: both sources reach the fusion, as before the choice existed --- */
    runtime_motion_source(RUNTIME_MOTION_SOURCE_AUTO);
    fake_now = 1000000000ull;
    runtime_motion_start();
    feed(0);
    check(states() > 0, "automatic: the controller's samples reach the game");
    check(rate_in_states(), "automatic: the controller's rate is in the states");
    feed(1);
    check(states() > 0, "automatic: the phone's samples reach the game");
    check(rate_in_states(), "automatic: the phone's rate is in the states");

    /* --- the phone in force: the controller's samples are dropped --- */
    runtime_motion_source(RUNTIME_MOTION_SOURCE_PHONE);
    feed(1);
    check(states() > 0, "the phone in force: the phone's samples reach the game");
    check(rate_in_states(), "the phone in force: the phone's rate is in the states");
    /* Now only the controller reports: the motion the game sees must go stale, because the controller's samples
       are dropped at the door. */
    fake_now += STALE_AFTER;
    feed(0);
    check(states() == 0, "the phone in force: the controller's samples do not reach the game");

    /* --- the controller in force: the phone's samples are dropped --- */
    runtime_motion_source(RUNTIME_MOTION_SOURCE_CONTROLLER);
    runtime_motion_live(1);      /* a controller with motion is attached */
    feed(0);
    check(states() > 0, "the controller in force: the controller's samples reach the game");
    check(rate_in_states(), "the controller in force: the controller's rate is in the states");
    fake_now += STALE_AFTER;
    feed(1);
    check(states() == 0, "the controller in force: the phone's samples do not reach the game");

    /* --- the controller in force, but no controller with motion is attached: the phone takes over, so the game is
       not left without motion --- */
    runtime_motion_live(0);
    feed(1);
    check(states() > 0, "the controller in force without a motion controller: the phone takes over");
    check(rate_in_states(), "the controller in force without a motion controller: the phone's rate is in the states");
    runtime_motion_live(1);

    /* --- the choice is remembered and can be read back --- */
    check(runtime_motion_source_get() == RUNTIME_MOTION_SOURCE_CONTROLLER, "the source in force can be read back");
    runtime_motion_source(RUNTIME_MOTION_SOURCE_PHONE);
    check(runtime_motion_source_get() == RUNTIME_MOTION_SOURCE_PHONE, "the source in force can be changed");
    runtime_motion_source(RUNTIME_MOTION_SOURCE_AUTO);
    check(runtime_motion_source_get() == RUNTIME_MOTION_SOURCE_AUTO, "the source in force can be set back to automatic");

    if (failures) { fprintf(stderr, "motion source: %d of %d checks failed\n", failures, checks); return 1; }
    printf("motion source: %d checks passed\n", checks);
    return 0;
}
