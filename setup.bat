@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
title RASH-HIT Fractal Analysis 1.2.2 - Setup and Automated Installer
cd /d "%~dp0"

echo ===============================================================================
echo            RASH-HIT Fractal Analysis 1.2.2 - Automated Windows Setup
echo ===============================================================================
echo.

REM 1. Detect System 64-bit Python 3.9+
set "SYS_PY="
where python >nul 2>&1
if not errorlevel 1 set "SYS_PY=python"
if not defined SYS_PY (
    where py >nul 2>&1
    if not errorlevel 1 set "SYS_PY=py -3"
)

if not defined SYS_PY (
    echo.
    echo [HATA] Sisteminizde Python 3.9+ bulunamadi.
    echo.
    echo RASH-HIT Fractal Analysis calismak icin 64-bit Python 3.9+ gerektirir.
    echo Lutfen asagidaki adimlari takip edin:
    echo   1. Python indirin: https://www.python.org/downloads/
    echo   2. Kurulum sirasinda Add python.exe to PATH secenegini ISARETLEYIN.
    echo   3. Kurulumu tamamlayip setup.bat dosyasini tekrar calistirin.
    echo.
    pause
    exit /b 1
)

REM 2. Bootstrap Virtual Environment [.venv] - Never pollute global Python!
set "VENV_DIR=%~dp0.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_CFG=%VENV_DIR%\pyvenv.cfg"
set "NEED_RECREATE=0"

REM 2a. .venv\Scripts\python.exe var mi?
if not exist "%VENV_PY%" set "NEED_RECREATE=1"

REM 2b. pyvenv.cfg var mi? (yarim venv tespiti)
if exist "%VENV_PY%" if not exist "%VENV_CFG%" set "NEED_RECREATE=1"

REM 2c. python.exe gercekten calisiyor mu? (No pyvenv.cfg gibi bozuk venv)
if exist "%VENV_PY%" if exist "%VENV_CFG%" (
    "%VENV_PY%" -c "import sys" >nul 2>&1
    if errorlevel 1 set "NEED_RECREATE=1"
)

REM Bozuk venv tespit edilirse: temizle ve yeniden olustur
if "%NEED_RECREATE%"=="1" (
    if exist "%VENV_DIR%" (
        echo [*] Bozuk .venv tespit edildi, yeniden olusturuluyor...
        REM Aktif python varsa kapat (dosya kilidi icin)
        taskkill /F /IM python.exe /T >nul 2>&1
        rem .venv\Scripts icindeki aktif process'ler serbest birakildi
        rmdir /s /q "%VENV_DIR%" >nul 2>&1
    )
)

if not exist "%VENV_PY%" (
    echo [*] Proje ozel sanal ortami [.venv] olusturuluyor...
    "%SYS_PY%" -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo.
        echo [HATA] .venv sanal ortami olusturulamadi!
        echo Global Python ortamini kirletmemek icin kurulum durduruldu.
        echo Lutfen disk izinlerinizi ve Python venv modulu desteginizi kontrol edin.
        echo.
        pause
        exit /b 1
    ) else (
        echo [PASS] .venv sanal ortami basariyla olusturuldu.
    )
) else (
    echo [*] Mevcut sanal ortam dogrulandi [.venv].
)
echo.

REM 3. Run comprehensive setup and diagnostics strictly inside .venv
"%VENV_PY%" "%~dp0setup.py" %*
if errorlevel 1 (
    echo.
    echo [HATA] Kurulum sirasinda bir sorun olustu. Lutfen yukaridaki mesajlari inceleyin.
    echo.
    pause
    exit /b 1
)

echo.
echo ===============================================================================
echo Kurulum tamamlandi.
echo Gunluk kullanim icin RASH-HIT-Analysis.bat dosyasini calistirin.
echo ===============================================================================
echo.
pause