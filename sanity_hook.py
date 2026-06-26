"""
Quick sanity test for pynput on this system.
Run this, then press Home and Ctrl+C to exit.
Should print HOME key events as you press them.
"""
import sys
import time

try:
    from pynput import keyboard
except ImportError:
    print("FAIL: pynput not installed")
    sys.exit(1)

print("pynput version:", keyboard.__version__ if hasattr(keyboard, '__version__') else "unknown")
print()
print("Listening for 10 seconds. Press Home, F1, F2, ESC, anything.")
print("If you see events, the global hook works on this system.")
print()

events = []

def on_press(key):
    events.append(key)
    print(f"  [{len(events)}] {key}", flush=True)

def on_release(key):
    pass

listener = keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()

time.sleep(10)
listener.stop()

print()
print(f"Total events captured: {len(events)}")
if any(str(k) == "Key.home" for k in events):
    print("HOME KEY WAS CAPTURED - global hook works!")
else:
    print("Home key NOT captured. pynput global hook may not be working.")
    print("Try running as administrator or use a different hotkey like F13.")