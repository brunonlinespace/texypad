# Texypad 0.0.4

Texypad is a Pad-family LaTeX editor built from the design direction established by Ricopad, Sheepy Pad and Portapad.

## Core design

- **Ricopad-style Ribbon only**: File, Home, Insert, View and Help tabs; 52×52 command surfaces with 32×32 icon area; hidden traditional menu bar; Pad-family title and dialog naming (`Document — Texypad`, `About — Texypad`).
- **Sheepy-style source behaviour**: line-numbered `QPlainTextEdit`, syntax highlighting, indentation, Ctrl+/ comments, Ctrl+D duplication, Go To Line, asynchronous external-process compilation, stop control and bounded diagnostics.
- **Portapad-style print view**: `QPdfDocument` + `QPdfView`, continuous/single-page modes, Fit Width/Fit Page/100%, Ctrl+wheel zoom, page navigation and page-by-page rendering to `QPrinter`.
- **Optional dual-sided workspace**: Source Only, Source + Print View, or Print View Only. Split mode is the default.
- **Live preview**: editing is debounced (850 ms by default), only one TeX process may run at once, newer edits queue one replacement build, and live compilation pauses when the print pane is hidden.
- **Command Library**: searchable built-in LaTeX/BibTeX catalogue, favourites, left/right/floating layouts, custom insertion snippets, and portable import/export collections. Custom snippets can use `[[selection]]` and `[[cursor]]` markers.

## Supported sources

Texypad edits `.tex`, `.sty`, `.cls` and `.bib`. Only `.tex` documents compile directly.

## TeX engines

Texypad detects host executables on `PATH` and supports:

- `pdflatex`
- `xelatex`
- `lualatex`

Compilation deliberately passes `-no-shell-escape`, `-interaction=nonstopmode`, `-file-line-error` and `-halt-on-error`. Texypad does **not** bundle a TeX distribution.

**Compile (F5)** performs one fast pass and is used by Live Preview. **Full Build (Ctrl+F5)** performs the first LaTeX pass, runs Biber or BibTeX when the generated control files call for it and the tool is installed, then performs two more LaTeX passes.

## Memory / resource behaviour

- Preview PDFs are generated in a per-window private temporary directory rather than beside the source file.
- The source pane keeps a single Qt text document and the preview keeps a single `QPdfDocument`/`QPdfView` pair.
- Live preview is debounced and never launches parallel compilers.
- Only the last three temporary build generations are retained during a window session; the whole temporary tree is removed when the window closes.
- A failed compile leaves the last valid PDF visible instead of discarding it.
- Source files are capped at 25 MiB and generated preview PDFs at 512 MiB.

## Source tree

The outer portable tree follows the Pad-family two-item convention:

```text
main.py
texypad/
```

All implementation, assets, documentation, QA and packaging helpers live under `texypad/`.

## Running from source

```bash
python3 -m pip install -r texypad/requirements.txt
python3 main.py
```

A TeX distribution is optional for editing but required for compilation/preview.

## 0.0.4 release

`0.0.4` is a narrowly scoped AppImage dependency correction. The runtime PyQt6 requirement is constrained to `>=6.8,<6.12` so the build environment retains `PyQt6.QtPdf` and `PyQt6.QtPdfWidgets`, which Texypad requires for its integrated PDF print view. The Fedora builder now verifies those modules immediately after dependency installation and fails early with a clear diagnostic if they are unavailable. Editor, compiler, PDF preview behavior, Command Library, Ribbon/menu behavior, touch behavior, Plasma/global-menu support, and document handling are otherwise unchanged from 0.0.3.

## License

GPLv3-or-later. Copyright © 2026 Bruno Machado.
