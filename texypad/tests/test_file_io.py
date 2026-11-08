from pathlib import Path
import tempfile
import unittest

from texypad.file_io import UnsupportedFileError, atomic_write_text, read_text_file, validate_source_path


class FileIoTests(unittest.TestCase):
    def test_atomic_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.tex"
            atomic_write_text(path, "\\section{Hello}\n")
            text, encoding, bom, newline = read_text_file(path)
            self.assertEqual(text, "\\section{Hello}\n")
            self.assertEqual(encoding, "utf-8")
            self.assertEqual(bom, b"")
            self.assertEqual(newline, "\n")

    def test_rejects_other_suffix(self):
        with self.assertRaises(UnsupportedFileError):
            validate_source_path(Path("notes.txt"), must_exist=False)


if __name__ == "__main__":
    unittest.main()
