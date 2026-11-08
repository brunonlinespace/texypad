"""Small, testable helpers for safe Texypad source-file I/O."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

MAX_FILE_SIZE = 25 * 1024 * 1024
SUPPORTED_SUFFIXES = {".tex", ".sty", ".cls", ".bib"}


class FileTooLargeError(OSError):
    pass


class UnsupportedFileError(OSError):
    pass


def absolute_user_path(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.fspath(Path(value).expanduser())))


def validate_source_path(path: Path, *, must_exist: bool = True) -> Path:
    path = absolute_user_path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedFileError("Texypad opens .tex, .sty, .cls and .bib source files only.")
    if must_exist:
        if not path.exists() or not path.is_file():
            raise UnsupportedFileError("The selected path is not a regular file.")
        if path.stat().st_size > MAX_FILE_SIZE:
            raise FileTooLargeError("The file exceeds Texypad's 25 MiB responsiveness limit.")
    return path


def read_text_file(path: Path) -> tuple[str, str, bytes, str]:
    path = validate_source_path(path)
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_SIZE:
        raise FileTooLargeError("The file exceeds Texypad's 25 MiB responsiveness limit.")
    bom = b""
    encoding = "utf-8"
    if raw.startswith(b"\xef\xbb\xbf"):
        bom = b"\xef\xbb\xbf"
        raw = raw[3:]
        encoding = "utf-8"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
        encoding = "latin-1"
    newline = "\r\n" if b"\r\n" in raw else "\n"
    return text.replace("\r\n", "\n").replace("\r", "\n"), encoding, bom, newline


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8", bom: bytes = b"", newline: str = "\n") -> None:
    path = validate_source_path(path, must_exist=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalised = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    payload = bom + normalised.encode(encoding)
    if len(payload) > MAX_FILE_SIZE:
        raise FileTooLargeError("The document exceeds Texypad's 25 MiB responsiveness limit.")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            mode = path.stat().st_mode & 0o777
            os.chmod(temp_name, mode)
        except OSError:
            pass
        os.replace(temp_name, path)
        if os.name != "nt":
            try:
                dfd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:
                pass
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except OSError:
            pass
