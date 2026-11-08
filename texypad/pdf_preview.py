"""Portapad-derived Qt PDF preview surface used by Texypad."""
from __future__ import annotations

import math
import os
from pathlib import Path

from PyQt6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter
from PyQt6.QtPrintSupport import QPrinter
from PyQt6.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget

try:
    from PyQt6.QtPdf import QPdfDocument
    from PyQt6.QtPdfWidgets import QPdfView
    PDF_AVAILABLE = True
    PDF_IMPORT_ERROR = None
except ImportError as error:
    QPdfDocument = None
    QPdfView = QWidget
    PDF_AVAILABLE = False
    PDF_IMPORT_ERROR = error

MIN_ZOOM = 0.10
MAX_ZOOM = 8.00
ZOOM_STEP = math.sqrt(2.0)
MAX_PRINT_RENDER_DIMENSION = 4096


class PreviewPdfView(QPdfView):
    """QPdfView with Portapad-style Ctrl+wheel zoom and page-key ownership."""
    zoom_steps = pyqtSignal(int)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_steps.emit(1 if delta > 0 else -1)
                event.accept()
                return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_PageDown, Qt.Key.Key_PageUp):
            owner = self.window()
            if hasattr(owner, "preview_page_step"):
                owner.preview_page_step(1 if event.key() == Qt.Key.Key_PageDown else -1)
                event.accept()
                return
        super().keyPressEvent(event)


class PdfPreview(QWidget):
    """Memory-conscious PDF preview: one QPdfDocument and one visible QPdfView."""
    ready_changed = pyqtSignal(bool)
    page_changed = pyqtSignal(int, int)
    zoom_changed = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._path: Path | None = None
        self._pending_path: Path | None = None
        self._status_scheduled = False
        self._last_error = ""
        self._continuous = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack)

        self.placeholder = QLabel(
            "Compile a .tex document to display its print view here.", self.stack
        )
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setMinimumWidth(220)
        self.stack.addWidget(self.placeholder)

        if not PDF_AVAILABLE:
            self.document = None
            self.view = None
            self.placeholder.setText(
                "Qt PDF is unavailable. Install PyQt6 with QtPdf support to use the print view."
            )
            return

        self.document = QPdfDocument(self)
        self.document.statusChanged.connect(self._queue_document_status)
        self.view = PreviewPdfView(self.stack)
        self.view.setDocument(self.document)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.view.zoom_steps.connect(self.zoom_by_steps)
        self.view.zoomFactorChanged.connect(lambda value: self.zoom_changed.emit(round(value * 100)))
        navigator = self.view.pageNavigator()
        navigator.currentPageChanged.connect(self._on_page_changed)
        self.stack.addWidget(self.view)

    def is_ready(self) -> bool:
        return bool(
            PDF_AVAILABLE
            and self.document is not None
            and self.document.status() == QPdfDocument.Status.Ready
            and self.document.pageCount() > 0
        )

    def current_path(self) -> Path | None:
        return self._path

    def clear(self, message: str | None = None) -> None:
        if self.document is not None:
            self.document.close()
        self._path = None
        self._pending_path = None
        if message:
            self.placeholder.setText(message)
        self.stack.setCurrentWidget(self.placeholder)
        self.ready_changed.emit(False)
        self.page_changed.emit(0, 0)

    def load_pdf(self, path: str | os.PathLike[str]) -> tuple[bool, str]:
        if not PDF_AVAILABLE or self.document is None or self.view is None:
            return False, "Qt PDF is unavailable."
        target = Path(path)
        if not target.is_file():
            return False, "The compiled PDF could not be found."
        self.document.close()
        self._path = None
        self._pending_path = target
        self.ready_changed.emit(False)
        self.placeholder.setText("Loading compiled PDF…")
        self.stack.setCurrentWidget(self.placeholder)
        error = self.document.load(str(target))
        no_error = getattr(QPdfDocument.Error, "None_", getattr(QPdfDocument.Error, "None", None))
        data_pending = getattr(QPdfDocument.Error, "DataNotYetAvailable", object())
        if error not in (no_error, data_pending):
            self._pending_path = None
            self.placeholder.setText(f"The compiled PDF could not be loaded ({error}).")
            return False, self.placeholder.text()
        self._queue_document_status(self.document.status())
        return True, ""

    def _queue_document_status(self, _status) -> None:
        if self._status_scheduled:
            return
        self._status_scheduled = True
        QTimer.singleShot(0, self._process_document_status)

    def _process_document_status(self) -> None:
        self._status_scheduled = False
        if self.document is None or self.view is None:
            return
        status = self.document.status()
        if status == QPdfDocument.Status.Ready:
            if self._pending_path is not None:
                self._path = self._pending_path
                self._pending_path = None
            self.stack.setCurrentWidget(self.view)
            self.view.setPageMode(QPdfView.PageMode.MultiPage if self._continuous else QPdfView.PageMode.SinglePage)
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self.ready_changed.emit(True)
            self._on_page_changed(self.view.pageNavigator().currentPage())
        elif status == QPdfDocument.Status.Error:
            self._path = None
            self._pending_path = None
            self.placeholder.setText("The compiled PDF could not be loaded by Qt PDF.")
            self.stack.setCurrentWidget(self.placeholder)
            self.ready_changed.emit(False)

    def _on_page_changed(self, page: int) -> None:
        total = self.document.pageCount() if self.document is not None else 0
        self.page_changed.emit(page + 1 if total else 0, total)

    def fit_width(self) -> None:
        if self.view is not None:
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

    def fit_page(self) -> None:
        if self.view is not None:
            self.view.setZoomMode(QPdfView.ZoomMode.FitInView)

    def actual_size(self) -> None:
        self.set_zoom(1.0)

    def set_zoom(self, factor: float) -> None:
        if self.view is None or not self.is_ready():
            return
        factor = max(MIN_ZOOM, min(MAX_ZOOM, float(factor)))
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(factor)

    def zoom_by_steps(self, steps: int) -> None:
        if self.view is None or not self.is_ready():
            return
        factor = self.view.zoomFactor() * (ZOOM_STEP ** int(steps))
        self.set_zoom(factor)

    def set_continuous(self, continuous: bool) -> None:
        self._continuous = bool(continuous)
        if self.view is not None:
            self.view.setPageMode(
                QPdfView.PageMode.MultiPage if self._continuous else QPdfView.PageMode.SinglePage
            )

    def page_step(self, amount: int) -> None:
        if self.view is None or not self.is_ready():
            return
        navigator = self.view.pageNavigator()
        current = navigator.currentPage()
        target = max(0, min(self.document.pageCount() - 1, current + int(amount)))
        navigator.jump(target, navigator.currentLocation(), navigator.currentZoom())

    def render_to_printer(self, printer: QPrinter) -> tuple[bool, str]:
        if not self.is_ready() or self.document is None:
            return False, "There is no compiled PDF to print."
        page_count = self.document.pageCount()
        first = printer.fromPage() or 1
        last = printer.toPage() or page_count
        first = max(1, min(first, page_count))
        last = max(first, min(last, page_count))
        painter = QPainter()
        try:
            if not painter.begin(printer):
                raise RuntimeError("Could not initialise the printer.")
            resolution = max(1, printer.resolution())
            for page_number in range(first - 1, last):
                if page_number > first - 1 and not printer.newPage():
                    raise RuntimeError("The printer could not start a new page.")
                paint_rect = printer.pageLayout().paintRectPixels(resolution)
                page_size = self.document.pagePointSize(page_number)
                dimensions = (
                    paint_rect.width(), paint_rect.height(), page_size.width(), page_size.height()
                )
                if any(not math.isfinite(float(v)) for v in dimensions) or min(dimensions) <= 0:
                    raise RuntimeError(f"Page {page_number + 1} has invalid print dimensions.")
                scale = min(
                    paint_rect.width() / page_size.width(),
                    paint_rect.height() / page_size.height(),
                )
                target_width = page_size.width() * scale
                target_height = page_size.height() * scale
                render_width = max(1, int(round(target_width)))
                render_height = max(1, int(round(target_height)))
                largest = max(render_width, render_height)
                if largest > MAX_PRINT_RENDER_DIMENSION:
                    reduction = MAX_PRINT_RENDER_DIMENSION / largest
                    render_width = max(1, int(round(render_width * reduction)))
                    render_height = max(1, int(round(render_height * reduction)))
                image = self.document.render(page_number, QSize(render_width, render_height))
                if image.isNull():
                    raise RuntimeError(f"Page {page_number + 1} could not be rendered.")
                x = paint_rect.x() + (paint_rect.width() - target_width) / 2
                y = paint_rect.y() + (paint_rect.height() - target_height) / 2
                painter.drawImage(QRectF(x, y, target_width, target_height), image)
            return True, ""
        except Exception as error:
            return False, str(error) or "The print job could not be completed."
        finally:
            if painter.isActive():
                painter.end()
