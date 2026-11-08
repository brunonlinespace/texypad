import json
import unittest

from texypad.command_io import build_command_collection, parse_command_collection
from texypad.latex_commands import (
    COMMAND_BY_KEY,
    CURSOR_TOKEN,
    SELECTION_TOKEN,
    render_template,
    validate_custom_command,
)


class CommandLibraryTests(unittest.TestCase):
    def test_builtin_section_renders_real_tex(self):
        spec = COMMAND_BY_KEY["section"]
        rendered, caret = render_template(spec, "Introduction")
        self.assertEqual(rendered, r"\section{Introduction}")
        self.assertEqual(caret, len(r"\section{Introduction"))

    def test_environment_uses_real_newlines(self):
        spec = COMMAND_BY_KEY["itemize"]
        rendered, _caret = render_template(spec, "First item")
        self.assertIn("\n", rendered)
        self.assertIn(r"\begin{itemize}", rendered)
        self.assertIn(r"\item First item", rendered)
        self.assertNotIn(r"\n", rendered)

    def test_custom_command_round_trip(self):
        spec = validate_custom_command(
            key=None,
            label="My theorem",
            category="Writing",
            description="A personal theorem wrapper.",
            template=f"\\begin{{theorem}}\n{SELECTION_TOKEN}{CURSOR_TOKEN}\n\\end{{theorem}}",
            languages=("latex",),
        )
        collection = build_command_collection([spec], {spec.key, "section"})
        payload = json.dumps(collection).encode("utf-8")
        custom, favourites = parse_command_collection(payload)
        self.assertEqual(len(custom), 1)
        self.assertEqual(custom[0], spec)
        self.assertEqual(favourites, {spec.key, "section"})

    def test_bibtex_builtin_is_language_scoped(self):
        self.assertEqual(COMMAND_BY_KEY["bib-article"].languages, ("bib",))


if __name__ == "__main__":
    unittest.main()
