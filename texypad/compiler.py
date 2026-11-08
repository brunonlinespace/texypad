"""Asynchronous TeX compilation controller using Sheepy-style QProcess handling."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, pyqtSignal


ENGINE_NAMES = ("pdflatex", "xelatex", "lualatex")
MAX_LOG_CHARS = 256_000
MAX_PREVIEW_PDF_BYTES = 512 * 1024 * 1024


class LatexCompiler(QObject):
    compile_started = pyqtSignal(str, bool)
    compile_finished = pyqtSignal(bool, str, str, bool)
    status_message = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.readyReadStandardError.connect(self._read_error)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self._temp = tempfile.TemporaryDirectory(prefix="texypad-")
        self._root = Path(self._temp.name)
        self._generation = 0
        self._build_dir: Path | None = None
        self._snapshot: Path | None = None
        self._source_dir: Path | None = None
        self._jobname = "texypad-preview"
        self._engine = ""
        self._engine_path = ""
        self._full = False
        self._log_parts: list[str] = []
        self._pipeline: list[tuple[str, list[str], Path]] = []
        self._current_stage = ""
        self._cancelled = False
        self._last_snapshot_hash = ""

    @staticmethod
    def available_engines() -> dict[str, str]:
        return {name: path for name in ENGINE_NAMES if (path := shutil.which(name))}

    @staticmethod
    def available_bibliography_tools() -> dict[str, str]:
        result = {}
        for name in ("biber", "bibtex"):
            path = shutil.which(name)
            if path:
                result[name] = path
        return result

    def is_running(self) -> bool:
        return self.process.state() != QProcess.ProcessState.NotRunning

    def stop(self) -> None:
        if not self.is_running():
            return
        self._cancelled = True
        self._pipeline.clear()
        self.process.terminate()
        if not self.process.waitForFinished(1200):
            self.process.kill()
        self.status_message.emit("Compilation stopped.")

    def close(self) -> None:
        self.stop()
        self._temp.cleanup()

    def compile_snapshot(
        self,
        text: str,
        source_path: Path | None,
        *,
        engine: str = "pdflatex",
        full: bool = False,
        force: bool = False,
    ) -> bool:
        if self.is_running():
            return False
        engines = self.available_engines()
        if engine not in engines:
            self.status_message.emit(f"{engine} was not found on the host system.")
            return False
        digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        signature = f"{engine}:{int(full)}:{digest}:{source_path or ''}"
        if not force and signature == self._last_snapshot_hash:
            self.status_message.emit("Preview is already current.")
            return False

        self._generation += 1
        build_dir = self._root / f"build-{self._generation:06d}"
        build_dir.mkdir(mode=0o700)
        self._build_dir = build_dir
        self._snapshot = build_dir / f"{self._jobname}.tex"
        self._snapshot.write_text(text, encoding="utf-8", newline="\n")
        self._source_dir = source_path.parent if source_path else Path.cwd()
        self._engine = engine
        self._engine_path = engines[engine]
        self._full = bool(full)
        self._cancelled = False
        self._log_parts = []
        self._pipeline = []
        self._last_snapshot_hash = signature

        engine_args = self._engine_arguments()
        self._pipeline.append(("LaTeX pass 1", [self._engine_path, *engine_args], self._source_dir))
        if self._full:
            # A bibliography stage is selected after pass 1, once .bcf/.aux exist.
            self._pipeline.append(("__bibliography__", [], build_dir))
            self._pipeline.append(("LaTeX pass 2", [self._engine_path, *engine_args], self._source_dir))
            self._pipeline.append(("LaTeX pass 3", [self._engine_path, *engine_args], self._source_dir))

        self.compile_started.emit(engine, full)
        self._start_next_stage()
        return True

    def _engine_arguments(self) -> list[str]:
        assert self._build_dir is not None and self._snapshot is not None
        return [
            "-interaction=nonstopmode",
            "-file-line-error",
            "-halt-on-error",
            "-no-shell-escape",
            f"-output-directory={self._build_dir}",
            str(self._snapshot),
        ]

    def _environment(self) -> QProcessEnvironment:
        env = QProcessEnvironment.systemEnvironment()
        source = str(self._source_dir or Path.cwd())
        for key in ("TEXINPUTS", "BIBINPUTS", "BSTINPUTS"):
            previous = env.value(key)
            value = source + os.pathsep + previous if previous else source + os.pathsep
            env.insert(key, value)
        return env

    def _start_next_stage(self) -> None:
        if self._cancelled:
            return
        if not self._pipeline:
            self._finish_pipeline()
            return
        stage, command, cwd = self._pipeline.pop(0)
        if stage == "__bibliography__":
            self._insert_bibliography_stage()
            self._start_next_stage()
            return
        self._current_stage = stage
        self._append_log(f"\n===== {stage} =====\n$ {' '.join(command)}\n")
        self.process.setWorkingDirectory(str(cwd))
        self.process.setProcessEnvironment(self._environment())
        self.process.setProgram(command[0])
        self.process.setArguments(command[1:])
        self.process.start()

    def _insert_bibliography_stage(self) -> None:
        assert self._build_dir is not None
        tools = self.available_bibliography_tools()
        bcf = self._build_dir / f"{self._jobname}.bcf"
        aux = self._build_dir / f"{self._jobname}.aux"
        stage: tuple[str, list[str], Path] | None = None
        if bcf.exists() and "biber" in tools:
            stage = ("Biber", [tools["biber"], self._jobname], self._build_dir)
        elif aux.exists() and "bibtex" in tools:
            try:
                aux_text = aux.read_text(encoding="utf-8", errors="replace")
            except OSError:
                aux_text = ""
            if "\\bibdata" in aux_text:
                stage = ("BibTeX", [tools["bibtex"], self._jobname], self._build_dir)
        if stage is not None:
            self._pipeline.insert(0, stage)

    def _read_output(self) -> None:
        self._append_log(bytes(self.process.readAllStandardOutput()).decode(errors="replace"))

    def _read_error(self) -> None:
        self._append_log(bytes(self.process.readAllStandardError()).decode(errors="replace"))

    def _append_log(self, text: str) -> None:
        if not text:
            return
        self._log_parts.append(text)
        total = sum(len(part) for part in self._log_parts)
        if total > MAX_LOG_CHARS:
            joined = "".join(self._log_parts)
            self._log_parts = ["[earlier compiler output truncated]\n" + joined[-MAX_LOG_CHARS:]]

    def _process_error(self, error) -> None:
        if self._cancelled:
            return
        self._append_log(f"\nTexypad could not start or continue {self._current_stage}.\n")
        if error == QProcess.ProcessError.FailedToStart:
            self._pipeline.clear()
            self._emit_finished(False, "")

    def _process_finished(self, exit_code: int, _status) -> None:
        self._read_output()
        self._read_error()
        if self._cancelled:
            self._emit_finished(False, "")
            return
        if exit_code != 0:
            self._append_log(f"\n{self._current_stage} exited with code {exit_code}.\n")
            self._emit_finished(False, "")
            return
        self._start_next_stage()

    def _finish_pipeline(self) -> None:
        assert self._build_dir is not None
        pdf = self._build_dir / f"{self._jobname}.pdf"
        if not pdf.is_file():
            self._append_log("\nCompilation completed without producing a PDF.\n")
            self._emit_finished(False, "")
            return
        try:
            if pdf.stat().st_size > MAX_PREVIEW_PDF_BYTES:
                self._append_log("\nThe generated PDF exceeds the 512 MiB preview safety limit.\n")
                self._emit_finished(False, "")
                return
        except OSError as error:
            self._append_log(f"\nCould not inspect generated PDF: {error}\n")
            self._emit_finished(False, "")
            return
        self._cleanup_old_builds(keep=3)
        self._emit_finished(True, str(pdf))

    def _emit_finished(self, success: bool, pdf_path: str) -> None:
        log = "".join(self._log_parts)
        self.compile_finished.emit(success, pdf_path, log, self._full)
        self._current_stage = ""

    def _cleanup_old_builds(self, keep: int = 3) -> None:
        dirs = sorted((p for p in self._root.glob("build-*") if p.is_dir()), key=lambda p: p.name)
        for old in dirs[:-keep]:
            try:
                shutil.rmtree(old)
            except OSError:
                pass

    @staticmethod
    def compact_errors(log: str, limit: int = 200) -> list[str]:
        """Return a compact set of TeX file:line/errors for the diagnostics pane."""
        lines: list[str] = []
        seen: set[str] = set()
        patterns = (
            re.compile(r"^(.+?\.tex):(\d+):\s*(.+)$"),
            re.compile(r"^!\s+(.+)$"),
            re.compile(r"^(LaTeX Warning:.*)$"),
            re.compile(r"^(Package .* Warning:.*)$"),
        )
        for raw in log.splitlines():
            text = raw.strip()
            if not text:
                continue
            selected = None
            for pattern in patterns:
                match = pattern.match(text)
                if match:
                    selected = text
                    break
            if selected and selected not in seen:
                seen.add(selected)
                lines.append(selected)
                if len(lines) >= limit:
                    lines.append("… diagnostics truncated …")
                    break
        return lines
