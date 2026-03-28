import subprocess
import sys

packages = [
    ("opencv-python-headless", "cv2"),
    ("numpy", "numpy"),
    ("scikit-learn", "sklearn"),
    ("pillow", "PIL"),
    ("imagehash", "imagehash"),
    ("face_recognition", "face_recognition")
]

def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

for package_name, import_name in packages:
    try:
        __import__(import_name)
        print(f"[SETUP] {package_name} already installed")
    except ImportError:
        print(f"[SETUP] Installing {package_name}...")
        install(package_name)

print("[SETUP] All dependencies ready")
