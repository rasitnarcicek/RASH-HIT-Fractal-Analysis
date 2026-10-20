# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""
tui.py — Console Text User Interface (TUI) for RASH-HIT Fractal Analysis.

Ana proje kalıbı: borderless flat layout, Rich Panel tabanlı seçim menüleri,
``os.system('cls')`` ile güvenilir ekran temizleme, ctypes ile Windows
Virtual Terminal modu açma. Bu yapı ana projedeki (``src/backend/tui.py``)
birebir kalıptır; sadece ``print_logo`` alt yazısı ve ``add_back`` etiket
Türkçeleştirilmiştir.

Bu sürüm (v1.2.0) tek motor (CPU + saf NumPy supercover) içerdiğinden ana
menü 3 seçenekle sınırlıdır:

  1. Analiz Modu (tekli SVG / toplu klasör)
  2. Sistem Bilgisi
  3. Çıkış
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import msvcrt  # type: ignore
except ImportError:  # POSIX
    msvcrt = None

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

console = Console()
try:
    from src.backend import __version__ as APP_VERSION, __engine_name__ as ENGINE_NAME
except Exception:  # pragma: no cover
    APP_VERSION = "1.2.1"
    ENGINE_NAME = "RASH-HIT Fractal Analysis Engine"

ACCENT = "white"
ACCENT2 = "white"
NAV_BACK = -2

LOGO_LINES = [
    "██████╗  █████╗ ███████╗██╗  ██╗      ██╗  ██╗██╗████████╗",
    "██╔══██╗██╔══██╗██╔════╝██║  ██║      ██║  ██║██║╚══██╔══╝",
    "██████╔╝███████║███████╗███████║█████╗███████║██║   ██║   ",
    "██╔══██╗██╔══██║╚════██║██╔══██║╚════╝██╔══██║██║   ██║   ",
    "██║  ██║██║  ██║███████║██║  ██║      ██║  ██║██║   ██║   ",
    "╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝      ╚═╝  ╚═╝╚═╝   ╚═╝   ",
]

LOGO_ASCII = "\n".join(LOGO_LINES)


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

def _enable_ansi() -> bool:
    """Best-effort enable of Windows Virtual Terminal processing (colors).

    Clearing the screen does NOT depend on this succeeding — Windows ``cls``
    is always available. This only affects whether Rich's ANSI color codes
    are interpreted by an old conhost that has VT disabled by default.
    """
    if os.name != "nt":
        return True
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
        ok = True
        for handle in (-11, -10):  # STD_OUTPUT_HANDLE, STD_INPUT_HANDLE
            h = kernel32.GetStdHandle(handle)
            if not h or h == ctypes.c_void_p(-1).value:
                ok = False
                continue
            mode = ctypes.c_uint32(0)
            if not kernel32.GetConsoleMode(h, ctypes.byref(mode)):
                ok = False
                continue
            extra = ENABLE_VIRTUAL_TERMINAL_INPUT if handle == -10 else 0
            if not kernel32.SetConsoleMode(
                h, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING | extra
            ):
                ok = False
        return ok
    except Exception:
        return False


def _sep(width: int = 56) -> None:
    w = min(width, max(20, console.width - 4))
    pad = max(0, (console.width - w) // 2)
    console.print(" " * pad + f"[dim {ACCENT2}]{'─' * w}[/dim {ACCENT2}]")


# ---------------------------------------------------------------------------
# Logo & screen
# ---------------------------------------------------------------------------

def print_logo() -> None:
    """Renders the RASH-HIT ASCII logo in pure white (modern academic style)."""
    max_w = max((len(ln) for ln in LOGO_LINES), default=0)
    pad = max(0, (console.width - max_w) // 2)
    for line in LOGO_LINES:
        console.print(" " * pad + f"[bold white]{line}[/bold white]")
    console.print(
        f"[bold white]F R A C T A L   A N A L Y S I S   v{APP_VERSION}[/bold white]",
        justify="center",
    )
    console.print(
        f"[dim white]Fractal Dimension Analysis with {ENGINE_NAME}[/dim white]",
        justify="center",
    )
    console.print("")


def clear_screen() -> None:
    """Clears the terminal reliably (ana proje kalıbı + Git Bash fix).

    Ana proje kalıbı (tui.py:101): önce ``os.system('cls')`` dene; başarısız
    olursa ANSI escape fallback.  Bu, cmd.exe konsolunda sorunsuz çalışır.

    Git Bash / MSYS2 fix: mintty penceresinde ``os.system('cls')`` sadece
    form-feed (``\\x0c``) döner ve ekranı temizlemez.  Bu durumda
    ``os.system('clear')`` (POSIX clear komutu) doğru ANSI escape'leri
    üretir ve terminali gerçekten temizler.  ``MSYSTEM=MINGW64`` env
    değişkeni Git Bash'i güvenilir şekilde tespit eder.
    """
    _enable_ansi()  # best-effort: enable colors; clearing does not depend on it
    is_git_bash = os.name == "nt" and (
        os.environ.get("MSYSTEM", "").startswith("MINGW")
        or os.environ.get("MSYSTEM", "").startswith("MSYS")
    )
    cleared = False
    try:
        if is_git_bash:
            # Git Bash mintty: POSIX ``clear`` komutu escape'leri
            # doğru şekilde mintty'ye yazar (cls çalışmaz).
            os.system("clear")
        elif os.name == "nt":
            os.system("cls")
        else:
            os.system("clear")
        cleared = True
    except Exception:
        pass
    if not cleared:
        try:
            sys.stdout.write("\x1b[2J\x1b[H")
            sys.stdout.flush()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Single-key reader
# ---------------------------------------------------------------------------

def get_key() -> str:
    """Reads a single key press interactively (cross-platform).

    POSIX fallback: ``sys.stdin.read(1)`` (numerik menü için).
    Windows: ``msvcrt.getch``; arrow keys ve ESC doğru çözümlenir.
    """
    if os.name == "nt":
        if msvcrt is None:
            try:
                return sys.stdin.read(1)
            except Exception:
                return ""
        # Carry-over tuşları temizle
        try:
            while msvcrt.kbhit():
                msvcrt.getch()
        except Exception:
            pass
        try:
            ch = msvcrt.getch()
        except Exception:
            try:
                return sys.stdin.read(1)
            except Exception:
                return ""
        if ch in (b"\x00", b"\xe0"):  # arrow-key prefix
            ch2 = msvcrt.getch()
            if ch2 == b"H":
                return "up"
            if ch2 == b"P":
                return "down"
            if ch2 == b"K":
                return "left"
            if ch2 == b"M":
                return "right"
        if ch == b"\r":
            return "enter"
        if ch == b"\x1b":
            return "escape"
        if ch == b" ":
            return "space"
        try:
            return ch.decode("utf-8", errors="ignore").lower()
        except Exception:
            return ""

    # POSIX
    import tty
    import termios
    fd = sys.stdin.fileno()
    try:
        old_settings = termios.tcgetattr(fd)
    except Exception:
        try:
            return sys.stdin.read(1)
        except Exception:
            return ""
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(ch3, ch3)
            return "escape"
        if ch in ("\r", "\n"):
            return "enter"
        if ch == " ":
            return "space"
        return ch.lower()
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

def _render_menu_panel(title: str, opts: List[str], idx: int, has_back: bool) -> None:
    """Render the menu options inside a Rich Panel (ana proje kalıbı)."""
    table = Table(
        box=box.SIMPLE, show_header=False, show_footer=False,
        padding=(0, 1), expand=False, border_style="white",
    )
    table.add_column("opt", justify="left", no_wrap=True)
    for i, opt in enumerate(opts):
        if i == idx:
            table.add_row(Text(f"▸ {opt}", style="bold reverse"))
        elif i == len(opts) - 1 and has_back:
            table.add_row(Text(f"  {opt}", style="dim"))
        else:
            table.add_row(Text(f"  {opt}", style="white"))
    panel = Panel(
        table,
        border_style=ACCENT,
        padding=(0, 1),
        title=f"[bold {ACCENT}]{title}[/bold {ACCENT}]",
        subtitle="[dim]↑/↓ select · ENTER confirm · ESC exit[/dim]",
    )
    console.print(panel)


def _read_numeric_choice(n: int) -> Tuple[str, int]:
    """Read a numeric choice from stdin. kind ∈ {'index','back','exit','noop'}."""
    try:
        raw = input("Seçiminiz: ").strip()
    except (KeyboardInterrupt, EOFError):
        return ("exit", -1)
    if not raw:
        return ("noop", -1)
    low = raw.lower()
    if low in ("q", "exit", "cikis", "iptal", "cancel", "esc", "0"):
        return ("exit", -1)
    if low in ("b", "back", "geri"):
        return ("back", -1)
    if low.isdigit():
        v = int(low)
        if 1 <= v <= n:
            return ("index", v - 1)
    return ("noop", -1)


def select_from_menu(title: str, options: List[str], preselected_idx: int = 0,
                     add_back: bool = False, escape_action: str = "exit",
                     clear: bool = True) -> int:
    """Interactive menu with up/down + ENTER + ESC (ana proje kalıbı).

    TTY: ok tuşu navigasyonu + ENTER; her seçim değişiminde
    ``clear_screen() + _render_menu_panel`` ile TAMAMEN yeniden çiz.
    Non-TTY: numerik menü fallback.

    escape_action: 'exit' -> ESC/q uygulamadan çıkar (üst düzey menüler)
                   'back' -> ESC/q NAV_BACK döner (alt menüler)
    """
    opts = list(options)
    if add_back:
        opts.append("↩ Ana Menüye Dön")
    n = len(opts)
    idx = preselected_idx if 0 <= preselected_idx < n else 0

    def _render() -> None:
        if clear:
            clear_screen()
            print_logo()
        _render_menu_panel(title, opts, idx, add_back)

    _render()

    # TTY modu: ok tuşu + numerik (hybrid). Ana proje kalıbı: her ok
    # basışında full redraw — cursor math yok, yarış yok. Non-TTY
    # fallback YOK (ana proje de yok); subprocess/stdin pipe senaryosunda
    # menü test edilemez, doğrudan --input/--dir kullanılır.
    while True:
        key = get_key()
        if key == "up":
            idx = (idx - 1) % n
        elif key == "down":
            idx = (idx + 1) % n
        elif key in ("enter", "space"):
            if add_back and idx == n - 1:
                return NAV_BACK
            return idx
        elif key in ("escape", "q"):
            if escape_action == "back":
                return NAV_BACK
            sys.exit(0)
        elif key.isdigit():
            # Numerik moddan gelen sayı tuşu
            v = int(key)
            if 1 <= v <= n:
                if add_back and v == n:
                    return NAV_BACK
                return v - 1
        else:
            continue
        # Tam redraw: ana proje kalıbı
        if clear:
            clear_screen()
        _render()


# ---------------------------------------------------------------------------
# Prompts (TTY'de de numerik olarak çalışır)
# ---------------------------------------------------------------------------

def _clean_prompt_input(raw: str) -> str:
    """Strip stray ESC/arrow-key sequences from raw input() text.

    Terminal bazen ok tuşu basışlarını stdin'e sızdırır (özellikle prompt
    içinde yanlışlıkla yukarı/aşağı basılırsa). Bu durumda raw string
    ``\\x1b[A`` veya ``^[[A`` gibi bir kalıntı içerir. Bunları temizle.
    """
    if not raw:
        return raw
    # ESC veya ANSI CSI başlangıcı varsa, oradan satır sonuna kadar at
    if "\x1b" in raw:
        raw = raw.split("\x1b", 1)[0]
    # Kontrol karakterlerini (CR, LF hariç) sil
    return "".join(c for c in raw if c == "\t" or (c.isprintable()))


def prompt_levels(default: int = 7, lo: int = 1, hi: int = 50) -> int:
    """Ask the user for the number of grid levels. 0 = cancel.

    Ana proje kalıbı: prompt'un BAŞINDA clear_screen + print_logo çağrılır;
    üst menüden temiz ekran + logo ile devralır. 0 = cancel.

    İptal (q / 0) veya Ctrl+C durumunda ekran temizlenir + logo tekrar
    basılır, böylece launcher'ın ``continue`` sonrası ``select_from_menu``
    temiz bir arka planla yeni paneli basar (üst üste binme olmaz).
    """
    clear_screen()
    print_logo()
    console.print(f"\n[bold white]Analiz seviye sayısını girin ({lo}-{hi}):[/bold white]")
    console.print(f"[dim]Varsayılan: {default} | İptal için 'q' veya '0'.[/dim]")
    while True:
        try:
            raw = _clean_prompt_input(input("Seviyeler: ")).strip()
        except (KeyboardInterrupt, EOFError):
            clear_screen()
            print_logo()
            return 0
        if not raw:
            return default
        if raw.lower() in ("q", "exit", "cikis", "iptal", "back", "cancel", "esc", "0"):
            clear_screen()
            print_logo()
            return 0
        try:
            val = int(raw)
        except ValueError:
            console.print(f"[bold white]Geçersiz giriş: {raw}[/bold white]\n")
            continue
        if lo <= val <= hi:
            return val
        console.print(f"[bold white]Seviye {lo}..{hi} aralığında olmalı (girilen: {val}).[/bold white]\n")


def prompt_svg_file() -> Optional[Path]:
    """Prompt for a single .svg file path. None = cancelled.

    Ana proje kalıbı: prompt'un BAŞINDA clear_screen + print_logo çağrılır.
    Üst menüden gelen ekran temizlenir, logo + mesaj + input prompt basılır.
    while True döngüsü sadece input alır; her seferinde clear çağırmaz.

    İptal (q) veya Ctrl+C durumunda ekran temizlenir + logo tekrar
    basılır; launcher'ın ``if not svg_file: continue`` dalı sonrası
    üst menü yeni temiz arka plana basılır (üst üste binme olmaz).
    """
    clear_screen()
    print_logo()
    console.print("\n[bold white]SVG dosyasının tam yolunu girin:[/bold white]")
    console.print("[dim]İptal için 'q' yazın.[/dim]")
    while True:
        try:
            raw = _clean_prompt_input(input("Dosya Yolu: ")).strip().strip("\"'")
        except (KeyboardInterrupt, EOFError):
            clear_screen()
            print_logo()
            return None
        if not raw:
            continue
        if raw.lower() in ("q", "exit", "cikis", "iptal", "back", "cancel", "esc", "0"):
            clear_screen()
            print_logo()
            return None
        p = Path(raw).expanduser()
        if p.exists() and p.is_file() and p.suffix.lower() == ".svg":
            return p
        console.print(f"[bold white]Hata: Geçersiz dosya yolu veya SVG değil: {raw}[/bold white]\n")


def prompt_svg_folder() -> Optional[Path]:
    """Prompt for a folder of .svg files. None = cancelled.

    Ana proje kalıbı: prompt'un BAŞINDA clear_screen + print_logo çağrılır.

    İptal (q) veya Ctrl+C durumunda ekran temizlenir + logo tekrar
    basılır; launcher'ın ``if not folder: continue`` dalı sonrası üst
    menü yeni temiz arka plana basılır (üst üste binme olmaz).
    """
    clear_screen()
    print_logo()
    console.print("\n[bold white]SVG klasörünün tam yolunu girin:[/bold white]")
    console.print("[dim]İptal için 'q' yazın.[/dim]")
    while True:
        try:
            raw = _clean_prompt_input(input("Klasör Yolu: ")).strip().strip("\"'")
        except (KeyboardInterrupt, EOFError):
            clear_screen()
            print_logo()
            return None
        if not raw:
            continue
        if raw.lower() in ("q", "exit", "cikis", "iptal", "back", "cancel", "esc", "0"):
            clear_screen()
            print_logo()
            return None
        p = Path(raw).expanduser()
        if p.exists() and p.is_dir():
            if any(p.glob("*.svg")):
                return p
            console.print(f"[bold white]Bu klasörde SVG dosyası bulunamadı: {raw}[/bold white]\n")
            continue
        console.print(f"[bold white]Hata: Geçersiz klasör yolu: {raw}[/bold white]\n")


def wait_for_enter() -> None:
    """Block until the user presses ENTER (used to gate menu returns)."""
    console.print("\n[dim white]Ana menüye dönmek için ENTER tuşuna basın...[/dim white]")
    try:
        input("")  # Python 3: prompt="" → sessiz stdin okuma
    except (KeyboardInterrupt, EOFError):
        pass


# ---------------------------------------------------------------------------
# Result summary
# ---------------------------------------------------------------------------

def print_result_summary(result: dict) -> None:
    """Renders the analysis summary table for a single SVG."""
    table = Table(
        box=box.SQUARE, safe_box=True, padding=(0, 2),
        header_style="bold white on black", border_style="white",
    )
    table.add_column("Metric", style="white bold")
    table.add_column("Value", style="white bold")
    table.add_row("Motif", f"[bold white]{result.get('motif_name', '?')}[/bold white]")
    table.add_row("Status", f"[bold white]{result.get('status', 'OK')}[/bold white]")
    db = result.get("fractal_dimension")
    r2 = result.get("r_squared")
    if db is not None:
        table.add_row("Fractal Dimension (Db)", f"[bold white]{db:.4f}[/bold white]")
    if r2 is not None:
        table.add_row("Regression Fit (R²)", f"[bold white]{r2:.4f}[/bold white]")
    if result.get("total_time_ms") is not None:
        table.add_row("Total Analysis Time", f"{result['total_time_ms']:.2f} ms")
    if result.get("output_path"):
        table.add_row("Output File", f"[dim]{result['output_path']}[/dim]")

    console.print("")
    console.print("[bold white] Analysis Result Summary [/bold white]")
    console.print(table)
    console.print("")


def show_system_information(rows: list) -> None:
    """Render a system information table."""
    table = Table(
        title="[bold white]Hardware & Runtime Environment[/bold white]",
        box=box.SQUARE, safe_box=True, padding=(0, 2),
        header_style="bold white on black", border_style="white",
    )
    table.add_column("Property", style="bold white", width=24)
    table.add_column("Specification", style="white", width=50)
    for k, v in rows:
        table.add_row(k, str(v))
    console.print("")
    console.print(table)
    console.print("")


def info_panel(title: str, body: str) -> None:
    """Print a single bordered message panel (ana proje kalıbı).

    Used by launcher for hata / başarı bildirimleri — Rich Panel tabanlı,
    borderless olmayan bir kutu.  Body zengin metin (rich markup) içerir.
    """
    console.print("")
    console.print(
        Panel(
            Text.from_markup(body),
            border_style="white",
            padding=(0, 2),
            title=f"[bold white]{title.strip()}[/bold white]",
            title_align="left",
        )
    )
    console.print("")
