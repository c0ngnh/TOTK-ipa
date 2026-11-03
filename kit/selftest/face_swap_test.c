/* The face buttons' swap (the user's request, 2026-11-03): the game's A, B, X, Y prompts must land where a
   Nintendo controller's buttons are, whatever the controller calls the buttons it pressed.

   GameController names the face buttons by the Xbox layout: buttonA at the bottom, buttonB on the right, buttonX on
   the left, buttonY at the top. A Switch controller has A on the right, B at the bottom, X at the top and Y on the
   left. Without the swap, a pad read by position gives the game the Switch's letters at the Xbox's places; with it,
   the two pairs change hands and the game sees the Nintendo arrangement.

   The test uses the real runtime/gamepad_layout.h, so it checks the mapping the game is given, not a copy of it. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "gamepad_layout.h"

static int failures;

static void check(int ok, const char *what) {
    if (!ok) { printf("FAIL: %s\n", what); failures++; }
}

/* The Switch letter a position bit stands for, as the game is given it (controller_map.h's default layout: east A,
   south B, north X, west Y). */
static uint64_t switch_bits(uint64_t positions) {
    enum { SOUTH = 1, EAST = 2, WEST = 4, NORTH = 8 };
    uint64_t out = 0;
    if (positions & EAST) out |= GAMEPAD_SWITCH_A;
    if (positions & SOUTH) out |= GAMEPAD_SWITCH_B;
    if (positions & NORTH) out |= GAMEPAD_SWITCH_X;
    if (positions & WEST) out |= GAMEPAD_SWITCH_Y;
    return out;
}

int main(void) {
    /* An Xbox-layout pad: the button and where it is. */
    struct { const char *name; int a, b, x, y; } presses[] = {
        {"buttonA (bottom)", 1, 0, 0, 0},
        {"buttonB (right)",  0, 1, 0, 0},
        {"buttonX (left)",   0, 0, 1, 0},
        {"buttonY (top)",    0, 0, 0, 1},
    };

    /* Without the switch, nothing is swapped: the game keeps the mapping it had. */
    unsetenv("TOTK_FACE_SWAP");
    check(!gamepad_face_swap(), "the swap is off without the variable");
    for (int p = 0; p < 4; p++) {
        uint64_t got = gamepad_face_positions_swapped(presses[p].a, presses[p].b, presses[p].x, presses[p].y, 1);
        uint64_t want = gamepad_face_positions(presses[p].a, presses[p].b, presses[p].x, presses[p].y, 1);
        check(got == want, "without the switch the mapping is the one that was there");
    }

    /* With it, the two pairs change hands: the controller's own A drives the game's A, and so on, so the game's
       prompts sit where a Nintendo controller's buttons are (A right, B bottom, X top, Y left). */
    setenv("TOTK_FACE_SWAP", "1", 1);
    check(gamepad_face_swap(), "the swap is on with the variable");
    check(switch_bits(gamepad_face_positions_swapped(1, 0, 0, 0, 1)) == GAMEPAD_SWITCH_A,
          "buttonA drives the game's A");
    check(switch_bits(gamepad_face_positions_swapped(0, 1, 0, 0, 1)) == GAMEPAD_SWITCH_B,
          "buttonB drives the game's B");
    check(switch_bits(gamepad_face_positions_swapped(0, 0, 1, 0, 1)) == GAMEPAD_SWITCH_X,
          "buttonX drives the game's X");
    check(switch_bits(gamepad_face_positions_swapped(0, 0, 0, 1, 1)) == GAMEPAD_SWITCH_Y,
          "buttonY drives the game's Y");

    /* Without the swap, the same controller read by position gives the game's letters at the Xbox's places: the
       button at the bottom drives the game's B, and the one on the right drives the game's A. */
    unsetenv("TOTK_FACE_SWAP");
    check(switch_bits(gamepad_face_positions_swapped(1, 0, 0, 0, 1)) == GAMEPAD_SWITCH_B,
          "without the swap buttonA drives the game's B");
    check(switch_bits(gamepad_face_positions_swapped(0, 1, 0, 0, 1)) == GAMEPAD_SWITCH_A,
          "without the swap buttonB drives the game's A");
    setenv("TOTK_FACE_SWAP", "1", 1);

    /* All four at once: every letter is there once, and no other. */
    uint64_t all = gamepad_face_positions_swapped(1, 1, 1, 1, 1);
    check(switch_bits(all) == (GAMEPAD_SWITCH_A | GAMEPAD_SWITCH_B | GAMEPAD_SWITCH_X | GAMEPAD_SWITCH_Y),
          "all four buttons give all four letters");
    check(gamepad_face_positions_swapped(0, 0, 0, 0, 1) == 0, "no button gives nothing");

    /* "0" is off, like an unset variable: the pane's switch hands over "0" or "1". */
    setenv("TOTK_FACE_SWAP", "0", 1);
    check(!gamepad_face_swap(), "the swap is off with 0");
    setenv("TOTK_FACE_SWAP", "1", 1);

    /* A controller read by label (a Nintendo one, or TOTK_FACE_BUTTONS=label) is already right and is not touched. */
    for (int p = 0; p < 4; p++) {
        uint64_t got = gamepad_face_positions_swapped(presses[p].a, presses[p].b, presses[p].x, presses[p].y, 0);
        uint64_t want = gamepad_face_positions(presses[p].a, presses[p].b, presses[p].x, presses[p].y, 0);
        check(got == want, "a controller read by label is not swapped");
    }
    /* A Nintendo controller's A is on the right, and the game shows A there: nothing to swap. */
    check(switch_bits(gamepad_face_positions_swapped(1, 0, 0, 0, 0)) == GAMEPAD_SWITCH_A,
          "by label, buttonA drives the game's A");

    if (failures) { printf("%d check(s) failed\n", failures); return 1; }
    printf("face buttons' swap: 18 checks passed\n");
    return 0;
}
