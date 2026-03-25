@echo off
echo ========================================
echo   Photo Organizer - Setup
echo ========================================
echo.
echo [1/3] Checking Python...
python --version 2>nul || (echo ERROR: Python not found. Install from python.org & pause & exit)
echo.
echo [2/3] Installing Python dependencies...
pip install Pillow opencv-python-headless scikit-learn numpy imagehash --quiet
echo.
echo [3/3] Installing Electron...
npm install
echo.
echo ========================================
echo   Setup complete! Run START.bat to launch.
echo ========================================
pause
