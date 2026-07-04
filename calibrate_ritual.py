"""Calibrate the ritual overlay position.

How it works:
1. Open the ritual menu in PoE2
2. Run: python calibrate_ritual.py
3. Click on the FAVOURS text (or any item in the grid)
4. The position is saved to ritual_offset.json
5. From now on, the ritual overlay uses this offset

Hotkey: Ctrl+Shift+C in the terminal to capture from clipboard pixel coords.
"""
import json
import sys
import time
from pathlib import Path

import cv2
import mss
import numpy as np

CONFIG_PATH = Path(__file__).parent / "ritual_offset.json"


def capture_screen():
    """Capture full screen."""
    with mss.mss() as sct:
        img = np.array(sct.grab(sct.monitors[1]))
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def show_click_prompt(img):
    """Display the screen and ask the user to click on FAVOURS text."""
    # Save a copy for the user to reference
    cv2.imwrite(str(Path(__file__).parent / "calibration_capture.png"), img)
    print()
    print("=" * 60)
    print("  RITUAL OVERLAY CALIBRATION")
    print("=" * 60)
    print()
    print("  1. The current screen was saved to: calibration_capture.png")
    print()
    print("  2. Open calibration_capture.png in an image viewer")
    print()
    print("  3. Find the FAVOURS text in the ritual menu header")
    print()
    print("  4. Note the pixel coordinates (x, y) of the LEFT edge of FAVOURS")
    print()
    print("  5. Enter the coordinates below (or paste 'auto' to use auto-detect)")
    print()
    return img


def manual_input():
    """Get coordinates from user input."""
    while True:
        raw = input("  FAVOURS text left edge (x y) or 'auto': ").strip()
        if raw.lower() == "auto":
            return None
        try:
            parts = raw.replace(",", " ").split()
            if len(parts) >= 2:
                x, y = int(parts[0]), int(parts[1])
                return (x, y)
            elif len(parts) == 1:
                # Could be a single number for auto-detect
                print("  Need both x and y, or 'auto'")
        except ValueError:
            print("  Invalid input, try again")


def compute_grid_offset(favours_xy, screen):
    """Given the FAVOURS text position, compute the grid offset."""
    if favours_xy is None:
        return None
    fx, fy = favours_xy
    h, w = screen.shape[:2]
    # The grid is below and to the right of the FAVOURS text
    # Based on our screenshots, the grid starts at approximately:
    # x = favours_x - 320 (grid is 320px to the left of FAVOURS right edge)
    # But we know from the 4K screenshots that the grid is at (453, 682)
    # when FAVOURS text starts at around (635, 468)
    # So: grid_x = favours_x - 182
    #     grid_y = favours_y + 214
    #
    # These offsets are calibrated for 4K (3840x2160).
    # For other resolutions, scale accordingly.
    sx = w / 3840
    sy = h / 2160
    grid_x = int((fx - 182) * sx)
    grid_y = int((fy + 214) * sy)
    return (grid_x, grid_y)


def verify_anchor(screen, grid_pos):
    """Check if the computed grid position has occupied items."""
    if grid_pos is None:
        return False
    gx, gy = grid_pos
    h, w = screen.shape[:2]
    gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
    count = 0
    SLOT_SIZE = 105
    CROP_INSET = 5
    CROP_SIZE = 95
    for row in range(10):
        for col in range(12):
            x = gx + col * SLOT_SIZE + CROP_INSET
            y = gy + row * SLOT_SIZE + CROP_INSET
            if x + CROP_SIZE > w or y + CROP_SIZE > h:
                continue
            crop = gray[y : y + CROP_SIZE, x : x + CROP_SIZE]
            if crop.size > 0 and crop.mean() > 28:
                count += 1
    return count >= 5


def main():
    print("Capturing screen...")
    screen = capture_screen()
    h, w = screen.shape[:2]
    print(f"Screen: {w}x{h}")

    show_click_prompt(screen)

    favours_xy = manual_input()
    if favours_xy is None:
        print("  Using auto-detect. Run again with calibration when you have the menu open.")
        return

    print(f"  FAVOURS at: {favours_xy}")
    grid = compute_grid_offset(favours_xy, screen)
    print(f"  Computed grid position: {grid}")

    if verify_anchor(screen, grid):
        print("  ✓ Grid position verified (found occupied items)")
    else:
        print("  ⚠ Grid position not verified - check calibration_capture.png")
        adjust = input("  Enter adjustment (dx dy) or press Enter to accept: ").strip()
        if adjust:
            try:
                dx, dy = map(int, adjust.split())
                grid = (grid[0] + dx, grid[1] + dy)
                print(f"  Adjusted to: {grid}")
            except ValueError:
                pass

    config = {
        "favours_xy": favours_xy,
        "grid_xy": grid,
        "screen_size": (w, h),
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    print(f"\n  Saved to {CONFIG_PATH}")
    print("  Restart the overlay app to use the calibration.")


if __name__ == "__main__":
    main()
