/* TOTK-ipa: the embedded-code hashes come from GameData/game-data/embedded-hashes.txt at launch
   (runtime/game_data.c), not from a header compiled into the app.

   The file holds one line per module: "<name> <x0-sha256> <w-sha256> <x1-sha256>". The import tool writes it after it
   has filled the app's executable, so the hashes bind the app's contents to the player's verified rewrites. */
#pragma once
#include "game_data.h"

typedef struct { const char *name, *x0, *w, *x1; } IosEmbed;

/* The three modules' rows, read once from the file. The values are pointers into the file's text, which the game data
   reader keeps for the life of the program. */
static IosEmbed totk_ios_embed[3];
static int totk_ios_embed_loaded;

static inline void totk_ios_embed_load(void) {
    if (totk_ios_embed_loaded) return;
    static const char *const names[3] = {"main", "subsdk0", "sdk"};
    for (unsigned i = 0; i < 3; i++) {
        char key[64];
        snprintf(key, sizeof key, "%s_X0", names[i]);
        totk_ios_embed[i].name = names[i];
        totk_ios_embed[i].x0 = runtime_game_sha256("embedded-hashes.txt", key);
        snprintf(key, sizeof key, "%s_W", names[i]);
        totk_ios_embed[i].w = runtime_game_sha256("embedded-hashes.txt", key);
        snprintf(key, sizeof key, "%s_X1", names[i]);
        totk_ios_embed[i].x1 = runtime_game_sha256("embedded-hashes.txt", key);
    }
    totk_ios_embed_loaded = 1;
}

#define ios_embed totk_ios_embed
