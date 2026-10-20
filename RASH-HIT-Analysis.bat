@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title RASH-HIT Fractal Analysis 1.2.2
cd /d "%~dp0"

echo ===============================================================================
echo                RASH-HIT FRACTAL ANALYSIS 1.2.2 (Windows x64)
echo     Pure NumPy Supercover Box-Counting Engine ^& Interactive Dashboard
echo ===============================================================================
echo.

REM -----------------------------------------------------------------------------
REM [1/5] Virtual Environment [.venv] Verification
REM -----------------------------------------------------------------------------
set "VENV_DIR=%~dp0.venv"
set "RUN_PY=%VENV_DIR%\Scripts\python.exe"

if not exist "%RUN_PY%" (
    echo.
    echo ===============================================================================
    echo [BILGI] Kurulum ortami [.venv] bulunamadi.
    echo Otomatik kurulum baslatiliyor [setup.bat]...
    echo ===============================================================================
    echo.
    if exist "%~dp0setup.bat" (
        call "%~dp0setup.bat"
        if errorlevel 1 (
            echo [HATA] Kurulum tamamlanamadi. Lutfen kurulum mesajlarini inceleyin.
            pause
            exit /b 1
        )
        if not exist "%RUN_PY%" (
            echo [HATA] Kurulum tamamlanamadi; .venv Python bulunamadi.
            pause
            exit /b 1
        )
    ) else (
        echo [HATA] setup.bat bulunamadi.
        pause
        exit /b 1
    )
)

REM -----------------------------------------------------------------------------
REM [2/5] Core Dependencies Check
REM -----------------------------------------------------------------------------
"%RUN_PY%" -c "import sys; sys.path.insert(0, 'src'); import numpy, rich, defusedxml, tinycss2; import backend" >nul 2>&1
if errorlevel 1 (
    echo.
    echo ===============================================================================
    echo [UYARI] Bazi bagimliliklar eksik gorunuyor. Ortam onariliyor...
    echo ===============================================================================
    echo.
    if exist "%~dp0setup.bat" (
        call "%~dp0setup.bat"
        if errorlevel 1 (
            echo [HATA] Bagimlilik onarimi basarisiz oldu.
            pause
            exit /b 1
        )
        "%RUN_PY%" -c "import sys; sys.path.insert(0, 'src'); import numpy, rich, defusedxml, tinycss2; import backend" >nul 2>&1
        if errorlevel 1 (
            echo [HATA] Bagimliliklar kurulumdan sonra da dogrulanamadi.
            pause
            exit /b 1
        )
    ) else (
        echo [HATA] setup.bat bulunamadi; ortam onarilamiyor.
        pause
        exit /b 1
    )
)

REM -----------------------------------------------------------------------------
REM [3/5] Project File Structure Verification
REM -----------------------------------------------------------------------------
if not exist "%~dp0launcher.py" (
    echo [HATA] launcher.py bulunamadi. Proje dosya yapisi eksik.
    pause
    exit /b 1
)
if not exist "%~dp0src\backend\__init__.py" (
    echo [HATA] src\backend\__init__.py bulunamadi. Proje dosya yapisi eksik.
    pause
    exit /b 1
)

REM -----------------------------------------------------------------------------
REM [4/5] User Data Directories Verification
REM -----------------------------------------------------------------------------
if not exist "%~dp0input_svgs" mkdir "%~dp0input_svgs" >nul 2>&1
if not exist "%~dp0outputs" mkdir "%~dp0outputs" >nul 2>&1

REM -----------------------------------------------------------------------------
REM [5/5] Launch Interactive TUI Launcher
REM -----------------------------------------------------------------------------
echo.
echo ===============================================================================
echo [BILGI] RASH-HIT Fractal Analysis baslatiliyor...
echo ===============================================================================
echo.
"%RUN_PY%" "%~dp0launcher.py" %*
set "EXITCODE=%ERRORLEVEL%"
endlocal & exit /b %EXITCODE%
