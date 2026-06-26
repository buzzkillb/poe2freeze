"""
Install dependencies and run the pricer/overlay.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
REQUIREMENTS = ROOT / "requirements.txt"


def main():
    py = sys.executable
    print(f"Using: {py}")
    print("Installing requirements...")
    subprocess.check_call(
        [py, "-m", "pip", "install", "-r", str(REQUIREMENTS)],
    )
    print("Done. Run 'python overlay.py' to start.")


if __name__ == "__main__":
    main()