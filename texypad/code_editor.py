"""LaTeX-oriented source editor derived from Sheepy Pad's editor conventions."""
from __future__ import annotations

import re
from dataclasses import dataclass

from PyQt6.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QSyntaxHighlighter,
)
from PyQt6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget


EDITOR_SCHEMES = {
    "dark": {
        "background": "#1e1e1e", "foreground": "#d4d4d4", "border": "#3f3f46",
        "selection": "#264f78", "gutter": "#181818", "gutter_text": "#858585",
        "current_line": "#2a2d2e", "command": "#4fc1ff", "environment": "#c586c0",
        "comment": "#6a9955", "math": "#dcdcaa", "brace": "#9cdcfe",
        "string": "#ce9178", "number": "#b5cea8", "special": "#4ec9b0",
    },
    "light": {
        "background": "#ffffff", "foreground": "#202124", "border": "#aeb4ba",
        "selection": "#b8d7f0", "gutter": "#f0f2f4", "gutter_text": "#687078",
        "current_line": "#eef5fb", "command": "#005a9c", "environment": "#7b2f91",
        "comment": "#2e7d32", "math": "#795e26", "brace": "#006b6b",
        "string": "#a31515", "number": "#805000", "special": "#006b6b",
    },
}


@dataclass(frozen=True, slots=True)
class Rule:
    pattern: re.Pattern[str]
    fmt: QTextCharFormat


def _fmt(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    value = QTextCharFormat()
    value.setForeground(QColor(color))
    value.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
    value.setFontItalic(italic)
    return value


class LatexHighlighter(QSyntaxHighlighter):
    """Fast regular-expression highlighter for TeX/LaTeX source."""

    def __init__(self, document: QTextDocument, scheme: str = "dark") -> None:
        super().__init__(document)
        c = EDITOR_SCHEMES["light" if scheme == "light" else "dark"]
        command = _fmt(c["command"], bold=True)
        env = _fmt(c["environment"], bold=True)
        math = _fmt(c["math"])
        brace = _fmt(c["brace"])
        string = _fmt(c["string"])
        number = _fmt(c["number"])
        special = _fmt(c["special"])
        self.comment_fmt = _fmt(c["comment"], italic=True)
        self.rules = (
            Rule(re.compile(r"\\(?:begin|end)\s*\{([^{}]+)\}"), env),
            Rule(re.compile(r"\\[A-Za-z@]+\*?|\\."), command),
            Rule(re.compile(r"\$\$.*?\$\$|(?<!\\)\$[^$]*?(?<!\\)\$"), math),
            Rule(re.compile(r"[{}\[\]]"), brace),
            Rule(re.compile(r"(?:\\(?:label|ref|pageref|cite|citep|citet|url|href))\s*\{[^{}]*\}"), string),
            Rule(re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?"), number),
            Rule(re.compile(r"[#&_^~]"), special),
        )

    @staticmethod
    def _comment_start(text: str) -> int:
        for index, char in enumerate(text):
            if char != "%":
                continue
            backslashes = 0
            pos = index - 1
            while pos >= 0 and text[pos] == "\\":
                backslashes += 1
                pos -= 1
            if backslashes % 2 == 0:
                return index
        return -1

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        comment_at = self._comment_start(text)
        code = text if comment_at < 0 else text[:comment_at]
        for rule in self.rules:
            for match in rule.pattern.finditer(code):
                if match.lastindex:
                    start, end = match.span(match.lastindex)
                else:
                    start, end = match.span()
                self.setFormat(start, end - start, rule.fmt)
        if comment_at >= 0:
            self.setFormat(comment_at, len(text) - comment_at, self.comment_fmt)


class BibHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, scheme: str = "dark") -> None:
        super().__init__(document)
        c = EDITOR_SCHEMES["light" if scheme == "light" else "dark"]
        self.entry = _fmt(c["environment"], bold=True)
        self.field = _fmt(c["command"], bold=True)
        self.string = _fmt(c["string"])
        self.comment = _fmt(c["comment"], italic=True)

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        stripped = text.lstrip()
        offset = len(text) - len(stripped)
        if stripped.startswith("%"):
            self.setFormat(offset, len(stripped), self.comment)
            return
        m = re.match(r"\s*@([A-Za-z]+)\s*\{\s*([^,]+)", text)
        if m:
            self.setFormat(m.start(1), len(m.group(1)), self.entry)
            self.setFormat(m.start(2), len(m.group(2)), self.string)
        m = re.match(r"\s*([A-Za-z][A-Za-z0-9_-]*)\s*=", text)
        if m:
            self.setFormat(m.start(1), len(m.group(1)), self.field)


class LineNumberArea(QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:  # noqa: N802
        self.editor.paint_line_number_area(event)


class CodeEditor(QPlainTextEdit):
    go_to_line_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scheme = "dark"
        self._language = "latex"
        self._line_numbers_visible = True
        self._line_number_area = LineNumberArea(self)
        self._highlighter: QSyntaxHighlighter | None = None
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._update_line_number_area)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fixed.setPointSize(max(10, fixed.pointSize()))
        self.setFont(fixed)
        self._replace_highlighter()
        self.apply_scheme("dark")
        self._update_margin()

    def set_source_language(self, language: str) -> None:
        language = "bib" if language == "bib" else "latex"
        if language != self._language:
            self._language = language
            self._replace_highlighter()

    def apply_scheme(self, scheme: str) -> None:
        self._scheme = "light" if scheme == "light" else "dark"
        c = EDITOR_SCHEMES[self._scheme]
        self.setStyleSheet(
            "QPlainTextEdit {"
            f"background:{c['background']}; color:{c['foreground']};"
            f"border:1px solid {c['border']}; selection-background-color:{c['selection']};"
            "}"
        )
        self._replace_highlighter()
        self._highlight_current_line()
        self.viewport().update()

    def _replace_highlighter(self) -> None:
        if self._highlighter is not None:
            self._highlighter.setDocument(None)
        cls = BibHighlighter if self._language == "bib" else LatexHighlighter
        self._highlighter = cls(self.document(), self._scheme)

    def set_line_numbers_visible(self, visible: bool) -> None:
        self._line_numbers_visible = bool(visible)
        self._line_number_area.setVisible(self._line_numbers_visible)
        self._update_margin()

    def set_word_wrap_enabled(self, enabled: bool) -> None:
        self.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if enabled else QPlainTextEdit.LineWrapMode.NoWrap
        )

    def set_tab_width_spaces(self, spaces: int) -> None:
        spaces = min(16, max(1, int(spaces)))
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * spaces)

    def line_number_area_width(self) -> int:
        if not self._line_numbers_visible:
            return 0
        digits = max(1, len(str(max(1, self.blockCount()))))
        return 10 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margin(self, _count: int = 0) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margin()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        rect = self.contentsRect()
        self._line_number_area.setGeometry(QRect(rect.left(), rect.top(), self.line_number_area_width(), rect.height()))

    def paint_line_number_area(self, event) -> None:
        c = EDITOR_SCHEMES[self._scheme]
        painter = QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QColor(c["gutter"]))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        current = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor(c["foreground"] if number == current else c["gutter_text"]))
                painter.drawText(0, top, self._line_number_area.width() - 5, self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    def _highlight_current_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor(EDITOR_SCHEMES[self._scheme]["current_line"]))
        selection.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.matches(QKeySequence.StandardKey.Find):
            super().keyPressEvent(event)
            return
        if event.key() == Qt.Key.Key_G and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.go_to_line_requested.emit()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._insert_newline_with_indent()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Tab and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self._indent_selection_or_insert_spaces()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Backtab:
            self._unindent_selection_or_line()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Slash and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.toggle_comment()
            event.accept()
            return
        if event.key() == Qt.Key.Key_D and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.duplicate_current_line_or_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def _insert_newline_with_indent(self) -> None:
        cursor = self.textCursor()
        cursor.beginEditBlock()
        block_text = cursor.block().text()
        leading = re.match(r"\s*", block_text).group(0)
        before = block_text[: cursor.positionInBlock()]
        extra = ""
        if re.search(r"\\begin\{[^{}]+\}\s*(?:%.*)?$", before):
            extra = "    "
        cursor.insertText("\n" + leading + extra)
        cursor.endEditBlock()
        self.setTextCursor(cursor)

    def _selected_block_cursors(self) -> tuple[QTextCursor, QTextCursor]:
        cursor = self.textCursor()
        start = QTextCursor(self.document())
        start.setPosition(cursor.selectionStart())
        end = QTextCursor(self.document())
        end.setPosition(cursor.selectionEnd())
        if end.positionInBlock() == 0 and end.position() > start.position():
            end.movePosition(QTextCursor.MoveOperation.PreviousBlock)
        return start, end

    def _indent_selection_or_insert_spaces(self) -> None:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            spaces = 4 - (cursor.positionInBlock() % 4)
            cursor.insertText(" " * spaces)
            return
        start, end = self._selected_block_cursors()
        first, last = start.blockNumber(), end.blockNumber()
        cursor.beginEditBlock()
        block = self.document().findBlockByNumber(first)
        for _ in range(first, last + 1):
            c = QTextCursor(block)
            c.insertText("    ")
            block = block.next()
        cursor.endEditBlock()

    def _unindent_selection_or_line(self) -> None:
        start, end = self._selected_block_cursors()
        first, last = start.blockNumber(), end.blockNumber()
        cursor = self.textCursor()
        cursor.beginEditBlock()
        block = self.document().findBlockByNumber(first)
        for _ in range(first, last + 1):
            text = block.text()
            remove = 1 if text.startswith("\t") else min(4, len(text) - len(text.lstrip(" ")))
            if remove:
                c = QTextCursor(block)
                c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, remove)
                c.removeSelectedText()
            block = block.next()
        cursor.endEditBlock()

    def toggle_comment(self) -> None:
        prefix = "%"
        start, end = self._selected_block_cursors()
        first, last = start.blockNumber(), end.blockNumber()
        blocks = [self.document().findBlockByNumber(i) for i in range(first, last + 1)]
        uncomment = all(block.text().lstrip().startswith(prefix) for block in blocks if block.text().strip())
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for block in blocks:
            text = block.text()
            if uncomment:
                index = len(text) - len(text.lstrip())
                if text[index:index + 1] == prefix:
                    c = QTextCursor(block)
                    c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, index)
                    c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                    c.removeSelectedText()
                    if block.text()[index:index + 1] == " ":
                        c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                        c.removeSelectedText()
            else:
                c = QTextCursor(block)
                c.insertText("% ")
        cursor.endEditBlock()

    def duplicate_current_line_or_selection(self) -> None:
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            text = cursor.selectedText().replace("\u2029", "\n")
            cursor.setPosition(cursor.selectionEnd())
            cursor.insertText(text)
        else:
            block = cursor.block()
            text = block.text()
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
            cursor.insertText("\n" + text)
        cursor.endEditBlock()

    def go_to_line(self, line_number: int) -> bool:
        block = self.document().findBlockByNumber(max(0, int(line_number) - 1))
        if not block.isValid():
            return False
        cursor = QTextCursor(block)
        self.setTextCursor(cursor)
        self.centerCursor()
        return True

    def mark_clean(self) -> None:
        self.document().setModified(False)

    def is_modified(self) -> bool:
        return self.document().isModified()
