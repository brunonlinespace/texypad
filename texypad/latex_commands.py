"""Built-in and user-defined LaTeX/BibTeX command-library metadata."""
from __future__ import annotations

from dataclasses import dataclass
import re
import uuid

SELECTION_TOKEN = "[[selection]]"
CURSOR_TOKEN = "[[cursor]]"
VALID_LANGUAGES = frozenset({"latex", "bib"})
MAX_CUSTOM_COMMANDS = 200
MAX_LABEL_LENGTH = 128
MAX_CATEGORY_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 512
MAX_TEMPLATE_LENGTH = 8192


@dataclass(frozen=True, slots=True)
class CommandSpec:
    key: str
    label: str
    category: str
    description: str
    template: str
    languages: tuple[str, ...] = ("latex",)
    builtin: bool = True

    @property
    def insertion_preview(self) -> str:
        value = self.template.replace(SELECTION_TOKEN, "…").replace(CURSOR_TOKEN, "│")
        value = value.replace("\n", " ↵ ")
        return value if len(value) <= 180 else value[:177] + "…"


def _cmd(
    key: str,
    label: str,
    category: str,
    description: str,
    template: str,
    *,
    languages: tuple[str, ...] = ("latex",),
) -> CommandSpec:
    # Built-ins below are written as visually explicit raw strings.  Collapse
    # their escaped newlines/backslashes once here so inserted text is real TeX.
    normalized_label = label.replace("\\\\", "\\")
    normalized_template = template.replace("\\n", "\n").replace("\\\\", "\\")
    return CommandSpec(key, normalized_label, category, description, normalized_template, languages, True)


BUILTIN_COMMANDS: tuple[CommandSpec, ...] = (
    _cmd("documentclass", r"\\documentclass", "Document", "Choose the LaTeX document class.", r"\\documentclass{article}\n\n[[cursor]]"),
    _cmd("usepackage", r"\\usepackage", "Document", "Load a LaTeX package.", r"\\usepackage{[[selection]][[cursor]]}"),
    _cmd("title", r"\\title", "Document", "Set the document title.", r"\\title{[[selection]][[cursor]]}"),
    _cmd("author", r"\\author", "Document", "Set the document author.", r"\\author{[[selection]][[cursor]]}"),
    _cmd("date", r"\\date", "Document", "Set the document date.", r"\\date{[[selection]][[cursor]]}"),
    _cmd("maketitle", r"\\maketitle", "Document", "Typeset title, author and date information.", r"\\maketitle\n[[cursor]]"),
    _cmd("tableofcontents", r"\\tableofcontents", "Document", "Insert a table of contents.", r"\\tableofcontents\n[[cursor]]"),
    _cmd("begin-document", "document environment", "Document", "Insert a complete document environment.", r"\\begin{document}\n[[selection]][[cursor]]\n\\end{document}"),

    _cmd("part", r"\\part", "Structure", "Insert a part heading.", r"\\part{[[selection]][[cursor]]}"),
    _cmd("chapter", r"\\chapter", "Structure", "Insert a chapter heading; supported by book/report-like classes.", r"\\chapter{[[selection]][[cursor]]}"),
    _cmd("section", r"\\section", "Structure", "Insert a section heading.", r"\\section{[[selection]][[cursor]]}"),
    _cmd("subsection", r"\\subsection", "Structure", "Insert a subsection heading.", r"\\subsection{[[selection]][[cursor]]}"),
    _cmd("subsubsection", r"\\subsubsection", "Structure", "Insert a subsubsection heading.", r"\\subsubsection{[[selection]][[cursor]]}"),
    _cmd("paragraph", r"\\paragraph", "Structure", "Insert a paragraph heading.", r"\\paragraph{[[selection]][[cursor]]}"),
    _cmd("label", r"\\label", "Structure", "Create a cross-reference label.", r"\\label{[[selection]][[cursor]]}"),

    _cmd("textbf", r"\\textbf", "Text", "Typeset bold text.", r"\\textbf{[[selection]][[cursor]]}"),
    _cmd("emph", r"\\emph", "Text", "Emphasise text according to context.", r"\\emph{[[selection]][[cursor]]}"),
    _cmd("underline", r"\\underline", "Text", "Underline text.", r"\\underline{[[selection]][[cursor]]}"),
    _cmd("texttt", r"\\texttt", "Text", "Typeset inline monospaced text.", r"\\texttt{[[selection]][[cursor]]}"),
    _cmd("footnote", r"\\footnote", "Text", "Insert a footnote.", r"\\footnote{[[selection]][[cursor]]}"),
    _cmd("quote", "quote environment", "Text", "Insert a short quotation environment.", r"\\begin{quote}\n[[selection]][[cursor]]\n\\end{quote}"),
    _cmd("quotation", "quotation environment", "Text", "Insert a multi-paragraph quotation environment.", r"\\begin{quotation}\n[[selection]][[cursor]]\n\\end{quotation}"),
    _cmd("verbatim", "verbatim environment", "Text", "Insert preformatted verbatim text.", r"\\begin{verbatim}\n[[selection]][[cursor]]\n\\end{verbatim}"),

    _cmd("inline-math", "Inline math $…$", "Math", "Insert inline mathematics.", r"$[[selection]][[cursor]]$"),
    _cmd("display-math", r"Display math \\[ … \\]", "Math", "Insert unnumbered display mathematics.", r"\\[\n[[selection]][[cursor]]\n\\]"),
    _cmd("equation", "equation environment", "Math", "Insert a numbered equation.", r"\\begin{equation}\n    [[selection]][[cursor]]\n\\end{equation}"),
    _cmd("align", "align environment", "Math", "Insert an aligned multi-line equation block; requires amsmath.", r"\\begin{align}\n    [[selection]][[cursor]]\n\\end{align}"),
    _cmd("frac", r"\\frac", "Math", "Insert a fraction.", r"\\frac{[[selection]][[cursor]]}{}"),
    _cmd("sqrt", r"\\sqrt", "Math", "Insert a square root.", r"\\sqrt{[[selection]][[cursor]]}"),
    _cmd("sum", r"\\sum", "Math", "Insert a summation with lower and upper limits.", r"\\sum_{[[selection]][[cursor]]}^{ }"),
    _cmd("int", r"\\int", "Math", "Insert an integral with limits.", r"\\int_{[[selection]][[cursor]]}^{ }"),
    _cmd("matrix", "matrix environment", "Math", "Insert a simple matrix; requires amsmath.", r"\\begin{matrix}\n    a & b \\\\\n    c & d\n\\end{matrix}[[cursor]]"),

    _cmd("itemize", "itemize environment", "Lists", "Insert a bulleted list.", r"\\begin{itemize}\n    \\item [[selection]][[cursor]]\n\\end{itemize}"),
    _cmd("enumerate", "enumerate environment", "Lists", "Insert a numbered list.", r"\\begin{enumerate}\n    \\item [[selection]][[cursor]]\n\\end{enumerate}"),
    _cmd("description", "description environment", "Lists", "Insert a description list.", r"\\begin{description}\n    \\item[Term] [[selection]][[cursor]]\n\\end{description}"),
    _cmd("item", r"\\item", "Lists", "Insert a list item.", r"\\item [[selection]][[cursor]]"),

    _cmd("figure", "figure environment", "Floats & Tables", "Insert a common figure template; includegraphics requires graphicx.", r"\\begin{figure}[htbp]\n    \\centering\n    \\includegraphics[width=0.8\\linewidth]{image-file}\n    \\caption{[[selection]][[cursor]]}\n    \\label{fig:label}\n\\end{figure}"),
    _cmd("includegraphics", r"\\includegraphics", "Floats & Tables", "Insert an image; requires graphicx.", r"\\includegraphics[width=0.8\\linewidth]{[[selection]][[cursor]]}"),
    _cmd("table", "table + tabular", "Floats & Tables", "Insert a simple floating table template.", r"\\begin{table}[htbp]\n    \\centering\n    \\begin{tabular}{ll}\n        A & B \\\\\n        C & D \\\\\n    \\end{tabular}\n    \\caption{[[selection]][[cursor]]}\n    \\label{tab:label}\n\\end{table}"),
    _cmd("tabular", "tabular environment", "Floats & Tables", "Insert a simple two-column tabular environment.", r"\\begin{tabular}{ll}\n    [[selection]][[cursor]] &  \\\\\n     &  \\\\\n\\end{tabular}"),

    _cmd("ref", r"\\ref", "References & Links", "Reference a label.", r"\\ref{[[selection]][[cursor]]}"),
    _cmd("pageref", r"\\pageref", "References & Links", "Reference the page containing a label.", r"\\pageref{[[selection]][[cursor]]}"),
    _cmd("cite", r"\\cite", "References & Links", "Insert a citation key.", r"\\cite{[[selection]][[cursor]]}"),
    _cmd("url", r"\\url", "References & Links", "Insert a URL; commonly provided by url/hyperref.", r"\\url{[[selection]][[cursor]]}"),
    _cmd("href", r"\\href", "References & Links", "Insert a hyperlink; requires hyperref.", r"\\href{[[selection]][[cursor]]}{link text}"),

    _cmd("newpage", r"\\newpage", "Layout", "Request a page break.", r"\\newpage\n[[cursor]]"),
    _cmd("clearpage", r"\\clearpage", "Layout", "Flush pending floats and start a new page.", r"\\clearpage\n[[cursor]]"),
    _cmd("noindent", r"\\noindent", "Layout", "Suppress paragraph indentation.", r"\\noindent [[selection]][[cursor]]"),
    _cmd("centering", r"\\centering", "Layout", "Switch to centred paragraph alignment within the current group/environment.", r"\\centering\n[[selection]][[cursor]]"),
    _cmd("vspace", r"\\vspace", "Layout", "Insert vertical space.", r"\\vspace{[[selection]][[cursor]]}"),
    _cmd("hspace", r"\\hspace", "Layout", "Insert horizontal space.", r"\\hspace{[[selection]][[cursor]]}"),

    _cmd("bib-article", "@article", "BibTeX", "Insert a BibTeX article entry.", "@article{[[selection]][[cursor]],\n  author = {},\n  title = {},\n  journal = {},\n  year = {},\n}\n", languages=("bib",)),
    _cmd("bib-book", "@book", "BibTeX", "Insert a BibTeX book entry.", "@book{[[selection]][[cursor]],\n  author = {},\n  title = {},\n  publisher = {},\n  year = {},\n}\n", languages=("bib",)),
    _cmd("bib-inproceedings", "@inproceedings", "BibTeX", "Insert a BibTeX conference-paper entry.", "@inproceedings{[[selection]][[cursor]],\n  author = {},\n  title = {},\n  booktitle = {},\n  year = {},\n}\n", languages=("bib",)),
    _cmd("bib-misc", "@misc", "BibTeX", "Insert a generic BibTeX entry.", "@misc{[[selection]][[cursor]],\n  author = {},\n  title = {},\n  year = {},\n  note = {},\n}\n", languages=("bib",)),
)

COMMAND_BY_KEY = {spec.key: spec for spec in BUILTIN_COMMANDS}
COMMAND_CATEGORIES: tuple[str, ...] = tuple(dict.fromkeys(spec.category for spec in BUILTIN_COMMANDS)) + ("Custom",)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def make_custom_key(label: str) -> str:
    slug = _SLUG_RE.sub("-", label.strip().casefold()).strip("-")[:36] or "command"
    return f"custom:{slug}:{uuid.uuid4().hex[:10]}"


def validate_custom_command(
    *,
    key: str | None,
    label: str,
    category: str,
    description: str,
    template: str,
    languages: tuple[str, ...] | list[str] | set[str],
) -> CommandSpec:
    label = str(label).strip()
    category = str(category).strip() or "Custom"
    description = str(description).strip()
    template = str(template)
    if not label or len(label) > MAX_LABEL_LENGTH:
        raise ValueError(f"Command labels must be 1–{MAX_LABEL_LENGTH} characters.")
    if len(category) > MAX_CATEGORY_LENGTH:
        raise ValueError(f"Categories may contain at most {MAX_CATEGORY_LENGTH} characters.")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(f"Descriptions may contain at most {MAX_DESCRIPTION_LENGTH} characters.")
    if not template or len(template) > MAX_TEMPLATE_LENGTH:
        raise ValueError(f"Insertion text must be 1–{MAX_TEMPLATE_LENGTH} characters.")
    normalized_languages = tuple(sorted({str(value) for value in languages if str(value) in VALID_LANGUAGES}))
    if not normalized_languages:
        raise ValueError("Choose at least one source type: LaTeX or BibTeX.")
    normalized_key = str(key).strip() if key else make_custom_key(label)
    if not normalized_key.startswith("custom:") or len(normalized_key) > 160:
        raise ValueError("The custom command identifier is invalid.")
    return CommandSpec(
        key=normalized_key,
        label=label,
        category=category,
        description=description,
        template=template,
        languages=normalized_languages,
        builtin=False,
    )


def render_template(spec: CommandSpec, selection: str) -> tuple[str, int]:
    """Render a command template and return (text, cursor offset within text)."""
    selection = selection.replace("\u2029", "\n")
    template = spec.template
    selection_at = template.find(SELECTION_TOKEN)
    cursor_at = template.find(CURSOR_TOKEN)
    rendered = template.replace(SELECTION_TOKEN, selection)
    cursor_at_after_selection = rendered.find(CURSOR_TOKEN)
    rendered = rendered.replace(CURSOR_TOKEN, "")
    if cursor_at_after_selection >= 0:
        caret = cursor_at_after_selection
    elif selection_at >= 0:
        caret = selection_at + len(selection)
    elif cursor_at >= 0:
        caret = min(cursor_at, len(rendered))
    else:
        caret = len(rendered)
    return rendered, max(0, min(len(rendered), caret))
