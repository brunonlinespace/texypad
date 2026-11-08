# Texypad 0.0.4 — AppImage Qt PDF dependency correction

Texypad 0.0.4 is a narrowly scoped packaging/dependency release based on 0.0.3.

- Constrains the runtime dependency to `PyQt6>=6.8,<6.12` so the isolated AppImage build environment retains `PyQt6.QtPdf` and `PyQt6.QtPdfWidgets`.
- Adds an early Fedora builder preflight that imports `PyQt6.QtPdf`, `PyQt6.QtPdfWidgets`, and `PyQt6.QtPrintSupport` immediately after dependency installation.
- Fails before PyInstaller with a clear diagnostic if the required Qt PDF/print modules are unavailable.
- Keeps the existing PyInstaller hidden imports and final AppDir checks for Qt PDF and PrintSupport.
- Advances version identity, Suite metadata, AppStream metadata, QA, and the source manifest to 0.0.4.
- Makes no editor, compiler, preview, Command Library, Ribbon/menu, touch, global-menu, or document-handling changes.

The public repository-root `README.md` remains the GitHub front page and is changed only for the 0.0.4 version references.
