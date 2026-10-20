# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek

import subprocess
import sys
import unittest
from pathlib import Path


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.root_dir = Path(__file__).resolve().parent.parent
        self.script_path = self.root_dir / "run_analysis.py"
        self.sample_svg = self.root_dir / "input_svgs" / "test.svg"

    def test_cli_help(self):
        res = subprocess.run(
            [sys.executable, str(self.script_path), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(self.root_dir),
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("RASH-HIT Fractal Analysis", res.stdout)
        self.assertIn("--input", res.stdout)
        self.assertIn("--dir", res.stdout)

    def test_cli_version(self):
        res = subprocess.run(
            [sys.executable, str(self.script_path), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(self.root_dir),
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("1.3.0", res.stdout)

    def test_cli_single_file(self):
        res = subprocess.run(
            [sys.executable, str(self.script_path), "--input", str(self.sample_svg), "--levels", "5"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(self.root_dir),
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(res.returncode, 0)
        # CLI must write the ASCII report to disk and announce it
        self.assertIn("Written:", res.stdout)
        # The report file should contain the standard sections
        import re
        # Rich wraps long Windows paths in subprocess capture (default
        # 80-col terminal width), so the path may be split across lines.
        # Walk the lines, take the segment after "Written:" and join
        # subsequent lines until we find a path-terminating ".txt".
        lines = res.stdout.splitlines()
        written_path = None
        for i, line in enumerate(lines):
            if "Written:" in line:
                tail = line.split("Written:", 1)[1].strip()
                if tail and tail.endswith(".txt"):
                    written_path = tail
                    break
                chunks = [tail]
                for nxt in lines[i + 1:]:
                    chunks.append(nxt.strip())
                    joined = "".join(chunks)
                    if joined.endswith(".txt"):
                        written_path = joined
                        break
                if written_path:
                    break
        self.assertIsNotNone(written_path, f"no L5 stamped path in: {res.stdout!r}")
        self.assertTrue(Path(written_path).exists())
        body = Path(written_path).read_text(encoding="utf-8")
        self.assertIn("Fractal Dimension Db", body)
        self.assertIn("R2", body)
        self.assertIn("ASCII OCCUPANCY REPORT", body)

    def test_cli_batch_dir(self):
        svg_dir = self.root_dir / "input_svgs"
        before = set(svg_dir.glob("ascii_book_L3_*.txt"))
        res = subprocess.run(
            [sys.executable, str(self.script_path), "--dir", str(svg_dir), "--levels", "3"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(self.root_dir),
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(res.returncode, 0)
        # The new TUI-style launcher reports success via the "Toplu Analiz
        # Tamamlandı" panel and a "Kitap raporu:" line; both are present.
        self.assertIn("Toplu Analiz Tamamlandı", res.stdout)
        self.assertIn("Kitap raporu", res.stdout)
        # Book file rendered through Rich may be word-wrapped; assert on
        # the new book file being on disk rather than substring in stdout.
        after = set(svg_dir.glob("ascii_book_L3_*.txt"))
        new_books = after - before
        self.assertTrue(new_books, "no new ascii_book_L3_*.txt produced")
        self.assertIn("test", res.stdout)


if __name__ == "__main__":
    unittest.main()
