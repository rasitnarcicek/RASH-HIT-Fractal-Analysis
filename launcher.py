# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""
launcher.py — RASH-HIT Fractal Analysis v1.2.2 (CPU-only).

Tek resmi etkileşimli terminal başlatıcısı.  Tüm dağıtım kanalları
(PyPI, npm, GitHub, Windows .bat, Linux/macOS .sh) bu modülü çağırır.

Tasarım: ana projedeki (ANTİGRAVİTY/RASH-HIT Fractal Studio)
``launcher.py`` kalıbı sadeleştirilerek uyarlandı:

  * borderless flat layout
  * RASH-HIT ASCII logosu (pure white)
  * ok tuşu (↑/↓) + ENTER navigasyon
  * post-run action menu (Yeni analiz / Ana menü)
  * sub-menu pattern (toplu klasör + tekli SVG)

Web Studio / GPU / Health Scan / Dependency Repair kasıtlı olarak
YOK — bu sürüm yalnızca CPU + saf NumPy supercover motorudur.

Ana menü:
  1. Analiz Modu (tekli SVG / toplu klasör)
  2. Sistem Bilgisi
  3. Çıkış

Doğrudan mod:
  rash-hit-fractal --input motif.svg -l 5
  rash-hit-fractal --dir ./motifs -l 4
  rash-hit-fractal --version
  rash-hit-fractal --check
  rash-hit-fractal --setup
"""
from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path
from typing import List, Optional

# `python launcher.py` veya `python -m launcher` her yerden çalışsın.
# src/ layout: hem src/ hem de proje kökü sys.path'e eklenir; böylece
# hem `from src.backend...` hem de `from launcher import main` çalışır.
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Windows'ta varsayılan konsol kodlaması (cp1254 vb.) RASH-HIT ASCII
# logosundaki blok karakterleri (█) yazamıyor: UnicodeEncodeError.
# stdout/stderr'i UTF-8'e sabitle — Türkçe/kodeksli konsol güvenliği.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass

import numpy
import defusedxml
import tinycss2

from src.backend import __version__ as VERSION, __engine_name__ as ENGINE_NAME
from src.backend.tui import (
    clear_screen,
    console,
    get_key,
    info_panel,
    NAV_BACK,
    print_logo,
    print_result_summary,
    prompt_levels,
    prompt_svg_file,
    prompt_svg_folder,
    select_from_menu,
    show_system_information,
    wait_for_enter,
)
from run_analysis import (
    analyze_svg_data,
    print_analysis_report,
    write_analysis_file,
)
from src.backend.ascii_exporter import (
    build_book_filename,
    build_output_filename,
    generate_batch_ascii_book,
    now_stamp,
)


# ---------------------------------------------------------------------------
# Pre-run helpers
# ---------------------------------------------------------------------------

def _run_single_svg(svg_path: Path, levels: int) -> Optional[Path]:
    """Tekli SVG analizini çalıştır, rapor dosyası yaz, yolu döndür."""
    stamp = now_stamp()
    result = analyze_svg_data(str(svg_path), levels=levels)
    if result.get("error"):
        info_panel(" Hata ", f"[bold white]✘ {result['error']}[/bold white]")
        return None
    print_analysis_report(result)
    out_name = build_output_filename(result["motif_name"], levels, stamp=stamp)
    out_path = svg_path.with_name(out_name)
    write_analysis_file(result, out_path, stamp=stamp)
    summary = {
        "motif_name": result["motif_name"],
        "status": "SUCCESS",
        "fractal_dimension": result.get("fractal_dimension"),
        "r_squared": result.get("r_squared"),
        "total_time_ms": result.get("total_time_ms"),
        "output_path": str(out_path),
    }
    print_result_summary(summary)
    return out_path


def _run_batch_dir(folder: Path, levels: int) -> Optional[Path]:
    """Toplu klasör analizini çalıştır; kitap rapor yolunu döndür."""
    stamp = now_stamp()
    svg_files = sorted(folder.glob("*.svg"))
    if not svg_files:
        info_panel(" Hata ", f"[bold white]✘ Klasörde SVG dosyası yok: {folder}[/bold white]")
        return None

    from rich.table import Table
    from rich import box

    table = Table(
        title="[bold white]Toplu İşlem İlerlemesi[/bold white]",
        box=box.SQUARE, safe_box=True, border_style="white",
        header_style="bold white on black", padding=(0, 1),
    )
    table.add_column("No", justify="right", style="dim", width=6)
    table.add_column("Dosya", style="bold white", width=28)
    table.add_column("Durum", style="bold", width=10)
    table.add_column("Db", justify="right", style="bold white", width=10)
    table.add_column("R²", justify="right", style="bold white", width=10)

    written: list = []
    for i, f in enumerate(svg_files, start=1):
        res = analyze_svg_data(str(f), levels=levels)
        if res.get("error"):
            table.add_row(f"[{i}/{len(svg_files)}]", f.name, "ERR", "-", "-")
            continue
        out_name = build_output_filename(res["motif_name"], levels, stamp=stamp)
        out_path = folder / out_name
        write_analysis_file(res, out_path, stamp=stamp)
        written.append((res["motif_name"], res["manifest"]))
        db = res.get("fractal_dimension", 0.0) or 0.0
        r2 = res.get("r_squared", 0.0) or 0.0
        table.add_row(
            f"[{i}/{len(svg_files)}]",
            f.name, "OK",
            f"{db:.4f}", f"{r2:.4f}",
        )
    console.print(table)
    console.print("")

    if not written:
        info_panel(" Hata ", "[bold white]✘ Hiçbir dosya başarıyla işlenemedi.[/bold white]")
        return None

    book_path = folder / build_book_filename(levels, stamp=stamp)
    generate_batch_ascii_book(written, levels=levels, out_path=book_path, stamp=stamp)
    info_panel(
        " Toplu Analiz Tamamlandı ",
        f"[bold white]✔ Başarılı: {len(written)}/{len(svg_files)} dosya\n"
        f"  Kitap raporu: {book_path}[/bold white]",
    )
    return book_path


# ---------------------------------------------------------------------------
# Interactive flows
# ---------------------------------------------------------------------------

def _post_run_action_menu() -> int:
    """Analiz sonrası: 0 = Yeni Analiz, 1 = Ana Menüye Dön.

    Ana proje kalıbı: ``clear=True`` ile ekranı siler, logo + yeni
    panel basar. Analiz çıktısı artık ekranda kalmaz — temiz geçiş.
    """
    idx = select_from_menu(
        "Analiz tamamlandı — sıradaki adım",
        [
            "1. Yeni Bir Analiz Başlat",
            "2. Ana Menüye Dön",
        ],
        clear=True,
        escape_action="back",  # ESC/q → "Ana Menüye Dön"
    )
    if idx in (NAV_BACK, 1):
        return 1
    return 0


def _interactive_analysis_mode() -> None:
    """Seçenek 1: Analiz modu — tekli SVG veya toplu klasör alt menüsü."""
    first = True
    while True:
        # 3 seçenek: Tekli / Toplu / Ana Menü. ``add_back=False`` çünkü
        # manuel olarak "Ana Menüye Dön" ekliyoruz; çift back etiketi
        # kullanıcıyı yanıltıyor.
        target_options = [
            "1. Tekli SVG Dosyası Analizi",
            "2. Toplu Klasör Analizi",
            "↩ Ana Menüye Dön",
        ]
        idx = select_from_menu(
            "Uçbirim Etkileşimli Analiz Modu",
            target_options,
            add_back=False,
            escape_action="back",
            clear=first,  # ilk girişte temizle, sonrakileri üst üste bas
        )
        first = False
        # idx == 2 → manuel "Ana Menüye Dön"; idx == NAV_BACK → ESC ile geri
        if idx in (-1, NAV_BACK, 2):
            return

        if idx == 0:
            svg_file = prompt_svg_file()
            if not svg_file:
                # prompt iptal (q) veya geçersiz yol → temiz ekranla alt
                # menüye dön; logo + tablo üst üste binmesin.
                clear_screen()
                print_logo()
                first = True
                continue
            levels = prompt_levels()
            if levels <= 0:
                clear_screen()
                print_logo()
                first = True
                continue
            clear_screen()
            print_logo()
            console.print(
                f"[bold white]Analiz Başlatılıyor:[/bold white] "
                f"[bold white]{svg_file.name}[/bold white]"
            )
            console.print(
                f"[dim white]Seviye: {levels} | Motor: {ENGINE_NAME} | CPU Pure NumPy[/dim white]\n"
            )
            _run_single_svg(svg_file, levels)
            choice = _post_run_action_menu()
            if choice == 1:
                return
            # Yeni analiz → alt menüye dön; clear+logo ana menüye dönüşte
            # tek seferlik yapılacak (aşağıdaki select_from_menu(clear=True)).
            first = True

        elif idx == 1:
            folder = prompt_svg_folder()
            if not folder:
                clear_screen()
                print_logo()
                first = True
                continue
            levels = prompt_levels()
            if levels <= 0:
                clear_screen()
                print_logo()
                first = True
                continue
            clear_screen()
            print_logo()
            svg_count = len(list(folder.glob("*.svg")))
            console.print(
                f"[bold white]Toplu Analiz Başlatılıyor:[/bold white] "
                f"[bold white]{folder.name}/[/bold white] ({svg_count} dosya)"
            )
            console.print(
                f"[dim white]Seviye: {levels} | Motor: {ENGINE_NAME} | CPU Pure NumPy[/dim white]\n"
            )
            _run_batch_dir(folder, levels)
            choice = _post_run_action_menu()
            if choice == 1:
                return
            first = True


def _system_information_screen() -> None:
    """Seçenek 2: Sistem ve donanım bilgileri.

    Ana proje kalıbı: ENTER beklemiyor; doğrudan döndüğünde ana menü
    ``clear=True`` ile ekranı silip yeni logo+panel basıyor. Bu sayede
    tablo üst üste binmiyor.
    """
    clear_screen()
    print_logo()
    rows = [
        ("RASH-HIT Version", f"v{VERSION}"),
        ("Compute Engine", ENGINE_NAME),
        ("Python Runtime", f"Python {platform.python_version()}"),
        ("Operating System", f"{platform.system()} {platform.machine()}"),
        ("CPU Processor", platform.processor() or "Unknown"),
        ("NumPy", numpy.__version__),
        ("defusedxml", defusedxml.__version__),
        ("tinycss2", tinycss2.__version__),
        ("Compute Mode", "CPU only (no GPU)"),
        ("Project Root", str(ROOT)),
    ]
    show_system_information(rows)
    wait_for_enter()  # ana proje kalıbı: tablo görünür kalsın, ESC/ok
                     # tuşları tablonun üstüne menü basmasın.


# ---------------------------------------------------------------------------
# Main menu loop
# ---------------------------------------------------------------------------

def main_menu() -> int:
    """3 seçenekli ana menü döngüsü."""
    first = True
    while True:
        options = [
            "1. Analiz Modu (Tekli SVG / Toplu Klasör)",
            "2. Sistem ve Donanım Bilgileri",
            "3. Çıkış",
        ]
        idx = select_from_menu(
            "Ana Menü - Bir İşlem Seçiniz",
            options,
            clear=first,  # İlk girişte temizle; sonrakileri üst üste bas
        )
        first = False

        if idx == 0:
            _interactive_analysis_mode()
            first = True  # analiz modundan dönünce temizle
        elif idx == 1:
            _system_information_screen()
            first = True  # sistem bilgisi → wait_for_enter → ana menü
                          # temiz ekrana yeni logo+panel bassın
        elif idx in (-1, 2):
            clear_screen()
            console.print(
                "[bold white]RASH-HIT Fractal Analysis kapatıldı. "
                "İyi çalışmalar![/bold white]\n"
            )
            return 0
    return 0


# ---------------------------------------------------------------------------
# CLI / diagnostics
# ---------------------------------------------------------------------------

def _print_check() -> None:
    """Ortam tanı bilgilerini yazdırır (--check için)."""
    from rich.table import Table
    from rich import box
    rows = [
        ("Python", platform.python_version(), True),
        ("NumPy", numpy.__version__, True),
        ("defusedxml", defusedxml.__version__, True),
        ("tinycss2", tinycss2.__version__, True),
    ]
    table = Table(
        title="[bold white]Environment Check[/bold white]",
        box=box.SQUARE, safe_box=True,
        header_style="bold white on black", border_style="white",
        padding=(0, 1),
    )
    table.add_column("Component", style="white bold")
    table.add_column("Version", style="white")
    table.add_column("Status", style="bold", justify="center")
    for name, ver, ok in rows:
        status = "[bold white]OK[/bold white]" if ok else "[bold white]MISSING[/bold white]"
        table.add_row(name, ver, status)
    console.print(table)


def _direct_cli(args: argparse.Namespace) -> int:
    """`--input` / `--dir` doğrudan modu — menü açmadan çalıştırır."""
    target = args.input or args.dir
    target_path = Path(target)
    if target_path.is_file():
        result = analyze_svg_data(str(target_path), levels=args.levels)
        if result.get("error"):
            console.print(f"[bold white]✘ {result['error']}[/bold white]")
            return 1
        print_analysis_report(result)
        stamp = now_stamp()
        out_name = build_output_filename(result["motif_name"], args.levels, stamp=stamp)
        out_path = target_path.with_name(out_name)
        write_analysis_file(result, out_path, stamp=stamp)
        console.print(f"\n[bold white]Written:[/bold white] {out_path}")
        return 0
    if target_path.is_dir():
        clear_screen()
        print_logo()
        svg_count = len(list(target_path.glob("*.svg")))
        console.print(
            f"[bold white]Toplu Analiz:[/bold white] "
            f"[bold white]{target_path.name}/[/bold white] ({svg_count} dosya)\n"
        )
        _run_batch_dir(target_path, args.levels)
        return 0
    console.print(f"[bold white]✘ Yol bulunamadı: {target}[/bold white]")
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    """Tüm dağıtım kanalları için tek giriş noktası."""
    parser = argparse.ArgumentParser(
        prog="rash-hit-fractal",
        description="RASH-HIT Fractal Analysis — pure NumPy supercover box-counting (CPU only).",
    )
    grp = parser.add_mutually_exclusive_group(required=False)
    grp.add_argument("-i", "--input", type=str, help="Input SVG file path (direct mode)")
    grp.add_argument("-d", "--dir", type=str, help="Directory of SVG files (direct batch mode)")
    parser.add_argument("-l", "--levels", type=int, default=7,
                        help="Number of grid levels (default: 7)")
    parser.add_argument("-v", "--version", action="version",
                        version=f"RASH-HIT Fractal Analysis v{VERSION} — {ENGINE_NAME}")
    parser.add_argument("--check", action="store_true",
                        help="Print environment diagnostics and exit")
    parser.add_argument("--setup", action="store_true",
                        help="No-op stub (install via `pip install rash-hit-fractal-analysis`)")

    args = parser.parse_args(argv)

    if args.check:
        clear_screen()
        print_logo()
        _print_check()
        return 0

    if args.setup:
        console.print(
            "[dim]Nothing to do: install via "
            "`pip install rash-hit-fractal-analysis`.[/dim]"
        )
        return 0

    if args.input or args.dir:
        return _direct_cli(args)

    # Varsayılan: interaktif TUI menü
    return main_menu()


if __name__ == "__main__":
    sys.exit(main())
