@echo off
setlocal enabledelayedexpansion
echo ================================================================
echo   Photo Organizer — Portable Build Script
echo ================================================================
echo.

:: ---- Step 1: Check Python ----
echo [1/6] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found on PATH.
    echo        Install Python 3.8+ from https://python.org
    echo        Make sure "Add Python to PATH" is checked during install.
    pause
    exit /b 1
)
python --version
echo.

:: ---- Step 2: Install Python dependencies ----
echo [2/6] Installing Python dependencies...
pip install Pillow opencv-python-headless scikit-learn numpy imagehash pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: Failed to install Python dependencies.
    pause
    exit /b 1
)
echo        Done.
echo.

:: ---- Step 3: Build scanner.exe with PyInstaller ----
echo [3/6] Building scanner.exe with PyInstaller...
cd python_scanner
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

pyinstaller scanner.spec --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    cd ..
    pause
    exit /b 1
)
cd ..
echo        scanner.exe built successfully.
echo.

:: ---- Step 4: Copy scanner.exe to python_bin/ ----
echo [4/6] Setting up python_bin directory...
if not exist "python_bin" mkdir python_bin
copy /y "python_scanner\dist\scanner.exe" "python_bin\scanner.exe" >nul
if errorlevel 1 (
    echo ERROR: Failed to copy scanner.exe to python_bin.
    pause
    exit /b 1
)
echo        python_bin\scanner.exe ready.
echo.

:: ---- Step 5: Install Node.js dependencies ----
echo [5/6] Installing Node.js dependencies...
call npm install
if errorlevel 1 (
    echo ERROR: npm install failed.
    pause
    exit /b 1
)
echo.

:: ---- Step 6: Build Electron portable app ----
echo [6/6] Building Electron portable app...
call npx electron-builder --win portable
if errorlevel 1 (
    echo ERROR: Electron build failed.
    pause
    exit /b 1
)
echo.

echo ================================================================
echo   BUILD COMPLETE!
echo ================================================================
echo.
echo   Output: dist\PhotoOrganizer-Portable.exe
echo.
echo   This is a fully self-contained portable app.
echo   No Python or Node.js needed on the target machine.
echo.
echo   Folder structure inside the build:
echo     resources\python_bin\scanner.exe  (bundled Python scanner)
echo     resources\app.asar               (Electron app)
echo ================================================================
pause
