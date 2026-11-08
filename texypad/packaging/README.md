# Packaging

`fedora/build-appimage.sh` is the canonical non-privileged Fedora AppImage builder for Texypad 0.0.4. It is validated for Fedora 43/44 on native x86_64 and aarch64 hosts and never invokes `sudo`, `dnf`, `su` or `pkexec`.

Python runtime and build dependencies are installed only into an isolated build virtual environment. The builder validates source metadata and QA, freezes with PyInstaller, assembles the AppDir, validates Desktop/AppStream metadata and the required Qt payload, then runs version and off-screen GUI smoke tests against the source, frozen executable, AppDir and finished AppImage.

Texypad genuinely requires `PyQt6.QtPdf`, `PyQt6.QtPdfWidgets` and Qt PrintSupport because its compiled-document view reads and prints PDF output. TeX engines (`pdflatex`, `xelatex`, `lualatex`) and bibliography tools (`biber`, `bibtex`) remain host runtime tools discovered by Texypad and are deliberately not installed or bundled by the AppImage builder.

The 0.0.4 source contract also requires the public repository-root `README.md`; the AppImage continues to bundle `texypad/README.md` as its internal application documentation.

Texypad 0.0.4 constrains PyQt6 to `>=6.8,<6.12` because the application genuinely depends on `PyQt6.QtPdf` and `PyQt6.QtPdfWidgets`. The Fedora builder performs an explicit import preflight after installing dependencies so incompatible PyQt6 resolutions fail before PyInstaller.
