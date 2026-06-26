@echo off
setlocal

set PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
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

if exist "%SCRIPT_DIR%data\mod_translations.json" (
    del "%SCRIPT_DIR%data\mod_translations.json"
    echo Deleted mod_translations.json
)

cd /d "%SCRIPT_DIR%"
"%PYTHON%" build_mod_translations.py
"%PYTHON%" test_pricer.py --warm

echo.
echo Reset complete.
pause

endlocal