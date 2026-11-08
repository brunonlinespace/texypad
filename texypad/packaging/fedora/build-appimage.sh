#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

APP_NAME="Texypad"
APP_ID="texypad"
APP_VERSION="0.0.4"
APPSTREAM_ID="io.github.brunonlinespace.texypad"
DESKTOP_FILE_ID="${APPSTREAM_ID}.desktop"
OUTPUT_STEM="Texypad"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROGRAM_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
PROJECT_ROOT="$(cd -- "$PROGRAM_ROOT/.." && pwd -P)"
SOURCE_ENTRY="$PROJECT_ROOT/main.py"
COMPONENT_MANIFEST="$PROJECT_ROOT/suite-pythoine-component.json"
PUBLIC_README="$PROJECT_ROOT/README.md"
SOURCE_MANIFEST="$PROGRAM_ROOT/SOURCE_MANIFEST.sha256"
RUNTIME_REQUIREMENTS="$PROGRAM_ROOT/requirements.txt"
BUILD_REQUIREMENTS="$PROGRAM_ROOT/packaging/pyinstaller/build-requirements.txt"
PYINSTALLER_SPEC="$PROGRAM_ROOT/packaging/pyinstaller/texypad.spec"
APPIMAGE_PAYLOAD="$PROGRAM_ROOT/packaging/appimage"
QA_RUNNER="$PROGRAM_ROOT/qa/static-qa.sh"

HOST_ARCH_RAW="$(uname -m)"
case "$HOST_ARCH_RAW" in
    x86_64) HOST_ARCH="x86_64" ;;
    aarch64|arm64) HOST_ARCH="aarch64" ;;
    *) printf 'Error: unsupported build architecture: %s\n' "$HOST_ARCH_RAW" >&2; exit 2 ;;
esac
ARCH="${ARCH:-$HOST_ARCH}"

FEDORA_RELEASE="unknown"; HOST_NAME="unknown Linux"; OS_ID="unknown"
if [[ -r /etc/os-release ]]; then
    mapfile -d '' -t OS_RELEASE_VALUES < <(
        set +u
        # shellcheck disable=SC1091
        source /etc/os-release
        printf '%s\0%s\0%s\0' "${ID:-unknown}" "${VERSION_ID:-unknown}" "${PRETTY_NAME:-unknown Linux}"
    )
    OS_ID="${OS_RELEASE_VALUES[0]:-unknown}"
    FEDORA_RELEASE="${OS_RELEASE_VALUES[1]:-unknown}"
    HOST_NAME="${OS_RELEASE_VALUES[2]:-unknown Linux}"
fi

BUILD_ROOT="${BUILD_ROOT:-$PROGRAM_ROOT/build/appimage-fedora${FEDORA_RELEASE}-${ARCH}}"
VENV="$BUILD_ROOT/venv"
PYI_DIST="$BUILD_ROOT/pyinstaller-dist"
PYI_WORK="$BUILD_ROOT/pyinstaller-work"
APPDIR="$BUILD_ROOT/Texypad.AppDir"
SMOKE_HOME="$BUILD_ROOT/smoke-home"
DIST_DIR="${OUTPUT_DIR:-$PROGRAM_ROOT/dist}"
CACHE_DIR="${XDG_CACHE_HOME:-${HOME}/.cache}/texypad-appimage-tools"
APPIMAGE="$DIST_DIR/${OUTPUT_STEM}-${APP_VERSION}-${ARCH}.AppImage"
SHA_FILE="${APPIMAGE}.sha256"
BUILD_INFO="$DIST_DIR/${OUTPUT_STEM}-${APP_VERSION}-${ARCH}.build-info.txt"
PYTHON_LOCK="$DIST_DIR/${OUTPUT_STEM}-${APP_VERSION}-${ARCH}.build-python-lock.txt"
APPIMAGETOOL_RESOLVED=""
MAX_TOOL_BYTES=$((200 * 1024 * 1024))
export PYTHONDONTWRITEBYTECODE=1

log(){ printf '\n==> %s\n' "$*"; }
die(){ printf 'Error: %s\n' "$*" >&2; exit 1; }
require_file(){ [[ -f "$1" ]] || die "Missing file: $1"; }

validate_build_root(){
    local allowed_root resolved_root
    allowed_root="$(readlink -m -- "$PROGRAM_ROOT/build")"
    resolved_root="$(readlink -m -- "$BUILD_ROOT")"
    [[ "$resolved_root" != "$allowed_root" ]] || die "BUILD_ROOT must be a child beneath ${allowed_root}."
    case "$resolved_root" in "$allowed_root"/*) ;; *) die "Unsafe BUILD_ROOT outside ${allowed_root}: ${resolved_root}" ;; esac
}

clean_source_python_caches(){
    while IFS= read -r -d '' p; do rm -rf -- "$p"; done < <(
        find "$PROJECT_ROOT" \( -path "$PROGRAM_ROOT/build" -o -path "$PROGRAM_ROOT/dist" -o -path "$PROJECT_ROOT/.git" \) -prune -o -type d -name '__pycache__' -print0)
    while IFS= read -r -d '' p; do rm -f -- "$p"; done < <(
        find "$PROJECT_ROOT" \( -path "$PROGRAM_ROOT/build" -o -path "$PROGRAM_ROOT/dist" -o -path "$PROJECT_ROOT/.git" \) -prune -o -type f \( -name '*.pyc' -o -name '*.pyo' \) -print0)
}
cleanup(){ rm -rf "$SMOKE_HOME"; clean_source_python_caches; }
trap cleanup EXIT

check_non_privileged_policy(){
    if grep -Eq '^[[:space:]]*(sudo|dnf|pkexec|su)([[:space:]]|$)' "$0"; then
        die "Privilege-elevation or host-package-install command detected in builder."
    fi
}

check_host_prerequisites(){
    log "Checking non-privileged host prerequisites"
    local missing=() c
    for c in python3 bash timeout sha256sum od stat find grep cp ln chmod install mktemp rm mkdir mv tr awk date uname readlink sort env; do
        command -v "$c" >/dev/null 2>&1 || missing+=("$c")
    done
    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then missing+=("curl-or-wget"); fi
    ((${#missing[@]}==0)) || die "Missing required host command(s): ${missing[*]}. The builder will not install system packages."
    python3 - <<'PYVENV' >/dev/null 2>&1 || die "Python venv/ensurepip support is required."
import ensurepip, venv
PYVENV
}

validate_component_manifest(){
    python3 - "$COMPONENT_MANIFEST" <<'PYMANIFEST'
import json, sys
from pathlib import Path
p=Path(sys.argv[1]); d=json.loads(p.read_text(encoding='utf-8'))
expected={
'id':'texypad','name':'Texypad','version':'0.0.4','component_kind':'editor',
'desktop_id':'io.github.brunonlinespace.texypad','publisher_id':'brunonlinespace',
'repository':'https://github.com/brunonlinespace/texypad','tagline':'Friendly. Fast. Focused.',
'extensions':['.tex','.bib'],'portable_command':['main.py'],
'capabilities':{'routing':True,'open':True,'create':True},
}
for k,v in expected.items():
    if d.get(k)!=v: raise SystemExit(f'Suite component manifest mismatch for {k}: {d.get(k)!r} != {v!r}')
PYMANIFEST
}

check_inputs(){
    validate_build_root
    if (( EUID == 0 )) && [[ "${TEXYPAD_ALLOW_ROOT_BUILD:-0}" != "1" ]]; then die "Do not run the Texypad AppImage builder with sudo/root."; fi
    case "$ARCH" in x86_64|aarch64) ;; *) die "Unsupported AppImage architecture: ${ARCH}" ;; esac
    [[ "$ARCH" == "$HOST_ARCH" ]] || die "Requested ${ARCH}, but host is ${HOST_ARCH_RAW}; cross-building is unsupported."
    if [[ "$OS_ID" != "fedora" || ! "$FEDORA_RELEASE" =~ ^(43|44)$ ]]; then
        [[ "${TEXYPAD_ALLOW_UNSUPPORTED_HOST:-0}" == "1" ]] || die "Validated for Fedora 43/44. Detected ${HOST_NAME}."
        printf 'Warning: continuing on unsupported host: %s\n' "$HOST_NAME" >&2
    fi
    for p in "$SOURCE_ENTRY" "$COMPONENT_MANIFEST" "$PUBLIC_README" "$SOURCE_MANIFEST" "$RUNTIME_REQUIREMENTS" "$BUILD_REQUIREMENTS" "$PYINSTALLER_SPEC" "$QA_RUNNER" \
        "$APPIMAGE_PAYLOAD/AppRun" "$APPIMAGE_PAYLOAD/$DESKTOP_FILE_ID" "$APPIMAGE_PAYLOAD/${APPSTREAM_ID}.metainfo.xml" \
        "$APPIMAGE_PAYLOAD/styles/breeze-dark.qss" "$APPIMAGE_PAYLOAD/styles/breeze-light.qss" \
        "$PROGRAM_ROOT/LICENSE" "$PROGRAM_ROOT/README.md" "$PROGRAM_ROOT/assets/icons/texypad.png"; do require_file "$p"; done
    validate_component_manifest
}

run_source_release_qa(){
    log "Running Texypad source release gate"
    bash "$QA_RUNNER"
}

validate_desktop_entry_basic(){
    local d="$1"
    grep -Fqx '[Desktop Entry]' "$d" || die "Invalid desktop entry: $d"
    grep -Fqx 'Type=Application' "$d" || die "Desktop Entry requires Type=Application"
    grep -Fqx 'Name=Texypad' "$d" || die "Desktop Entry requires Name=Texypad"
    grep -Eq '^Exec=texypad([[:space:]]|$)' "$d" || die "Desktop Entry requires Exec=texypad"
    grep -Fqx 'Icon=texypad' "$d" || die "Desktop Entry requires Icon=texypad"
    grep -Fqx 'MimeType=text/x-tex;text/x-bibtex;' "$d" || die "Desktop Entry MIME contract mismatch"
}

validate_appstream_basic(){
    python3 - "$1" "$APP_VERSION" <<'PYXML'
from pathlib import Path
import sys, xml.etree.ElementTree as ET
root=ET.parse(Path(sys.argv[1])).getroot(); version=sys.argv[2]
def text(q):
    n=root.find(q); return (n.text or '').strip() if n is not None else ''
assert text('id')=='io.github.brunonlinespace.texypad'
assert text('name')=='Texypad'
assert text('project_license')=='GPL-3.0-or-later'
assert text("launchable[@type='desktop-id']")=='io.github.brunonlinespace.texypad.desktop'
dev=root.find("developer[@id='io.github.brunonlinespace']"); assert dev is not None and (dev.findtext('name') or '').strip()=='Bruno Machado'
urls={n.attrib.get('type'):(n.text or '').strip() for n in root.findall('url')}
assert urls.get('homepage')=='https://github.com/brunonlinespace/texypad'
assert urls.get('bugtracker')=='https://github.com/brunonlinespace/texypad/issues'
assert root.find("content_rating[@type='oars-1.1']") is not None
assert {(n.text or '').strip() for n in root.findall('./provides/binary')}=={'texypad'}
assert {(n.text or '').strip() for n in root.findall('./provides/mediatype')}=={'text/x-tex','text/x-bibtex'}
rels=root.findall('./releases/release')
assert len(rels)==1 and rels[0].attrib.get('version')==version and rels[0].attrib.get('date')=='2026-11-08'
first=root.find('./description/p'); assert first is not None and len(' '.join(''.join(first.itertext()).split()))>=100
PYXML
}

prepare_smoke_home(){ rm -rf "$SMOKE_HOME"; mkdir -p "$SMOKE_HOME/.config" "$SMOKE_HOME/.cache" "$SMOKE_HOME/.local/share" "$SMOKE_HOME/Documents"; }

run_gui_smoke_test(){
    local label="$1"; shift; local f status
    prepare_smoke_home
    f="$(mktemp "${TMPDIR:-/tmp}/texypad-gui.XXXXXX.log")"
    log "Running ${label} GUI smoke test"
    set +e
    timeout 30s env HOME="$SMOKE_HOME" XDG_CONFIG_HOME="$SMOKE_HOME/.config" XDG_CACHE_HOME="$SMOKE_HOME/.cache" XDG_DATA_HOME="$SMOKE_HOME/.local/share" \
        QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software "$@" --texypad-smoke-test >"$f" 2>&1
    status=$?
    set -e
    if [[ "$status" -ne 0 ]] || ! grep -Fq 'GUI smoke test passed.' "$f"; then
        cat "$f" >&2; rm -f "$f"; die "${label} GUI smoke test failed with exit code ${status}."
    fi
    rm -f "$f"
}

run_version_smoke_test(){
    local label="$1"; shift; local f status
    prepare_smoke_home
    f="$(mktemp "${TMPDIR:-/tmp}/texypad-version.XXXXXX.log")"
    log "Running ${label} version smoke test"
    set +e
    timeout 30s env HOME="$SMOKE_HOME" XDG_CONFIG_HOME="$SMOKE_HOME/.config" XDG_CACHE_HOME="$SMOKE_HOME/.cache" XDG_DATA_HOME="$SMOKE_HOME/.local/share" \
        QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software "$@" --version >"$f" 2>&1
    status=$?
    set -e
    if [[ "$status" -ne 0 ]] || ! grep -Fxq "$APP_NAME $APP_VERSION" "$f"; then
        cat "$f" >&2; rm -f "$f"; die "${label} version smoke test failed with exit code ${status}."
    fi
    rm -f "$f"
}

validate_qt_pdf_runtime(){
    log "Checking Texypad Qt PDF runtime dependencies"
    "$VENV/bin/python" - <<'PYQTPDF' || die "Required PyQt6 Qt PDF modules are unavailable. Texypad requires PyQt6>=6.8,<6.12 with QtPdf, QtPdfWidgets and QtPrintSupport present."
from importlib.metadata import version
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView
from PyQt6.QtPrintSupport import QPrinter

print(f"PyQt6 {version('PyQt6')}: QtPdf/QtPdfWidgets/QtPrintSupport import check passed.")
assert QPdfDocument is not None and QPdfView is not None and QPrinter is not None
PYQTPDF
}

prepare_environment(){
    log "Preparing isolated build environment"
    rm -rf "$BUILD_ROOT"; clean_source_python_caches; mkdir -p "$BUILD_ROOT" "$DIST_DIR" "$CACHE_DIR"; chmod 0700 "$CACHE_DIR"
    python3 -m venv "$VENV"
    "$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade pip wheel setuptools
    "$VENV/bin/python" -m pip install --disable-pip-version-check -r "$RUNTIME_REQUIREMENTS" -r "$BUILD_REQUIREMENTS"
    PYTHONPYCACHEPREFIX="$BUILD_ROOT/pycache" "$VENV/bin/python" -m compileall -q -x '/(build|dist)/' "$SOURCE_ENTRY" "$PROGRAM_ROOT"
    "$VENV/bin/python" -m pip check
    validate_qt_pdf_runtime
    "$VENV/bin/python" -m pip freeze --all > "$PYTHON_LOCK"
    log "Running Texypad release QA in build environment"
    PATH="$VENV/bin:$PATH" bash "$QA_RUNNER"
    run_version_smoke_test "source" "$VENV/bin/python" "$SOURCE_ENTRY"
    run_gui_smoke_test "source" "$VENV/bin/python" "$SOURCE_ENTRY"
}

freeze_application(){
    log "Freezing Texypad with PyInstaller"
    "$VENV/bin/python" -m PyInstaller --clean --noconfirm --distpath "$PYI_DIST" --workpath "$PYI_WORK" "$PYINSTALLER_SPEC"
    [[ -x "$PYI_DIST/texypad/texypad" ]] || die "PyInstaller executable was not created."
    run_version_smoke_test "frozen executable" "$PYI_DIST/texypad/texypad"
    run_gui_smoke_test "frozen executable" "$PYI_DIST/texypad/texypad"
}

assemble_appdir(){
    log "Assembling AppDir"
    rm -rf "$APPDIR"
    mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/texypad" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/metainfo" \
        "$APPDIR/usr/share/icons/hicolor/512x512/apps" "$APPDIR/usr/share/doc/texypad"
    cp -a "$PYI_DIST/texypad/." "$APPDIR/usr/lib/texypad/"
    ln -s ../lib/texypad/texypad "$APPDIR/usr/bin/texypad"
    install -m 0755 "$APPIMAGE_PAYLOAD/AppRun" "$APPDIR/AppRun"
    install -m 0644 "$APPIMAGE_PAYLOAD/$DESKTOP_FILE_ID" "$APPDIR/$DESKTOP_FILE_ID"
    install -m 0644 "$APPIMAGE_PAYLOAD/$DESKTOP_FILE_ID" "$APPDIR/usr/share/applications/$DESKTOP_FILE_ID"
    install -m 0644 "$APPIMAGE_PAYLOAD/${APPSTREAM_ID}.metainfo.xml" "$APPDIR/usr/share/metainfo/${APPSTREAM_ID}.metainfo.xml"
    install -m 0644 "$PROGRAM_ROOT/assets/icons/texypad.png" "$APPDIR/texypad.png"
    install -m 0644 "$PROGRAM_ROOT/assets/icons/texypad.png" "$APPDIR/usr/share/icons/hicolor/512x512/apps/texypad.png"
    ln -s texypad.png "$APPDIR/.DirIcon"
    install -m 0644 "$PROGRAM_ROOT/LICENSE" "$APPDIR/usr/share/doc/texypad/LICENSE"
    install -m 0644 "$PROGRAM_ROOT/README.md" "$APPDIR/usr/share/doc/texypad/README.md"
    install -m 0644 "$PROGRAM_ROOT/docs/RELEASE_NOTES.md" "$APPDIR/usr/share/doc/texypad/RELEASE_NOTES.md"

    validate_desktop_entry_basic "$APPDIR/$DESKTOP_FILE_ID"
    validate_desktop_entry_basic "$APPDIR/usr/share/applications/$DESKTOP_FILE_ID"
    validate_appstream_basic "$APPDIR/usr/share/metainfo/${APPSTREAM_ID}.metainfo.xml"
    if command -v desktop-file-validate >/dev/null 2>&1; then
        desktop-file-validate "$APPDIR/$DESKTOP_FILE_ID"
        desktop-file-validate "$APPDIR/usr/share/applications/$DESKTOP_FILE_ID"
    else
        printf 'Info: desktop-file-validate unavailable; built-in checks passed.\n' >&2
    fi
    if command -v appstreamcli >/dev/null 2>&1; then
        appstreamcli validate --no-net "$APPDIR/usr/share/metainfo/${APPSTREAM_ID}.metainfo.xml"
    else
        printf 'Info: appstreamcli unavailable; built-in AppStream checks passed.\n' >&2
    fi
}

validate_bundle(){
    log "Validating Texypad Qt bundle"
    find "$APPDIR/usr/lib/texypad" -name 'libqxcb.so' -print -quit | grep -q . || die "Qt XCB platform plugin was not bundled."
    find "$APPDIR/usr/lib/texypad" \( -iname '*Qt6Pdf*' -o -iname '*QtPdf*' \) -print -quit | grep -q . || die "Qt PDF libraries were not bundled."
    find "$APPDIR/usr/lib/texypad" \( -iname '*Qt6PrintSupport*' -o -iname '*QtPrintSupport*' \) -print -quit | grep -q . || die "Qt PrintSupport was not bundled."
    find "$APPDIR/usr/lib/texypad" \( -name 'libqwayland*.so' -o -name '*wayland*.so' \) -print -quit | grep -q . \
        || printf 'Warning: Qt Wayland plugin was not detected; test XWayland carefully.\n' >&2
    run_version_smoke_test "AppDir" "$APPDIR/AppRun"
    run_gui_smoke_test "AppDir" "$APPDIR/AppRun"
}

elf_sanity_check(){ local t="$1" m z; require_file "$t"; z="$(stat -c %s "$t")"; [[ "$z" -gt 0 && "$z" -le "$MAX_TOOL_BYTES" ]] || die "appimagetool invalid size: ${z}"; m="$(od -An -tx1 -N4 "$t" | tr -d ' \n')"; [[ "$m" == 7f454c46 ]] || die "appimagetool is not ELF: $t"; }
download_tool(){ local url="$1" dst="$2" part="${2}.part"; [[ "$url" == https://* ]] || die "appimagetool URL must use HTTPS."; rm -f "$part"; if command -v curl >/dev/null 2>&1; then curl --proto '=https' --tlsv1.2 --fail --location --retry 3 --retry-all-errors --connect-timeout 30 --max-time 300 --max-filesize "$MAX_TOOL_BYTES" -o "$part" "$url"; else wget --https-only --tries=3 --timeout=30 -O "$part" "$url"; fi; elf_sanity_check "$part"; chmod 0755 "$part"; mv -f "$part" "$dst"; }
prepare_appimagetool(){
    local t url; mkdir -p "$CACHE_DIR"; chmod 0700 "$CACHE_DIR"
    if [[ -n "${APPIMAGETOOL_PATH:-}" ]]; then t="$(readlink -f -- "$APPIMAGETOOL_PATH")"; [[ -x "$t" ]] || die "APPIMAGETOOL_PATH is not executable"; log "Using appimagetool supplied through APPIMAGETOOL_PATH"
    elif [[ -n "${APPIMAGETOOL:-}" ]]; then t="$(readlink -f -- "$APPIMAGETOOL")"; [[ -x "$t" ]] || die "APPIMAGETOOL is not executable"; log "Using appimagetool supplied through APPIMAGETOOL"
    elif command -v appimagetool >/dev/null 2>&1; then t="$(command -v appimagetool)"; log "Using appimagetool from PATH"
    else t="$CACHE_DIR/appimagetool-${ARCH}.AppImage"; url="${APPIMAGETOOL_URL:-https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage}"; if [[ ! -x "$t" ]]; then log "Downloading official appimagetool"; download_tool "$url" "$t"; else log "Using cached appimagetool"; fi; fi
    elf_sanity_check "$t"
    if [[ -n "${APPIMAGETOOL_SHA256:-}" ]]; then
        [[ "$APPIMAGETOOL_SHA256" =~ ^[[:xdigit:]]{64}$ ]] || die "APPIMAGETOOL_SHA256 must be 64 hexadecimal characters."
        printf '%s  %s\n' "$APPIMAGETOOL_SHA256" "$t" | sha256sum --check --status || die "appimagetool SHA-256 verification failed."
    elif [[ "${TEXYPAD_RELEASE_BUILD:-0}" == 1 ]]; then
        die "TEXYPAD_RELEASE_BUILD=1 requires APPIMAGETOOL_SHA256."
    else
        printf 'Warning: APPIMAGETOOL_SHA256 not supplied; resolved hash will be recorded.\n' >&2
    fi
    APPIMAGETOOL_RESOLVED="$t"
}

build_appimage(){
    log "Creating $(basename "$APPIMAGE")"
    rm -f "$APPIMAGE" "$SHA_FILE" "$BUILD_INFO"
    ARCH="$ARCH" "$APPIMAGETOOL_RESOLVED" --appimage-extract-and-run "$APPDIR" "$APPIMAGE"
    [[ -s "$APPIMAGE" ]] || die "appimagetool did not create expected output."
    chmod 0755 "$APPIMAGE"
    run_version_smoke_test "final AppImage" "$APPIMAGE" --appimage-extract-and-run || die "Final AppImage version smoke test failed."
    run_gui_smoke_test "final AppImage" "$APPIMAGE" --appimage-extract-and-run || die "Final AppImage GUI smoke test failed."
    sha256sum "$APPIMAGE" > "$SHA_FILE"
}

write_build_info(){
    local ah mh rh bh python_version pyinstaller_version
    ah="$(sha256sum "$APPIMAGETOOL_RESOLVED" | awk '{print $1}')"
    mh="$(sha256sum "$COMPONENT_MANIFEST" | awk '{print $1}')"
    rh="$(sha256sum "$RUNTIME_REQUIREMENTS" | awk '{print $1}')"
    bh="$(sha256sum "$0" | awk '{print $1}')"
    python_version="$("$VENV/bin/python" --version 2>&1)"
    pyinstaller_version="$("$VENV/bin/python" -m PyInstaller --version)"
    {
        printf 'app=%s\nversion=%s\narch=%s\nhost=%s\npython=%s\npyinstaller=%s\n' \
            "$APP_NAME" "$APP_VERSION" "$ARCH" "$HOST_NAME" "$python_version" "$pyinstaller_version"
        printf 'appimagetool=%s\nappimagetool_sha256=%s\n' "$APPIMAGETOOL_RESOLVED" "$ah"
        printf 'component_manifest_sha256=%s\nruntime_requirements_sha256=%s\nbuilder_sha256=%s\n' "$mh" "$rh" "$bh"
        printf 'source_manifest=%s\n' "$(basename "$SOURCE_MANIFEST")"
        printf 'qt_contract=QtPdf + QtPdfWidgets + QtPrintSupport required; TeX toolchain remains host runtime dependency\n'
    } > "$BUILD_INFO"
}

check_non_privileged_policy
check_host_prerequisites
check_inputs
run_source_release_qa
prepare_environment
freeze_application
assemble_appdir
validate_bundle
prepare_appimagetool
build_appimage
write_build_info
log "Build complete"
printf 'AppImage: %s\nChecksum: %s\nBuild information: %s\nPython lock: %s\n' "$APPIMAGE" "$SHA_FILE" "$BUILD_INFO" "$PYTHON_LOCK"
