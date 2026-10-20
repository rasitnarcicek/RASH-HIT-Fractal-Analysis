# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek

"""Tests for the unified launcher entry point.

The launcher is the single source of truth for every distribution
channel (PyPI, npm, GitHub, .bat, .sh).  These tests pin the contract:

* `--version` / `-v` prints the package version.
* `--check` reports the runtime environment.
* `--setup` is a no-op stub (npm has its own pip bootstrap).
* `--input <file.svg>` runs the analysis and writes the report.
* `--dir <folder>` runs the batch analysis.
* No arguments → the launcher module's ``main`` returns 0 when stdin
  feeds "4" (Exit) into the prompt.

The interactive TUI cannot be end-to-end tested in CI, so the
non-interactive flags carry the production load.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "launcher.py"
SAMPLE_SVG = ROOT / "input_svgs" / "test.svg"


class TestLauncherCLI(unittest.TestCase):
    """Subprocess-level smoke tests for the unified entry point."""

    def _run(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(LAUNCHER), *args]
        # Python 3.14'te ardışık subprocess.run çağrılarında stdin handle
        # mirası [WinError 6]'ya yol açıyor; stdin None değilse DEVNULL
        # ile izole ediyoruz.
        stdin_arg = None if stdin is None else subprocess.DEVNULL
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            input=stdin,
            stdin=stdin_arg,
            timeout=60,
        )

    def test_version(self):
        res = self._run("--version")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("1.3.0", res.stdout)
        self.assertIn("RASH-HIT", res.stdout)

    def test_check(self):
        res = self._run("--check")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("NumPy", res.stdout)
        self.assertIn("Python", res.stdout)
        self.assertIn("OK", res.stdout)

    def test_setup_is_noop(self):
        res = self._run("--setup")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Nothing to do", res.stdout)

    def test_input_direct_mode(self):
        # v1.3.0: default is the AREA mode engine label (Studio parity).
        if not SAMPLE_SVG.exists():
            self.skipTest(f"sample SVG missing: {SAMPLE_SVG}")
        res = self._run("--input", str(SAMPLE_SVG), "--levels", "4")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Written:", res.stdout)
        # Rich wraps long Windows paths at the default 80-col terminal
        # width when the launcher runs in a subprocess, so the path
        # may be split across newlines.  Walk the lines, take the
        # segment that follows "Written:" and join subsequent lines
        # until we find a path-terminating ".txt".
        import re
        lines = res.stdout.splitlines()
        written = None
        for i, line in enumerate(lines):
            if "Written:" in line:
                tail = line.split("Written:", 1)[1].strip()
                if tail and tail.endswith(".txt"):
                    written = tail
                    break
                # Path wrapped to next line(s); keep joining until ".txt".
                chunks = [tail]
                for nxt in lines[i + 1:]:
                    chunks.append(nxt.strip())
                    joined = "".join(chunks)
                    if joined.endswith(".txt"):
                        written = joined
                        break
                if written:
                    break
        self.assertIsNotNone(written, f"no L4 stamped path in: {res.stdout!r}")
        self.assertTrue(Path(written).exists())
        body = Path(written).read_text(encoding="utf-8")
        self.assertIn("RASH-HIT", body)  # v1.3.0: AREA mode engine label
        self.assertIn("Mode      : area", body)
        self.assertIn("Fractal Dimension Db", body)

    def test_dir_batch_mode(self):
        svg_dir = ROOT / "input_svgs"
        if not svg_dir.is_dir() or not any(svg_dir.glob("*.svg")):
            self.skipTest("input_svgs folder empty or missing")
        # Capture pre-existing book files so we only assert on the new one.
        before = set(svg_dir.glob("ascii_book_L3_*.txt"))
        res = self._run("--dir", str(svg_dir), "--levels", "3")
        self.assertEqual(res.returncode, 0, res.stderr)
        # New TUI-style launcher reports success via the
        # "Toplu Analiz Tamamlandı" panel and a "Kitap raporu:" line.
        self.assertIn("Toplu Analiz Tamamlandı", res.stdout)
        self.assertIn("Kitap raporu", res.stdout)
        # The book file path is rendered through Rich which can word-wrap;
        # instead of substring-matching, verify the new book file is on disk.
        after = set(svg_dir.glob("ascii_book_L3_*.txt"))
        new_books = after - before
        self.assertTrue(new_books, "no new ascii_book_L3_*.txt produced")
        book = next(iter(new_books))
        self.assertTrue(book.exists() and book.stat().st_size > 0)


class TestLauncherImport(unittest.TestCase):
    """Pure import / unit tests for the launcher module."""

    def test_engine_name_is_consistent(self):
        # The launcher and the ASCII exporter must report the same engine
        # name — every channel ends up writing this into the report header.
        from launcher import ENGINE_NAME
        from src.backend.ascii_exporter import ENGINE_NAME as ASCII_ENGINE
        self.assertEqual(ENGINE_NAME, ASCII_ENGINE)
        self.assertEqual(ENGINE_NAME, "RASH-HIT Fractal Analysis Engine")

    def test_help_lists_known_flags(self):
        res = subprocess.run(
            [sys.executable, str(LAUNCHER), "--help"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(ROOT), timeout=30,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        for flag in ("--input", "--dir", "--levels", "--version", "--check", "--setup"):
            self.assertIn(flag, res.stdout)


if __name__ == "__main__":
    unittest.main()
