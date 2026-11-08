# Texypad 0.0.4 QA checklist

1. `python3 main.py --version` prints exactly `Texypad 0.0.4`.
2. Portable root contains only `README.md`, `main.py`, `suite-pythoine-component.json` and `texypad/`.
3. Open/save `.tex`, `.sty`, `.cls`, `.bib`; unsupported suffixes are rejected.
4. Window and owned-dialog titles end in `— Texypad`.
5. Ribbon tabs are File, Home, Insert, View, Help; Home is initially selected.
6. Pressing Ctrl+F in the source editor does not raise `NameError`; Texypad's Find surface opens via the QAction shortcut.
7. `Ctrl+Alt+L` opens a modeless `Command Library — Texypad` dialog.
8. Library search filters labels, categories, descriptions and insertion text.
9. Library placement can be Left Sidebar, Right Sidebar or Floating Only without altering the source/print split sizes.
10. Favourites persist in Texypad preferences.
11. Add/Edit/Remove Custom Command validates and persists custom snippets; `[[selection]]` and `[[cursor]]` behave as documented.
12. `.texypadcommands` export/import round-trips custom commands and favourites; Merge and Replace both work.
13. `.bib` files show BibTeX-specific Library entries while normal LaTeX sources show LaTeX entries.
14. Source Only stops live-preview scheduling; returning to split/preview schedules one refresh.
15. Rapid typing never creates concurrent TeX processes.
16. F5 performs one pass; Ctrl+F5 performs full build; Shift+F5 stops an active build.
17. Engine command line includes `-no-shell-escape`.
18. Failed build exposes diagnostics and retains the previous valid PDF.
19. Qt PDF preview supports Fit Width, Fit Page, 100%, zoom and continuous pages.
20. Print uses the compiled PDF and does not print source text.
21. Closing a modified document prompts before loss.
22. Temporary compilation data is removed when the window closes.


Latest exp3 scope: verify touch-friendly ribbon taps/drags, content-height ribbon sizing, and the updated TX notebook icon.


Latest exp4 menu/About scope: verify the QMenuBar is visible/exportable to Plasma global menu, all six menus retain their shared actions/shortcuts, About is modeless and one-instance, and reopening About raises the existing dialog.

- Verify `assets/icons/texypad.png` and the AppImage icon are RGBA with a genuinely transparent outer background.


Latest exp6-r1 scope: verify the new theme-aware command icon family in Ribbon and menus, including dark/light inversion and retention of the approved transparent TX notebook app icon.


Exp6-r1 startup/icon regression gate: `QKeySequence` must be imported in `app.py`; both packaged command-icon theme directories must exist and contain the full icon-key set.


AppImage dependency correction checks:
- `requirements.txt` is exactly `PyQt6>=6.8,<6.12`.
- The isolated build environment must successfully import `PyQt6.QtPdf`, `PyQt6.QtPdfWidgets`, and `PyQt6.QtPrintSupport` before PyInstaller runs.
- Final AppDir validation must still detect Qt PDF and PrintSupport libraries.
