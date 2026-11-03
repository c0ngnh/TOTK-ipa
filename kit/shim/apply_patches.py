#!/usr/bin/env python3
"""TOTK-ipa: the kit's own additions to the upstream runtime and app.

Each patch is a small, checked edit of the upstream tree: the text to find must be there exactly once, or the build
stops with a message (the upstream code changed; the patch needs to be written again).

    apply_patches.py <tree>     the tree is games/totk of a MacNativeGames checkout
"""
import sys
from pathlib import Path


def replace_once(path, old, new, note):
    """Make one checked edit of a file.

    The edit is idempotent: if the new text is already there, the file was patched before and nothing is done. The new
    text is looked for first, because most of the kit's patches begin with the text they replace (they only add to it),
    and so the old text is still there after the edit: looking for the old text first would patch the file twice.
    """
    text = path.read_text(encoding='utf-8')
    if new in text:
        print(f'  already patched {path.name}: {note}', flush=True)
        return
    if text.count(old) != 1:
        raise SystemExit(f'{path.name}: {note}: expected exactly one "{old.strip()[:60]}" '
                         f'(MacNativeGames changed; update kit/shim/apply_patches.py)')
    path.write_text(text.replace(old, new), encoding='utf-8')
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

    # --- #9: the player picks which sensor feeds the game's six-axis device ---
    # The iPhone's own motion sensor and a Bluetooth controller's sensor both reach the game's one six-axis device,
    # so only one of them may drive it. Which one is the player's choice, made on the on-screen pad (the button next
    # to the pad's own show/hide button, kit/shim/touch_pad_botw.m). The runtime holds the choice and drops the other
    # source's samples at the door, so the two can never be mixed into one fusion.
    runtime_h = tree / 'runtime/runtime.h'
    replace_once(runtime_h,
                 'void runtime_motion_feed(const double acc_g[3], const double gyro_rad_s[3], uint64_t now_ns);   /* runtime/motion_fusion.c */\n',
                 'void runtime_motion_feed(const double acc_g[3], const double gyro_rad_s[3], uint64_t now_ns);   /* runtime/motion_fusion.c */\n'
                 '/* TOTK-ipa: which sensor feeds the game\'s single six-axis device (the user\'s request, 2026-11-03).\n'
                 '   AUTO: the controller while it reports motion, the phone otherwise. PHONE: the iPhone\'s own sensor.\n'
                 '   CONTROLLER: the controller\'s sensor. The source in force is the only one whose samples reach the\n'
                 '   fusion (runtime/motion_fusion.c), so the two never mix. */\n'
                 'enum { RUNTIME_MOTION_SOURCE_AUTO = 0, RUNTIME_MOTION_SOURCE_PHONE = 1, RUNTIME_MOTION_SOURCE_CONTROLLER = 2 };\n'
                 'void runtime_motion_source(int source);   /* the source in force (the enum above) */\n'
                 'int runtime_motion_source_get(void);\n'
                 'void runtime_motion_feed_phone(const double acc_g[3], const double gyro_rad_s[3], uint64_t now_ns);   /* the iPhone\'s own sensor */\n',
                 '#9 the motion source in the runtime')

    fusion = tree / 'runtime/motion_fusion.c'
    # The gate: a sample from the source that is not in force is dropped before it reaches the fusion.
    replace_once(fusion,
                 'static int mouse_owns, controller_live, phone_live;\n',
                 'static int mouse_owns, controller_live, phone_live;\n'
                 '/* TOTK-ipa: the source in force (the user\'s request, 2026-11-03). The phone\'s sensor and a controller\'s\n'
                 '   sensor both feed this fusion, and the game has one six-axis device, so only one of them may drive it.\n'
                 '   The player picks it on the on-screen pad; a sample from the other source is dropped here, before it\n'
                 '   reaches the fusion, so the two never mix. In automatic mode nothing is dropped: the hand-over between\n'
                 '   the two is made where it always was (ios/Sources/phone_motion.m), which is what the game had before\n'
                 '   the choice existed. */\n'
                 'static int motion_source = RUNTIME_MOTION_SOURCE_AUTO;\n'
                 '\n'
                 '/* Is a source allowed to drive the fusion now? A chosen source lets only itself through; in automatic\n'
                 '   mode both do, as before (lock held). The controller in force yields to the phone when no controller\n'
                 '   with motion is attached: the player asked for a sensor that is not there, and the game must not be\n'
                 '   left without motion. The phone\'s own layer makes the same rule (ios/Sources/phone_motion.m). */\n'
                 'static int source_allows(int who) {   /* who: 0 the controller, 1 the phone */\n'
                 '    if (motion_source == RUNTIME_MOTION_SOURCE_PHONE) return who == 1;\n'
                 '    if (motion_source == RUNTIME_MOTION_SOURCE_CONTROLLER) return who == 0 || !controller_live;\n'
                 '    return 1;\n'
                 '}\n',
                 '#9 the motion source gate')
    # The phone's samples come in through their own door, so the controller\'s and the phone\'s cannot be mixed up.
    replace_once(fusion,
                 'void runtime_motion_feed(const double raw_acc[3], const double raw_gyro[3], uint64_t now) {\n'
                 '    double acc[3], gyro[3];\n'
                 '    pthread_mutex_lock(&lock);\n',
                 '/* TOTK-ipa: the phone\'s samples come in through their own door (the user\'s request, 2026-11-03): the\n'
                 '   controller\'s feed and the phone\'s feed are the same fusion, but only the source in force is let\n'
                 '   through, and each one keeps its own bias and dead zone. */\n'
                 'static void feed_source(int who, const double raw_acc[3], const double raw_gyro[3], uint64_t now) {\n'
                 '    double acc[3], gyro[3];\n'
                 '    pthread_mutex_lock(&lock);\n'
                 '    if (!source_allows(who)) { pthread_mutex_unlock(&lock); return; }\n',
                 '#9 the phone\'s own feed')
    replace_once(fusion,
                 '    if (mouse_owns) { pthread_mutex_unlock(&lock); return; }\n'
                 '    feed_locked(acc, gyro, now);\n'
                 '    pthread_mutex_unlock(&lock);\n'
                 '}\n',
                 '    if (mouse_owns) { pthread_mutex_unlock(&lock); return; }\n'
                 '    feed_locked(acc, gyro, now);\n'
                 '    pthread_mutex_unlock(&lock);\n'
                 '}\n'
                 'void runtime_motion_feed(const double raw_acc[3], const double raw_gyro[3], uint64_t now) {\n'
                 '    feed_source(0, raw_acc, raw_gyro, now);   /* the controller\'s sensor */\n'
                 '}\n'
                 'void runtime_motion_feed_phone(const double raw_acc[3], const double raw_gyro[3], uint64_t now) {\n'
                 '    feed_source(1, raw_acc, raw_gyro, now);   /* the iPhone\'s own sensor */\n'
                 '}\n'
                 '/* TOTK-ipa: the source in force (the user\'s request, 2026-11-03). Changing it starts the fusion over:\n'
                 '   the angle and the direction are the new source\'s own, and a bias learned from one sensor is not the\n'
                 '   other\'s. */\n'
                 'void runtime_motion_source(int source) {\n'
                 '    pthread_mutex_lock(&lock);\n'
                 '    if (motion_source != source) {\n'
                 '        motion_source = source;\n'
                 '        restart = 1; last_ns = 0;\n'
                 '        if (bias_mode == 1) { memset(bias, 0, sizeof bias); memset(bias_logged, 0, sizeof bias_logged); bias_known = 0; win_n = 0; }\n'
                 '        fprintf(stderr, "[gyro] the motion source is now %s\\n",\n'
                 '                source == RUNTIME_MOTION_SOURCE_PHONE ? "the phone\'s own sensor" :\n'
                 '                source == RUNTIME_MOTION_SOURCE_CONTROLLER ? "the controller\'s sensor" : "automatic");\n'
                 '    }\n'
                 '    pthread_mutex_unlock(&lock);\n'
                 '}\n'
                 'int runtime_motion_source_get(void) { pthread_mutex_lock(&lock); int s = motion_source; pthread_mutex_unlock(&lock); return s; }\n',
                 '#9 the source in force')

    # The controller's own sensors follow the player's choice too (the user's request, 2026-11-03): with the phone's
    # sensor in force the controller's sensors are turned off, so the two cannot both report.
    feedback = tree / 'runtime/gamepad_feedback.m'
    replace_once(feedback,
                 '        if (m.sensorsRequireManualActivation) m.sensorsActive = YES;\n',
                 '        /* TOTK-ipa: the player\'s choice of motion source (the user\'s request, 2026-11-03): with the\n'
                 '           phone\'s sensor in force the controller\'s sensors stay off, so the two never report at once. */\n'
                 '        if (m.sensorsRequireManualActivation) m.sensorsActive = runtime_motion_source_get() == RUNTIME_MOTION_SOURCE_PHONE ? NO : YES;\n',
                 '#9 the controller\'s sensors follow the chosen source')
    replace_once(feedback,
                 '        motionPad.motion.sensorsActive = YES;\n',
                 '        motionPad.motion.sensorsActive = runtime_motion_source_get() == RUNTIME_MOTION_SOURCE_PHONE ? NO : YES;\n'
                 '        /* TOTK-ipa: the same choice after the app returns (the user\'s request, 2026-11-03). */\n',
                 '#9 the controller\'s sensors follow the chosen source after the app returns')

    print('the kit\'s patches are in place', flush=True)

    # The app's own motion source API (ios/Sources/device_motion.h): the on-screen pad's button picks the source, and
    # phone_motion.m starts and stops the sensors to match.
    device_h = tree / 'ios/Sources/device_motion.h'
    replace_once(device_h,
                 '#import <Foundation/Foundation.h>\n',
                 '#import <Foundation/Foundation.h>\n'
                 '#include "runtime.h"   /* TOTK-ipa: the motion source\'s values (the runtime\'s own enum) */\n',
                 '#9 the app\'s motion source API: the runtime\'s enum')
    replace_once(device_h,
                 'void totk_device_motion_note_touch(void);      /* the touch layer saw a finger: the phone\'s gyro takes the aiming over */\n',
                 'void totk_device_motion_note_touch(void);      /* the touch layer saw a finger: the phone\'s gyro takes the aiming over */\n'
                 '/* TOTK-ipa: which sensor feeds the game\'s single six-axis device (the user\'s request, 2026-11-03).\n'
                 '   AUTO: the controller while it reports motion, the phone otherwise. PHONE: the iPhone\'s own sensor.\n'
                 '   CONTROLLER: the controller\'s sensor. The values are the runtime\'s own (runtime/runtime.h). */\n'
                 'enum { TOTK_MOTION_SOURCE_AUTO = RUNTIME_MOTION_SOURCE_AUTO,\n'
                 '       TOTK_MOTION_SOURCE_PHONE = RUNTIME_MOTION_SOURCE_PHONE,\n'
                 '       TOTK_MOTION_SOURCE_CONTROLLER = RUNTIME_MOTION_SOURCE_CONTROLLER };\n'
                 'void totk_device_motion_set_source(int source);   /* the player\'s choice (the pad\'s button); main thread */\n'
                 'int totk_device_motion_source(void);             /* the source in force */\n',
                 '#9 the app\'s motion source API')

    # The iPhone's own sensor follows the player's choice (the user's request, 2026-11-03): with the source set to
    # the phone, the controller's sensors are turned off and the phone's sensor runs; with the source set to the
    # controller, the phone's sensor stops and the controller's runs; in automatic mode the old hand-over stands.
    phone = tree / 'ios/Sources/phone_motion.m'
    replace_once(phone,
                 'static _Atomic int phone_owns_gyro;                               /* touch took the aiming away from it */\n',
                 'static _Atomic int phone_owns_gyro;                               /* touch took the aiming away from it */\n'
                 '/* TOTK-ipa: the source the player picked (the on-screen pad\'s button, the user\'s request, 2026-11-03).\n'
                 '   AUTO keeps the hand-over below: the controller while it reports motion, the phone otherwise.\n'
                 '   PHONE forces the iPhone\'s own sensor, CONTROLLER forces the controller\'s. */\n'
                 'static _Atomic int chosen_source = RUNTIME_MOTION_SOURCE_AUTO;\n',
                 '#9 the chosen motion source')
    # The hand-over only stands in automatic mode: a chosen source is the player's decision and nothing takes it away.
    replace_once(phone,
                 'void totk_device_motion_note_touch(void) {   /* the touch layer saw a finger (touch_pad.m); main thread */\n'
                 '    if (enabled && atomic_load(&active) && atomic_load(&controller_has_motion) && !atomic_load(&phone_owns_gyro))\n'
                 '        claim_phone_gyro();\n'
                 '}\n',
                 'void totk_device_motion_note_touch(void) {   /* the touch layer saw a finger (touch_pad.m); main thread */\n'
                 '    /* TOTK-ipa: a chosen source stands: a finger on the screen does not take the aiming away from the\n'
                 '       source the player picked (the user\'s request, 2026-11-03). Only in automatic mode does the touch\n'
                 '       hand the aiming over, as before. */\n'
                 '    if (atomic_load(&chosen_source) != RUNTIME_MOTION_SOURCE_AUTO) return;\n'
                 '    if (enabled && atomic_load(&active) && atomic_load(&controller_has_motion) && !atomic_load(&phone_owns_gyro))\n'
                 '        claim_phone_gyro();\n'
                 '}\n',
                 '#9 a chosen source is not taken away by a touch')
    # The controller's sensor must not be handed back when the player chose the phone, and the phone's sensor must
    # stop when the player chose the controller.
    replace_once(phone,
                 'static void follow_owner(void) {\n'
                 '    if (!atomic_load(&active)) { watch_gamepad(NO); return; }\n'
                 '    BOOL pad = atomic_load(&controller_has_motion) && !atomic_load(&phone_owns_gyro);\n'
                 '    watch_gamepad(atomic_load(&controller_has_motion) && atomic_load(&phone_owns_gyro));\n'
                 '    if (pad) { stop_updates(); runtime_motion_phone(0); return; }\n'
                 '    if (!sensing && start_updates()) runtime_motion_phone(1);   /* re-aligned to gravity */\n'
                 '}\n',
                 'static void follow_owner(void) {\n'
                 '    if (!atomic_load(&active)) { watch_gamepad(NO); return; }\n'
                 '    BOOL pad = atomic_load(&controller_has_motion) && !atomic_load(&phone_owns_gyro);\n'
                 '    watch_gamepad(atomic_load(&controller_has_motion) && atomic_load(&phone_owns_gyro));\n'
                 '    /* TOTK-ipa: the chosen source decides (the user\'s request, 2026-11-03). With the controller chosen the\n'
                 '       phone\'s sensor stops, so the two never report at once; with the phone chosen the phone\'s sensor\n'
                 '       runs and the controller\'s sensors are turned off (gamepad_feedback.m). In automatic mode the hand-\n'
                 '       over above stands, as before.\n'
                 '       The controller chosen with no controller that has motion attached leaves the game without motion,\n'
                 '       so the phone\'s sensor takes over then: the player asked for a sensor that is not there, and the\n'
                 '       game must not be left without motion. */\n'
                 '    int source = atomic_load(&chosen_source);\n'
                 '    if (source == RUNTIME_MOTION_SOURCE_CONTROLLER && atomic_load(&controller_has_motion)) {\n'
                 '        stop_updates(); runtime_motion_phone(0); return;\n'
                 '    }\n'
                 '    if (source == RUNTIME_MOTION_SOURCE_PHONE || (source == RUNTIME_MOTION_SOURCE_CONTROLLER)) {\n'
                 '        if (!sensing && start_updates()) runtime_motion_phone(1);   /* re-aligned to gravity */\n'
                 '        return;\n'
                 '    }\n'
                 '    if (pad) { stop_updates(); runtime_motion_phone(0); return; }\n'
                 '    if (!sensing && start_updates()) runtime_motion_phone(1);   /* re-aligned to gravity */\n'
                 '}\n',
                 '#9 the chosen source decides who aims')
    # The phone's samples go through the phone's own door (runtime/motion_fusion.c).
    replace_once(phone,
                 '        runtime_motion_feed(acc, gyro, runtime_now_ns());\n',
                 '        runtime_motion_feed_phone(acc, gyro, runtime_now_ns());   /* TOTK-ipa: the phone\'s own door */\n',
                 '#9 the phone\'s samples come in through their own door')
    # The API the pad's button calls.
    replace_once(phone,
                 'void totk_phone_motion_start(void) {\n',
                 '/* TOTK-ipa: the player picks the motion source (the user\'s request, 2026-11-03). The choice reaches\n'
                 '   the runtime, which drops the other source\'s samples, and the sensors are started and stopped to\n'
                 '   match: with the phone chosen the controller\'s sensors go off, with the controller chosen the\n'
                 '   phone\'s sensor stops. The choice is kept between launches (NSUserDefaults, TOTK_MOTION_SOURCE). */\n'
                 'void totk_device_motion_set_source(int source) {   /* main thread */\n'
                 '    if (source != RUNTIME_MOTION_SOURCE_AUTO && source != RUNTIME_MOTION_SOURCE_PHONE &&\n'
                 '        source != RUNTIME_MOTION_SOURCE_CONTROLLER) return;\n'
                 '    load_source();\n'
                 '    if (atomic_exchange(&chosen_source, source) == source) return;\n'
                 '    runtime_motion_source(source);\n'
                 '    /* The hand-over flag follows the choice, so the automatic hand-over does not fight it: with the phone\n'
                 '       chosen the phone holds the aiming, with the controller chosen the controller takes it back. */\n'
                 '    atomic_store(&phone_owns_gyro, source == RUNTIME_MOTION_SOURCE_PHONE ? 1 : 0);\n'
                 '    /* The controller\'s sensors follow the choice too: off with the phone in force, on otherwise (so a\n'
                 '       controller that was silenced by the phone gets its sensors back). */\n'
                 '    set_controller_sensors(source == RUNTIME_MOTION_SOURCE_PHONE ? NO : YES);\n'
                 '    follow_owner();\n'
                 '}\n'
                 'int totk_device_motion_source(void) { load_source(); return atomic_load(&chosen_source); }\n'
                 '\n'
                 'void totk_phone_motion_start(void) {\n',
                 '#9 the app\'s motion source API')
    # The choice the player made last time is read once, the first time it is asked for: the on-screen pad's button
    # asks for it while the view is built, which is before the game starts.
    replace_once(phone,
                 'static _Atomic int chosen_source = RUNTIME_MOTION_SOURCE_AUTO;\n',
                 'static _Atomic int chosen_source = RUNTIME_MOTION_SOURCE_AUTO;\n'
                 'static int source_loaded;\n'
                 '\n'
                 '/* TOTK-ipa: the choice the player made last time (the user\'s request, 2026-11-03), read once and kept\n'
                 '   in NSUserDefaults (TOTK_MOTION_SOURCE). The on-screen pad\'s button asks for the source while the view\n'
                 '   is built, which is before the game starts, so it is read here and not in totk_phone_motion_start. */\n'
                 'static void load_source(void) {\n'
                 '    if (source_loaded) return;\n'
                 '    source_loaded = 1;\n'
                 '    NSInteger saved = [NSUserDefaults.standardUserDefaults integerForKey:@"TOTK_MOTION_SOURCE"];\n'
                 '    int source = (saved == RUNTIME_MOTION_SOURCE_PHONE || saved == RUNTIME_MOTION_SOURCE_CONTROLLER)\n'
                 '              ? (int)saved : RUNTIME_MOTION_SOURCE_AUTO;\n'
                 '    atomic_store(&chosen_source, source);\n'
                 '    runtime_motion_source(source);\n'
                 '}\n',
                 '#9 the saved motion source')
    # The app's own API when the phone sensor is not built in (the Mac host).
    replace_once(phone,
                 'void totk_phone_motion_start(void) {}\n'
                 'void totk_device_motion_note_touch(void) {}\n',
                 'void totk_phone_motion_start(void) {}\n'
                 'void totk_device_motion_note_touch(void) {}\n'
                 '/* TOTK-ipa: the motion source API (the user\'s request, 2026-11-03); on the Mac the phone has no sensor. */\n'
                 'void totk_device_motion_set_source(int source) { runtime_motion_source(source); }\n'
                 'int totk_device_motion_source(void) { return runtime_motion_source_get(); }\n',
                 '#9 the app\'s motion source API off iOS')

    # --- #10: the Bluetooth controller's face buttons swapped, so the game sees the Nintendo arrangement ---
    # A controller that is not a Nintendo one is read by position: GameController names its face buttons by the Xbox
    # layout (A bottom, B right, X left, Y top), and the game's prompts then show the Switch's letters at the places the
    # player does not expect them. The player asked for the swap (2026-11-03): A and B take each other's place, and X and
    # Y take each other's, so the game sees the Switch's own arrangement (A right, B bottom, X top, Y left).
    # The swap is done on the positions, so the game gets the same bit for the same place whatever the controller calls
    # the button that was pressed. The player's choice comes from the Settings pane's row (TOTK_FACE_SWAP), which the app
    # hands over as that environment variable; without the variable nothing is swapped, as before.
    layout_h = tree / 'runtime/gamepad_layout.h'
    replace_once(layout_h,
                 '#include <ctype.h>\n'
                 '#include <stdint.h>\n'
                 '#include <stdlib.h>\n'
                 '#include <string.h>\n',
                 '#include <ctype.h>\n'
                 '#include <stdatomic.h>\n'
                 '#include <stdint.h>\n'
                 '#include <stdlib.h>\n'
                 '#include <string.h>\n',
                 '#10 the face buttons swapped need the atomics')
    replace_once(layout_h,
                 'static inline uint64_t gamepad_face_positions(int a, int b, int x, int y, int by_position) {\n'
                 '    enum { SOUTH = 1, EAST = 2, WEST = 4, NORTH = 8 };\n'
                 '    if (by_position) return (a ? SOUTH : 0) | (b ? EAST : 0) | (x ? WEST : 0) | (y ? NORTH : 0);\n'
                 '    return (a ? EAST : 0) | (b ? SOUTH : 0) | (x ? NORTH : 0) | (y ? WEST : 0);\n'
                 '}\n',
                 'static inline uint64_t gamepad_face_positions(int a, int b, int x, int y, int by_position) {\n'
                 '    enum { SOUTH = 1, EAST = 2, WEST = 4, NORTH = 8 };\n'
                 '    if (by_position) return (a ? SOUTH : 0) | (b ? EAST : 0) | (x ? WEST : 0) | (y ? NORTH : 0);\n'
                 '    return (a ? EAST : 0) | (b ? SOUTH : 0) | (x ? NORTH : 0) | (y ? WEST : 0);\n'
                 '}\n'
                 '\n'
                 '/* TOTK-ipa: the face buttons swapped, so the game sees the Nintendo arrangement (A right, B bottom, X top,\n'
                 '   Y left) whatever the controller\'s own labels are (the user\'s request, 2026-11-03). A Bluetooth\n'
                 '   controller that is not a Nintendo one is read by position (GameController names its buttons by the Xbox\n'
                 '   layout), and the game\'s prompts then show the Switch\'s letters at the places the player does not\n'
                 '   expect them.\n'
                 '   The swap exchanges the two pairs: A and B take each other\'s place, and X and Y take each other\'s. It is\n'
                 '   done on the positions, not on the letters, so the game gets the same bit for the same place whatever\n'
                 '   the controller calls the button that was pressed: the controller\'s own A drives the game\'s A.\n'
                 '   Only a controller read by position is swapped. A Nintendo controller is read by label and is already\n'
                 '   right (its A is on the right, where the game shows A), so swapping it would break it; the same goes\n'
                 '   for TOTK_FACE_BUTTONS=label, which asks for the labels as they are.\n'
                 '   TOTK_FACE_SWAP=1 turns it on; the Settings pane\'s own row hands the choice over as that variable.\n'
                 '   Without the variable nothing is swapped, which is what the game had before.\n'
                 '   The on-screen pad\'s own button (kit/shim/touch_pad_botw.m) can also change it while the game runs, so\n'
                 '   the choice is held in a variable of our own and not only in the environment: the variable the pane\n'
                 '   sets is read as it was, and the button then overrules it (runtime_gamepad_face_swap_set). The\n'
                 '   environment is not changed: a second game thread would only see the launch value again that way. */\n'
                 'static _Atomic int g_face_swap = -1;   /* -1: the button has not chosen yet; 0 off, 1 on */\n'
                 'static inline int gamepad_face_swap(void) {\n'
                 '    int v = atomic_load(&g_face_swap);\n'
                 '    if (v >= 0) return v;   /* the player\'s choice at the button stands */\n'
                 '    const char *e = getenv("TOTK_FACE_SWAP");\n'
                 '    return e && *e && strcmp(e, "0") != 0;\n'
                 '}\n'
                 '\n'
                 '/* TOTK-ipa: the swap in force, set by the on-screen pad\'s button while the game runs. The button\'s choice\n'
                 '   stands against the environment (the pane\'s row is the choice at the launch); -1 gives the environment\n'
                 '   back, so the button and the pane never fight over two answers at once. */\n'
                 'static inline void gamepad_face_swap_set(int on) { atomic_store(&g_face_swap, on < 0 ? -1 : on ? 1 : 0); }\n'
                 '\n'
                 '/* The physical positions, with the pairs exchanged when the player asked for it. */\n'
                 'static inline uint64_t gamepad_face_positions_swapped(int a, int b, int x, int y, int by_position) {\n'
                 '    if (!by_position || !gamepad_face_swap()) return gamepad_face_positions(a, b, x, y, by_position);\n'
                 '    return gamepad_face_positions(b, a, y, x, by_position);\n'
                 '}\n',
                 '#10 the face buttons swapped')
    # The controller's own face buttons go through the swap.
    replace_once(tree / 'runtime/gamepad.m',
                 '    uint64_t buttons = gamepad_face_positions(pad.buttonA.isPressed, pad.buttonB.isPressed, pad.buttonX.isPressed, pad.buttonY.isPressed, by_position);\n',
                 '    /* TOTK-ipa: the face buttons go through the swap (the user\'s request, 2026-11-03), so the game sees the\n'
                 '       Nintendo arrangement whatever the controller\'s labels are. */\n'
                 '    uint64_t buttons = gamepad_face_positions_swapped(pad.buttonA.isPressed, pad.buttonB.isPressed, pad.buttonX.isPressed, pad.buttonY.isPressed, by_position);\n',
                 '#10 the controller\'s face buttons go through the swap')

    # --- #11: the on-screen pad's own button changes the face buttons' swap while the game runs ---
    # The Settings pane's row (TOTK_FACE_SWAP) can only be changed between launches, and a player with a Bluetooth
    # controller would rather have a button on the pad itself: the same button that picks the motion source, next to
    # it. The runtime holds the choice (gamepad_layout.h's flag), so the change takes effect at once, without a
    # restart, and it reaches the game on the next frame.
    # The runtime API is declared in runtime.h and defined in runtime/gamepad.m, next to the controller's own settings.
    replace_once(runtime_h,
                 'int runtime_gamepad_type_set(int type);     /* runtime/gamepad.m: the settings panel\'s controller type (gamepad_layout.h GAMEPAD_TYPE_*), saved; returns the type in force */\n',
                 'int runtime_gamepad_type_set(int type);     /* runtime/gamepad.m: the settings panel\'s controller type (gamepad_layout.h GAMEPAD_TYPE_*), saved; returns the type in force */\n'
                 '/* TOTK-ipa: the Bluetooth controller\'s face buttons swapped (the user\'s request, 2026-11-03): A and B take\n'
                 '   each other\'s place, and X and Y take each other\'s, so the game sees the Nintendo arrangement (A right,\n'
                 '   B bottom, X top, Y left) whatever the controller calls the buttons it pressed. Only a controller read\n'
                 '   by position is swapped; a Nintendo one is read by label and is already right.\n'
                 '   The on-screen pad\'s button sets it while the game runs (runtime_gamepad_face_swap_set); the Settings\n'
                 '   pane\'s row (TOTK_FACE_SWAP) is the choice at the launch. The getter tells the app which one is in\n'
                 '   force, so the button can show it. */\n'
                 'void runtime_gamepad_face_swap_set(int on);   /* runtime/gamepad.m: the swap in force, at once */\n'
                 'int runtime_gamepad_face_swap(void);          /* runtime/gamepad.m: the swap in force (1 or 0) */\n',
                 '#11 the face swap in the runtime')
    replace_once(tree / 'runtime/gamepad.m',
                 'static void save_controller_type(int type) { setting_write("controller-type.txt", gamepad_type_name(type), "controller type"); }\n',
                 'static void save_controller_type(int type) { setting_write("controller-type.txt", gamepad_type_name(type), "controller type"); }\n'
                 '\n'
                 '/* TOTK-ipa: the face buttons\' swap (the user\'s request, 2026-11-03). The on-screen pad\'s button changes it\n'
                 '   while the game runs, so the choice is a variable of our own and not only the environment the Settings\n'
                 '   pane hands over at the launch (gamepad_layout.h reads that variable once, on the first call). */\n'
                 'void runtime_gamepad_face_swap_set(int on) { gamepad_face_swap_set(on != 0); }\n'
                 'int runtime_gamepad_face_swap(void) { return gamepad_face_swap(); }\n',
                 '#11 the face swap in the runtime')

    # --- #12: the phone's frame rate has three settings: 30, 60 and uncapped (the user's request, 2026-11-03) ---
    # The runtime knew two: held at 30 (TOTK_PHONE_FPS) and the display's rate. The uncapped setting is the runtime's own
    # uncapped path (uncapped_now), but on the phone its ceiling was the display's rate (uncapped_cap: TOTK_UNCAPPED_HZ
    # is "display" there), so it ran at 60 and was not the uncapped the button promises.
    # The change is in three places:
    #   - the rate in force is one number: 30, 60 or 0 (uncapped), so the button's three-way cycle and the runtime agree;
    #   - the uncapped ceiling on the phone is the runtime's own PHONE_UNCAPPED_HZ, above the display's rate: the game is
    #     paced by its own clock and the display link shows the newest finished frame at every refresh (the uncapped path);
    #   - the held rate still wins over the uncapped one, and the real-time frame step (game_patches*.c) keeps the game's
    #     speed at any rate, so nothing runs fast.
    # The runtime's phone_hold30 flag stays, so the code that reads it (game_hold_fps, sr_frame) keeps working.
    replace_once(tree / 'third_party/d2r_gfx/gfx/nvn/hle_nvn.c',
                 'static _Atomic int g_phone_hold30 = -1;   /* -1: TOTK_PHONE_FPS not read yet */\n'
                 'static int phone_holds_30(void) {\n'
                 '#if TARGET_OS_IPHONE\n'
                 '    int v = atomic_load(&g_phone_hold30);\n'
                 '    if (v < 0) { const char *e = getenv("TOTK_PHONE_FPS"); v = e && atoi(e) == 30; atomic_store(&g_phone_hold30, v); }\n'
                 '    return v;\n'
                 '#else\n'
                 '    return 0;\n'
                 '#endif\n'
                 '}\n'
                 'int runtime_phone_fps(void) { return phone_holds_30() ? 30 : 60; }\n'
                 'void runtime_phone_fps_set(int fps) { atomic_store(&g_phone_hold30, fps == 30); fprintf(stderr, "[totk] phone frame rate: %s\\n", fps == 30 ? "held at 30" : "up to 60"); }\n',
                 'static _Atomic int g_phone_hold30 = -1;   /* -1: TOTK_PHONE_FPS not read yet */\n'
                 'static int phone_holds_30(void) {\n'
                 '#if TARGET_OS_IPHONE\n'
                 '    int v = atomic_load(&g_phone_hold30);\n'
                 '    if (v < 0) { const char *e = getenv("TOTK_PHONE_FPS"); v = e && atoi(e) == 30; atomic_store(&g_phone_hold30, v); }\n'
                 '    return v;\n'
                 '#else\n'
                 '    return 0;\n'
                 '#endif\n'
                 '}\n'
                 '/* TOTK-ipa (2026-11-03): the phone\'s frame rate in force is one number: 30 (held at 30), 60 (the display\'s\n'
                 '   rate) or 0 (uncapped). The button\'s three-way cycle (settings_map.c totk_frame_button_target) and the\n'
                 '   runtime agree on that one number, so a button press and the Settings pane\'s row mean the same thing.\n'
                 '   The uncapped setting is the runtime\'s own uncapped path with the ceiling above the display\'s rate\n'
                 '   (PHONE_UNCAPPED_HZ): the game is paced by its own clock and the display link shows the newest finished\n'
                 '   frame at every refresh. The game keeps its speed at any rate (the real-time frame step,\n'
                 '   game_patches*.c, follows the measured frame time), so the higher rate does not make the game run fast. */\n'
                 'static _Atomic int g_phone_fps = -1;   /* -1: the rate not read yet */\n'
                 'int runtime_phone_fps(void) {\n'
                 '    int v = atomic_load(&g_phone_fps);\n'
                 '    if (v < 0) { const char *e = getenv("TOTK_PHONE_FPS"); v = e ? atoi(e) : 60; atomic_store(&g_phone_fps, v); }\n'
                 '    return v == 30 ? 30 : v == 0 ? 0 : 60;\n'
                 '}\n'
                 'void runtime_phone_fps_set(int fps) {\n'
                 '    if (fps != 30 && fps != 60 && fps != 0) return;\n'
                 '    atomic_store(&g_phone_fps, fps);\n'
                 '    atomic_store(&g_phone_hold30, fps == 30);\n'
                 '    fprintf(stderr, "[totk] phone frame rate: %s\\n", fps == 30 ? "held at 30" : fps == 0 ? "uncapped" : "up to 60");\n'
                 '}\n',
                 '#12 the phone\'s frame rate in three settings')
    # The uncapped ceiling on the phone: the runtime's own clock above the display's rate. The display link still shows
    # the newest finished frame at every refresh, so the extra frames are the game's own (a smoother input response and a
    # steadier simulation), not more pictures on the screen.
    replace_once(tree / 'third_party/d2r_gfx/gfx/nvn/hle_nvn.c',
                 '#define UNCAPPED_HZ 240           /* the highest TOTK_UNCAPPED_HZ takes */\n'
                 '#define UNCAPPED_DEFAULT_HZ 144   /* the Mac\'s ceiling without TOTK_UNCAPPED_HZ */\n',
                 '#define UNCAPPED_HZ 240           /* the highest TOTK_UNCAPPED_HZ */\n'
                 '#define UNCAPPED_DEFAULT_HZ 144   /* the Mac\'s ceiling without TOTK_UNCAPPED_HZ */\n'
                 '/* TOTK-ipa (2026-11-03): the phone\'s uncapped ceiling, used when the frame-rate button is on "uncapped".\n'
                 '   The display link is fixed at 60 Hz (frontend_ios.m TOTK_IOS_LINK_HZ), so the game cannot show more\n'
                 '   pictures than that; the extra frames are the game\'s own, so the input is read and answered sooner and\n'
                 '   the simulation runs at a steadier step. 120 is the rate: it is twice the link\'s, so the game is never\n'
                 '   more than one frame ahead of the picture on the screen, and the phone is not asked for more than a\n'
                 '   120 Hz game can hold. The real-time frame step keeps the game\'s speed at that rate. */\n'
                 '#define PHONE_UNCAPPED_HZ 120\n',
                 '#12 the phone\'s uncapped ceiling')
    # The uncapped setting itself: the phone's rate is 0 (uncapped). The rate in force is asked for every frame, so the
    # button's press takes effect at once: the ceiling is not read once, when the display is configured.
    replace_once(tree / 'third_party/d2r_gfx/gfx/nvn/hle_nvn.c',
                 'static int uncapped_now(void) { int m = mfx_enabled(); return g_uncapped && !game_hold_fps() && (m == MFX_OFF || m == MFX_MAX); }\n',
                 'static int uncapped_now(void) { int m = mfx_enabled(); return g_uncapped && !game_hold_fps() && (m == MFX_OFF || m == MFX_MAX); }\n'
                 '/* TOTK-ipa (2026-11-03): the phone\'s uncapped setting: the frame-rate button on "uncapped" (the rate is 0).\n'
                 '   The rate in force is asked for every frame, so a button press takes effect at once. */\n'
                 'static int phone_uncapped_on(void) { return runtime_phone_fps() == 0; }\n',
                 '#12 the phone\'s uncapped setting')
    # The rate the game is paced at now. The ceiling is read every frame and not once (present_cfg), so the button's press
    # takes effect at once: the phone's uncapped setting raises it above the display's rate.
    replace_once(tree / 'third_party/d2r_gfx/gfx/nvn/hle_nvn.c',
                 'static uint64_t present_period(const win_t *o) {\n'
                 '    unsigned itv = present_ticks(o); int m = mfx_enabled(), hz = g_uncapped && !uncapped_now() ? g_paced_hz : g_hz;\n',
                 '/* TOTK-ipa (2026-11-03): the rate the game is paced at now. The phone\'s uncapped setting raises the ceiling\n'
                 '   above the display\'s rate (PHONE_UNCAPPED_HZ): the game is paced by its own clock and the display link\n'
                 '   shows the newest finished frame at every refresh, as the uncapped path does on the Mac. The held rate\n'
                 '   (30) still wins: the pacing returns it before the rate is looked at (present_period). */\n'
                 'static int effective_hz(void) {\n'
                 '    int hz = g_uncapped && !uncapped_now() ? g_paced_hz : g_hz;\n'
                 '    if (g_uncapped && !game_hold_fps() && phone_uncapped_on()) hz = PHONE_UNCAPPED_HZ;\n'
                 '    return hz;\n'
                 '}\n'
                 'static uint64_t present_period(const win_t *o) {\n'
                 '    unsigned itv = present_ticks(o); int m = mfx_enabled(), hz = effective_hz();\n',
                 '#12 the rate the game is paced at now')
    # The state report tells the player the cap it applies: the same rate the pacing uses.
    replace_once(tree / 'third_party/d2r_gfx/gfx/nvn/hle_nvn.c',
                 '    else if (uncapped_now()) { cap = g_hz; src = !dm_detclock_enabled() && uncapped_interval_on() ? SR_CAP_UNCAPPED : SR_CAP_UNCAPPED_INTERVAL; }\n',
                 '    else if (uncapped_now()) { cap = effective_hz(); src = !dm_detclock_enabled() && uncapped_interval_on() ? SR_CAP_UNCAPPED : SR_CAP_UNCAPPED_INTERVAL; }\n',
                 '#12 the state report tells the same cap')
    # The runtime's own declaration says what the rate can be: three settings, not two.
    replace_once(runtime_h,
                 'int runtime_phone_fps(void);                /* d2r_gfx hle_nvn.c, iPhone / iPad: 30 while held at 30 (TOTK_PHONE_FPS), else 60 */\n'
                 'void runtime_phone_fps_set(int fps);        /* 30 holds 30, anything else up to 60: the touch controls\' button, at once */\n',
                 'int runtime_phone_fps(void);                /* d2r_gfx hle_nvn.c, iPhone / iPad: the rate in force: 30 (held), 60 (the display\'s rate) or 0 (uncapped) */\n'
                 'void runtime_phone_fps_set(int fps);        /* 30 holds 30, 0 uncapped, 60 up to the display\'s rate: the touch controls\' button, at once */\n',
                 '#12 the phone\'s frame rate in three settings')

    # --- #13: the Settings pane's frame-rate rows know the uncapped setting (the user's request, 2026-11-03) ---
    # The pane's rows offer the rates the game can run at: the preset row (TOTK_PHONE_FPS: 30 or 60) and the custom
    # row (TOTK_FPS_CAP: 30 or 60). The button's third setting, uncapped, is not in them, so a player who wants it has
    # to press the button on the pad every time (the button's choice is kept, but the pane would overwrite it at the
    # next launch). The rows get the third choice, so the pane and the button mean the same thing.
    # The uncapped rate is 0 in the runtime (TOTK_PHONE_FPS=0, runtime_phone_fps): the game's own clock above the
    # display's rate. The pane writes "uncapped", which the maps turn into that 0.
    settings_map_h = tree / 'ios/Sources/settings_map.h'
    replace_once(settings_map_h,
                 '/* cap is "30" or "60". 0 when cap is not a pane value (out is untouched). The iOS display link is fixed at 60 Hz, so\n'
                 '   there is no higher entry: the uncapped path could never show more than 60 either. */\n'
                 'int totk_frame_env_build(const char *cap, totk_frame_env *out);\n',
                 '/* cap is "30", "60" or "uncapped". 0 when cap is not a pane value (out is untouched). "uncapped" is the\n'
                 '   game\'s own clock above the display\'s rate (TOTK_PHONE_FPS=0): the display link shows the newest finished\n'
                 '   frame at every refresh, and the game keeps its speed (the real-time frame step). */\n'
                 'int totk_frame_env_build(const char *cap, totk_frame_env *out);\n',
                 '#13 the uncapped rate in the pane')
    replace_once(settings_map_h,
                 '/* fps is the pane\'s preset row, "60" (up to the display\'s rate) or "30" (held). 0 for anything else. */\n'
                 'int totk_preset_frame_env_build(const char *fps, totk_frame_env *out);\n',
                 '/* fps is the pane\'s preset row, "60" (up to the display\'s rate), "30" (held) or "uncapped". 0 for anything\n'
                 '   else. */\n'
                 'int totk_preset_frame_env_build(const char *fps, totk_frame_env *out);\n',
                 '#13 the uncapped rate in the preset row')
    replace_once(settings_map_h,
                 'const char *totk_frame_button_key(int custom);\n'
                 'int totk_frame_button_target(int held30);   /* 30 or the normal rate (60); the runtime only knows 30 or not-30 */\n',
                 'const char *totk_frame_button_key(int custom);\n'
                 '/* The button\'s three-way cycle: the rate in force comes in, the next one goes out. The runtime\'s rates are\n'
                 '   30 (held), 60 (the display\'s rate) and 0 (uncapped). */\n'
                 'int totk_frame_button_target(int current);\n',
                 '#13 the button\'s three-way cycle')
    settings_map_c = tree / 'ios/Sources/settings_map.c'
    replace_once(settings_map_c,
                 'int totk_frame_env_build(const char *cap, totk_frame_env *out) {\n'
                 '    if (!cap) return 0;\n'
                 '    totk_frame_env e;\n'
                 '    if (!strcmp(cap, "30")) e = (totk_frame_env){NULL, "30"};\n'
                 '    else if (!strcmp(cap, "60")) e = (totk_frame_env){"60", NULL};\n'
                 '    else return 0;\n'
                 '    *out = e;\n'
                 '    return 1;\n'
                 '}\n',
                 'int totk_frame_env_build(const char *cap, totk_frame_env *out) {\n'
                 '    if (!cap) return 0;\n'
                 '    totk_frame_env e;\n'
                 '    if (!strcmp(cap, "30")) e = (totk_frame_env){NULL, "30"};\n'
                 '    else if (!strcmp(cap, "60")) e = (totk_frame_env){"60", NULL};\n'
                 '    /* TOTK-ipa: the uncapped setting: the game\'s own clock above the display\'s rate. The display link is\n'
                 '       fixed at 60 Hz, so the picture stays at 60; the game itself runs faster, which makes the input and\n'
                 '       the simulation steadier. TOTK_PHONE_FPS=0 is the runtime\'s uncapped rate. */\n'
                 '    else if (!strcmp(cap, "uncapped") || !strcmp(cap, "max")) e = (totk_frame_env){NULL, "0"};\n'
                 '    else return 0;\n'
                 '    *out = e;\n'
                 '    return 1;\n'
                 '}\n',
                 '#13 the uncapped rate in the custom row')
    replace_once(settings_map_c,
                 'int totk_preset_frame_env_build(const char *fps, totk_frame_env *out) {\n'
                 '    if (!fps) return 0;\n'
                 '    if (!strcmp(fps, "30")) *out = (totk_frame_env){NULL, "30"};\n'
                 '    else if (!strcmp(fps, "60")) *out = (totk_frame_env){NULL, NULL};\n'
                 '    else return 0;\n'
                 '    return 1;\n'
                 '}\n',
                 'int totk_preset_frame_env_build(const char *fps, totk_frame_env *out) {\n'
                 '    if (!fps) return 0;\n'
                 '    if (!strcmp(fps, "30")) *out = (totk_frame_env){NULL, "30"};\n'
                 '    else if (!strcmp(fps, "60")) *out = (totk_frame_env){NULL, NULL};\n'
                 '    /* TOTK-ipa: the uncapped setting: the game\'s own clock above the display\'s rate (TOTK_PHONE_FPS=0). */\n'
                 '    else if (!strcmp(fps, "uncapped") || !strcmp(fps, "max")) *out = (totk_frame_env){NULL, "0"};\n'
                 '    else return 0;\n'
                 '    return 1;\n'
                 '}\n',
                 '#13 the uncapped rate in the preset row')
    replace_once(settings_map_c,
                 'int totk_frame_button_target(int held30) { return held30 ? 60 : 30; }\n',
                 '/* The button\'s three-way cycle: 30 → 60 → uncapped → 30. The runtime\'s rates are 30, 60 and 0. */\n'
                 'int totk_frame_button_target(int current) {\n'
                 '    if (current == 30) return 60;\n'
                 '    if (current == 60) return 0;\n'
                 '    return 30;\n'
                 '}\n',
                 '#13 the button\'s three-way cycle')

    # --- #14: the start screen's frame-rate choice has the third setting too (the user's request, 2026-11-03) ---
    # The start screen offers 30 and 60; the button on the pad has three settings (30, 60, uncapped), so a player who
    # chose the uncapped one on the pad would find the start screen offering only two, and its choice would win at the
    # next launch. The screen gets the third choice, and the words are the pane's own.
    start = tree / 'ios/Sources/start_screen.m'
    replace_once(start,
                 '    _fps = [[UISegmentedControl alloc] initWithItems:@[@"30 fps", @"60 fps"]];\n'
                 '    _fps.selectedSegmentIndex = [[d stringForKey:@"TOTK_PHONE_FPS"] isEqualToString:@"30"] ? 0 : 1;\n',
                 '    /* TOTK-ipa: the third setting (uncapped), so the screen and the pad\'s button offer the same rates. */\n'
                 '    _fps = [[UISegmentedControl alloc] initWithItems:@[@"30 fps", @"60 fps", T(@"不限帧", @"Uncapped")]];\n'
                 '    NSString *fpsChoice = [d stringForKey:@"TOTK_PHONE_FPS"];\n'
                 '    _fps.selectedSegmentIndex = [fpsChoice isEqualToString:@"30"] ? 0 : [fpsChoice isEqualToString:@"uncapped"] ? 2 : 1;\n',
                 '#14 the uncapped rate on the start screen')
    replace_once(start,
                 '    [d setObject:_fps.selectedSegmentIndex == 0 ? @"30" : @"60" forKey:@"TOTK_PHONE_FPS"];\n',
                 '    /* TOTK-ipa: the third setting (uncapped) as the pane\'s own word for it. */\n'
                 '    [d setObject:_fps.selectedSegmentIndex == 0 ? @"30" : _fps.selectedSegmentIndex == 2 ? @"uncapped" : @"60" forKey:@"TOTK_PHONE_FPS"];\n',
                 '#14 the uncapped rate on the start screen')

    # The patches are edits of the upstream tree, so they must still hold what they say (kit/shim/patch_check.py).
    # The check is here and not in the workflow, so that the kit's own source carries it: the workflow file can only
    # be changed by a token with the workflow scope, and that scope is not something a player's token is given.
    import patch_check
    patch_check.check(tree)


if __name__ == '__main__':
    main(sys.argv[1])
