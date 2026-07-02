# Path of Exile 2 - Smooth Settings (RTX 5080)

Tested stable on the following hardware:

| Component | Spec |
|-----------|------|
| CPU | AMD 9800X3D |
| RAM | 32GB DDR5 |
| GPU | RTX 5080 |
| Storage | Gen5 NVMe |
| OS | Windows 11 |
| API | Vulkan |
| Display Mode | Windowed Fullscreen @ 3840×2160 |

**Target framerate:** 120 FPS, no crashing, no stuttering.

---

## Table of Contents

1. [NVIDIA Control Panel](#nvidia-control-panel)
2. [NVIDIA App (Beta)](#nvidia-app-beta)
3. [In-Game Settings](#in-game-settings)
4. [Verification](#verification)

---

## NVIDIA Control Panel

- **Shader Cache Size:** 10GB

> Increase the default (~4GB) to prevent shader compilation stutter when exploring new areas, league launches, or patches.

---

## NVIDIA App (Beta)

- **Turn Beta On** (in NVIDIA App settings)
- **DLSS Override → Model Presets → Super Resolution:** Preset M
- **Power Management Mode:** Prefer Maximum Performance

> Preset M uses the new transformer model which gives better image quality at the cost of slightly more VRAM. Enable the NVIDIA App beta to get access to model presets.

---

## In-Game Settings

### Display

| Setting | Value |
|---------|-------|
| Display Mode | Windowed Fullscreen |
| VSync | Off |
| Dynamic Resolution | On |
| Window Resolution | 3840×2160 |
| Upscale Mode | NVIDIA DLSS |
| Max Image Quality | Ultra Performance |
| Sharpness | 20% |
| HDR | Off |

> Ultra Performance DLSS + 20% sharpness is a sweet spot — much sharper than 0% while still hitting 120 FPS in endgame. Skip HDR to avoid frame drops on non-HDR monitors.

### Graphics

| Setting | Value |
|---------|-------|
| Texture Quality | High |
| Texture Filtering | 16x |
| Lighting | Shadows + Global Illumination |
| Shadow + GI Quality | High |
| Sun Shadow Quality | High |
| Number of Lights | High |
| Bloom | 100% |
| Water Detail Level | High |

### Performance

| Setting | Value |
|---------|-------|
| NVIDIA Reflex | On |
| Foreground FPS Cap | 120 |
| Background FPS Cap | Off |
| Triple Buffering | On |
| Dynamic Culling | On |
| Target Framerate | 120 |
| Engine Multithreading | On |

> Background FPS Cap = Off reduces input lag when alt-tabbing. Triple Buffering smooths frametime. Dynamic Culling helps a lot in cities and dense maps.

---

## Verification

After applying these settings:

1. **No crashes** during mapping, ritual, breach, or endgame content
2. **Stable 120 FPS** in open-world areas
3. **80-100 FPS** in heavy endgame (T17 maps, breach+ritual, Simulacrum)
4. **Input lag** feels responsive due to Reflex + low background FPS cap

If you still see stuttering, check:

- Shader cache location (should be on your fastest NVMe, not the game drive)
- DLSS preset D is lower quality than M if you need more headroom
- Disable any overlays (Discord, GeForce Experience, browser tabs with hardware acceleration)

---

*Tested on Runes of Aldur league. Settings may need adjustment after major patches.*
