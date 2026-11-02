/* The VR hooks the graphics layer calls by name (third_party/d2r_gfx/gfx/nvn/nvn_mtl.m): the head search (a Mac
   diagnostic) and the third-person camera distance (zeldaVR's setting). Both live in runtime/game_patches_v143.c,
   inside its Mac-only blocks, so an iPhone build has no definition and the link fails. The kit does not need them:
   the VR camera is off on iOS and the camera distance is the game's own. They are defined here as nothing doing, so
   the graphics layer's calls reach a function that returns.

   The graphics layer declares them weak_import and checks them before calling; these strong definitions are what the
   linker needs. */
#include <TargetConditionals.h>
#include <stddef.h>

#if TARGET_OS_IPHONE
void runtime_vr_find_head(int stage) { (void)stage; }
void runtime_camera_distance_set(int cm) { (void)cm; }
#endif
