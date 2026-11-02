#!/usr/bin/env python3
"""TOTK-ipa: the kit's own additions to the upstream runtime and app.

Each patch is a small, checked edit of the upstream tree: the text to find must be there exactly once, or the build
stops with a message (the upstream code changed; the patch needs to be written again).

    apply_patches.py <tree>     the tree is games/totk of a MacNativeGames checkout
"""
import sys
from pathlib import Path


def replace_once(path, old, new, note):
    text = path.read_text()
    if text.count(old) != 1:
        raise SystemExit(f'{path.name}: {note}: expected exactly one "{old.strip()[:60]}" '
                         f'(MacNativeGames changed; update kit/shim/apply_patches.py)')
    path.write_text(text.replace(old, new))
    print(f'  patched {path.name}: {note}', flush=True)


def insert_after(path, anchor, text, note):
    replace_once(path, anchor, anchor + text, note)


def main(tree):
    tree = Path(tree)

    # --- #2: the controller's Home and Capture buttons are system gestures on iOS ---
    # Home opens the Games overlay and Capture takes a screenshot, so a press of either interrupts the game. The app
    # gives the two buttons no function, so they are taken away from the system and the controller keeps them
    # (Breath of the Wild's front end does the same: dm/ios/Sources/DmGamepad.m pad_keep_system_buttons).
    gamepad = tree / 'runtime/gamepad.m'
    replace_once(gamepad,
                 'static void attach_gamepad(GCController *controller) {\n'
                 '    GCExtendedGamepad *pad = controller.extendedGamepad;\n'
                 '    if (!pad) return;\n',
                 '/* TOTK-ipa: the Home and Capture buttons are system gestures on iOS: Home opens the Games overlay and\n'
                 '   Capture takes a screenshot, so a press of either interrupts the game. The app gives them no function,\n'
                 '   so they are taken away from the system and the controller keeps them (Breath of the Wild\'s front end\n'
                 '   does the same: dm/ios/Sources/DmGamepad.m pad_keep_system_buttons). */\n'
                 'static void pad_keep_system_buttons(GCController *c) {\n'
                 '    for (NSString *b in @[GCInputButtonHome, GCInputButtonShare])\n'
                 '        c.physicalInputProfile.buttons[b].preferredSystemGestureState = GCSystemGestureStateDisabled;\n'
                 '}\n'
                 '\n'
                 'static void attach_gamepad(GCController *controller) {\n'
                 '    GCExtendedGamepad *pad = controller.extendedGamepad;\n'
                 '    if (!pad) return;\n'
                 '    pad_keep_system_buttons(controller);\n',
                 '#2 the controller\'s system gestures')

    # --- #4: the split image (romfs.bin.000, .001, ...) is mapped in memory, part by part ---
    # The runtime's mmap fast path was written for a single file: with parts it fell back to pread for every read.
    # The phone gets the 17 GB image as parts (devicectl drops the connection on a single file of that size), so the
    # fast path was never used there. Each part is mapped on its own; a read that crosses a part boundary is done
    # part by part.
    romfs = tree / 'runtime/romfs.c'
    replace_once(romfs,
                 'static const uint8_t *image_map;\n'
                 'static char mount_name[32];\n'
                 'static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;\n',
                 'static const uint8_t *image_map;\n'
                 '/* TOTK-ipa: the split image (romfs.bin.000, .001, ...) mapped part by part: image_maps[c] is part c,\n'
                 '   each of chunk_size bytes except the last. The whole image is not one range: it is 17 GB and the parts\n'
                 '   are separate files, so one mapping per part is what the layout allows. */\n'
                 'static const uint8_t *image_maps[MAX_CHUNKS];\n'
                 'static char mount_name[32];\n'
                 'static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;\n'
                 '\n'
                 '/* Copy n bytes from the image at off into buf, through the mappings. 0 when the range is not in the\n'
                 '   image (the caller then reads with pread). */\n'
                 'static int image_mapped_read(void *buf,uint64_t off,size_t n) {\n'
                 ' if(!nchunks||!image_maps[0])return 0;\n'
                 ' uint8_t *out=(uint8_t *)buf;\n'
                 ' while(n){\n'
                 '  uint64_t c=off/chunk_size,o=off%chunk_size;\n'
                 '  if(c>=nchunks||!image_maps[c])return 0;\n'
                 '  size_t take=n<(size_t)(chunk_size-o)?n:(size_t)(chunk_size-o);\n'
                 '  memcpy(out,image_maps[c]+o,take);\n'
                 '  out+=take;off+=take;n-=take;\n'
                 ' }\n'
                 ' return 1;\n'
                 '}\n',
                 '#4 the split image in memory')
    replace_once(romfs,
                 ' if(fd==image_fd&&image_map){memcpy(buffer,image_map+base+(uint64_t)offset,(size_t)n);done=n;}\n',
                 ' if(fd==image_fd&&image_map){memcpy(buffer,image_map+base+(uint64_t)offset,(size_t)n);done=n;}\n'
                 ' else if(fd==image_fd&&image_maps[0]&&image_mapped_read(buffer,base+(uint64_t)offset,(size_t)n))done=n;\n',
                 '#4 the read path through the parts')
    replace_once(romfs,
                 ' if(!nchunks&&getenv("TOTK_ROMFS_MMAP")&&strcmp(getenv("TOTK_ROMFS_MMAP"),"0")){\n'
                 '  void *mapped=mmap(NULL,(size_t)ROMFS_IMAGE_SIZE,PROT_READ,MAP_PRIVATE,image_fd,0);\n'
                 '  if(mapped!=MAP_FAILED){image_map=mapped;fprintf(stderr,"[totk] RomFS mmap read path enabled\\n");}\n'
                 '  else fprintf(stderr,"[totk] RomFS mmap failed (%s); using pread\\n",strerror(errno));\n'
                 ' }\n',
                 ' if(getenv("TOTK_ROMFS_MMAP")&&strcmp(getenv("TOTK_ROMFS_MMAP"),"0")){\n'
                 '  if(!nchunks){\n'
                 '   void *mapped=mmap(NULL,(size_t)ROMFS_IMAGE_SIZE,PROT_READ,MAP_PRIVATE,image_fd,0);\n'
                 '   if(mapped!=MAP_FAILED){image_map=mapped;fprintf(stderr,"[totk] RomFS mmap read path enabled\\n");}\n'
                 '   else fprintf(stderr,"[totk] RomFS mmap failed (%s); using pread\\n",strerror(errno));\n'
                 '  }else{\n'
                 '   /* TOTK-ipa: the parts are mapped one by one (the phone gets the image split, and the old fast path\n'
                 '      was written for a single file, so it never ran there). */\n'
                 '   for(unsigned c=0;c<nchunks;c++){\n'
                 '    off_t len=(off_t)(c+1<nchunks?chunk_size:(uint64_t)ROMFS_IMAGE_SIZE-c*chunk_size);\n'
                 '    void *mapped=mmap(NULL,(size_t)len,PROT_READ,MAP_PRIVATE,chunk_fds[c],0);\n'
                 '    if(mapped==MAP_FAILED){\n'
                 '     fprintf(stderr,"[totk] RomFS mmap failed on part %u (%s); using pread\\n",c,strerror(errno));\n'
                 '     for(unsigned j=0;j<c;j++){munmap((void *)image_maps[j],(size_t)chunk_size);image_maps[j]=NULL;}\n'
                 '     break;\n'
                 '    }\n'
                 '    image_maps[c]=mapped;\n'
                 '   }\n'
                 '   if(image_maps[0])fprintf(stderr,"[totk] RomFS mmap read path enabled (%u parts)\\n",nchunks);\n'
                 '  }\n'
                 ' }\n',
                 '#4 the parts mapped in memory')

    # --- #8: the shared fonts come from the phone's GameData when it holds them ---
    # The app carries the six shared fonts (they never change), but the resources folder beside the app carries them
    # too, so a player who keeps the whole game outside the app has every file in one place. When the phone's
    # Documents/GameData holds every font its manifest names, they are read from there; otherwise the app's own copy is
    # used. All of them are checked, not one: the runtime ends the game on a font it cannot open, so a half-copied
    # folder must not be preferred over the app's complete one.
    main_m = tree / 'ios/Sources/main.m'
    replace_once(main_m,
                 '    setenv("TOTK_SHARED_FONTS",[res stringByAppendingPathComponent:@"shared-fonts"].fileSystemRepresentation,1);\n',
                 '    /* TOTK-ipa: the shared fonts (the six .bfttf files, from the console\'s firmware): the app carries them,\n'
                 '       and the resources folder beside it carries them too, so the game is complete in one place. The\n'
                 '       phone\'s copy is used when it holds every font its manifest names; otherwise the app\'s own copy\n'
                 '       is used. All of them are checked, not one: the runtime ends the game on a font it cannot open,\n'
                 '       so a half-copied folder must not be preferred over the app\'s complete one. */\n'
                 '    NSString *appFonts = [res stringByAppendingPathComponent:@"shared-fonts"];\n'
                 '    NSString *phoneFonts = [gameData stringByAppendingPathComponent:@"shared-fonts"];\n'
                 '    BOOL phoneHasFonts = NO;\n'
                 '    NSData *fontManifest = [NSData dataWithContentsOfFile:[phoneFonts stringByAppendingPathComponent:@"manifest.json"]];\n'
                 '    NSDictionary *fontRows = fontManifest ? [NSJSONSerialization JSONObjectWithData:fontManifest options:0 error:nil] : nil;\n'
                 '    NSArray *fontList = [fontRows[@"fonts"] isKindOfClass:NSArray.class] ? fontRows[@"fonts"] : nil;\n'
                 '    if (fontList.count) {\n'
                 '        phoneHasFonts = YES;\n'
                 '        for (NSDictionary *row in fontList) {\n'
                 '            NSString *fontName = [row[@"type"] isKindOfClass:NSNumber.class] && [row[@"name"] isKindOfClass:NSString.class]\n'
                 '                ? [NSString stringWithFormat:@"%@-%@.bfttf", row[@"type"], row[@"name"]] : nil;\n'
                 '            if (!fontName || ![fm fileExistsAtPath:[phoneFonts stringByAppendingPathComponent:fontName]]) { phoneHasFonts = NO; break; }\n'
                 '        }\n'
                 '    }\n'
                 '    setenv("TOTK_SHARED_FONTS",(phoneHasFonts ? phoneFonts : appFonts).fileSystemRepresentation,1);\n'
                 '    if (!phoneHasFonts && fontList.count)\n'
                 '        fprintf(stderr, "[totk] the shared fonts in the phone folder are incomplete; the app copy is used\\n");\n',
                 '#8 the shared fonts from the phone\'s GameData')

    # --- #7: the MetalFX frame interpolation, in the Settings pane ---
    # The runtime has the frame interpolation (gfx/nvn/totk_mfx.m) and its own settings panel can turn it on, but that
    # panel is Mac only (runtime_settings_toggle is empty on iOS), so the phone could not reach it. The runtime reads
    # the mode from TOTK_MFX at its start (mfx_init), so the pane's row is handed over like every other row.
    sys.path.insert(0, str(Path(__file__).parent))
    import settings_rows
    settings_rows.main(tree / 'ios/Settings.bundle')

    # --- #3 and #6: the phone's thermal state, Low Power Mode, the memory readout and the Metal HUD ---
    # The phone's own settings (kit/shim/phone_extra.m): the frame cap follows the thermal state and Low Power
    # Mode, the memory the app may still use is read for the start screen, and the MetalFX interpolation is set from
    # the Settings app's row.
    shim = tree / 'ios/Sources/phone_extra.m'
    shim.write_bytes((Path(__file__).with_name('phone_extra.m')).read_bytes())
    (tree / 'ios/Sources/phone_extra.h').write_bytes((Path(__file__).with_name('phone_extra.h')).read_bytes())

    # The app's own Metal HUD (frame rate, frame and GPU time, memory): Apple's HUD over the game, as Breath of the
    # Wild's front end has it (dm/ios/Sources/front_ios.m: developerHUDProperties).
    main_m = tree / 'ios/Sources/main.m'
    replace_once(main_m,
                 '#import "touch_pad.h"\n',
                 '#import "touch_pad.h"\n'
                 '#import "phone_extra.h"\n',
                 '#3 the phone\'s settings')
    replace_once(main_m,
                 '    runtime_ios_attach_layer((CAMetalLayer *)self.gameView.layer, self.gameView);\n',
                 '    runtime_ios_attach_layer((CAMetalLayer *)self.gameView.layer, self.gameView);\n'
                 '    /* TOTK-ipa: Apple\'s Metal performance HUD over the game (frame rate, frame and GPU time, memory),\n'
                 '       as Breath of the Wild\'s front end has it (dm/ios/Sources/front_ios.m). The Settings app\'s row\n'
                 '       (TOTK_METAL_HUD) turns it on. */\n'
                 '    if ([NSUserDefaults.standardUserDefaults boolForKey:@"TOTK_METAL_HUD"])\n'
                 '        ((CAMetalLayer *)self.gameView.layer).developerHUDProperties = @{@"mode": @"default"};\n'
                 '    /* TOTK-ipa: the phone\'s heat and its Low Power Mode now decide the frame cap (phone_extra.m). */\n'
                 '    phone_settings_start();\n',
                 '#6 the Metal performance HUD')

    # The start screen: the memory the app may still use, so a player sees the phone under pressure.
    start = tree / 'ios/Sources/start_screen.m'
    replace_once(start,
                 '#import "start_screen.h"\n',
                 '#import "start_screen.h"\n'
                 '#import "phone_extra.h"\n',
                 '#6 the memory readout')
    replace_once(start,
                 '    note.font = [UIFont systemFontOfSize:13]; note.textColor = [UIColor colorWithWhite:0.6 alpha:1];\n',
                 '    /* TOTK-ipa: the memory the OS would still give the game (os_proc_available_memory). The game asks for\n'
                 '       a 3.2 GiB pool, so a player who watches this fall knows the phone is under pressure. */\n'
                 '    UILabel *memory = [UILabel new];\n'
                 '    memory.text = [NSString stringWithFormat:@"%@ %.1f GB", T(@"可用内存", @"Memory available"),\n'
                 '                         (double)phone_available_memory() / (1024.0 * 1024.0 * 1024.0)];\n'
                 '    memory.font = [UIFont systemFontOfSize:12]; memory.textColor = [UIColor colorWithWhite:0.5 alpha:1];\n'
                 '    memory.textAlignment = NSTextAlignmentCenter;\n'
                 '    note.font = [UIFont systemFontOfSize:13]; note.textColor = [UIColor colorWithWhite:0.6 alpha:1];\n',
                 '#6 the memory readout')
    replace_once(start,
                 '    [rows addObjectsFromArray:_hasPicture ? @[pictureRow, fpsRow, note, _start] : @[fpsRow, _start]];\n',
                 '    [rows addObjectsFromArray:_hasPicture ? @[pictureRow, fpsRow, note, memory, _start] : @[fpsRow, memory, _start]];\n',
                 '#6 the memory readout on the screen')

    print('the kit\'s patches are in place', flush=True)

    # The patches are edits of the upstream tree, so they must still hold what they say (kit/shim/patch_check.py).
    # The check is here and not in the workflow, so that the kit's own source carries it: the workflow file can only
    # be changed by a token with the workflow scope, and that scope is not something a player's token is given.
    import patch_check
    patch_check.check(tree)


if __name__ == '__main__':
    main(sys.argv[1])
