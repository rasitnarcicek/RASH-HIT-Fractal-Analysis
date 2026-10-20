# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""
setup.py — Automated Environment Setup for RASH-HIT Fractal Analysis 1.2.1.

Bu sürüm CPU-only saf NumPy motorudur; GPU/CUDA/Taichi/OpenPyXL/Shapely
içermez. Ana proje kalıbından sadeleştirilmiş, gerekli adımlar:

  1. Python sürüm/ mimari kontrolü (3.9+ 64-bit)
  2. Pip kurulumu + requirements.txt
  3. Editable install: ``pip install -e .`` (src/ layout)
  4. src/ import doğrulama (sys.path.insert ile)
  5. Bilimsel hesap doğrulama: test.svg üzerinde L3 hesap
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Tuple

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"

MIN_PY_VERSION = (3, 9)

# ---------------------------------------------------------------------------
# pythonw.exe tespiti: File Explorer'dan .py'ye çift tıklayınca Windows
# pythonw.exe ile çalıştırır (no console window, sessizce kapanır). Bu
# durumda kendimizi cmd.exe /c python setup.py ile yeniden başlatırız;
# böylece kullanıcı gerçek bir terminal penceresi görür.
# ---------------------------------------------------------------------------

def _is_pythonw() -> bool:
    """pythonw.exe ile mi çalışıyoruz? (no-console, pencere görünmez)."""
    exe = sys.executable.lower()
    return "pythonw" in exe or os.path.basename(exe).lower() == "pythonw.exe"


def _rerun_in_console() -> None:
    """pythonw.exe tespit edildi: setup.bat'ı yeni pencerede başlat.

    File Explorer'dan ``setup.py``'ye çift tıklayınca Windows pythonw.exe
    (no-console) ile başlatır. pythonw altında ``subprocess.Popen`` +
    ``CREATE_NEW_CONSOLE | DETACHED_PROCESS`` + ``proc.wait()`` zinciri
    test edildi ve görünür pencere açılamadı (Windows job object
    kısıtlaması).

    Bu yüzden: setup.bat'ı ``subprocess.Popen`` ile yeni pencerede
    başlat, çıktıyı bir log dosyasına yönlendir. Kullanıcı daha sonra
    bu log dosyasını kontrol edebilir. setup.bat'ın kendi sonundaki
    ``pause`` pencereyi açık tutacaktır; eğer bu da başarısız olursa
    en azından log dosyasından kurulum sonucunu görebilir.
    """
    setup_bat = ROOT / "setup.bat"
    log_file = ROOT / "setup_pythonw.log"
    if not setup_bat.exists():
        os._exit(1)
    # CREATE_NEW_CONSOLE (0x10) YALNIZ — DETACHED_PROCESS ile birleşince
    # WinError 87 veriyor. pythonw process'te görünür konsol olmadığı
    # için CREATE_NEW_CONSOLE yeni pencerede cmd açar; kullanıcı
    # orada setup'ı görür. Parent process olarak biz proc.wait() ile
    # bloklanırız — görünmez olduğumuz için kullanıcıyı etkilemez.
    flags = 0x00000010  # sadece CREATE_NEW_CONSOLE
    try:
        with open(log_file, "w", encoding="utf-8") as logf:
            proc = subprocess.Popen(
                ["cmd.exe", "/c", str(setup_bat)],
                creationflags=flags,
                stdout=logf,
                stderr=logf,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                cwd=str(ROOT),
            )
            try:
                proc.wait(timeout=300)
            except Exception:
                logf.write("\n[timeout: setup 5 dakika icinde tamamlanamadi]\n")
    except Exception as e:
        try:
            with open(log_file, "a", encoding="utf-8") as logf:
                logf.write(f"\n[HATA] {type(e).__name__}: {e}\n")
                logf.write(
                    "\nLutfen manuel olarak setup.bat dosyasina cift tiklayin.\n"
                    f"Yol: {setup_bat}\n"
                )
        except Exception:
            pass
    os._exit(0)


def color(text: str, code: str) -> str:
    if os.name == "nt":
        os.system("")  # VT enable
    return f"\033[{code}m{text}\033[0m"


def banner() -> None:
    print(color(
        "\n================================================================================\n"
        "             RASH-HIT FRACTAL ANALYSIS 1.2.1 - SETUP & DIAGNOSTICS\n"
        "    Pure NumPy Supercover Box-Counting Engine & Interactive Dashboard\n"
        "================================================================================\n",
        "96",
    ))


def check_python() -> bool:
    print(color("[1/5] Python Runtime Environment...", "1"))
    ver = sys.version_info
    ver_str = f"{ver.major}.{ver.minor}.{ver.micro}"
    arch = platform.architecture()[0]
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    print(f"  * Python: {ver_str} ({arch})")
    print(f"  * Executable: {sys.executable}")
    print(f"  * Environment: {'Isolated (.venv)' if in_venv else 'Global'}")
    if (ver.major, ver.minor) < MIN_PY_VERSION:
        print(color(f"  [ERROR] Python {MIN_PY_VERSION[0]}.{MIN_PY_VERSION[1]}+ is required (got {ver_str}).", "91"))
        return False
    if arch != "64bit":
        print(color("  [WARNING] 32-bit Python detected. 64-bit strongly recommended.", "93"))
    print(color("  [PASS] Python runtime OK.\n", "92"))
    return True


def install_dependencies() -> bool:
    print(color("[2/5] Installing Core Dependencies...", "1"))
    # pip probe — kırık venv tespit edilirse setup.bat zaten bunu kullanıcı
    # onayıyla sildi. Buraya geldiysek ya setup.bat başarılı olmuştur (yeni
    # venv), ya da global Python ortamındayız. Her iki durumda da net mesaj.
    probe = subprocess.run(
        [sys.executable, "-m", "pip", "--version"],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        venv_path = ROOT / ".venv"
        if in_venv and venv_path.exists():
            # setup.bat'a rağmen hâlâ buradaysak: ensurepip de başarısız
            # olmuş demektir. Önce kullanıcıya basit kurtarma yolu sun;
            # bu işe yaramazsa silme talimatı ver.
            print(color(
                "  [HATA] .venv'de pip calismiyor (ensurepip de basarisiz).\n"
                "\n"
                "  Hızlı kurtarma (deneyin):\n"
                "    .venv\\Scripts\\python.exe -m ensurepip --default-pip\n"
                "\n"
                "  Basarisiz olursa su komutlari calistirin:\n"
                "    Bu pencereyi kapatin\n"
                "    Yeni cmd.exe acin\n"
                "    rmdir /s /q .venv\n"
                "    setup.bat\n"
                "\n"
                "  Kilitli dosyalar icin gerekirse Bilgisayari yeniden baslatin.",
                "91",
            ))
            return False
        print(color(
            "  [ERROR] Sistem Python ortaminda pip calismiyor.\n"
            "  Cozum: python -m ensurepip --default-pip",
            "91",
        ))
        return False
    # pip upgrade
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip", "--quiet"], check=False)
    except Exception:
        pass
    # requirements.txt
    req = ROOT / "requirements.txt"
    if not req.exists():
        print(color("  [ERROR] requirements.txt bulunamadi.", "91"))
        return False
    res = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req), "--quiet"])
    if res.returncode != 0:
        print(color("  [ERROR] requirements.txt install failed.", "91"))
        return False
    # editable install (src/ layout) — sadece global Python'da veya editable
    # zaten kuruluysa skip et. .venv içindeyken editable install subprocess'i
    # bazen kendi setup.py'yi recursive çağırıp pip modülünü geçici olarak
    # kilitleyebilir; bu yüzden .venv'de sys.path injection yeterli.
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    skip_editable = False
    if in_venv:
        # .venv içindeyiz: editable install denemeden önce src/backend zaten
        # import edilebiliyor mu kontrol et
        probe = subprocess.run(
            [sys.executable, "-c", "import sys; sys.path.insert(0, 'src'); import backend; print('OK')"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        if probe.returncode == 0:
            skip_editable = True
            print("  * Editable install: atlanıyor (.venv + src/ import OK).")
    if not skip_editable:
        print("  * Editable install (src/ layout)...")
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"],
            cwd=str(ROOT),
        )
        if res.returncode != 0:
            print(color("  [WARNING] editable install failed; fallback runtime path injection (src/) will be used.", "93"))
    print(color("  [PASS] Core dependencies installed.\n", "92"))
    return True


def validate_src_imports() -> bool:
    print(color("[3/5] Validating src/ layout imports...", "1"))
    code = (
        "import sys, importlib.metadata; "
        "sys.path.insert(0, 'src'); "
        "import numpy, rich, defusedxml, tinycss2; "
        "from src.backend import __version__, __engine_name__; "
        "rich_v = importlib.metadata.version('rich'); "
        f"print(f'  * Version: {{__version__}} | Engine: {{__engine_name__}}'); "
        "print(f'  * NumPy: {numpy.__version__} | rich: {rich_v}')"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if res.returncode != 0:
        print(color(f"  [ERROR] src/ import failed:\n{res.stderr}", "91"))
        return False
    print(res.stdout, end="")
    print(color("  [PASS] src/ backend package is importable.\n", "92"))
    return True


def run_preflight() -> bool:
    print(color("[4/5] Pre-Flight Calculation Test (test.svg, L=3)...", "1"))
    code = (
        "import sys; "
        "sys.path.insert(0, 'src'); "
        "from src.backend.geometric_contact_pipeline import run_geometric_contact; "
        "from pathlib import Path; "
        "m = run_geometric_contact(Path('input_svgs/test.svg'), max_level=3); "
        "print(f'  * test.svg: Db = {m[\"fractal_dimension\"]:.4f}, R² = {m[\"r_squared\"]:.4f}, cells = {m[\"segment_count\"]}')"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if res.returncode != 0:
        print(color(f"  [ERROR] Pre-flight test failed:\n{res.stderr}", "91"))
        return False
    print(res.stdout, end="")
    print(color("  [PASS] Scientific calculation verified.\n", "92"))
    return True


def ensure_user_dirs() -> None:
    print(color("[5/5] User Data Directories...", "1"))
    (ROOT / "input_svgs").mkdir(parents=True, exist_ok=True)
    (ROOT / "outputs").mkdir(parents=True, exist_ok=True)
    print(f"  * input_svgs/ ready (place .svg files here)")
    print(f"  * outputs/ ready (analysis reports land here)")
    print(color("  [PASS] User directories created.\n", "92"))


def main() -> int:
    # File Explorer'dan setup.py'ye çift tıklayınca Windows varsayılan
    # olarak pythonw.exe ile çalıştırır (no-console subprocess). Bu
    # durumda hiçbir pencere açılmaz, çıktı kullanıcıya görünmez ve
    # "direkt kapanıyor" gibi algılanır. Kendimizi cmd.exe + console
    # python ile yeniden başlatıp gerçek terminal penceresi açıyoruz.
    if _is_pythonw():
        _rerun_in_console()
    banner()
    if "--reset" in sys.argv:
        venv = ROOT / ".venv"
        if venv.exists():
            print(color(f"  * Removing broken .venv at {venv} ...", "93"))
            import shutil
            shutil.rmtree(venv, ignore_errors=True)
            print(color("  * Done. Re-run without --reset to bootstrap a fresh .venv.\n", "92"))
        return 0
    if not check_python():
        return 1
    if not install_dependencies():
        print(color(
            "\n[HINT] Eger .venv bozuksa: 'setup.py --reset' ile silip tekrar calistirin.\n",
            "93",
        ))
        return 1
    if not validate_src_imports():
        return 1
    if not run_preflight():
        return 1
    ensure_user_dirs()
    print(color(
        "\n================================================================================\n"
        "         SETUP COMPLETED SUCCESSFULLY!  (SYSTEM READY)\n"
        "================================================================================\n"
        "Kurulum tamamlandi. Gunluk kullanim icin:\n"
        "  -> Windows : RASH-HIT-Analysis.bat (double-click)\n"
        "  -> Linux/macOS : ./start.sh\n"
        "  -> Manuel : .venv\\Scripts\\python.exe launcher.py\n"
        "\n"
        "CLI dogrudan mod:\n"
        "  python launcher.py --input input_svgs/test.svg -l 3\n"
        "  python launcher.py --dir  input_svgs/             -l 4\n"
        "  python launcher.py --version\n"
        "  python launcher.py --check\n"
        "================================================================================\n",
        "92",
    ))
    # File Explorer'dan çift tıklayınca pythonw.exe (GUI subprocess)
    # kullanılır; sys.stdout.isatty() her zaman False döner ve pencere
    # hemen kapanır. Bu yüzden TTY kontrolü YAPMA — her zaman input()
    # çağır. EOFError/Ctrl+C durumunda sessizce çık (subprocess'lerde
    # stdin kapalı olabilir; .bat üzerinden çağrıldığında zaten setup.bat
    # kendi ``pause`` komutuyla bekletiyor, bu input() pencerenin erken
    # kapanmasını engelliyor).
    try:
        input("\nPencere kapatmak icin ENTER tusuna basin...")
    except (KeyboardInterrupt, EOFError, OSError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
