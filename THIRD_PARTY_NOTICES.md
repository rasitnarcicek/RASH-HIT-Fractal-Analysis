# Third-Party Notices & Dependencies

RASH-HIT Fractal Analysis relies on third-party open-source computational software libraries. This document lists all dependencies, their licenses, and usage context.

---

## 1. Numerical Computation

### NumPy
- **Project**: NumPy
- **License**: BSD 3-Clause License
- **Usage**: The sole numerical dependency of the pure NumPy supercover engine (v1.2.0): fixed-point int64 lattice conversion, exact Liang-Barsky segment-box intersection, supercover cell set construction, and least-squares regression fitting. Runs entirely on the CPU — no GPU requirement.

---

## 2. SVG Parsing & Security

### tinycss2
- **Project**: tinycss2
- **License**: BSD 3-Clause License
- **Usage**: Used for parsing SVG inline and block CSS style declarations.

### defusedxml
- **Project**: defusedxml
- **License**: Python Software Foundation License (PSFL)
- **Usage**: Used for secure XML parsing hardened against XML entity expansion (XXE) vulnerabilities.

---

## 3. Terminal User Interface

### rich
- **Project**: rich
- **License**: MIT License
- **Usage**: Terminal UI rendering for the interactive launcher (`launcher.py`): menu panels, the RASH-HIT ASCII logo, progress tables, environment checks, and analysis summaries.
