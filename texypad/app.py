#!/usr/bin/env python3
"""Texypad — lightweight Pad-family LaTeX editor with live PDF print view."""
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPainter, QPalette, QPixmap, QTextCursor, QTextDocument
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from texypad import APP_ID, APP_NAME, APP_VERSION, ORGANIZATION_NAME
from texypad.code_editor import CodeEditor
from texypad.command_io import (
    COMMAND_COLLECTION_FILTER,
    MAX_COMMAND_COLLECTION_SIZE,
    CommandCollectionError,
    build_command_collection,
    parse_command_collection,
)
from texypad.compiler import ENGINE_NAMES, LatexCompiler
from texypad.latex_commands import (
    BUILTIN_COMMANDS,
    COMMAND_BY_KEY,
    COMMAND_CATEGORIES,
    MAX_CUSTOM_COMMANDS,
    CommandSpec,
    render_template,
    validate_custom_command,
)
from texypad.file_io import FileTooLargeError, UnsupportedFileError, atomic_write_text, read_text_file, validate_source_path
from texypad.pdf_preview import PDF_AVAILABLE, PdfPreview
from texypad.runtime_paths import RuntimePaths

GITHUB_URL = "https://github.com/brunonlinespace/texypad"
ISSUES_URL = GITHUB_URL + "/issues"
RIBBON_BUTTON_SIZE = 52
RIBBON_ICON_SIZE = 32
MAX_CONFIG_SIZE = 4 * 1024 * 1024
OPEN_WINDOWS: set["TexypadWindow"] = set()

DEFAULT_DOCUMENT = r"""\documentclass{article}

\title{Untitled Document}
\author{}
\date{\today}

\begin{document}

\maketitle

\section{Introduction}

Start writing here.

\end{document}
"""


def register_window(window: "TexypadWindow") -> None:
    OPEN_WINDOWS.add(window)
    window.destroyed.connect(lambda _obj=None, w=window: OPEN_WINDOWS.discard(w))


def app_dialog_title(subject: str) -> str:
    subject = str(subject).strip()
    suffix = f" — {APP_NAME}"
    return subject if subject.endswith(suffix) else f"{subject}{suffix}"


def show_message(parent, icon: QMessageBox.Icon, title: str, text: str) -> int:
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(app_dialog_title(title))
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(str(text))
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    return box.exec()


def confirm_message(parent, title: str, text: str) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(app_dialog_title(title))
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(str(text))
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    return box.exec() == QMessageBox.StandardButton.Yes


def glyph_icon(widget: QWidget, glyph: str) -> QIcon:
    """Small palette-aware fallback used only when a packaged command icon is missing."""
    size = RIBBON_ICON_SIZE
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setPen(widget.palette().color(widget.foregroundRole()))
    font = widget.font()
    font.setBold(True)
    font.setPointSize(max(8, int(size * 0.42)))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)


class RibbonScrollArea(QScrollArea):
    """Horizontally pannable ribbon page without stealing child-button taps.

    A simple tap should still activate the underlying ribbon button or tab.
    Horizontal movement only turns into explicit panning once it exceeds a
    drag-like threshold and is clearly more horizontal than vertical.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._touch_origin: tuple[float, float] | None = None
        self._touch_last: tuple[float, float] | None = None
        self._touch_pan_active = False
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)

    def pan_from_wheel_event(self, event) -> bool:
        bar = self.horizontalScrollBar()
        if bar.maximum() <= bar.minimum():
            return False
        pixel_delta = event.pixelDelta()
        angle_delta = event.angleDelta()
        delta = pixel_delta.y() or pixel_delta.x()
        if not delta:
            delta = angle_delta.y() or angle_delta.x()
            if delta:
                notches = int(delta / 120)
                if notches == 0:
                    notches = 1 if delta > 0 else -1
                delta = notches * max(48, bar.singleStep() * 3)
        if not delta:
            return False
        bar.setValue(bar.value() - int(delta))
        event.accept()
        return True

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.pan_from_wheel_event(event):
            return
        super().wheelEvent(event)

    def viewportEvent(self, event) -> bool:  # noqa: N802
        event_type = event.type()
        if event_type == QEvent.Type.TouchBegin:
            points = event.points()
            if points:
                pos = points[0].position()
                coords = (float(pos.x()), float(pos.y()))
                self._touch_origin = coords
                self._touch_last = coords
                self._touch_pan_active = False
            return super().viewportEvent(event)
        elif event_type == QEvent.Type.TouchUpdate and self._touch_origin is not None:
            points = event.points()
            if points:
                pos = points[0].position()
                current = (float(pos.x()), float(pos.y()))
                if not self._touch_pan_active:
                    delta_x = current[0] - self._touch_origin[0]
                    delta_y = current[1] - self._touch_origin[1]
                    threshold = float(max(12, QApplication.startDragDistance()))
                    if abs(delta_x) >= threshold and abs(delta_x) > abs(delta_y):
                        self._touch_pan_active = True
                        self._touch_last = current
                    else:
                        self._touch_last = current
                        return super().viewportEvent(event)
                if self._touch_pan_active and self._touch_last is not None:
                    delta = self._touch_last[0] - current[0]
                    self._touch_last = current
                    bar = self.horizontalScrollBar()
                    if bar.maximum() > bar.minimum() and delta:
                        bar.setValue(bar.value() + int(round(delta)))
                    event.accept()
                    return True
        elif event_type in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            was_panning = self._touch_pan_active
            self._touch_origin = None
            self._touch_last = None
            self._touch_pan_active = False
            if was_panning:
                event.accept()
                return True
        return super().viewportEvent(event)


class CustomCommandDialog(QDialog):
    """Editor for one user-defined LaTeX/BibTeX insertion snippet."""

    def __init__(self, window: "TexypadWindow", spec: CommandSpec | None = None) -> None:
        super().__init__(window)
        self.window = window
        self.original = spec
        self.result_spec: CommandSpec | None = None
        self.setWindowTitle(app_dialog_title("Edit Custom Command" if spec else "Add Custom Command"))
        self.setWindowIcon(window.windowIcon())
        self.setMinimumSize(620, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        form = QFormLayout()
        self.label_edit = QLineEdit(self)
        self.category_edit = QLineEdit(self)
        self.category_edit.setPlaceholderText("Custom")
        self.language_combo = QComboBox(self)
        self.language_combo.addItems(["LaTeX", "BibTeX", "LaTeX + BibTeX"])
        self.description_edit = QLineEdit(self)
        form.addRow("Name:", self.label_edit)
        form.addRow("Category:", self.category_edit)
        form.addRow("Available in:", self.language_combo)
        form.addRow("Description:", self.description_edit)
        layout.addLayout(form)

        help_label = QLabel(
            "Insertion text can use [[selection]] for the current selection and "
            "[[cursor]] for the final caret position. These markers are removed when inserted.",
            self,
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        self.template_edit = QPlainTextEdit(self)
        self.template_edit.setPlaceholderText(r"\command{[[selection]][[cursor]]}")
        layout.addWidget(self.template_edit, 1)

        if spec is not None:
            self.label_edit.setText(spec.label)
            self.category_edit.setText(spec.category)
            self.description_edit.setText(spec.description)
            self.template_edit.setPlainText(spec.template)
            languages = set(spec.languages)
            self.language_combo.setCurrentIndex(2 if languages == {"latex", "bib"} else (1 if languages == {"bib"} else 0))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self._accept_validated)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_validated(self) -> None:
        language_index = self.language_combo.currentIndex()
        languages = ("latex", "bib") if language_index == 2 else (("bib",) if language_index == 1 else ("latex",))
        try:
            self.result_spec = validate_custom_command(
                key=self.original.key if self.original else None,
                label=self.label_edit.text(),
                category=self.category_edit.text(),
                description=self.description_edit.text(),
                template=self.template_edit.toPlainText(),
                languages=languages,
            )
        except ValueError as error:
            show_message(self, QMessageBox.Icon.Warning, "Invalid Custom Command", str(error))
            return
        self.accept()


class CommandLibraryPanel(QWidget):
    """Searchable, categorised command/snippet library inspired by Timblee Pad."""

    def __init__(self, window: "TexypadWindow", parent: QWidget | None = None) -> None:
        super().__init__(parent or window)
        self.window = window
        self._lists: dict[str, QListWidget] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search commands, categories or descriptions")
        self.search_input.textChanged.connect(self.refresh)
        layout.addWidget(self.search_input)

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        layout.addWidget(self.tabs, 1)
        for category in ("Favourites", "All", *COMMAND_CATEGORIES):
            list_widget = QListWidget(self.tabs)
            list_widget.setAlternatingRowColors(True)
            list_widget.itemSelectionChanged.connect(
                lambda selected=list_widget: self._selection_changed(selected)
            )
            list_widget.itemDoubleClicked.connect(
                lambda _item, selected=list_widget: self._insert_from_list(selected)
            )
            self.tabs.addTab(list_widget, category)
            self._lists[category] = list_widget

        self.details = QLabel("", self)
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.details)

        primary = QHBoxLayout()
        self.insert_button = QPushButton("Insert", self)
        self.favourite_button = QPushButton("Add to My Favourites", self)
        self.insert_button.clicked.connect(self.insert_selected)
        self.favourite_button.clicked.connect(self.toggle_selected_favourite)
        primary.addWidget(self.insert_button)
        primary.addWidget(self.favourite_button)
        layout.addLayout(primary)

        custom = QHBoxLayout()
        self.add_custom_button = QPushButton("Add Custom…", self)
        self.edit_custom_button = QPushButton("Edit Custom…", self)
        self.remove_custom_button = QPushButton("Remove Custom", self)
        self.add_custom_button.clicked.connect(self.window.add_custom_command)
        self.edit_custom_button.clicked.connect(self.edit_selected_custom)
        self.remove_custom_button.clicked.connect(self.remove_selected_custom)
        custom.addWidget(self.add_custom_button)
        custom.addWidget(self.edit_custom_button)
        custom.addWidget(self.remove_custom_button)
        layout.addLayout(custom)

        transfer = QHBoxLayout()
        self.import_button = QPushButton("Import…", self)
        self.export_button = QPushButton("Export…", self)
        self.import_button.clicked.connect(self.window.import_commands)
        self.export_button.clicked.connect(self.window.export_commands)
        transfer.addWidget(self.import_button)
        transfer.addWidget(self.export_button)
        layout.addLayout(transfer)

        self.tabs.currentChanged.connect(lambda _index: self._update_details())
        self.refresh()

    def _current_category(self) -> str:
        index = self.tabs.currentIndex()
        return self.tabs.tabText(index) if index >= 0 else "All"

    def _current_list(self) -> QListWidget | None:
        return self._lists.get(self._current_category())

    @staticmethod
    def _key_from_list(list_widget: QListWidget | None) -> str | None:
        if list_widget is None or list_widget.currentItem() is None:
            return None
        key = list_widget.currentItem().data(Qt.ItemDataRole.UserRole)
        return str(key) if isinstance(key, str) else None

    def current_key(self) -> str | None:
        return self._key_from_list(self._current_list())

    def _selection_changed(self, source: QListWidget) -> None:
        if source is self._current_list():
            self._update_details()

    def refresh(self) -> None:
        query = self.search_input.text().strip().casefold()
        selected_key = self.current_key()
        selected_category = self._current_category()
        language = self.window.current_source_language()
        for widget in self._lists.values():
            widget.blockSignals(True)
            widget.clear()

        for spec in self.window.command_specs():
            if language not in spec.languages:
                continue
            haystack = f"{spec.key} {spec.label} {spec.category} {spec.description} {spec.template}".casefold()
            if query and query not in haystack:
                continue
            starred = "★" if spec.key in self.window.favourite_commands else "☆"
            text = f"{starred}  {spec.label} — {spec.description}"
            category_target = spec.category if spec.builtin and spec.category in self._lists else "Custom"
            targets = ["All", category_target]
            if spec.key in self.window.favourite_commands:
                targets.insert(0, "Favourites")
            for category in targets:
                list_widget = self._lists.get(category)
                if list_widget is None:
                    continue
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, spec.key)
                item.setToolTip(f"{spec.category}: {spec.description}")
                list_widget.addItem(item)
                if category == selected_category and spec.key == selected_key:
                    list_widget.setCurrentItem(item)

        for widget in self._lists.values():
            widget.blockSignals(False)
        current = self._current_list()
        if current is not None and current.currentItem() is None and current.count():
            current.setCurrentRow(0)
        self._update_details()

    def _update_details(self) -> None:
        key = self.current_key()
        spec = self.window.command_spec_for_key(key) if key else None
        enabled = spec is not None and self.window.current_source_language() in spec.languages
        self.insert_button.setEnabled(enabled)
        self.favourite_button.setEnabled(spec is not None)
        custom = bool(spec is not None and not spec.builtin)
        self.edit_custom_button.setEnabled(custom)
        self.remove_custom_button.setEnabled(custom)
        if spec is None:
            self.details.setText("No command selected.")
            self.favourite_button.setText("Add to My Favourites")
            return
        source_names = ", ".join("BibTeX" if value == "bib" else "LaTeX" for value in spec.languages)
        self.details.setText(
            f"{spec.label}  •  {spec.category}  •  {source_names}\n"
            f"{spec.description}\nInsertion: {spec.insertion_preview}"
        )
        self.favourite_button.setText(
            "Remove from My Favourites" if spec.key in self.window.favourite_commands else "Add to My Favourites"
        )

    def _insert_from_list(self, list_widget: QListWidget) -> None:
        key = self._key_from_list(list_widget)
        if key:
            self.window.insert_library_command(key)

    def insert_selected(self) -> None:
        key = self.current_key()
        if key:
            self.window.insert_library_command(key)

    def toggle_selected_favourite(self) -> None:
        key = self.current_key()
        if key:
            self.window.toggle_command_favourite(key)

    def edit_selected_custom(self) -> None:
        key = self.current_key()
        if key:
            self.window.edit_custom_command(key)

    def remove_selected_custom(self) -> None:
        key = self.current_key()
        if key:
            self.window.remove_custom_command(key)


class CommandLibraryDialog(QDialog):
    """Modeless floating wrapper around the shared command library."""

    def __init__(self, window: "TexypadWindow") -> None:
        super().__init__(window)
        self.window = window
        self.setWindowTitle(app_dialog_title("Command Library"))
        self.setWindowIcon(window.windowIcon())
        self.setModal(False)
        self.setMinimumSize(780, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.panel = CommandLibraryPanel(window, self)
        layout.addWidget(self.panel, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def refresh(self) -> None:
        self.panel.refresh()


class TexypadWindow(QMainWindow):
    def __init__(self, initial_file: str | None = None) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        register_window(self)
        self.paths = RuntimePaths.detect()
        self.file_path: Path | None = None
        self.file_encoding = "utf-8"
        self.file_bom = b""
        self.file_newline = "\n"
        self.file_disk_signature: tuple[int, int] | None = None
        self._loading = False
        self._closing = False
        self._compile_pending = False
        self._last_compile_success = False
        self._current_preview_pdf: Path | None = None
        self._find_query = ""
        self._outline_lines: dict[int, int] = {}
        self.preferences = self._load_preferences()
        self.custom_commands: list[CommandSpec] = []
        self.favourite_commands: set[str] = set()
        self.command_library_dialog: CommandLibraryDialog | None = None
        self.about_dialog: QDialog | None = None
        self._restore_command_library_preferences()
        self.resize(1120, 760)
        self.setMinimumSize(760, 520)
        self.setAcceptDrops(True)
        if self.paths.icon_path.is_file():
            self.setWindowIcon(QIcon(str(self.paths.icon_path)))

        self.compiler = LatexCompiler(self)
        self.compiler.compile_started.connect(self._compile_started)
        self.compiler.compile_finished.connect(self._compile_finished)
        self.compiler.status_message.connect(self._set_compile_status)

        self.live_timer = QTimer(self)
        self.live_timer.setSingleShot(True)
        self.live_timer.timeout.connect(self._run_live_preview)
        self.outline_timer = QTimer(self)
        self.outline_timer.setSingleShot(True)
        self.outline_timer.setInterval(450)
        self.outline_timer.timeout.connect(self._rebuild_outline)

        self._build_actions()
        self._refresh_action_icons()
        self._build_ui()
        self._build_menus()
        self._build_ribbon()
        self._apply_preferences()
        self._new_document(mark_modified=False)
        if initial_file:
            self.load_file(initial_file)
        self._update_all_state()

    # ---------- Preferences ----------
    def _load_preferences(self) -> dict:
        defaults = {
            "view_mode": "split",
            "live_preview": True,
            "engine": "pdflatex",
            "live_delay_ms": 850,
            "line_numbers": True,
            "word_wrap": False,
            "continuous_preview": True,
            "show_outline": False,
            "show_diagnostics": False,
            "source_theme": "system",
            "splitter_sizes": [520, 520],
            "command_library_sidebar_position": "disabled",
            "favourite_commands": [],
            "custom_commands": [],
        }
        path = self.paths.config_path
        try:
            if not path.is_file() or path.stat().st_size > MAX_CONFIG_SIZE:
                return defaults
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return defaults
        except (OSError, ValueError, json.JSONDecodeError):
            return defaults
        result = defaults.copy()
        if raw.get("view_mode") in {"source", "split", "preview"}:
            result["view_mode"] = raw["view_mode"]
        if raw.get("engine") in ENGINE_NAMES:
            result["engine"] = raw["engine"]
        if raw.get("source_theme") in {"system", "dark", "light"}:
            result["source_theme"] = raw["source_theme"]
        for key in ("live_preview", "line_numbers", "word_wrap", "continuous_preview", "show_outline", "show_diagnostics"):
            if isinstance(raw.get(key), bool):
                result[key] = raw[key]
        delay = raw.get("live_delay_ms")
        if isinstance(delay, int):
            result["live_delay_ms"] = max(350, min(5000, delay))
        sizes = raw.get("splitter_sizes")
        if isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(x, int) and x >= 0 for x in sizes):
            result["splitter_sizes"] = sizes
        position = raw.get("command_library_sidebar_position")
        if position in {"disabled", "left", "right"}:
            result["command_library_sidebar_position"] = position
        favourites = raw.get("favourite_commands")
        if isinstance(favourites, list):
            result["favourite_commands"] = favourites[:500]
        custom = raw.get("custom_commands")
        if isinstance(custom, list):
            result["custom_commands"] = custom[:MAX_CUSTOM_COMMANDS]
        return result

    def _restore_command_library_preferences(self) -> None:
        restored: list[CommandSpec] = []
        for value in self.preferences.get("custom_commands", [])[:MAX_CUSTOM_COMMANDS]:
            if not isinstance(value, dict):
                continue
            try:
                spec = validate_custom_command(
                    key=value.get("key"),
                    label=value.get("label", ""),
                    category=value.get("category", "Custom"),
                    description=value.get("description", ""),
                    template=value.get("template", ""),
                    languages=value.get("languages", ("latex",)),
                )
            except (TypeError, ValueError):
                continue
            if spec.key not in {item.key for item in restored}:
                restored.append(spec)
        self.custom_commands = restored
        available = set(COMMAND_BY_KEY) | {spec.key for spec in restored}
        favourites = self.preferences.get("favourite_commands", [])
        self.favourite_commands = {
            value for value in favourites
            if isinstance(value, str) and value in available
        }

    @staticmethod
    def _command_preference_dict(spec: CommandSpec) -> dict:
        return {
            "key": spec.key,
            "label": spec.label,
            "category": spec.category,
            "description": spec.description,
            "template": spec.template,
            "languages": list(spec.languages),
        }

    def _save_preferences(self) -> None:
        if self._closing:
            return
        self.preferences["splitter_sizes"] = self.splitter.sizes() if hasattr(self, "splitter") else [520, 520]
        if hasattr(self, "custom_commands"):
            self.preferences["custom_commands"] = [self._command_preference_dict(spec) for spec in self.custom_commands]
            self.preferences["favourite_commands"] = sorted(self.favourite_commands, key=str.casefold)
        try:
            self.paths.config_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp = self.paths.config_path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(self.preferences, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(temp, self.paths.config_path)
        except OSError:
            pass

    # ---------- Actions ----------
    def _action(self, text: str, callback, shortcut: str | None = None, *, checkable: bool = False, glyph: str = "•") -> QAction:
        action = QAction(text, self)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        action.setProperty("texypad_glyph", glyph)
        return action

    def _set_action_icon_key(self, action: QAction, icon_key: str) -> None:
        action.setProperty("texypad_icon_key", icon_key)

    def _command_icon_variant(self) -> str:
        """Return the packaged icon family matching the current application theme."""
        window_colour = self.palette().color(QPalette.ColorRole.Window)
        return "dark" if window_colour.lightness() < 128 else "light"

    def _command_icon_path(self, icon_key: str) -> Path:
        return (
            self.paths.package_root
            / "assets"
            / "icons"
            / "commands"
            / self._command_icon_variant()
            / f"{icon_key}.png"
        )

    def _refresh_action_icons(self) -> None:
        """Load the real packaged Texypad command-icon family onto shared actions."""
        for action in self.findChildren(QAction):
            icon_key = action.property("texypad_icon_key")
            if not icon_key:
                continue
            path = self._command_icon_path(str(icon_key))
            if path.is_file():
                action.setIcon(QIcon(str(path)))
            else:
                glyph = str(action.property("texypad_glyph") or "•")
                action.setIcon(glyph_icon(self, glyph))


    def _build_actions(self) -> None:
        self.new_action = self._action("New", self.new_document, "Ctrl+N", glyph="+")
        self.open_action = self._action("Open…", self.open_dialog, "Ctrl+O", glyph="O")
        self.new_window_action = self._action("New Window", self.new_window, "Ctrl+Shift+N", glyph="W")
        self.save_action = self._action("Save", self.save, "Ctrl+S", glyph="S")
        self.save_as_action = self._action("Save As…", self.save_as, "Ctrl+Shift+S", glyph="SA")
        self.rename_action = self._action("Rename…", self.rename_file, "Ctrl+Alt+R", glyph="R")
        self.open_folder_action = self._action("Open Containing Folder", self.open_containing_folder, glyph="D")
        self.export_pdf_action = self._action("Export Compiled PDF…", self.export_pdf, "Ctrl+Alt+E", glyph="PDF")
        self.print_action = self._action("Print…", self.print_document, "Ctrl+P", glyph="P")
        self.save_exit_action = self._action("Save and Exit", self.save_and_exit, glyph="SE")
        self.exit_action = self._action("Exit", self.close, "Ctrl+Q", glyph="X")

        self.undo_action = self._action("Undo", self.editor_undo, "Ctrl+Z", glyph="↶")
        self.redo_action = self._action("Redo", self.editor_redo, "Ctrl+Y", glyph="↷")
        self.cut_action = self._action("Cut", self.editor_cut, "Ctrl+X", glyph="✂")
        self.copy_action = self._action("Copy", self.editor_copy, "Ctrl+C", glyph="C")
        self.paste_action = self._action("Paste", self.editor_paste, "Ctrl+V", glyph="V")
        self.select_all_action = self._action("Select All", self.editor_select_all, "Ctrl+A", glyph="A")
        self.find_action = self._action("Find", self.show_find, "Ctrl+F", glyph="F")
        self.replace_action = self._action("Replace…", self.replace_text, "Ctrl+H", glyph="FR")
        self.goto_action = self._action("Go To Line…", self.go_to_line, "Ctrl+G", glyph="#")
        self.duplicate_action = self._action("Duplicate Line / Selection", self.editor_duplicate, "Ctrl+D", glyph="D+")
        self.comment_action = self._action("Toggle Comment", self.editor_toggle_comment, "Ctrl+/", glyph="%")

        self.quick_compile_action = self._action("Compile", lambda: self.compile_document(full=False, force=True), "F5", glyph="▶")
        self.full_compile_action = self._action("Full Build", lambda: self.compile_document(full=True, force=True), "Ctrl+F5", glyph="B")
        self.stop_compile_action = self._action("Stop Compile", self.compiler.stop, "Shift+F5", glyph="■")
        self.live_preview_action = self._action("Live Preview", self.toggle_live_preview, checkable=True, glyph="LIVE")
        self.show_diagnostics_action = self._action("Diagnostics", self.toggle_diagnostics, "Ctrl+`", checkable=True, glyph="!")

        self.section_action = self._action("Section", lambda: self.insert_command("\\section{", "}"), "Ctrl+1", glyph="H1")
        self.subsection_action = self._action("Subsection", lambda: self.insert_command("\\subsection{", "}"), "Ctrl+2", glyph="H2")
        self.subsubsection_action = self._action("Subsubsection", lambda: self.insert_command("\\subsubsection{", "}"), "Ctrl+3", glyph="H3")
        self.bold_action = self._action("Bold", lambda: self.insert_command("\\textbf{", "}"), "Ctrl+B", glyph="B")
        self.italic_action = self._action("Emphasis", lambda: self.insert_command("\\emph{", "}"), "Ctrl+I", glyph="I")
        self.inline_math_action = self._action("Inline Math", lambda: self.insert_command("$", "$"), "Ctrl+M", glyph="$x$")
        self.display_math_action = self._action("Display Math", lambda: self.insert_command("\\[\n", "\n\\]"), "Ctrl+Shift+M", glyph="Σ")
        self.fraction_action = self._action("Fraction", lambda: self.insert_command("\\frac{", "}{}", cursor_back=1), glyph="a/b")
        self.itemize_action = self._action("Itemized List", lambda: self.insert_environment("itemize", "\\item "), glyph="•")
        self.enumerate_action = self._action("Numbered List", lambda: self.insert_environment("enumerate", "\\item "), glyph="1.")
        self.figure_action = self._action("Figure", self.insert_figure, glyph="IMG")
        self.table_action = self._action("Table", self.insert_table, glyph="TBL")
        self.cite_action = self._action("Citation", lambda: self.insert_command("\\cite{", "}"), glyph="CIT")
        self.ref_action = self._action("Reference", lambda: self.insert_command("\\ref{", "}"), glyph="REF")
        self.label_action = self._action("Label", lambda: self.insert_command("\\label{", "}"), glyph="LBL")
        self.command_library_action = self._action("Command Library…", self.show_command_library, "Ctrl+Alt+L", glyph="LIB")
        self.add_custom_command_action = self._action("Add Custom Command…", self.add_custom_command, glyph="+C")
        self.import_commands_action = self._action("Import Commands…", self.import_commands, glyph="IN")
        self.export_commands_action = self._action("Export Commands…", self.export_commands, glyph="OUT")

        self.source_only_action = self._action("Source Only", lambda: self.set_view_mode("source"), checkable=True, glyph="SRC")
        self.split_view_action = self._action("Source + Print View", lambda: self.set_view_mode("split"), checkable=True, glyph="S|P")
        self.preview_only_action = self._action("Print View Only", lambda: self.set_view_mode("preview"), checkable=True, glyph="PDF")
        group = QActionGroup(self)
        group.setExclusive(True)
        for action in (self.source_only_action, self.split_view_action, self.preview_only_action):
            group.addAction(action)
        self.line_numbers_action = self._action("Line Numbers", self.toggle_line_numbers, checkable=True, glyph="#")
        self.word_wrap_action = self._action("Word Wrap", self.toggle_word_wrap, checkable=True, glyph="↵")
        self.continuous_action = self._action("Continuous Pages", self.toggle_continuous, checkable=True, glyph="⇣")
        self.fit_width_action = self._action("Fit Width", self.preview_fit_width, glyph="↔")
        self.fit_page_action = self._action("Fit Page", self.preview_fit_page, glyph="□")
        self.zoom_out_action = self._action("Zoom Out", lambda: self.preview.zoom_by_steps(-1), "Ctrl+-", glyph="−")
        self.zoom_reset_action = self._action("100%", self.preview_actual_size, "Ctrl+0", glyph="100")
        self.zoom_in_action = self._action("Zoom In", lambda: self.preview.zoom_by_steps(1), "Ctrl++", glyph="+")
        self.outline_action = self._action("Document Outline", self.toggle_outline, checkable=True, glyph="OUT")
        self.source_theme_action = self._action("Editing Field Theme…", self.choose_source_theme, glyph="◐")
        self.library_position_action = self._action("Command Library Position…", self.choose_command_library_position, glyph="LIB")

        self.documentation_action = self._action("Documentation", self.open_documentation, "F1", glyph="?")
        self.shortcuts_action = self._action("Keyboard Shortcuts", self.show_shortcuts, glyph="⌨")
        self.github_action = self._action("GitHub Repository", lambda: QDesktopServices.openUrl(QUrl(GITHUB_URL)), glyph="GH")
        self.issue_action = self._action("Report an Issue", lambda: QDesktopServices.openUrl(QUrl(ISSUES_URL)), glyph="!")
        self.about_action = self._action("About", self.show_about, glyph="i")

        for action, icon_key in (
            (self.new_action, "new"),
            (self.open_action, "open"),
            (self.new_window_action, "new"),
            (self.save_action, "save"),
            (self.save_as_action, "save-as"),
            (self.rename_action, "text"),
            (self.open_folder_action, "folder"),
            (self.export_pdf_action, "pdf"),
            (self.print_action, "print"),
            (self.save_exit_action, "save"),
            (self.exit_action, "stop"),
            (self.undo_action, "undo"),
            (self.redo_action, "redo"),
            (self.cut_action, "text"),
            (self.copy_action, "copy"),
            (self.paste_action, "paste"),
            (self.select_all_action, "select-all"),
            (self.find_action, "find"),
            (self.replace_action, "replace"),
            (self.goto_action, "goto"),
            (self.duplicate_action, "duplicate"),
            (self.comment_action, "line-comment"),
            (self.quick_compile_action, "compile"),
            (self.full_compile_action, "full-build"),
            (self.stop_compile_action, "stop"),
            (self.live_preview_action, "live-preview"),
            (self.show_diagnostics_action, "diagnostics"),
            (self.section_action, "section"),
            (self.subsection_action, "subsection"),
            (self.subsubsection_action, "subsubsection"),
            (self.bold_action, "bold"),
            (self.italic_action, "italic"),
            (self.inline_math_action, "inline-math"),
            (self.display_math_action, "display-math"),
            (self.fraction_action, "fraction"),
            (self.itemize_action, "itemize"),
            (self.enumerate_action, "enumerate"),
            (self.figure_action, "figure"),
            (self.table_action, "table"),
            (self.cite_action, "cite"),
            (self.ref_action, "reference"),
            (self.label_action, "label"),
            (self.command_library_action, "command-library"),
            (self.add_custom_command_action, "custom-command"),
            (self.import_commands_action, "import"),
            (self.export_commands_action, "export"),
            (self.source_only_action, "source-view"),
            (self.split_view_action, "split-view"),
            (self.preview_only_action, "preview-view"),
            (self.line_numbers_action, "line-numbers"),
            (self.word_wrap_action, "word-wrap"),
            (self.continuous_action, "continuous"),
            (self.fit_width_action, "fit-width"),
            (self.fit_page_action, "fit-page"),
            (self.zoom_out_action, "zoom-out"),
            (self.zoom_reset_action, "zoom-reset"),
            (self.zoom_in_action, "zoom-in"),
            (self.outline_action, "outline"),
            (self.source_theme_action, "source-theme"),
            (self.library_position_action, "library-position"),
            (self.documentation_action, "documentation"),
            (self.shortcuts_action, "shortcuts"),
            (self.github_action, "github"),
            (self.issue_action, "issue"),
            (self.about_action, "about"),
        ):
            self._set_action_icon_key(action, icon_key)

    # ---------- UI ----------
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.find_bar = QWidget(central)
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(6, 4, 6, 4)
        find_layout.addWidget(QLabel("Find:"))
        self.find_edit = QLineEdit(self.find_bar)
        self.find_edit.setClearButtonEnabled(True)
        self.find_edit.setMaximumWidth(360)
        self.find_edit.returnPressed.connect(self.find_next)
        self.find_edit.textChanged.connect(self._find_text_changed)
        find_layout.addWidget(self.find_edit)
        prev_button = QPushButton("Previous", self.find_bar)
        prev_button.clicked.connect(self.find_previous)
        next_button = QPushButton("Next", self.find_bar)
        next_button.clicked.connect(self.find_next)
        close_button = QPushButton("Close", self.find_bar)
        close_button.clicked.connect(lambda: self.find_bar.hide())
        self.find_counter = QLabel("0/0", self.find_bar)
        find_layout.addWidget(prev_button)
        find_layout.addWidget(next_button)
        find_layout.addWidget(self.find_counter)
        find_layout.addStretch(1)
        find_layout.addWidget(close_button)
        self.find_bar.hide()

        self.editor = CodeEditor(self)
        self.editor.setObjectName("sourceEditor")
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.cursorPositionChanged.connect(self._update_cursor_status)
        self.editor.document().modificationChanged.connect(lambda _value: self._update_title())
        self.editor.go_to_line_requested.connect(self.go_to_line)

        self.preview = PdfPreview(self)
        self.preview.setObjectName("pdfPreview")
        self.preview.ready_changed.connect(lambda _ready: self._update_action_state())
        self.preview.page_changed.connect(self._preview_page_changed)
        self.preview.zoom_changed.connect(lambda value: self.zoom_label.setText(f"Zoom: {value}%"))

        self.source_container = QWidget(self)
        source_layout = QVBoxLayout(self.source_container)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_header = QLabel("Source", self.source_container)
        source_header.setObjectName("paneHeader")
        source_header.setContentsMargins(8, 4, 8, 4)
        source_layout.addWidget(source_header)
        source_layout.addWidget(self.editor, 1)

        self.preview_container = QWidget(self)
        preview_layout = QVBoxLayout(self.preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_header = QLabel("Print View", self.preview_container)
        preview_header.setObjectName("paneHeader")
        preview_header.setContentsMargins(8, 4, 8, 4)
        preview_layout.addWidget(preview_header)
        preview_layout.addWidget(self.preview, 1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.source_container)
        self.splitter.addWidget(self.preview_container)

        # As in Timblee Pad, the reusable Library can be a left/right resizable
        # sidebar or remain floating-only.  Nest it outside the source/print
        # splitter so enabling the Library never changes the document split.
        self.command_library_sidebar = CommandLibraryPanel(self)
        self.command_library_sidebar.setMinimumWidth(250)
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.addWidget(self.splitter)
        self.workspace_splitter.addWidget(self.command_library_sidebar)
        self.command_library_sidebar.hide()

        self.main_layout.addWidget(self.find_bar)
        self.main_layout.addWidget(self.workspace_splitter, 1)

        self.diagnostics_dock = QDockWidget("Diagnostics", self)
        self.diagnostics_dock.setObjectName("diagnosticsDock")
        self.diagnostics_text = CodeEditor(self.diagnostics_dock)
        self.diagnostics_text.setReadOnly(True)
        self.diagnostics_text.set_line_numbers_visible(False)
        self.diagnostics_text.set_source_language("latex")
        self.diagnostics_dock.setWidget(self.diagnostics_text)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.diagnostics_dock)
        self.diagnostics_dock.visibilityChanged.connect(self._diagnostics_visibility_changed)

        self.outline_dock = QDockWidget("Document Outline", self)
        self.outline_dock.setObjectName("outlineDock")
        self.outline_tree = QTreeWidget(self.outline_dock)
        self.outline_tree.setHeaderHidden(True)
        self.outline_tree.itemActivated.connect(self._outline_activated)
        self.outline_tree.itemClicked.connect(self._outline_activated)
        self.outline_dock.setWidget(self.outline_tree)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.outline_dock)
        self.outline_dock.visibilityChanged.connect(self._outline_visibility_changed)

        status = self.statusBar()
        self.path_label = QLabel("Untitled.tex", status)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.compile_label = QLabel("Idle", status)
        self.counter_label = QLabel("Ln: 1/1, Col: 1, Char: 0", status)
        self.encoding_label = QLabel("UTF-8", status)
        self.page_label = QLabel("Page: —", status)
        self.zoom_label = QLabel("Zoom: —", status)
        status.addWidget(self.path_label, 1)
        status.addPermanentWidget(self.compile_label)
        status.addPermanentWidget(self.counter_label)
        status.addPermanentWidget(self.encoding_label)
        status.addPermanentWidget(self.page_label)
        status.addPermanentWidget(self.zoom_label)

    def _build_menus(self) -> None:
        bar = self.menuBar()
        bar.clear()
        bar.setVisible(True)
        bar.setEnabled(True)
        self.file_menu = bar.addMenu("&File")
        for action in (self.new_action, self.open_action, self.new_window_action, self.save_action, self.save_as_action, self.rename_action, self.open_folder_action, self.export_pdf_action, self.print_action, self.save_exit_action, self.exit_action):
            self.file_menu.addAction(action)
        self.edit_menu = bar.addMenu("&Edit")
        for action in (self.undo_action, self.redo_action, self.cut_action, self.copy_action, self.paste_action, self.select_all_action, self.find_action, self.replace_action, self.goto_action, self.duplicate_action, self.comment_action):
            self.edit_menu.addAction(action)
        self.build_menu = bar.addMenu("&Build")
        for action in (self.quick_compile_action, self.full_compile_action, self.stop_compile_action, self.live_preview_action, self.show_diagnostics_action):
            self.build_menu.addAction(action)
        self.insert_menu = bar.addMenu("&Insert")
        for action in (
            self.section_action, self.subsection_action, self.subsubsection_action, self.label_action,
            self.bold_action, self.italic_action, self.inline_math_action, self.display_math_action,
            self.fraction_action, self.itemize_action, self.enumerate_action, self.figure_action,
            self.table_action, self.cite_action, self.ref_action, self.command_library_action,
            self.add_custom_command_action, self.import_commands_action, self.export_commands_action,
        ):
            self.insert_menu.addAction(action)
        self.view_menu = bar.addMenu("&View")
        for action in (self.source_only_action, self.split_view_action, self.preview_only_action, self.line_numbers_action, self.word_wrap_action, self.continuous_action, self.fit_width_action, self.fit_page_action, self.zoom_out_action, self.zoom_reset_action, self.zoom_in_action, self.outline_action, self.source_theme_action, self.library_position_action):
            self.view_menu.addAction(action)
        self.library_sidebar_menu = self.view_menu.addMenu("Command Library")
        self.library_sidebar_group = QActionGroup(self)
        self.library_sidebar_group.setExclusive(True)
        self.command_library_sidebar_actions: dict[str, QAction] = {}
        for position, label in (("left", "Left Sidebar"), ("right", "Right Sidebar"), ("disabled", "Floating Only")):
            action = QAction(label, self, checkable=True)
            action.triggered.connect(lambda _checked=False, selected=position: self.set_command_library_sidebar_position(selected))
            self.library_sidebar_group.addAction(action)
            self.library_sidebar_menu.addAction(action)
            self.command_library_sidebar_actions[position] = action
        self.help_menu = bar.addMenu("&Help")
        for action in (self.documentation_action, self.shortcuts_action, self.github_action, self.issue_action, self.about_action):
            self.help_menu.addAction(action)
        bar.setVisible(True)

    def _build_ribbon(self) -> None:
        self.ribbon = QTabWidget(self.centralWidget())
        self.ribbon.setObjectName("texypadRibbon")
        self.ribbon.setDocumentMode(True)
        self.ribbon.setMovable(False)
        self.ribbon.setTabsClosable(False)
        self.ribbon.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.ribbon.tabBar().setExpanding(False)
        self.ribbon.tabBar().setUsesScrollButtons(True)
        self.ribbon.tabBar().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.ribbon.tabBar().installEventFilter(self)
        self._ribbon_expanded_height = 214
        self.main_layout.insertWidget(0, self.ribbon)
        self.ribbon_buttons: list[QToolButton] = []
        self.ribbon_height_sources: list[QWidget] = []

        def register_ribbon_height_source(widget: QWidget) -> QWidget:
            widget.installEventFilter(self)
            self.ribbon_height_sources.append(widget)
            return widget

        def register_ribbon_surface(widget: QWidget) -> QWidget:
            widget.setProperty("texypad_ribbon_surface", True)
            widget.installEventFilter(self)
            return widget

        def new_page(label: str) -> QHBoxLayout:
            scroll = RibbonScrollArea(self.ribbon)
            scroll.setObjectName(f"ribbon{label}Page")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            register_ribbon_height_source(scroll)
            register_ribbon_surface(scroll.viewport())
            body = QWidget(scroll)
            row = QHBoxLayout(body)
            row.setContentsMargins(6, 4, 6, 22)
            row.setSpacing(6)
            row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            register_ribbon_height_source(body)
            scroll.setWidget(body)
            self.ribbon.addTab(scroll, label)
            return row

        def button_border_colour() -> str:
            probe = QToolButton(self.ribbon)
            probe.setFixedSize(RIBBON_BUTTON_SIZE, RIBBON_BUTTON_SIZE)
            probe.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            probe.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            probe.ensurePolished()
            pixmap = QPixmap(RIBBON_BUTTON_SIZE, RIBBON_BUTTON_SIZE)
            pixmap.fill(Qt.GlobalColor.transparent)
            probe.render(pixmap)
            image = pixmap.toImage()
            middle = RIBBON_BUTTON_SIZE // 2
            colour = None
            for x in range(min(8, RIBBON_BUTTON_SIZE)):
                candidate = image.pixelColor(x, middle)
                if candidate.alpha() > 0:
                    colour = candidate
                    break
            probe.deleteLater()
            if colour is None:
                colour = self.palette().color(QPalette.ColorRole.Mid)
            return colour.name(QColor.NameFormat.HexRgb)

        section_border_colour = button_border_colour()

        def new_group(page: QHBoxLayout, title: str) -> QGridLayout:
            frame = QFrame(self.ribbon)
            register_ribbon_height_source(frame)
            frame.setObjectName("ribbonSection")
            frame.setFrameShape(QFrame.Shape.NoFrame)
            frame.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
            frame.setStyleSheet(
                "QFrame#ribbonSection {"
                " background-color: palette(button);"
                f" border: 1px solid {section_border_colour};"
                " border-radius: 6px;"
                " }"
                "QFrame#ribbonSection QLabel#ribbonSectionCaption {"
                " background: transparent; border: none; margin-bottom: 2px;"
                " }"
            )
            outer = QVBoxLayout(frame)
            outer.setContentsMargins(8, 5, 8, 6)
            outer.setSpacing(4)
            caption = QLabel(title, frame)
            caption.setObjectName("ribbonSectionCaption")
            caption.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            caption.setAccessibleName(f"{title} section")
            outer.addWidget(caption)
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(3)
            outer.addLayout(grid)
            page.addWidget(frame)
            return grid

        def button(grid: QGridLayout, action: QAction, row: int, col: int) -> QToolButton:
            control = QToolButton(self.ribbon)
            control.setDefaultAction(action)
            control.setFixedSize(RIBBON_BUTTON_SIZE, RIBBON_BUTTON_SIZE)
            control.setIconSize(QSize(RIBBON_ICON_SIZE, RIBBON_ICON_SIZE))
            control.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            control.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
            if not action.icon().isNull():
                control.setIcon(action.icon())
            else:
                glyph = str(action.property("texypad_glyph") or "•")
                control.setIcon(glyph_icon(control, glyph))
            clean_label = action.text().replace("&", "").replace("…", "").strip()
            shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            control.setText("")
            control.setToolTip(clean_label + (f" ({shortcut})" if shortcut else ""))
            control.setStatusTip(clean_label)
            control.setAccessibleName(clean_label)
            control.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            register_ribbon_surface(control)
            grid.addWidget(control, row, col, 1, 1, Qt.AlignmentFlag.AlignCenter)
            self.ribbon_buttons.append(control)
            return control

        file_page = new_page("File")
        grid = new_group(file_page, "Create File")
        button(grid, self.new_action, 0, 0); button(grid, self.open_action, 0, 1); button(grid, self.new_window_action, 1, 0)
        grid = new_group(file_page, "This File")
        button(grid, self.save_action, 0, 0); button(grid, self.save_as_action, 0, 1); button(grid, self.rename_action, 1, 0); button(grid, self.open_folder_action, 1, 1)
        grid = new_group(file_page, "Output")
        button(grid, self.quick_compile_action, 0, 0); button(grid, self.full_compile_action, 0, 1); button(grid, self.export_pdf_action, 1, 0); button(grid, self.print_action, 1, 1)
        grid = new_group(file_page, "Close File")
        button(grid, self.save_exit_action, 0, 0); button(grid, self.exit_action, 1, 0)

        home = new_page("Home")
        grid = new_group(home, "Clipboard")
        button(grid, self.undo_action, 0, 0); button(grid, self.redo_action, 1, 0); button(grid, self.cut_action, 0, 1); button(grid, self.copy_action, 0, 2); button(grid, self.paste_action, 1, 1); button(grid, self.select_all_action, 1, 2)
        grid = new_group(home, "Navigation")
        button(grid, self.find_action, 0, 0); button(grid, self.replace_action, 1, 0); button(grid, self.goto_action, 0, 1); button(grid, self.comment_action, 1, 1); button(grid, self.duplicate_action, 0, 2)
        grid = new_group(home, "Build")
        button(grid, self.quick_compile_action, 0, 0); button(grid, self.full_compile_action, 0, 1); button(grid, self.stop_compile_action, 1, 0); button(grid, self.show_diagnostics_action, 1, 1)

        insert_page = new_page("Insert")
        grid = new_group(insert_page, "Structure")
        button(grid, self.section_action, 0, 0); button(grid, self.subsection_action, 0, 1); button(grid, self.subsubsection_action, 1, 0); button(grid, self.label_action, 1, 1)
        grid = new_group(insert_page, "Text & Math")
        button(grid, self.bold_action, 0, 0); button(grid, self.italic_action, 1, 0); button(grid, self.inline_math_action, 0, 1); button(grid, self.display_math_action, 1, 1); button(grid, self.fraction_action, 0, 2)
        grid = new_group(insert_page, "Objects")
        button(grid, self.itemize_action, 0, 0); button(grid, self.enumerate_action, 1, 0); button(grid, self.figure_action, 0, 1); button(grid, self.table_action, 1, 1); button(grid, self.cite_action, 0, 2); button(grid, self.ref_action, 1, 2)
        grid = new_group(insert_page, "Command Library")
        button(grid, self.command_library_action, 0, 0); button(grid, self.add_custom_command_action, 1, 0); button(grid, self.import_commands_action, 0, 1); button(grid, self.export_commands_action, 1, 1)

        view = new_page("View")
        grid = new_group(view, "Document View")
        button(grid, self.source_only_action, 0, 0); button(grid, self.split_view_action, 0, 1); button(grid, self.preview_only_action, 0, 2); button(grid, self.live_preview_action, 1, 0); button(grid, self.outline_action, 1, 1); button(grid, self.show_diagnostics_action, 1, 2)
        grid = new_group(view, "Print View")
        button(grid, self.fit_width_action, 0, 0); button(grid, self.fit_page_action, 0, 1); button(grid, self.zoom_out_action, 1, 0); button(grid, self.zoom_reset_action, 1, 1); button(grid, self.zoom_in_action, 1, 2); button(grid, self.continuous_action, 0, 2)
        grid = new_group(view, "Preferences")
        button(grid, self.line_numbers_action, 0, 0); button(grid, self.word_wrap_action, 1, 0); button(grid, self.source_theme_action, 0, 1); button(grid, self.library_position_action, 0, 2)
        self.engine_combo = QComboBox(self.ribbon)
        self.engine_combo.setMinimumWidth(110)
        self.engine_combo.setFixedHeight(RIBBON_BUTTON_SIZE)
        self.engine_combo.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        for engine in ENGINE_NAMES:
            self.engine_combo.addItem(engine)
        self.engine_combo.setToolTip("LaTeX compiler used by live preview and builds")
        self.engine_combo.currentTextChanged.connect(self._engine_changed)
        register_ribbon_surface(self.engine_combo)
        register_ribbon_height_source(self.engine_combo)
        grid.addWidget(self.engine_combo, 1, 1, 1, 2)

        help_page = new_page("Help")
        grid = new_group(help_page, "Help")
        button(grid, self.documentation_action, 0, 0); button(grid, self.shortcuts_action, 1, 0); button(grid, self.about_action, 0, 1)
        grid = new_group(help_page, "GitHub")
        button(grid, self.github_action, 0, 0); button(grid, self.issue_action, 1, 0)

        self.ribbon.currentChanged.connect(self._update_ribbon_height)
        self.ribbon.setCurrentIndex(1)
        QTimer.singleShot(0, self._update_ribbon_height)

    def _measure_ribbon_height(self) -> int:
        if not hasattr(self, "ribbon"):
            return 214
        tab_bar = self.ribbon.tabBar()
        tab_height = max(tab_bar.height(), tab_bar.sizeHint().height(), tab_bar.minimumSizeHint().height(), 1)
        current = self.ribbon.currentWidget()
        page_height = 0
        if isinstance(current, QScrollArea):
            body = current.widget()
            if body is not None:
                page_height = max(page_height, body.sizeHint().height(), body.minimumSizeHint().height())
            viewport = current.viewport()
            if viewport is not None:
                page_height = max(page_height, viewport.sizeHint().height(), viewport.minimumSizeHint().height())
            page_height += current.frameWidth() * 2
        elif current is not None:
            page_height = max(page_height, current.sizeHint().height(), current.minimumSizeHint().height())
        margins = self.ribbon.contentsMargins()
        total = tab_height + page_height + margins.top() + margins.bottom() + 8
        return max(140, int(total))

    def _update_ribbon_height(self, _index: int | None = None) -> None:
        if not hasattr(self, "ribbon"):
            return
        height = self._measure_ribbon_height()
        self._ribbon_expanded_height = height
        self.ribbon.setMinimumHeight(height)
        self.ribbon.setMaximumHeight(height)
        self.ribbon.updateGeometry()

    def eventFilter(self, watched, event):
        ribbon = getattr(self, "ribbon", None)
        if ribbon is not None and watched is ribbon.tabBar():
            if event.type() == QEvent.Type.Wheel:
                delta = event.angleDelta().y() or event.angleDelta().x()
                if delta:
                    count = ribbon.count()
                    if count:
                        ribbon.setCurrentIndex((ribbon.currentIndex() + (-1 if delta > 0 else 1)) % count)
                        return True
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest):
                QTimer.singleShot(0, self._update_ribbon_height)
        if bool(getattr(watched, 'property', lambda _name: False)("texypad_ribbon_surface")):
            if event.type() == QEvent.Type.Wheel and ribbon is not None:
                scroll = ribbon.currentWidget()
                if isinstance(scroll, RibbonScrollArea) and scroll.pan_from_wheel_event(event):
                    return True
        if watched in getattr(self, "ribbon_height_sources", []):
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest):
                QTimer.singleShot(0, self._update_ribbon_height)
        return super().eventFilter(watched, event)

    def _apply_preferences(self) -> None:
        self.live_preview_action.setChecked(bool(self.preferences["live_preview"]))
        self.line_numbers_action.setChecked(bool(self.preferences["line_numbers"]))
        self.word_wrap_action.setChecked(bool(self.preferences["word_wrap"]))
        self.continuous_action.setChecked(bool(self.preferences["continuous_preview"]))
        self.show_diagnostics_action.setChecked(bool(self.preferences["show_diagnostics"]))
        self.outline_action.setChecked(bool(self.preferences["show_outline"]))
        self.editor.set_line_numbers_visible(self.line_numbers_action.isChecked())
        self.editor.set_word_wrap_enabled(self.word_wrap_action.isChecked())
        self.preview.set_continuous(self.continuous_action.isChecked())
        self.diagnostics_dock.setVisible(self.show_diagnostics_action.isChecked())
        self.outline_dock.setVisible(self.outline_action.isChecked())
        self.splitter.setSizes(self.preferences.get("splitter_sizes", [520, 520]))
        index = self.engine_combo.findText(self.preferences.get("engine", "pdflatex"))
        self.engine_combo.setCurrentIndex(max(0, index))
        self._apply_source_theme()
        self.set_view_mode(self.preferences.get("view_mode", "split"), save=False)
        position = self.preferences.get("command_library_sidebar_position", "disabled")
        for value, action in self.command_library_sidebar_actions.items():
            action.setChecked(value == position)
        self._apply_command_library_sidebar_position()

    # ---------- Document lifecycle ----------
    def _new_document(self, *, mark_modified: bool = True) -> None:
        self._loading = True
        self.file_path = None
        self.file_encoding = "utf-8"
        self.file_bom = b""
        self.file_newline = "\n"
        self.file_disk_signature = None
        self.editor.set_source_language("latex")
        self.editor.setPlainText(DEFAULT_DOCUMENT)
        self.editor.document().setModified(mark_modified)
        self.preview.clear()
        self._current_preview_pdf = None
        self._loading = False
        self._update_all_state()
        self._schedule_live_preview()

    def new_document(self) -> None:
        if not self._maybe_save_changes():
            return
        self._new_document(mark_modified=False)

    def new_window(self) -> None:
        window = TexypadWindow()
        window.show()

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, app_dialog_title("Open"), str(self.file_path.parent if self.file_path else Path.home()), "LaTeX Sources (*.tex *.sty *.cls *.bib);;TeX Documents (*.tex);;All Supported (*.tex *.sty *.cls *.bib)")
        if path:
            self.load_file(path)

    def load_file(self, value: str | os.PathLike[str]) -> bool:
        if not self._maybe_save_changes():
            return False
        try:
            path = validate_source_path(Path(value))
            text, encoding, bom, newline = read_text_file(path)
        except (OSError, FileTooLargeError, UnsupportedFileError) as error:
            show_message(self, QMessageBox.Icon.Critical, "Open Failed", str(error))
            return False
        self._loading = True
        self.file_path = path
        self.file_encoding, self.file_bom, self.file_newline = encoding, bom, newline
        try:
            stat = path.stat()
            self.file_disk_signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            self.file_disk_signature = None
        self.editor.set_source_language("bib" if path.suffix.lower() == ".bib" else "latex")
        self.editor.setPlainText(text)
        self.editor.mark_clean()
        self.preview.clear()
        self._current_preview_pdf = None
        self._loading = False
        self._update_all_state()
        self._schedule_live_preview()
        return True

    def save(self) -> bool:
        if self.file_path is None:
            return self.save_as()
        return self._save_to(self.file_path)

    def save_as(self) -> bool:
        suggested = str(self.file_path or (Path.home() / "Untitled.tex"))
        path, _ = QFileDialog.getSaveFileName(self, app_dialog_title("Save As"), suggested, "TeX Document (*.tex);;LaTeX Style (*.sty);;LaTeX Class (*.cls);;BibTeX Database (*.bib)")
        if not path:
            return False
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".tex")
        try:
            target = validate_source_path(target, must_exist=False)
        except UnsupportedFileError as error:
            show_message(self, QMessageBox.Icon.Warning, "Unsupported File", str(error))
            return False
        if target.exists() and target != self.file_path and not confirm_message(self, "Replace File", f"Replace the existing file?\n\n{target}"):
            return False
        ok = self._save_to(target, external_check=False)
        if ok:
            self.file_path = target
            self.editor.set_source_language("bib" if target.suffix.lower() == ".bib" else "latex")
            self._update_all_state()
        return ok

    def _save_to(self, target: Path, *, external_check: bool = True) -> bool:
        if external_check and self.file_path == target and target.exists() and self.file_disk_signature is not None:
            try:
                stat = target.stat()
                current = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                current = None
            if current is not None and current != self.file_disk_signature:
                if not confirm_message(self, "File Changed on Disk", "This file changed outside Texypad after it was opened. Overwrite the newer disk version?"):
                    return False
        try:
            atomic_write_text(target, self.editor.toPlainText(), self.file_encoding, self.file_bom, self.file_newline)
            stat = target.stat()
            self.file_disk_signature = (stat.st_mtime_ns, stat.st_size)
        except (OSError, UnicodeError, FileTooLargeError, UnsupportedFileError) as error:
            show_message(self, QMessageBox.Icon.Critical, "Save Failed", str(error))
            return False
        self.file_path = target
        self.editor.mark_clean()
        self.statusBar().showMessage("Saved.", 2500)
        self._update_all_state()
        return True

    def rename_file(self) -> None:
        if self.file_path is None:
            show_message(self, QMessageBox.Icon.Information, "Rename", "Save the document before renaming it.")
            return
        if self.editor.is_modified() and not self.save():
            return
        name, ok = QInputDialog.getText(self, app_dialog_title("Rename"), "New filename:", text=self.file_path.name)
        if not ok or not name.strip() or name.strip() == self.file_path.name:
            return
        target = self.file_path.with_name(name.strip())
        try:
            target = validate_source_path(target, must_exist=False)
        except UnsupportedFileError as error:
            show_message(self, QMessageBox.Icon.Warning, "Unsupported File", str(error))
            return
        if target.exists():
            show_message(self, QMessageBox.Icon.Warning, "Rename", "A file with that name already exists.")
            return
        try:
            self.file_path.rename(target)
        except OSError as error:
            show_message(self, QMessageBox.Icon.Critical, "Rename Failed", str(error))
            return
        self.file_path = target
        try:
            stat = target.stat(); self.file_disk_signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            self.file_disk_signature = None
        self._update_all_state()

    def open_containing_folder(self) -> None:
        path = self.file_path.parent if self.file_path else Path.cwd()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def save_and_exit(self) -> None:
        if self.save():
            self.editor.document().setModified(False)
            self.close()

    def _maybe_save_changes(self) -> bool:
        if not self.editor.is_modified():
            return True
        box = QMessageBox(self)
        box.setWindowTitle(app_dialog_title("Unsaved Changes"))
        box.setIcon(QMessageBox.Icon.Warning)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText("Save changes before continuing?")
        box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        result = box.exec()
        if result == QMessageBox.StandardButton.Save:
            return self.save()
        return result == QMessageBox.StandardButton.Discard

    # ---------- Editing ----------
    def _on_text_changed(self) -> None:
        if self._loading:
            return
        self._update_cursor_status()
        self._update_action_state()
        self.outline_timer.start()
        self._schedule_live_preview()

    def editor_undo(self): self.editor.undo()
    def editor_redo(self): self.editor.redo()
    def editor_cut(self): self.editor.cut()
    def editor_copy(self): self.editor.copy()
    def editor_paste(self): self.editor.paste()
    def editor_select_all(self): self.editor.selectAll()
    def editor_duplicate(self): self.editor.duplicate_current_line_or_selection()
    def editor_toggle_comment(self): self.editor.toggle_comment()

    def insert_command(self, before: str, after: str, *, cursor_back: int = 0) -> None:
        cursor = self.editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n")
        cursor.beginEditBlock()
        cursor.insertText(before + selected + after)
        if not selected:
            steps = len(after) + int(cursor_back)
            if steps:
                cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor, steps)
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def insert_environment(self, name: str, body: str = "") -> None:
        cursor = self.editor.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n") or body
        text = f"\\begin{{{name}}}\n{selected}\n\\end{{{name}}}"
        cursor.insertText(text)
        if not selected.strip():
            cursor.movePosition(QTextCursor.MoveOperation.Up)
        self.editor.setTextCursor(cursor)

    def insert_figure(self) -> None:
        self.editor.textCursor().insertText("\\begin{figure}[htbp]\n    \\centering\n    \\includegraphics[width=0.8\\linewidth]{image-file}\n    \\caption{Caption}\n    \\label{fig:label}\n\\end{figure}\n")

    def insert_table(self) -> None:
        self.editor.textCursor().insertText("\\begin{table}[htbp]\n    \\centering\n    \\begin{tabular}{ll}\n        A & B \\\\\n        C & D \\\\\n    \\end{tabular}\n    \\caption{Caption}\n    \\label{tab:label}\n\\end{table}\n")

    # ---------- Command Library ----------
    def current_source_language(self) -> str:
        return "bib" if self.file_path is not None and self.file_path.suffix.lower() == ".bib" else "latex"

    def command_specs(self) -> list[CommandSpec]:
        return [*BUILTIN_COMMANDS, *self.custom_commands]

    def command_spec_for_key(self, key: str | None) -> CommandSpec | None:
        if not key:
            return None
        builtin = COMMAND_BY_KEY.get(key)
        if builtin is not None:
            return builtin
        return next((spec for spec in self.custom_commands if spec.key == key), None)

    def insert_library_command(self, key: str) -> bool:
        spec = self.command_spec_for_key(key)
        if spec is None:
            return False
        language = self.current_source_language()
        if language not in spec.languages:
            show_message(
                self,
                QMessageBox.Icon.Information,
                "Command Not Available",
                f"{spec.label} is not available for this source type.",
            )
            return False
        cursor = self.editor.textCursor()
        selection = cursor.selectedText().replace("\u2029", "\n")
        start = cursor.selectionStart()
        rendered, caret = render_template(spec, selection)
        cursor.beginEditBlock()
        cursor.insertText(rendered)
        cursor.setPosition(start + caret)
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.statusBar().showMessage(f"Inserted {spec.label}.", 2500)
        return True

    def toggle_command_favourite(self, key: str) -> None:
        if self.command_spec_for_key(key) is None:
            return
        if key in self.favourite_commands:
            self.favourite_commands.remove(key)
        else:
            self.favourite_commands.add(key)
        self._save_preferences()
        self._refresh_command_library_views()

    def add_custom_command(self) -> bool:
        dialog = CustomCommandDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result_spec is None:
            return False
        if len(self.custom_commands) >= MAX_CUSTOM_COMMANDS:
            show_message(
                self,
                QMessageBox.Icon.Warning,
                "Command Library Full",
                f"Texypad stores at most {MAX_CUSTOM_COMMANDS} custom commands.",
            )
            return False
        self.custom_commands.append(dialog.result_spec)
        self.custom_commands.sort(key=lambda spec: (spec.category.casefold(), spec.label.casefold()))
        self._save_preferences()
        self._refresh_command_library_views()
        self.statusBar().showMessage(f"Added custom command {dialog.result_spec.label}.", 3000)
        return True

    def edit_custom_command(self, key: str) -> bool:
        current = self.command_spec_for_key(key)
        if current is None or current.builtin:
            return False
        dialog = CustomCommandDialog(self, current)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result_spec is None:
            return False
        self.custom_commands = [dialog.result_spec if spec.key == key else spec for spec in self.custom_commands]
        self.custom_commands.sort(key=lambda spec: (spec.category.casefold(), spec.label.casefold()))
        self._save_preferences()
        self._refresh_command_library_views()
        self.statusBar().showMessage(f"Updated custom command {dialog.result_spec.label}.", 3000)
        return True

    def remove_custom_command(self, key: str) -> bool:
        spec = self.command_spec_for_key(key)
        if spec is None or spec.builtin:
            return False
        if not confirm_message(self, "Remove Custom Command", f"Remove '{spec.label}' from the Command Library?"):
            return False
        self.custom_commands = [item for item in self.custom_commands if item.key != key]
        self.favourite_commands.discard(key)
        self._save_preferences()
        self._refresh_command_library_views()
        return True

    def _refresh_command_library_views(self) -> None:
        if hasattr(self, "command_library_sidebar"):
            self.command_library_sidebar.refresh()
        if self.command_library_dialog is not None:
            self.command_library_dialog.refresh()

    def show_command_library(self) -> None:
        if self.command_library_dialog is None:
            dialog = CommandLibraryDialog(self)
            dialog.finished.connect(lambda _result: setattr(self, "command_library_dialog", None))
            self.command_library_dialog = dialog
        self.command_library_dialog.refresh()
        self.command_library_dialog.show()
        self.command_library_dialog.raise_()
        self.command_library_dialog.activateWindow()

    def set_command_library_sidebar_position(self, position: str) -> None:
        if position not in {"disabled", "left", "right"}:
            return
        self.preferences["command_library_sidebar_position"] = position
        for value, action in self.command_library_sidebar_actions.items():
            action.blockSignals(True)
            action.setChecked(value == position)
            action.blockSignals(False)
        self._apply_command_library_sidebar_position()
        self._save_preferences()

    def _apply_command_library_sidebar_position(self) -> None:
        position = self.preferences.get("command_library_sidebar_position", "disabled")
        sidebar = self.command_library_sidebar
        document = self.splitter
        if position == "disabled":
            sidebar.hide()
            return
        sidebar.show()
        if position == "left":
            self.workspace_splitter.insertWidget(0, sidebar)
            self.workspace_splitter.insertWidget(1, document)
            self.workspace_splitter.setStretchFactor(0, 0)
            self.workspace_splitter.setStretchFactor(1, 1)
            self.workspace_splitter.setSizes([300, max(500, self.width() - 300)])
        else:
            self.workspace_splitter.insertWidget(0, document)
            self.workspace_splitter.insertWidget(1, sidebar)
            self.workspace_splitter.setStretchFactor(0, 1)
            self.workspace_splitter.setStretchFactor(1, 0)
            self.workspace_splitter.setSizes([max(500, self.width() - 300), 300])
        sidebar.refresh()

    def import_commands(self) -> bool:
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self,
            app_dialog_title("Import Commands"),
            "",
            COMMAND_COLLECTION_FILTER,
        )
        if not selected:
            return False
        source = Path(selected).expanduser()
        try:
            if not source.is_file():
                raise OSError("The selected path is not a regular file.")
            if source.stat().st_size > MAX_COMMAND_COLLECTION_SIZE:
                raise OSError("The command collection exceeds the 2 MiB import limit.")
            imported_custom, imported_favourites = parse_command_collection(source.read_bytes())
        except (OSError, CommandCollectionError) as error:
            show_message(self, QMessageBox.Icon.Warning, "Import Commands Failed", str(error))
            return False

        mode = "merge"
        if self.custom_commands or self.favourite_commands:
            box = QMessageBox(self)
            box.setWindowTitle(app_dialog_title("Import Commands"))
            box.setIcon(QMessageBox.Icon.Question)
            box.setText("How should the imported custom commands and favourites be applied?")
            box.setInformativeText(
                "Merge keeps the current Library and adds imported entries. "
                "Replace makes the imported collection the complete user-defined Library."
            )
            merge_button = box.addButton("Merge", QMessageBox.ButtonRole.AcceptRole)
            replace_button = box.addButton("Replace", QMessageBox.ButtonRole.DestructiveRole)
            cancel_button = box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(merge_button)
            box.exec()
            clicked = box.clickedButton()
            if clicked is cancel_button:
                return False
            if clicked is replace_button:
                mode = "replace"

        if mode == "replace":
            new_custom = list(imported_custom)
            new_favourites = set(imported_favourites)
        else:
            merged = {spec.key: spec for spec in self.custom_commands}
            for spec in imported_custom:
                merged[spec.key] = spec
            new_custom = list(merged.values())[:MAX_CUSTOM_COMMANDS]
            available = set(COMMAND_BY_KEY) | set(merged)
            new_favourites = {
                key for key in (self.favourite_commands | imported_favourites)
                if key in available
            }
        new_custom.sort(key=lambda spec: (spec.category.casefold(), spec.label.casefold()))
        self.custom_commands = new_custom
        available = set(COMMAND_BY_KEY) | {spec.key for spec in new_custom}
        self.favourite_commands = {key for key in new_favourites if key in available}
        self._save_preferences()
        self._refresh_command_library_views()
        self.statusBar().showMessage(
            f"Imported {len(imported_custom)} custom command(s) and {len(imported_favourites)} favourite(s).",
            4000,
        )
        return True

    def export_commands(self) -> bool:
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self,
            app_dialog_title("Export Commands"),
            "texypad-commands.texypadcommands",
            COMMAND_COLLECTION_FILTER,
        )
        if not selected:
            return False
        destination = Path(selected).expanduser()
        if not destination.suffix:
            destination = destination.with_suffix(".texypadcommands")
        if destination.exists() and not confirm_message(
            self,
            "Replace Command Collection",
            f"Replace the existing file?\n\n{destination}",
        ):
            return False
        collection = build_command_collection(self.custom_commands, self.favourite_commands)
        payload = (json.dumps(collection, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        descriptor: int | None = None
        temporary: Path | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{destination.name}.texypad-",
                suffix=".tmp",
                dir=destination.parent,
            )
            temporary = Path(raw_path)
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            temporary = None
        except OSError as error:
            show_message(self, QMessageBox.Icon.Critical, "Export Commands Failed", str(error))
            return False
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass
        self.statusBar().showMessage(
            f"Exported {len(collection['custom_commands'])} custom command(s) and "
            f"{len(collection['favourites'])} favourite(s).",
            4000,
        )
        return True

    # ---------- Search ----------
    def show_find(self) -> None:
        self.find_bar.show()
        if self.editor.textCursor().hasSelection():
            selected = self.editor.textCursor().selectedText()
            if "\u2029" not in selected and len(selected) <= 1024:
                self.find_edit.setText(selected)
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def _find_text_changed(self, text: str) -> None:
        self._find_query = text[:1024]
        self.find_counter.setText("—" if self._find_query else "0/0")

    def _find(self, backward: bool = False) -> None:
        query = self.find_edit.text()
        if not query:
            return
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        found = self.editor.find(query, flags)
        if not found:
            cursor = self.editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
            self.editor.setTextCursor(cursor)
            found = self.editor.find(query, flags)
        self.find_counter.setText("Found" if found else "0/0")

    def find_next(self): self._find(False)
    def find_previous(self): self._find(True)

    def replace_text(self) -> None:
        find, ok = QInputDialog.getText(self, app_dialog_title("Replace"), "Find:", text=self.find_edit.text())
        if not ok or not find:
            return
        replacement, ok = QInputDialog.getText(self, app_dialog_title("Replace"), "Replace with:")
        if not ok:
            return
        text = self.editor.toPlainText().replace(find, replacement)
        if text != self.editor.toPlainText():
            self.editor.setPlainText(text)
            self.editor.document().setModified(True)

    def go_to_line(self) -> None:
        line, ok = QInputDialog.getInt(self, app_dialog_title("Go To Line"), "Line number:", self.editor.textCursor().blockNumber() + 1, 1, max(1, self.editor.blockCount()))
        if ok:
            self.editor.go_to_line(line)

    # ---------- Outline ----------
    def _rebuild_outline(self) -> None:
        import re
        self.outline_tree.clear()
        self._outline_lines.clear()
        pattern = re.compile(r"^\s*\\(part|chapter|section|subsection|subsubsection)\*?\s*\{([^{}]*)\}")
        levels = {"part": 0, "chapter": 0, "section": 1, "subsection": 2, "subsubsection": 3}
        parents: dict[int, QTreeWidgetItem] = {}
        for index, line in enumerate(self.editor.toPlainText().splitlines(), start=1):
            match = pattern.match(line)
            if not match:
                continue
            kind, title = match.groups()
            level = levels[kind]
            item = QTreeWidgetItem([title.strip() or f"({kind})"])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            parent = None
            for parent_level in range(level - 1, -1, -1):
                if parent_level in parents:
                    parent = parents[parent_level]
                    break
            if parent is None:
                self.outline_tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            parents[level] = item
            for deeper in [key for key in parents if key > level]:
                parents.pop(deeper, None)
        self.outline_tree.expandAll()

    def _outline_activated(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        line = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(line, int):
            self.editor.go_to_line(line)
            if self.preferences["view_mode"] == "preview":
                self.set_view_mode("split")
            self.editor.setFocus()

    # ---------- Build / live preview ----------
    def _engine_changed(self, engine: str) -> None:
        if engine not in ENGINE_NAMES:
            return
        self.preferences["engine"] = engine
        self._save_preferences()
        self._schedule_live_preview(force=True)

    def _schedule_live_preview(self, *, force: bool = False) -> None:
        if self._loading or not self.live_preview_action.isChecked() or self.preferences.get("view_mode") == "source":
            return
        if self.file_path and self.file_path.suffix.lower() != ".tex":
            return
        self.live_timer.start(150 if force else int(self.preferences.get("live_delay_ms", 850)))

    def _run_live_preview(self) -> None:
        if self.compiler.is_running():
            self._compile_pending = True
            return
        self.compile_document(full=False, force=False)

    def compile_document(self, *, full: bool, force: bool) -> None:
        if self.file_path and self.file_path.suffix.lower() != ".tex":
            show_message(self, QMessageBox.Icon.Information, "Compile", "Only .tex documents can be compiled. .sty, .cls and .bib files remain editable source files.")
            return
        if self.compiler.is_running():
            self._compile_pending = True
            self.statusBar().showMessage("A compile is already running; the latest edit is queued.", 2500)
            return
        engine = self.engine_combo.currentText() if hasattr(self, "engine_combo") else self.preferences.get("engine", "pdflatex")
        started = self.compiler.compile_snapshot(self.editor.toPlainText(), self.file_path, engine=engine, full=full, force=force)
        if not started and engine not in self.compiler.available_engines():
            self.preview.clear(f"{engine} is not installed or not visible on PATH.\n\nInstall a TeX distribution or select another compiler.")
            self._update_action_state()

    def _compile_started(self, engine: str, full: bool) -> None:
        self._set_compile_status(f"{engine}: {'full build' if full else 'compiling'}…")
        self.stop_compile_action.setEnabled(True)

    def _compile_finished(self, success: bool, pdf_path: str, log: str, full: bool) -> None:
        self.stop_compile_action.setEnabled(False)
        self._last_compile_success = success
        diagnostics = self.compiler.compact_errors(log)
        if diagnostics:
            self.diagnostics_text.setPlainText("\n".join(diagnostics) + "\n\n--- Full compiler output ---\n" + log[-120000:])
        else:
            self.diagnostics_text.setPlainText(log[-120000:] if log else "No compiler messages.")
        if success:
            loaded, error = self.preview.load_pdf(pdf_path)
            if loaded:
                self._current_preview_pdf = Path(pdf_path)
                self._set_compile_status("Build OK" if full else "Preview current")
            else:
                self._set_compile_status("PDF load failed")
                self.statusBar().showMessage(error, 4000)
        else:
            self._set_compile_status("Build failed")
            if diagnostics:
                self.diagnostics_dock.show()
                self.show_diagnostics_action.setChecked(True)
        self._update_action_state()
        if self._compile_pending:
            self._compile_pending = False
            if self.live_preview_action.isChecked() and self.preferences.get("view_mode") != "source":
                self.live_timer.start(120)

    def _set_compile_status(self, text: str) -> None:
        self.compile_label.setText(text)

    def toggle_live_preview(self, checked: bool) -> None:
        self.preferences["live_preview"] = bool(checked)
        self._save_preferences()
        if checked:
            self._schedule_live_preview(force=True)
        else:
            self.live_timer.stop()

    # ---------- Preview / printing ----------
    def export_pdf(self) -> None:
        source = self.preview.current_path()
        if source is None or not source.is_file():
            show_message(self, QMessageBox.Icon.Information, "Export PDF", "Compile the document successfully before exporting its PDF.")
            return
        suggested = (self.file_path.with_suffix(".pdf") if self.file_path else Path.home() / "Untitled.pdf")
        path, _ = QFileDialog.getSaveFileName(self, app_dialog_title("Export Compiled PDF"), str(suggested), "PDF Document (*.pdf)")
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".pdf": target = target.with_suffix(".pdf")
        if target.exists() and not confirm_message(self, "Replace PDF", f"Replace the existing PDF?\n\n{target}"):
            return
        try:
            shutil.copy2(source, target)
        except OSError as error:
            show_message(self, QMessageBox.Icon.Critical, "Export Failed", str(error))
            return
        self.statusBar().showMessage(f"Exported {target.name}", 3000)

    def print_document(self) -> None:
        if not self.preview.is_ready():
            show_message(self, QMessageBox.Icon.Information, "Print", "Compile the document successfully before printing.")
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        if self.preview.document is not None:
            printer.setFromTo(1, self.preview.document.pageCount())
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle(app_dialog_title("Print"))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        ok, error = self.preview.render_to_printer(printer)
        if not ok:
            output = printer.outputFileName()
            try:
                if output and os.path.isfile(output) and os.path.getsize(output) == 0:
                    os.remove(output)
            except OSError:
                pass
            show_message(self, QMessageBox.Icon.Critical, "Print Failed", error)

    def preview_fit_width(self): self.preview.fit_width()
    def preview_fit_page(self): self.preview.fit_page()
    def preview_actual_size(self): self.preview.actual_size()
    def preview_page_step(self, amount: int): self.preview.page_step(amount)

    # ---------- View ----------
    def set_view_mode(self, mode: str, *, save: bool = True) -> None:
        if mode not in {"source", "split", "preview"}: mode = "split"
        self.preferences["view_mode"] = mode
        self.source_container.setVisible(mode in {"source", "split"})
        self.preview_container.setVisible(mode in {"preview", "split"})
        self.source_only_action.setChecked(mode == "source")
        self.split_view_action.setChecked(mode == "split")
        self.preview_only_action.setChecked(mode == "preview")
        if mode != "source":
            self._schedule_live_preview(force=True)
        else:
            self.live_timer.stop()
        if save: self._save_preferences()

    def toggle_line_numbers(self, checked: bool) -> None:
        self.preferences["line_numbers"] = bool(checked); self.editor.set_line_numbers_visible(checked); self._save_preferences()

    def toggle_word_wrap(self, checked: bool) -> None:
        self.preferences["word_wrap"] = bool(checked); self.editor.set_word_wrap_enabled(checked); self._save_preferences()

    def toggle_continuous(self, checked: bool) -> None:
        self.preferences["continuous_preview"] = bool(checked); self.preview.set_continuous(checked); self._save_preferences()

    def toggle_diagnostics(self, checked: bool) -> None:
        self.preferences["show_diagnostics"] = bool(checked); self.diagnostics_dock.setVisible(checked); self._save_preferences()

    def _diagnostics_visibility_changed(self, visible: bool) -> None:
        self.show_diagnostics_action.setChecked(visible)
        self.preferences["show_diagnostics"] = bool(visible)

    def toggle_outline(self, checked: bool) -> None:
        self.preferences["show_outline"] = bool(checked); self.outline_dock.setVisible(checked); self._save_preferences()
        if checked: self._rebuild_outline()

    def _outline_visibility_changed(self, visible: bool) -> None:
        self.outline_action.setChecked(visible)
        self.preferences["show_outline"] = bool(visible)

    def choose_source_theme(self) -> None:
        options = ["System", "Dark", "Light"]
        current = self.preferences.get("source_theme", "system").capitalize()
        choice, ok = QInputDialog.getItem(self, app_dialog_title("Editing Field Theme"), "Source editing field:", options, max(0, options.index(current) if current in options else 0), False)
        if ok:
            self.preferences["source_theme"] = choice.lower(); self._apply_source_theme(); self._save_preferences()

    def choose_command_library_position(self) -> None:
        labels = {
            "left": "Left Sidebar",
            "right": "Right Sidebar",
            "disabled": "Floating Only",
        }
        values = ["left", "right", "disabled"]
        options = [labels[value] for value in values]
        current_value = self.preferences.get("command_library_sidebar_position", "disabled")
        current_index = values.index(current_value) if current_value in values else 2
        choice, ok = QInputDialog.getItem(
            self,
            app_dialog_title("Command Library Position"),
            "Command Library:",
            options,
            current_index,
            False,
        )
        if ok:
            self.set_command_library_sidebar_position(values[options.index(choice)])

    def _apply_source_theme(self) -> None:
        theme = self.preferences.get("source_theme", "system")
        if theme == "system":
            base = self.palette().color(self.backgroundRole())
            theme = "dark" if base.lightness() < 128 else "light"
        self.editor.apply_scheme(theme)
        self.diagnostics_text.apply_scheme(theme)

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.StyleChange, QEvent.Type.ApplicationPaletteChange):
            self._refresh_action_icons()
            if hasattr(self, "ribbon_buttons"):
                for button in self.ribbon_buttons:
                    default = button.defaultAction()
                    if default is not None and not default.icon().isNull():
                        button.setIcon(default.icon())
        super().changeEvent(event)

    # ---------- Status / state ----------
    def _update_cursor_status(self) -> None:
        cursor = self.editor.textCursor()
        total_lines = max(1, self.editor.blockCount())
        self.counter_label.setText(f"Ln: {cursor.blockNumber()+1}/{total_lines}, Col: {cursor.positionInBlock()+1}, Char: {len(self.editor.toPlainText())}")

    def _preview_page_changed(self, current: int, total: int) -> None:
        self.page_label.setText(f"Page: {current}/{total}" if total else "Page: —")

    def _update_title(self) -> None:
        name = self.file_path.name if self.file_path else "Untitled.tex"
        marker = "*" if self.editor.is_modified() else ""
        self.setWindowTitle(f"{marker}{name} — {APP_NAME}")
        self.path_label.setText(str(self.file_path) if self.file_path else "Untitled.tex")
        self.path_label.setToolTip(str(self.file_path) if self.file_path else "Untitled.tex")

    def _update_action_state(self) -> None:
        is_tex = self.file_path is None or self.file_path.suffix.lower() == ".tex"
        running = self.compiler.is_running()
        self.quick_compile_action.setEnabled(is_tex and not running)
        self.full_compile_action.setEnabled(is_tex and not running)
        self.stop_compile_action.setEnabled(running)
        ready = self.preview.is_ready()
        self.print_action.setEnabled(ready)
        self.export_pdf_action.setEnabled(ready)
        for action in (self.fit_width_action, self.fit_page_action, self.zoom_out_action, self.zoom_reset_action, self.zoom_in_action, self.continuous_action):
            action.setEnabled(PDF_AVAILABLE)

    def _update_all_state(self) -> None:
        self.editor.set_source_language(self.current_source_language())
        self._update_title(); self._update_cursor_status(); self._update_action_state()
        self.encoding_label.setText(self.file_encoding.upper())
        self._rebuild_outline()
        self._refresh_command_library_views()

    # ---------- Help ----------
    def open_documentation(self) -> None:
        readme = self.paths.package_root / "README.md"
        if readme.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(readme)))
        else:
            show_message(self, QMessageBox.Icon.Information, "Documentation", "README.md was not found beside this Texypad build.")

    def show_shortcuts(self) -> None:
        rows = [
            ("File", self.new_action), ("File", self.open_action), ("File", self.save_action), ("File", self.save_as_action), ("File", self.print_action),
            ("Edit", self.undo_action), ("Edit", self.redo_action), ("Edit", self.find_action), ("Edit", self.replace_action), ("Edit", self.goto_action), ("Edit", self.comment_action), ("Edit", self.duplicate_action),
            ("Build", self.quick_compile_action), ("Build", self.full_compile_action), ("Build", self.stop_compile_action),
            ("Insert", self.section_action), ("Insert", self.subsection_action), ("Insert", self.subsubsection_action), ("Insert", self.bold_action), ("Insert", self.italic_action), ("Insert", self.inline_math_action), ("Insert", self.display_math_action),
            ("View", self.zoom_out_action), ("View", self.zoom_reset_action), ("View", self.zoom_in_action),
        ]
        dialog = QDialog(self)
        dialog.setWindowTitle(app_dialog_title("Keyboard Shortcuts"))
        dialog.resize(620, 500)
        layout = QVBoxLayout(dialog)
        table = QTreeWidget(dialog)
        table.setHeaderLabels(["Group", "Command", "Shortcut"])
        for group, action in rows:
            table.addTopLevelItem(QTreeWidgetItem([group, action.text(), action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)]))
        table.resizeColumnToContents(0); table.resizeColumnToContents(1)
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject); buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def show_about(self) -> None:
        if self.about_dialog is not None:
            self.about_dialog.show()
            self.about_dialog.raise_()
            self.about_dialog.activateWindow()
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(app_dialog_title("About"))
        dialog.setWindowIcon(self.windowIcon())
        dialog.setModal(False)
        dialog.setMinimumWidth(390)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(10)

        if self.paths.icon_path.is_file():
            logo = QLabel(dialog)
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = QPixmap(str(self.paths.icon_path))
            if not pixmap.isNull():
                logo.setPixmap(
                    pixmap.scaled(
                        112,
                        112,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                layout.addWidget(logo)

        application_name = QLabel(f"<h2>{APP_NAME}</h2>", dialog)
        application_name.setTextFormat(Qt.TextFormat.RichText)
        application_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(application_name)

        version = QLabel(f"Version {APP_VERSION}", dialog)
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        tagline = QLabel("<b>Friendly. Fast. Focused.</b>", dialog)
        tagline.setTextFormat(Qt.TextFormat.RichText)
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline)

        description = QLabel(
            "A lightweight Pad-family LaTeX editor combining syntax-aware source "
            "editing, asynchronous TeX compilation and an integrated PDF print view.",
            dialog,
        )
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(description)

        preferences_path = html.escape(str(self.paths.config_path))
        details = QLabel(
            f"<a href='{GITHUB_URL}'>{GITHUB_URL}</a><br>"
            "Built on Python and PyQt6; combining Ricopad-inspired Ribbon authoring, "
            "Sheepy Pad-inspired source/process handling and Portapad-inspired PDF preview.<br>"
            f"<b>Preferences:</b> {preferences_path}<br><br>"
            "Copyright © 2026 Bruno Machado<br>"
            "[<a href='https://github.com/brunonlinespace/'>"
            "https://github.com/brunonlinespace/</a>]<br>"
            "Licensed under the GNU General Public License v3 or later.",
            dialog,
        )
        details.setTextFormat(Qt.TextFormat.RichText)
        details.setAlignment(Qt.AlignmentFlag.AlignCenter)
        details.setOpenExternalLinks(True)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(details)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, dialog)
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("OK")
        buttons.accepted.connect(dialog.close)
        layout.addWidget(buttons)
        dialog.finished.connect(lambda _result: setattr(self, "about_dialog", None))
        self.about_dialog = dialog
        dialog.show()

    # ---------- Drag/drop and close ----------
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and any(url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in {".tex", ".sty", ".cls", ".bib"} for url in event.mimeData().urls()):
            event.acceptProposedAction(); return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in {".tex", ".sty", ".cls", ".bib"}]
        if not paths: event.ignore(); return
        first, rest = paths[0], paths[1:]
        if self.load_file(first):
            for path in rest[:63]:
                window = TexypadWindow(str(path)); window.show()
        event.acceptProposedAction()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._maybe_save_changes():
            event.ignore(); return
        self.live_timer.stop(); self.outline_timer.stop()
        # Save the final source/print splitter size and Library choices before
        # marking the window as closing; _save_preferences intentionally ignores
        # late writes once teardown has started.
        self._save_preferences()
        self._closing = True
        self.preview.clear()
        self.compiler.close()
        event.accept()


def apply_appimage_theme(application: QApplication, package_root: Path) -> None:
    requested = os.environ.get("TEXYPAD_APPIMAGE_THEME", "").strip().lower()
    if requested not in {"dark", "light", "system"}:
        return
    if requested == "system":
        application.setStyleSheet("")
        return
    qss = package_root / "packaging" / "appimage" / "styles" / f"breeze-{requested}.qss"
    try:
        application.setStyleSheet(qss.read_text(encoding="utf-8"))
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Texypad lightweight LaTeX editor")
    parser.add_argument("files", nargs="*", help="Optional .tex/.sty/.cls/.bib files to open")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--texypad-smoke-test", action="store_true", help=argparse.SUPPRESS)
    args, qt_args = parser.parse_known_args(argv)
    application = QApplication([sys.argv[0], *qt_args])
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(APP_VERSION)
    application.setOrganizationName(ORGANIZATION_NAME)
    application.setOrganizationDomain("brunonlinespace")
    paths = RuntimePaths.detect()
    if paths.icon_path.is_file(): application.setWindowIcon(QIcon(str(paths.icon_path)))
    apply_appimage_theme(application, paths.package_root)
    initial = args.files[0] if args.files else None
    window = TexypadWindow(initial)
    window.show()
    for extra in args.files[1:64]:
        additional = TexypadWindow(extra)
        additional.show()
    if args.texypad_smoke_test:
        QTimer.singleShot(250, application.quit)
    status = application.exec()
    if args.texypad_smoke_test and status == 0:
        print("GUI smoke test passed.", flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
