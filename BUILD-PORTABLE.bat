@echo off
echo ========================================
echo   Building Portable .exe
echo ========================================
echo.
npx electron-builder --win portable
echo.
echo Done! Check the "dist" folder for PhotoOrganizer-Portable.exe
pause
