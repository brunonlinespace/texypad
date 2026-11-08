# Texypad architecture — 0.0.4

## Donor mapping

### Ricopad 0.4.1

Texypad adopts the Ribbon-only interaction model, five-tab File / Home / Insert / View / Help information architecture, compact hidden action menus, Pad-family title/dialog convention, status-bar layout concept and the preference of putting implementation beneath a two-item portable root.

### Sheepy Pad 0.2.0-r1

Texypad adopts the source-editor approach (plain source, line-number gutter, source highlighting, current-line feedback, indentation, comment toggle, line duplication and Go To Line) and the use of Qt `QProcess` for an external toolchain rather than embedding a compiler.

### Portapad 0.0.2-r2

Texypad's preview is deliberately a PDF document/view pair using Qt PDF. The print path renders each PDF page to the selected printer at bounded raster dimensions, following Portapad's print strategy.

## Command Library

The exp2 Command Library adapts Timblee Pad's searchable/favourites/custom-library model to LaTeX rather than copying HTML-tag semantics directly. Built-ins are immutable metadata; user snippets are stored in preferences and may be exported as versioned `.texypadcommands` JSON collections. `[[selection]]` and `[[cursor]]` are editor-side insertion markers only and never reach the TeX source.

The Library is outside the source/print splitter in a second horizontal workspace splitter. It can therefore be placed on the left or right, or disabled as a sidebar while remaining available in a modeless floating dialog, without changing the user's source/PDF proportions.

## Live compile state machine

1. Text changes restart a single-shot timer.
2. Source-only view stops the timer; there is no point generating an invisible live preview.
3. Timer expiry starts a single compiler process if one is not already active.
4. If edits arrive while compilation is active, Texypad records one pending replacement build rather than spawning or repeatedly killing processes.
5. On success, the new PDF replaces the visible preview.
6. On failure, diagnostics update but the last valid PDF stays loaded.
7. On close, the process is stopped, QPdfDocument is closed and the private temporary directory is removed.

## Snapshot compilation

Unsaved editor contents are written only to Texypad's private temporary build tree. The TeX process uses the actual document directory as its working directory so ordinary relative `\\input`, images and bibliography paths can continue to resolve. The user's `.tex` file is not rewritten merely to refresh preview.

## Security boundary

LaTeX is a programmable document format and compiling untrusted TeX is not equivalent to passively viewing text. Texypad disables shell escape at the engine command line. This removes the normal `\\write18` shell-execution path, but users should still treat unknown TeX sources as active input to a complex native toolchain.


The application command-icon family is a packaged static asset set. Each shared QAction carries an icon key. Texypad chooses `assets/icons/commands/light/` for light application palettes and `assets/icons/commands/dark/` for dark palettes, then applies the same icon to Ribbon and menu surfaces. The two sets deliberately invert the approved notebook-derived treatment: silver-on-dark for light themes and dark-on-silver for dark themes.


## Qt PDF build dependency

The integrated print view requires `PyQt6.QtPdf` and `PyQt6.QtPdfWidgets`. AppImage builds therefore constrain PyQt6 to `>=6.8,<6.12` and verify the PDF/PrintSupport imports before freezing. This is a packaging constraint only; TeX engines and bibliography tools remain host runtime dependencies.
