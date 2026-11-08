<p align="center">
  <a href="https://github.com/brunonlinespace/texypad">
    <img
      src="texypad/assets/icons/texypad.png"
      alt="Texypad"
      width="256"
    >
  </a>
</p>

# Texypad

**Friendly. Fast. Focused.**

Texypad is a focused **LaTeX and BibTeX editor** built with Python and PyQt6. It combines source-oriented editing with an integrated PDF print view, host TeX compilation, a searchable LaTeX/BibTeX Command Library, and the familiar Ribbon-driven interface used across the Pad family.

Current release: **0.0.4**

Repository: <https://github.com/brunonlinespace/texypad>

> [!IMPORTANT]
> **Texypad is still early-stage software and has not yet been extensively tested.**
>
> Version 0.0.4 passes the project's included static, unit and GUI smoke checks, but it has not yet been exercised broadly across the full range of real-world LaTeX classes, packages, bibliography setups, TeX distributions, document sizes, desktop environments, or operating-system configurations. Expect rough edges and compatibility gaps. Keep backups of important documents and, for now, treat Texypad as a developing editor rather than a proven production LaTeX environment.

## What Texypad is

Texypad is intended to sit between a plain source editor and a full LaTeX IDE.

It edits ordinary `.tex`, `.sty`, `.cls` and `.bib` files directly and does not introduce a private document format. For `.tex` documents, Texypad can compile the current source using a TeX engine installed on the host system and display the generated PDF beside the source editor.

The default workspace is dual-sided:

```text
Source editor  |  Print view
```

The workspace can also be switched to **Source Only** or **Print View Only**.

Texypad deliberately relies on the user's existing TeX toolchain. It does **not** bundle TeX Live, MiKTeX, MacTeX, LaTeX packages, Biber or BibTeX.

## Highlights

- Dedicated editing for `.tex`, `.sty`, `.cls` and `.bib` source files.
- Integrated **Source + Print View** workspace with a resizable split.
- Live PDF preview using Qt's `QPdfDocument` and `QPdfView`.
- Host compilation through **pdfLaTeX**, **XeLaTeX** or **LuaLaTeX**.
- Quick single-pass Compile and a fuller multi-pass build workflow.
- Automatic **Biber** or **BibTeX** stage during Full Build when the generated control files require one and the corresponding host tool is available.
- LaTeX/BibTeX syntax highlighting and line numbers.
- Find, Replace, Go To Line, Toggle Comment and Duplicate Line / Selection.
- Direct insertion helpers for sections, emphasis, maths, lists, figures, tables, citations, references and labels.
- Searchable **Command Library** with **55 built-in entries** across document setup, structure, text, maths, lists, floats/tables, references/links, layout and BibTeX.
- Persistent Library **Favourites** and user-defined custom commands/snippets.
- Custom snippets can use `[[selection]]` and `[[cursor]]` markers.
- Portable `.texypadcommands` Library import/export.
- Command Library placement as **Left Sidebar**, **Right Sidebar**, or **Floating Only**.
- Optional **Document Outline** for LaTeX section navigation.
- Compiler diagnostics with bounded captured output.
- PDF Fit Width, Fit Page, 100%, zoom controls, continuous-page view and printing.
- Export of the latest successfully compiled PDF.
- **122 packaged command icons**: 61 light-theme variants and 61 dark-theme variants.
- Touch-aware horizontally pannable Ribbon.
- Native application menu retained for desktop/global-menu integration, including KDE Plasma.
- Pad-family About dialog, title-bar conventions and application identity.

## Interface

Texypad provides both a native application menu and a Ribbon built from the same shared actions.

The application menu is:

**File · Edit · Build · Insert · View · Help**

The Ribbon uses:

**File · Home · Insert · View · Help**

### File

The file workflow includes:

- New
- Open…
- New Window
- Save
- Save As…
- Rename…
- Open Containing Folder
- Export Compiled PDF…
- Print…
- Save and Exit
- Exit

### Edit

Editing commands include:

- Undo / Redo
- Cut / Copy / Paste
- Select All
- Find
- Replace…
- Go To Line…
- Duplicate Line / Selection
- Toggle Comment

### Build

- **Compile** — one LaTeX pass
- **Full Build** — LaTeX pass 1, optional Biber/BibTeX, then LaTeX passes 2 and 3
- **Stop Compile**
- **Live Preview**
- **Diagnostics**

### Insert

Texypad provides direct insertion commands for common LaTeX structures, including:

- Section / Subsection / Subsubsection
- Label / Reference / Citation
- Bold / Emphasis
- Inline Math / Display Math / Fraction
- Itemized List / Numbered List
- Figure / Table
- Command Library
- Custom Command creation
- Command import/export

### View

View controls include:

- Source Only
- Source + Print View
- Print View Only
- Line Numbers
- Word Wrap
- Continuous Pages
- Fit Width / Fit Page
- Zoom controls
- Document Outline
- Editing Field Theme
- Command Library placement

## Source and print view

The integrated PDF pane is intended to make ordinary LaTeX editing feel immediate without replacing the TeX toolchain itself.

Live Preview is debounced rather than launching a compiler for every keystroke. Only one compilation process is allowed to run at a time; edits made while a build is active can queue a replacement preview instead of starting parallel compilers.

A failed compilation leaves the last valid PDF visible rather than discarding it.

Preview PDFs are built inside a private per-window temporary directory and are removed with the temporary build tree when the window closes.

## TeX engines and compilation

Texypad looks for these executables on the host `PATH`:

- `pdflatex`
- `xelatex`
- `lualatex`

The selected engine is launched with:

```text
-interaction=nonstopmode
-file-line-error
-halt-on-error
-no-shell-escape
```

The explicit `-no-shell-escape` policy is intentional.

**Compile (`F5`)** performs a single LaTeX pass and is also the basis of Live Preview.

**Full Build (`Ctrl+F5`)** performs:

1. LaTeX pass 1;
2. Biber when a `.bcf` is produced and `biber` is available, otherwise BibTeX when the generated `.aux` requests bibliography data and `bibtex` is available;
3. LaTeX pass 2;
4. LaTeX pass 3.

Texypad does not attempt to install missing engines, bibliography tools or LaTeX packages.

## Command Library

The Command Library is a reusable LaTeX/BibTeX insertion surface rather than a code generator or validator.

Built-in entries are grouped into:

- Document
- Structure
- Text
- Math
- Lists
- Floats & Tables
- References & Links
- Layout
- BibTeX

The current built-in catalogue contains **55 entries**.

Users can add custom snippets with a name, category, description, source scope and insertion template. Two special markers are supported:

```text
[[selection]]
[[cursor]]
```

`[[selection]]` is replaced with the editor's current selection. `[[cursor]]` marks the final caret position after insertion.

Custom Library data and favourites are stored in Texypad's preferences. Collections can also be exported and imported as `.texypadcommands` files.

## PDF view and printing

Texypad uses Qt PDF components for its integrated print view.

Available controls include:

- Continuous or single-page presentation
- Fit Width
- Fit Page
- 100% / zoom controls
- Page navigation
- PDF printing through Qt PrintSupport
- Export of the most recent successfully compiled PDF

Generated preview PDFs are limited to **512 MiB**.

## File handling

Texypad accepts source files up to **25 MiB** with these extensions:

```text
.tex
.sty
.cls
.bib
```

Only `.tex` documents compile directly.

Source documents remain ordinary files on disk. Texypad's editing and preview architecture does not embed them into a project database or proprietary workspace format.

## Keyboard shortcuts

Common shortcuts include:

| Action | Shortcut |
| --- | --- |
| New | `Ctrl+N` |
| Open | `Ctrl+O` |
| Save | `Ctrl+S` |
| Save As | `Ctrl+Shift+S` |
| New Window | `Ctrl+Shift+N` |
| Print | `Ctrl+P` |
| Find | `Ctrl+F` |
| Replace | `Ctrl+H` |
| Go To Line | `Ctrl+G` |
| Duplicate Line / Selection | `Ctrl+D` |
| Toggle Comment | `Ctrl+/` |
| Section | `Ctrl+1` |
| Subsection | `Ctrl+2` |
| Subsubsection | `Ctrl+3` |
| Bold | `Ctrl+B` |
| Emphasis | `Ctrl+I` |
| Inline Math | `Ctrl+M` |
| Display Math | `Ctrl+Shift+M` |
| Compile | `F5` |
| Full Build | `Ctrl+F5` |
| Stop Compile | `Shift+F5` |
| Command Library | `Ctrl+Alt+L` |
| Diagnostics | `Ctrl+`` |
| Documentation | `F1` |
| Exit | `Ctrl+Q` |

The in-application **Help → Keyboard Shortcuts** dialog is the better reference for the complete current set.

## Running from source

Texypad requires **Python 3** and **PyQt6 6.8 or later, below PyQt6 7**.

The source-portable layout is:

```text
main.py
suite-pythoine-component.json
texypad/
```

From the extracted source root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r texypad/requirements.txt
python3 main.py
```

Useful launch forms include:

```bash
python3 main.py --version
python3 main.py document.tex
python3 main.py references.bib
```

A TeX distribution is optional for source editing but required for compilation and PDF preview generation.

For example, Texypad can use a host installation that provides one or more of:

```text
pdflatex
xelatex
lualatex
biber
bibtex
```

## Building the AppImage

Texypad includes a non-privileged Fedora AppImage builder:

```bash
bash texypad/packaging/fedora/build-appimage.sh
```

The current builder is validated for **Fedora 43/44** on native **x86_64** and **aarch64** hosts. It does not invoke `sudo`, `dnf`, `su` or `pkexec`.

The builder creates an isolated Python environment, runs the source-release checks, freezes Texypad with PyInstaller, assembles the AppDir, validates application metadata and the required Qt PDF/PrintSupport payload, then performs exact-version and off-screen GUI smoke tests against the source, frozen executable, AppDir and finished AppImage.

TeX engines and bibliography tools remain external host dependencies and are not bundled into the AppImage.

Do not normally run the builder as root.

## Validation

The source tree includes a release/static QA entrypoint:

```bash
bash texypad/qa/static-qa.sh
```

It checks application/version identity, the portable source layout, core UI contracts, TeX-engine safety flags, supported file types, Qt PDF/PrintSupport dependencies, command-icon completeness, Suite Pythoine metadata, packaging contracts, source-manifest integrity, Python syntax and the included unit tests.

These checks are useful regression guards, but they are **not a substitute for broad real-world LaTeX testing**.

## Testing status and known maturity

Texypad 0.0.4 should be considered **young software**.

The project has automated checks for important source, packaging and startup contracts, but the editor has **not yet been extensively tested in day-to-day LaTeX use**. In particular, broad coverage is still limited for areas such as:

- large or long-lived LaTeX projects;
- unusual document classes and package combinations;
- complex multi-file document trees;
- bibliography configurations beyond common Biber/BibTeX flows;
- uncommon TeX-engine or distribution setups;
- very large generated PDFs;
- edge cases in compiler diagnostics;
- long editing sessions and repeated live-preview rebuilds;
- desktop environments and operating systems beyond the currently exercised development/packaging setups.

There may be compiler, preview, file-handling or UI edge cases that have not yet been discovered.

If you use Texypad for important work, keep the source under version control or maintain independent backups, and verify the generated output with the TeX tools you already trust.

Bug reports and reproducible examples are particularly useful while the application matures.

## Configuration

On Linux, Texypad stores preferences at:

```text
~/.config/brunonlinespace/texypad/texypad.json
```

On Windows, the source code uses:

```text
%APPDATA%\brunonlinespace\Texypad\texypad.json
```

Preferences include the selected view mode and TeX engine, Live Preview settings, line numbers, word wrap, PDF-view options, splitter position, Document Outline/Diagnostics visibility, editing-field theme, Command Library placement, favourites and custom commands.

Edited LaTeX/BibTeX documents remain external files and are not stored inside the preferences file.

## Scope

Texypad is a **focused LaTeX/BibTeX source editor with an integrated compiled-PDF view**.

It is not intended to replace the TeX distribution itself. It does not install TeX engines or LaTeX packages, provide a package manager, bundle a complete TeX environment, or turn LaTeX documents into a private workspace format.

More advanced IDE-style features should not be assumed unless they are explicitly implemented and documented in the source.

## License

Texypad is licensed under the **GNU General Public License v3.0 or later**.

See `texypad/LICENSE` for the complete license text.

## Links

- Texypad: <https://github.com/brunonlinespace/texypad>
- Issues: <https://github.com/brunonlinespace/texypad/issues>
- GitHub profile: <https://github.com/brunonlinespace/>

Copyright © 2026 Bruno Machado.
