@echo off
setlocal

set SCRIPT_DIR=%~dp0
set DB=%SCRIPT_DIR%prices.db

echo === PoE2 Ninja Pricer - Cache Reset ===
echo.

if exist "%DB%" (
    del "%DB%"
    echo Deleted prices.db
) else (
    echo No cache file found
)

echo.
echo Reset complete. Restart the overlay to rebuild.
pause

endlocal