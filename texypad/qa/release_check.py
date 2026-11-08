#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, xml.etree.ElementTree as ET
from pathlib import Path

root=Path(__file__).resolve().parents[2]
pkg=root/'texypad'
errors=[]
def need(cond,msg):
    if not cond: errors.append(msg)
def text(path): return path.read_text(encoding='utf-8')

init=text(pkg/'__init__.py'); app=text(pkg/'app.py'); compiler=text(pkg/'compiler.py'); file_io=text(pkg/'file_io.py'); preview=text(pkg/'pdf_preview.py')
need('APP_VERSION = "0.0.4"' in init,'version identity mismatch')
need(set(p.name for p in root.iterdir())=={'README.md','main.py','suite-pythoine-component.json','texypad'},'portable root must contain only README.md, main.py, suite-pythoine-component.json and texypad/')
need('Friendly. Fast. Focused.' in app,'Pad-family slogan mismatch')
need('Simple. Fast. Focused.' not in app,'stale slogan remains')
need('QKeySequence' in app.split('from PyQt6.QtGui import',1)[1].split('\n',1)[0],'QKeySequence startup fix regressed')
need('QPdfDocument' in preview and 'QPdfView' in preview,'Qt PDF preview dependency missing')
need('from PyQt6.QtPrintSupport import QPrintDialog, QPrinter' in app,'Texypad print dependency missing')
need('from PyQt6.QtPrintSupport import QPrinter' in preview,'PDF preview print dependency missing')
need('-no-shell-escape' in compiler,'safe TeX shell-escape policy regressed')
need('ENGINE_NAMES = ("pdflatex", "xelatex", "lualatex")' in compiler,'TeX engine contract mismatch')
need('SUPPORTED_SUFFIXES = {".tex", ".sty", ".cls", ".bib"}' in file_io,'direct-open source suffix contract mismatch')
need('--texypad-smoke-test' in app and 'GUI smoke test passed.' in app,'GUI smoke-test hook missing')
for term in ('RIBBON_BUTTON_SIZE = 52','RIBBON_ICON_SIZE = 32','Source + Print View','Command Library','new_page("Insert")','def _build_menus(self)','bar.setVisible(True)','dialog.setModal(False)'):
    need(term in app,f'established UI contract missing: {term}')
need('bar.setNativeMenuBar(False)' not in app,'Plasma/global-menu behavior regressed')
need((root/'README.md').is_file(),'missing public repository-root README.md')
need('Current release: **0.0.4**' in text(root/'README.md'),'public root README version mismatch')
need('has not yet been extensively tested' in text(root/'README.md'),'public README limited-testing notice missing')

command_root=pkg/'assets/icons/commands'
for variant in ('light','dark'):
    icons=sorted((command_root/variant).glob('*.png')) if (command_root/variant).is_dir() else []
    need(len(icons)>=61,f'{variant} command icon family incomplete: {len(icons)}')

cm_path=root/'suite-pythoine-component.json'
need(cm_path.is_file(),'missing Suite Pythoine component manifest')
if cm_path.is_file():
    cm=json.loads(text(cm_path))
    expected={'id':'texypad','name':'Texypad','version':'0.0.4','component_kind':'editor','extensions':['.tex','.bib'],'portable_command':['main.py'],'desktop_id':'io.github.brunonlinespace.texypad','publisher_id':'brunonlinespace','repository':'https://github.com/brunonlinespace/texypad','tagline':'Friendly. Fast. Focused.','capabilities':{'routing':True,'open':True,'create':True}}
    for k,v in expected.items(): need(cm.get(k)==v,f'Suite manifest mismatch for {k}: {cm.get(k)!r} != {v!r}')

runtime_req=pkg/'requirements.txt'
need(runtime_req.is_file(),'missing runtime requirements')
if runtime_req.is_file():
    rr=text(runtime_req)
    active=[line.strip() for line in rr.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    need(active==['PyQt6>=6.8,<6.12'],f'unexpected runtime requirements: {active!r}')

build_req=pkg/'packaging/pyinstaller/build-requirements.txt'
need(build_req.is_file(),'missing canonical build requirements')
if build_req.is_file():
    br=text(build_req)
    need('\\n' not in br,'build requirements contain literal \\n escape')
    active=[line.strip() for line in br.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    need(active==['PyInstaller>=6.21,<7'],f'unexpected build requirements: {active!r}')
spec=pkg/'packaging/pyinstaller/texypad.spec'
need(spec.is_file(),'missing PyInstaller spec')
if spec.is_file():
    sp=text(spec)
    need('"PyQt6.QtPdf"' in sp and '"PyQt6.QtPdfWidgets"' in sp,'PyInstaller Qt PDF hidden imports missing')

builder=pkg/'packaging/fedora/build-appimage.sh'
need(builder.is_file(),'missing Fedora AppImage builder')
if builder.is_file():
    b=text(builder)
    need('APP_VERSION="0.0.4"' in b,'builder version mismatch')
    need('PUBLIC_README="$PROJECT_ROOT/README.md"' in b and '"$PUBLIC_README"' in b,'builder root README input contract missing')
    for forbidden in ('sudo ','dnf ','pkexec '): need(forbidden not in b,f'non-privileged builder contains {forbidden.strip()}')
    for term in ('validate_build_root','pip check','pip freeze --all','validate_component_manifest','APPIMAGETOOL_SHA256','run_version_smoke_test "final AppImage"','run_gui_smoke_test "final AppImage"'):
        need(term in b,f'hardened builder contract missing: {term}')
    need('validate_qt_pdf_runtime' in b,'early Qt PDF dependency preflight missing')
    need('from PyQt6.QtPdf import QPdfDocument' in b and 'from PyQt6.QtPdfWidgets import QPdfView' in b and 'from PyQt6.QtPrintSupport import QPrinter' in b,'Qt PDF/PrintSupport preflight imports missing')
    need('Qt PDF libraries were not bundled.' in b and 'Qt PrintSupport was not bundled.' in b,'Texypad-specific Qt bundle checks missing')

metadata=pkg/'packaging/appimage/io.github.brunonlinespace.texypad.metainfo.xml'
need(metadata.is_file(),'AppStream metadata missing')
if metadata.is_file():
    root_xml=ET.parse(metadata).getroot(); xml=text(metadata)
    def xt(q):
        n=root_xml.find(q); return (n.text or '').strip() if n is not None else ''
    need(xt('id')=='io.github.brunonlinespace.texypad','AppStream id mismatch')
    need(xt("launchable[@type='desktop-id']")=='io.github.brunonlinespace.texypad.desktop','AppStream desktop launchable mismatch')
    dev=root_xml.find("developer[@id='io.github.brunonlinespace']")
    need(dev is not None and (dev.findtext('name') or '').strip()=='Bruno Machado','structured developer metadata missing')
    need(root_xml.find("content_rating[@type='oars-1.1']") is not None,'OARS metadata missing')
    rels=root_xml.findall('./releases/release')
    need(len(rels)==1 and rels[0].attrib.get('version')=='0.0.4' and rels[0].attrib.get('date')=='2026-11-08','current-only AppStream release/date mismatch')
    first=root_xml.find('./description/p')
    first_text=' '.join(''.join(first.itertext()).split()) if first is not None else ''
    need(len(first_text)>=100,'AppStream first description paragraph too short')
    need('<url type="homepage">https://github.com/brunonlinespace/texypad</url>' in xml,'homepage metadata missing')
    need('<url type="bugtracker">https://github.com/brunonlinespace/texypad/issues</url>' in xml,'bugtracker metadata missing')

desktop=pkg/'packaging/appimage/io.github.brunonlinespace.texypad.desktop'
need(desktop.is_file(),'canonical desktop file missing')
if desktop.is_file():
    d=text(desktop)
    need('MimeType=text/x-tex;text/x-bibtex;' in d,'desktop MIME routing mismatch')
    need('Exec=texypad %F' in d,'desktop Exec mismatch')

manifest=pkg/'SOURCE_MANIFEST.sha256'
need(manifest.is_file(),'source manifest missing')
if manifest.is_file():
    expected={}
    for line in text(manifest).splitlines():
        if not line.strip(): continue
        digest,rel=line.split('  ',1); expected[rel]=digest
    actual={}
    for path in root.rglob('*'):
        if not path.is_file(): continue
        rel=path.relative_to(root).as_posix()
        if rel=='texypad/SOURCE_MANIFEST.sha256' or '__pycache__' in rel or rel.endswith(('.pyc','.pyo')): continue
        if rel.startswith('texypad/build/') or rel.startswith('texypad/dist/'): continue
        actual[rel]=hashlib.sha256(path.read_bytes()).hexdigest()
    need(set(expected)==set(actual),'source manifest file list mismatch')
    for rel,digest in actual.items(): need(expected.get(rel)==digest,f'source manifest hash mismatch: {rel}')

for path in root.rglob('*.py'):
    rel=path.relative_to(root).as_posix()
    if rel.startswith('texypad/build/') or rel.startswith('texypad/dist/'): continue
    try: compile(text(path),str(path),'exec')
    except Exception as exc: errors.append(f'Python syntax failure in {rel}: {exc}')

if errors:
    print('RELEASE CHECK: FAIL')
    for e in errors: print(' -',e)
    raise SystemExit(1)
print('RELEASE CHECK: PASS')
