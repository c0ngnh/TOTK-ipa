// TOTK-ipa: the phone's own settings (kit/shim/phone_settings.m).
#pragma once
#include <stdint.h>

/* The memory the OS would still give this app (os_proc_available_memory). */
uint64_t phone_available_memory(void);

/* The frame cap in force: 30 or 60. The player's choice, lowered while the phone is hot or in Low Power Mode. */
int phone_frame_cap(void);
void phone_frame_cap_set(int fps);

/* Start the watcher for the phone's thermal state and Low Power Mode, and take the MetalFX frame interpolation the
   Settings app's row (TOTK_MFX) chose. Called once, before the game starts. */
void phone_settings_start(void);
