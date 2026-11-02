/* TOTK-ipa: the RomFS identity comes from GameData/game-data/romfs-config.txt at launch (runtime/game_data.c). */
#include "game_data.h"
#define ROMFS_IMAGE_SIZE (runtime_game_number("romfs-config.txt", "ROMFS_IMAGE_SIZE"))
#define ROMFS_IMAGE_SHA256 (runtime_game_sha256("romfs-config.txt", "ROMFS_IMAGE_SHA256"))
#define ROMFS_INDEX_SHA256 (runtime_game_sha256("romfs-config.txt", "ROMFS_INDEX_SHA256"))
