# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import io
import json
import xml.etree.ElementTree as ET

import pytest
from conftest import make_pdf
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject

from rigoraudit import cli, extract
from rigoraudit.paragraphs import PARAGRAPHS, read_paragraphs
from rigoraudit.verify import ManuscriptText

FULL = "is a full line of made-up text that runs across the whole width of the column"
HEADER = "Journal of Examples 2026 | page {}"
PAGES = [
    [
        HEADER.format(1),
        "A Made-Up Study of Example Things",
        "Introduction",
        f"The first paragraph {FULL}",
        "and it ends on this short line.",
        f"The second paragraph {FULL}",
        f"and this line {FULL}",
        "ends with a word that is hyphen-",
        "ated across lines.",
        "1",
    ],
    [
        HEADER.format(2),
        "Results",
        f"Accuracy was measured and this {FULL}",
        f"so this paragraph goes on and {FULL}",
        f"until a figure cuts it off in the {FULL}",
        "Figure 1. A legend for the made-up figure.",
        "2",
    ],
    [
        HEADER.format(3),
        f"middle of a sentence, which goes on after the figure {FULL}",
        "and ends here.",
        "References",
        "Doe J (2020) A made-up reference. Example Letters 1:1.",
        "3",
    ],
]


@pytest.fixture
def pdf_pages(tmp_path):
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_pdf(PAGES))
    pages, outline = extract.read_pdf(path)
    assert outline == ()
    return pages


def read_lines(tmp_path, pages):
    path = tmp_path / "layout.pdf"
    path.write_bytes(make_pdf(pages))
    return extract.read_lines(path)


def test_running_lines_are_headers_footers_and_page_numbers(pdf_pages):
    lines = [p.splitlines() for p in pdf_pages]
    found = {lines[p][i] for p, i in extract.running_lines(pdf_pages)}
    assert {HEADER.format(n) for n in (1, 2, 3)} <= found
    assert {"1", "2", "3"} <= found
    assert not any("paragraph" in line for line in found)


def test_running_lines_on_facing_pages():
    # the page number changes sides, and every other page drops a space
    body = ["Methods.", "Results.", "Analysis.", "Discussion."]
    pages = [
        f"{n} Journal of Examples\nOPEN ACCESS Article\n{body[n - 1]}"
        if n % 2
        else f"Journal of Examples {n}\nOPEN ACCESSArticle\n{body[n - 1]}"
        for n in range(1, 5)
    ]
    assert extract.running_lines(pages) == {(p, i) for p in range(4) for i in (0, 1)}


def test_facing_pages_are_lined_up():
    def page(x):
        return [extract.Line("Some text", x + dx, 700, 10) for dx in (0, 0, 12, 270)]

    even, odd, _ = extract.facing([page(50), page(57), page(50)])
    assert [ln.x for ln in odd] == [ln.x for ln in even]
    assert extract.facing([page(50), page(50)])[1] == page(50)


def test_run_in_heading_with_its_stop_in_the_body_font():
    style = extract.Layout(10, [50.0], 12, {}, 80, font="Body")

    def line(text, lead):
        return extract.Line(text, 50, 700, 10, font="Bold", lead=lead, lead_font="Bold")

    assert style.run_in(line("Main effects . We fit a model", "Main effects")) == (
        "Main effects ."
    )
    assert style.run_in(line("Journal. ; 4(2): 1-9.", "Journal.")) == ""


def test_run_in_heading_ending_in_a_dash():
    style = extract.Layout(10, [50.0], 12, {}, 80, font="Body")
    line = extract.Line(
        "Main task—Subjects pressed a key", 50, 700, 10, font="Body",
        lead="Main task—", lead_font="Bold",
    )  # fmt: skip
    assert style.run_in(line) == "Main task—"


def test_pdf_paragraphs_without_indents_or_spacing(tmp_path):
    paras, left_out = extract.pdf_paragraphs(read_lines(tmp_path, PAGES), ())
    [results] = [p for p in paras if p["section"] == "Results"]
    [(_, first), (at, then)] = results["page_starts"]
    assert (first, then) == (2, 3)
    assert results["text"][at:].startswith("middle of a sentence")
    got = [(p["section"], p["paragraph"], p["pages"]) for p in paras]
    assert got == [
        ("Front matter", 1, [1]),
        ("Introduction", 1, [1]),
        ("Introduction", 2, [1]),
        ("Results", 1, [2, 3]),
        ("Figure 1 legend", 1, [2]),
    ]
    assert all(p["approximate"] for p in paras)
    text = [p["text"] for p in paras]
    assert text[1].endswith("and it ends on this short line.")
    assert text[2].endswith("hyphenated across lines.")  # line-end hyphen joined
    assert text[3].endswith("in the " + FULL + " middle of a sentence, which goes "
                            "on after the figure " + FULL + " and ends here.")  # fmt: skip
    assert not any("Journal of Examples" in t for t in text)
    assert left_out == {"References": 1}


JATS = """<article xmlns:mml="http://www.w3.org/1998/Math/MathML">
<front><article-meta>
  <abstract><p>We made up a study.</p></abstract>
  <abstract abstract-type="plain-language-summary"><p>A plain summary.</p></abstract>
</article-meta></front>
<body>
  <sec><title>Introduction</title><p>First idea.</p><p>Second idea.</p></sec>
  <sec><title>Results</title>
    <p>Before any subsection.</p>
    <sec><title>Accuracy</title>
      <p>Accuracy was 80% (<xref>Figure 1A</xref>).<fig-group><fig>
        <label>Figure 1.</label>
        <caption><title>A made-up figure.</title><p>Panel A shows accuracy.</p></caption>
      </fig></fig-group></p>
      <p>The rate was <inline-formula><alternatives><mml:math><mml:msubsup>
        <mml:mi>k</mml:mi><mml:mn>0</mml:mn><mml:mn>2</mml:mn></mml:msubsup>
        <mml:mo>&#x2062;</mml:mo><mml:mi>t</mml:mi></mml:math>
        <tex-math>k_0^2 t</tex-math></alternatives></inline-formula>.</p>
      <p>As in <disp-formula><mml:math><mml:mi>y</mml:mi></mml:math><label>(1)</label></disp-formula></p>
      <disp-formula><label>(2)</label><graphic/></disp-formula>
    </sec>
  </sec>
  <table-wrap><label>Table 1.</label><caption><title>Counts.</title></caption>
    <table><tr><th>Group</th><th>N</th></tr><tr><td>A</td><td>12</td></tr></table>
  </table-wrap>
</body>
<back>
  <ack><title>Acknowledgements</title><p>We thank no one.</p></ack>
  <ref-list><ref>Doe J (2020)</ref></ref-list>
  <sec sec-type="synthesis-author-response"><title>Synthesis</title>
    <p>A reviewers' summary.</p></sec>
</back>
<sub-article><body><p>A reviewer's comment.</p></body></sub-article>
</article>"""


def body(text, drop=14):
    return (text, 50, 10, drop)


def indented(text):
    return (text, 62, 10, 14)


def small(text, drop=10):
    return (text, 50, 8, drop)


LAYOUT = [
    [
        HEADER.format(1),
        ("A Made-Up Study of Example Things", 50, 16, 20),
        body("Abstract We made up a study of example things.", 24),
        ("Introduction", 50, 12, 24),
        indented(f"The first paragraph {FULL}"),
        body("ends a sentence on a short line."),
        body(f"But it goes on, since the next line {FULL}"),
        body("and ends here."),
        indented(f"The second paragraph {FULL}"),
        body("has a symbol drawn above its line"),
        ("~", 62, 10, -6),  # drawn where an indent would start
        ("x, and it goes on", 70, 10, 20),
        body("to the end."),
        body(f"A paragraph after more space than usual {FULL}", 22),
        body("ends here."),
        "1",
    ],
    [
        HEADER.format(2),
        ("Results", 50, 12, 20),
        indented(f"Accuracy was measured and this {FULL}"),
        body("until a figure cuts it"),
        small(f"Figure 1. A made-up figure. Panel A shows accuracy in a {FULL}", 30),
        small("made-up task."),
        small(f"Panel B shows the same {FULL}"),
        small("for another made-up task."),
        small("The online version of this article includes a supplement:", 13),
        small("Figure supplement 1. A made-up supplement.", 13),
        small("Figure supplement 2. Another made-up supplement.", 13),
        ("Time (s)", 200, 6, 10),  # a label in the figure
        body("off in the middle of a sentence, and it ends here.", 30),
        small("Table 1. Made-up rates. Each is per second.", 30),
        "2",
    ],
    [
        HEADER.format(3),
        ("References", 50, 12, 20),
        body("Doe J (2020) A reference."),
        "3",
    ],
]


def test_pdf_paragraphs_from_the_layout(tmp_path):
    lines = read_lines(tmp_path, LAYOUT)
    style = extract.layout(lines)
    assert (style.size, style.indent, style.spacing[10]) == (10, 12, 14)
    paras, left_out = extract.pdf_paragraphs(lines, ())
    got = [(p["section"], p["text"][:24]) for p in paras]
    assert got == [
        ("Front matter", "A Made-Up Study of Examp"),
        ("Abstract", "We made up a study of ex"),
        ("Introduction", "The first paragraph is a"),
        ("Introduction", "The second paragraph is "),
        ("Introduction", "A paragraph after more s"),
        ("Results", "Accuracy was measured an"),
        ("Figure 1 legend", "A made-up figure."),  # the title
        ("Figure 1 legend", "Panel A shows accuracy i"),
        ("Figure 1—figure supplement 1 legend", "A made-up supplement."),
        ("Figure 1—figure supplement 2 legend", "Another made-up suppleme"),
        ("Table 1 caption", "Made-up rates."),
        ("Table 1 caption", "Each is per second."),
    ]
    text = [p["text"] for p in paras]
    assert text[3].endswith("drawn above its line ~ x, and it goes on to the end.")
    assert text[5].endswith(
        "cuts it off in the middle of a sentence, and it ends here."
    )
    assert text[7].endswith("for another made-up task.")
    assert left_out == {extract.OTHER: 1, extract.NOTE: 1, "References": 1}


def number(text, x=500):
    """An equation's number, on the line before's baseline."""
    return (text, x, 10, 0)


EQUATIONS = [
    [
        ("Methods", 50, 12, 20),
        indented(f"The model {FULL}"),
        body(FULL),
        body("follows the rule:"),
        ("y = a + b x", 200, 10, 24),
        number("(1)"),
        body("where a is the start and b the slope of the made-up line,", 24),
        body("and the rule goes on:"),
        ("z = y + c", 200, 10, 24),
        number("(2)"),
        ("w = z - c", 200, 10, 18),  # a second one just below the first
        number("(Equation 3)", 460),
        body("so z and w are made up too, and the list has (1) one and (2)", 24),
        body("another item. Here a formula x = 1 is in the line"),
        ("a", 300, 10, -5.5),  # a bit of it drawn on its own, by the baseline
        body(f"and a sum {FULL}", 19.5),
        body("is set apart:"),
        # no number; its sign is a symbol the PDF stores as a glyph number
        ("s /C24 a + b", 200, 10, 24),
        body("and a picture follows:", 24),
        ("[4]", 500, 10, 40),  # all the PDF has of an equation set as a picture
        body("which ends the made-up section.", 40),
    ]
    + [body(FULL)] * 10
]


def test_display_equations(tmp_path):
    lines = read_lines(tmp_path, EQUATIONS)
    found = extract.find_equations(lines, 612)
    assert [(e.number, e.text) for e in found] == [
        ("1", "y = a + b x (1)"),
        ("2", "z = y + c (2)"),
        ("3", "w = z - c (Equation 3)"),
        (None, "s /C24 a + b"),
        ("4", "[4]"),
    ]
    assert {e.page for e in found} == {1}
    # each fills its column between the text above and below it
    first, second, third, _, picture = (e.box for e in found)
    assert (first[0], first[2]) == (50, 612)
    above, below = lines[0][3].y, lines[0][5].y  # the number is on its line
    assert first[3] == above - 2.5 and first[1] == below + 8
    assert second[1] == third[3]  # split halfway between the two
    assert picture[3] - picture[1] > 60  # the picture's space, not its number's

    paras, left_out = extract.pdf_paragraphs(lines, (), found)
    assert len(paras) == 1
    text = paras[0]["text"]
    assert "rule: [Equation 1] where a is the start" in text
    assert "y = a" not in text and "and (2) another" in text
    assert "apart: [Equation] and a picture follows: [Equation 4] which" in text
    assert left_out[extract.EQUATIONS] == 5
    assert [(e.section, e.paragraph) for e in found] == [("Methods", 1)] * 5
    assert [text[e.at :][:12] for e in found] == [
        "[Equation 1]", "[Equation 2]", "[Equation 3]", "[Equation] a", "[Equation 4]",
    ]  # fmt: skip


def test_an_indent_is_found_in_two_columns(tmp_path):
    # two indented lines in each column, too few to count in either alone
    column = [indented(f"A paragraph {FULL}")] + [body(FULL)] * 40
    column[20] = indented(f"Another paragraph {FULL}")
    right = [(t, x + 270, size, drop) for t, x, size, drop in column]
    right[0] = (*right[0][:3], -14 * 40)  # back up to the top of the page
    style = extract.layout(read_lines(tmp_path, [column + right]))
    assert (style.starts, style.indent) == ([50.0, 320.0], 12)


def test_a_paragraph_starts_at_the_top_of_the_next_column(tmp_path):
    def column(x, first, names):
        lines = [(f"{first} {FULL}", x + 12, 10, 14)]
        for name in names:  # each ends a paragraph before another starts
            lines += [(f"{FULL} {k}", x, 10, 14) for k in range(9)]
            lines += [
                (f"and ends {name}.", x, 10, 14),
                (f"{name} {FULL}", x + 12, 10, 14),
            ]
        return lines + [(f"{FULL} {k}", x, 10, 14) for k in range(9)]

    left = [("Results", 50, 12, 20), *column(50, "One", ["Two", "Three"])]
    left.append(("and ends here.", 50, 10, 14))
    # the right column's first line, indented, is far above the left's last
    right = column(320, "Four", ["Five", "Six"])
    right[0] = (*right[0][:3], -14 * 31)
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, [left + right]), ())
    assert [p["text"].split()[0] for p in paras] == [
        "One",
        "Two",
        "Three",
        "Four",
        "Five",
        "Six",
    ]


def test_a_paragraph_ending_in_a_raised_citation_number(tmp_path):
    # the full stop after the number is printed on its own, mid-line
    lines = [("Results", 50, 12, 20), body(f"One {FULL}", 20)]
    lines += [body(f"{FULL} {k}") for k in range(6)]
    lines += [body("and ends at a citation"), ("12", 160, 8, -6), (".", 170, 10, 6)]
    lines += [body(f"Two {FULL}", 24), *[body(f"{FULL} {k}") for k in range(6)]]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, [lines]), ())
    assert [p["text"].split()[0] for p in paras] == ["One", "Two"]


def test_an_abstract_set_apart_ends_where_the_main_text_starts(tmp_path):
    # no heading between them: the abstract is set out to the left, and
    # the main text starts after more space, at the column's edge
    def at(text, x=100, drop=14):
        return (text, x, 10, drop)

    lines = [("Abstract", 55, 12, 20), at(f"We made up {FULL}", 55, 20)]
    lines += [at("and summed it in an abstract.", 55)]
    lines += [at(f"The main text {FULL}", drop=24)]
    lines += [at(f"{FULL} {k}") for k in range(6)]
    lines += [("Results", 55, 12, 24), at(f"We found {FULL}", drop=20)]
    lines += [at(f"{FULL} {k}") for k in range(6)]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, [lines]), ())
    assert [(p["section"], p["text"].split()[0]) for p in paras] == [
        ("Abstract", "We"),
        ("Main text", "The"),
        ("Results", "We"),
    ]


def test_a_line_pushed_down_by_a_formula_stays_in_its_paragraph(tmp_path):
    # paragraphs are set apart by space; a fraction in the line makes room
    # above it, in the middle of a sentence
    lines = [("Results", 50, 12, 20), body(f"One {FULL}", 20)]
    lines += [body(f"{FULL} {k}") for k in range(3)]
    lines += [body(f"and the made-up rate a/b {FULL}", 19)]
    lines += [body(f"{FULL} {k}") for k in range(3)] + [body("It ends.")]
    lines += [body(f"Two {FULL}", 24), *[body(f"{FULL} {k}") for k in range(3)]]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, [lines]), ())
    assert [p["text"].split()[0] for p in paras] == ["One", "Two"]


def test_a_full_line_read_in_pieces_does_not_end_its_paragraph(tmp_path):
    # a fraction in the line splits it in two on one baseline and pushes
    # the next line down; the line's last piece alone is short
    lines = [("Results", 50, 12, 20), body(f"One {FULL}", 20)]
    lines += [body(f"{FULL} {k}") for k in range(3)]
    lines += [body("and the made-up rate a/b"), ("a", 180, 6, -5), ("b", 180, 6, 11)]
    lines += [
        ("which goes on to a made-up value and runs on to the end of", 200, 10, -6)
    ]
    lines += [body(f"the line, as it {FULL}", 18)]
    lines += [body(f"{FULL} {k}") for k in range(3)] + [body("It ends.")]
    lines += [body(f"Two {FULL}", 24), *[body(f"{FULL} {k}") for k in range(3)]]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, [lines]), ())
    assert [p["text"].split()[0] for p in paras] == ["One", "Two"]


def test_back_matter_in_smaller_type(tmp_path):
    lines = [("Results", 50, 12, 20), body(f"One {FULL}", 20)]
    lines += [body(f"{FULL} {k}") for k in range(5)] + [body("It ends.")]
    lines += [("Data Availability", 50, 10, 24)]
    lines += [(f"The made-up data {FULL}", 50, 8, 12), ("are online.", 50, 8, 10)]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, [lines]), ())
    assert [(p["section"], p["text"].split()[0]) for p in paras] == [
        ("Results", "One"),
        ("Data Availability", "The"),
    ]


def test_raised_citation_numbers_stay_in_their_paragraph(tmp_path):
    # the numbers are a line of their own, in smaller type above the row
    lines = [("Results", 50, 12, 20), body(f"One {FULL}", 20)]
    lines += [body(f"{FULL} {k}") for k in range(3)]
    lines += [body("as shown before"), ("3,5", 130, 8, -6), body("and again", 20)]
    lines += [body(f"{FULL} {k}") for k in range(3)]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, [lines]), ())
    assert len(paras) == 1
    assert "as shown before3,5 and again" in paras[0]["text"]


def test_a_drop_cap_opens_its_paragraph(tmp_path):
    # a large first letter, three lines tall, with the lines beside it moved in
    lines = [("Results", 50, 12, 20), ("O", 50, 40, 48)]
    lines += [(f"ne {FULL}", 80, 10, -28), (f"beside {FULL}", 80, 10, 14)]
    lines += [(f"beside {FULL}", 80, 10, 14)]
    lines += [body(f"{FULL} {k}") for k in range(5)] + [body("It ends.")]
    lines += [indented(f"Two {FULL}")] + [body(f"{FULL} {k}") for k in range(5)]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, [lines]), ())
    assert [p["text"][:6] for p in paras] == ["One is", "Two is"]


def test_a_drop_cap_starts_the_main_text(tmp_path):
    # no heading: the front matter ends where the large letter is
    lines = [("A Made-Up Title", 50, 16, 20), small(f"An abstract {FULL}", 30)]
    lines += [small(f"{FULL} {k}") for k in range(4)]
    lines += [("O", 50, 40, 60), (f"ne {FULL}", 80, 10, -28)]
    lines += [(f"beside {FULL}", 80, 10, 14), (f"beside {FULL}", 80, 10, 14)]
    lines += [body(f"{FULL} {k}") for k in range(5)] + [body("It ends.")]
    lines += [("Results", 50, 12, 20)] + [body(f"Two {FULL} {k}") for k in range(5)]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, [lines]), ())
    got = [(p["section"], p["text"][:3]) for p in paras]
    assert ("Main text", "One") in got
    assert got[-1] == ("Results", "Two")


def test_a_footnote_in_the_front_matter_does_not_end_its_paragraph(tmp_path):
    # no heading yet: a note in smaller type at the page's foot comes
    # between a paragraph and the rest of it on the next page
    pages = [
        [
            ("A Made-Up Title", 50, 16, 20),
            indented(f"One {FULL}"),
            *[body(f"{FULL} {k}") for k in range(4)],
            body(f"and runs on {FULL}"),
            ("1Made-Up Department, Example University", 50, 6, 30),
            small("Correspondence to the made-up author"),
        ],
        [
            body(f"onto this page {FULL}"),
            body("and ends."),
            indented(f"Two {FULL}"),
            *[body(f"{FULL} {k}") for k in range(4)],
            ("Results", 50, 12, 20),
            indented(f"Three {FULL}"),
            *[body(f"{FULL} {k}") for k in range(4)],
        ],
    ]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, pages), ())
    got = [p["text"].split()[0] for p in paras]
    assert got == ["A", "One", "1Made-Up", "Correspondence", "Two", "Three"]
    assert "and runs on" in paras[1]["text"] and "and ends." in paras[1]["text"]


def test_run_in_headings_in_smaller_type(tmp_path):
    # the heading is set smaller than the body, and is most of its line
    def para(word):
        return [body(f"{word} {k} {FULL}") for k in range(5)] + [body("It ends.")]

    lines = [("Results", 50, 12, 20), *para("One")]
    lines += [("**A made-up heading in bold type.** Then", 50, 10, 14, 8.5)]
    lines += para("more")
    lines += [("**A made-up heading in bold type set on**", 50, 8.5, 14)]
    lines += [("**two lines.** Next", 50, 10, 14, 8.5), *para("more")]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, [lines]), ())
    assert [p["text"].split()[0] for p in paras] == ["One", "Then", "Next"]
    assert [p["section"].split(" › ")[-1] for p in paras[1:]] == [
        "A made-up heading in bold type",
        "A made-up heading in bold type set on two lines",
    ]


def test_headings_in_larger_type(tmp_path):
    def lines(word, n):
        return [body(f"{word} {k} {FULL}") for k in range(n)]

    margin = ("Author Manuscript", 20, 11, 7)  # on every page, in the margin
    first = [("Methods", 50, 12, 20), indented(f"One {FULL}"), *lines("one", 8)]
    first += [margin, body("and ends one.", 7), ("Subjects", 50, 11, 20)]
    first += [body(f"Two {FULL}", 13), *lines("two", 8), body("and ends two.")]
    first += [("Task and", 50, 11, 20), ("made-up stimuli", 50, 11, 13)]
    first += [body(f"Three {FULL}", 13), *lines("three", 4)]
    first += [("Left values", 50, 11, 20), ("Right values", 50, 11, 14)]
    first += [("0", 200, 10, 14), body("and goes on past a figure's labels.", 14)]
    pages = [first] + [
        [*lines(w, 10), margin, body(f"{w} {FULL}", 7), *lines(w + "x", 10)]
        for w in ("ab", "cd")
    ]
    paras, left_out = extract.pdf_paragraphs(read_lines(tmp_path, pages), ())
    got = [(p["section"], p["text"].split()[0]) for p in paras]
    assert got == [
        ("Methods", "One"),
        ("Methods › Subjects", "Two"),
        ("Methods › Task and made-up stimuli", "Three"),
    ]
    assert "three 3 " + FULL + " and goes on past" in paras[2]["text"]
    assert left_out[extract.OTHER] == 5  # three margin labels, two figure labels


def test_headings_below_the_outline(tmp_path):
    lines = read_lines(
        tmp_path,
        [
            [
                ("Results", 50, 12, 20),
                indented(f"Accuracy was measured and this {FULL}"),
                body("ends here."),
                body("**Experiment 2**"),
                indented(f"A second experiment {FULL}"),
                body("ends here."),
                indented(f"**A run-in heading.** This paragraph {FULL}"),
                body("ends here."),
                body("**Discussion**"),
                indented(f"We discuss {FULL}"),
                body("and end here."),
            ]
            + [body(FULL)] * 6
        ],
    )
    assert extract.layout(lines).font == "Helvetica"
    paras, _ = extract.pdf_paragraphs(lines, ())
    got = [(p["section"], p["text"][:20]) for p in paras]
    assert got == [
        ("Results", "Accuracy was measure"),
        ("Results › Experiment 2", "A second experiment "),
        ("Results › A run-in heading", "This paragraph is a "),
        ("Discussion", "We discuss is a full"),
    ]


def test_run_in_headings_from_the_outline(tmp_path):
    # the outline lists the headings; each runs into its paragraph's first
    # line, after its own line or on its own, in larger type
    from rigoraudit.sections import Heading

    def para(word):
        return [body(f"{word} {k} {FULL}") for k in range(5)] + [body("It ends.")]

    lines = [("Results", 50, 12, 20), *para("One")]
    lines += [("**A made-up heading in larger type.** Then", 50, 11, 20, 10)]
    lines += para("more")
    lines += [("**Another made-up heading set over two**", 50, 11, 20)]
    lines += [("**lines.** Next", 50, 10, 14, 10), *para("more")]
    outline = (
        Heading("A made-up study", 0, 1),
        Heading("Results", 1, 1),
        Heading("A made-up heading in larger type.", 2, 1),
        Heading("Another made-up heading set over two lines.", 2, 1),
    )
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, [lines]), outline)
    assert [(p["section"], p["text"].split()[0]) for p in paras] == [
        ("Results", "One"),
        ("Results › A made-up heading in larger type.", "Then"),
        ("Results › Another made-up heading set over two lines.", "Next"),
    ]


def test_headings_in_a_section_set_wider(tmp_path):
    # the Methods run across the page where the rest has narrow columns, in
    # the same type size: a heading there can be longer than a narrow line,
    # and can group words in angle brackets
    narrow = "is a narrow line of made-up text, set in a column"
    wide = f"{FULL} and {FULL}"
    pages = [
        [("Introduction", 50, 12, 20), indented(f"One {narrow}")]
        + [body(f"{p}{k} {narrow}") for k in range(40)]
        for p in "ab"
    ]
    pages.append(
        [("Methods", 50, 12, 20), indented(f"Two {wide}")]
        + [body(f"two {k} {wide}") for k in range(8)]
        + [body("and ends two."), body("**Step 1: The pair < Stimulus; Response >**")]
        + [indented(f"Three {wide}")]
        + [body(f"three {k} {wide}") for k in range(8)]
        + [body("and ends three.")]
        + [body("**Step 2: A made-up heading that is longer than one narrow line**")]
        + [indented(f"Four {wide}")]
        + [body(f"four {k} {wide}") for k in range(8)]
    )
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, pages), ())
    got = [(p["section"], p["text"].split()[0]) for p in paras]
    assert got[-3:] == [
        ("Methods", "Two"),
        ("Methods › Step 1: The pair < Stimulus; Response >", "Three"),
        (
            "Methods › Step 2: A made-up heading that is longer than one narrow line",
            "Four",
        ),
    ]


def test_paragraphs_set_apart_by_space_across_pages(tmp_path):
    # no indents, a gap between paragraphs: at the top of a page there is
    # no gap, so a short line ending a sentence at the bottom ended one
    def para(word, n, drop=24):
        return [body(f"{word} {FULL}", drop)] + [
            body(f"{word} {k} {FULL}") for k in range(n)
        ]

    pages = [
        [("Results", 50, 12, 20), *para("One", 6, 14), body("It ends.")],
        [*para("Two", 6, 14), body(f"and two runs on {FULL}")],
        [body(f"onto this page {FULL}"), body("and ends."), *para("Three", 6)],
    ]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, pages), ())
    assert [p["text"].split()[0] for p in paras] == ["One", "Two", "Three"]


def test_a_section_set_in_smaller_type(tmp_path):
    def methods(text):
        return (text, 50, 9, 12)

    lines = read_lines(
        tmp_path,
        [
            [("Introduction", 50, 12, 20)]
            + [indented(f"An introduction {FULL}")]
            + [body(FULL)] * 40,
            [("Methods", 50, 12, 20), (f"   We made it up and {FULL}", 50, 9, 12)]
            + [methods(FULL)] * 12
            + [methods("and ended here.")]
            + [small(f"Figure 1. A made-up figure. Panel A {FULL}", 20)]
            + [small("ends.")]
            + [(f"   It went on and {FULL}", 50, 9, 20)]
            + [methods(FULL)] * 12
            + [methods("and ended here.")],
        ],
    )
    paras, _ = extract.pdf_paragraphs(lines, ())
    got = [(p["section"], p["text"][:16]) for p in paras]
    assert got == [
        ("Introduction", "An introduction "),
        ("Methods", "We made it up an"),
        ("Figure 1 legend", "A made-up figure"),
        ("Figure 1 legend", "Panel A is a ful"),
        ("Methods", "It went on and i"),
    ]
    assert paras[1]["text"].endswith("and ended here.")


def test_a_long_section_in_smaller_type_indented_less(tmp_path):
    def section(heading, page, size, indent, drop, lines):
        out = [(heading, 50, 12, 20)] if heading else []
        for k in "AB":  # two paragraphs; no line the same on two pages
            out.append((f"{page} {k} {FULL}", 50 + indent, size, drop))
            out += [(f"{page} {FULL}", 50, size, drop)] * lines
            out.append((f"and {page} ended here.", 50, size, drop))
        return out

    # the Methods, in 9 points, have more text than the rest of the body in
    # 10 points, and their paragraphs are indented by 6 points, not 12
    pages = [section("Introduction", "One", 10, 12, 14, 14)]
    pages += [
        section(h, p, 9, 6, 12, 18)
        for h, p in [("Methods", "Two"), (None, "Three"), (None, "Four")]
    ]
    pages += [
        section("Results", "Five", 10, 12, 14, 14),
        section("Discussion", "Six", 10, 12, 14, 14),
    ]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, pages), ())
    got = [(p["section"], p["text"].split(" is a")[0]) for p in paras]
    assert got == [
        (name, f"{p} {k}")
        for name, pages in [("Introduction", ["One"]), ("Methods", ["Two", "Three", "Four"]),
                            ("Results", ["Five"]), ("Discussion", ["Six"])]
        for p in pages
        for k in "AB"
    ]  # fmt: skip


def test_a_legend_continued_on_the_next_page(tmp_path):
    lines = read_lines(
        tmp_path,
        [
            [
                ("Results", 50, 12, 24),
                indented(f"Accuracy was measured and {FULL}"),
                body(f"and goes on, {FULL}"),
                body(f"and on, {FULL}"),
                body("ends here."),
                small(
                    f"Figure 1. A made-up figure. Panel A shows accuracy in a {FULL}",
                    30,
                ),
                small("made-up task, and"),
                small("Figure 1 continued on next page", 20),
            ],
            [
                small("Figure 1 continued", 24),
                ("Discussion", 50, 12, 24),
                indented(f"We discussed the made-up results and {FULL}"),
                body(f"and goes on, {FULL}"),
                body(f"and on, {FULL}"),
                body("ends here."),
                small("panel B shows the same for another made-up task.", 30),
                small("Figure supplement 1. A made-up supplement.", 13),
            ],
        ],
    )
    paras, left_out = extract.pdf_paragraphs(lines, ())
    got = [(p["section"], p["text"][:24], p["pages"]) for p in paras]
    assert got == [
        ("Results", "Accuracy was measured an", [1]),
        ("Figure 1 legend", "A made-up figure.", [1, 2]),
        ("Figure 1 legend", "Panel A shows accuracy i", [1, 2]),
        ("Discussion", "We discussed the made-up", [2]),
        ("Figure 1—figure supplement 1 legend", "A made-up supplement.", [2]),
    ]
    assert paras[2]["text"].endswith(
        "made-up task, and panel B shows the same for another made-up task."
    )
    assert left_out == {extract.MARKER: 2}


def test_outline_titles_lose_invisible_characters():
    assert extract._visible("\ufeffResults\u200d \ufffc") == "Results"


def test_outline_entries_that_point_at_no_page_are_left_out(tmp_path):
    writer = PdfWriter(clone_from=io.BytesIO(make_pdf([["Some made-up text."]])))
    writer.add_outline_item("Results", 0)
    lost = writer.add_outline_item("Lost", 0).get_object()
    lost[NameObject("/A")][NameObject("/D")] = ArrayObject(
        [writer._add_object(DictionaryObject()), NameObject("/Fit")]
    )
    path = tmp_path / "paper.pdf"
    writer.write(path)
    _, outline = extract.read_pdf(path)
    assert [h.title for h in outline] == ["Results"]


def test_hyphens_with_a_space_after_them(tmp_path):
    lines = read_lines(
        tmp_path,
        [
            [
                ("Introduction", 50, 12, 24),
                indented(f"A made- up word {FULL}"),
                body("and a word made- "),  # the hyphen belongs to the word
                body("up across lines, a word hyphen-"),  # the hyphen breaks it
                body("ated across lines, and pre- and post-tests, trial- to-trial."),
            ]
        ],
    )
    assert [ln.hyphen for ln in lines[0]] == [False, False, True, False, False]
    paras, _ = extract.pdf_paragraphs(lines, ())
    assert paras[0]["text"] == (
        f"A made-up word {FULL} and a word made-up across lines, a word "
        "hyphenated across lines, and pre- and post-tests, trial-to-trial."
    )


def test_maths_fonts_characters_as_printed():
    assert extract._symbols(" ¼ ð Þ þ", "AdvP4C4E74") == " = ( ) +"
    assert extract._symbols(" /C0 /C2/C14 /C138 fg 0", "AdvP4C4E74") == " − ×° ] {} ′"
    assert extract._symbols("s/C18/C19 ﬃ", "AdvP4C4E46") == "s() "
    assert extract._symbols("½", "AdvP4C4E74") == "["
    assert extract._symbols(";", "AdvP4C4E51") == ","
    assert extract._symbols("p ¼ 0.03", "Times-Roman") == "p ¼ 0.03"


def test_maths_fonts_in_the_text_layer_and_lines(tmp_path):
    path = tmp_path / "made_up.pdf"
    line = "Made-up rate a **~** 0.8 and b **z** c **{** d."
    path.write_bytes(make_pdf([[line]], second="AdvP40798"))
    pages, _ = extract.read_pdf(path)
    assert pages[0].strip() == "Made-up rate a = 0.8 and b + c − d."
    assert extract.read_lines(path)[0][0].text == "Made-up rate a = 0.8 and b + c − d."


def test_a_subscript_run_on_into_the_sentence_keeps_the_body_size(tmp_path):
    # As some journals' PDFs do: the subscript's "+" is in another font, and
    # after "1" the PDF moves back to the body's size and baseline without
    # changing font, so pypdf hands over "1) are ..." as one piece in the
    # subscript's size.
    path = tmp_path / "made_up.pdf"
    path.write_bytes(make_pdf([["x"]]))
    writer = PdfWriter(clone_from=path)
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 1 Tf 10 0 0 10 50 700 Tm (Values \\(B) Tj "
        b"7 0 0 6 82 698 Tm (t) Tj /F2 1 Tf (+) Tj /F1 1 Tf (1) Tj "
        b"10 0 0 10 92 700 Tm (\\) are updated by a made-up rule) Tj ET"
    )
    writer.pages[0].replace_contents(stream)
    writer.write(path)
    [[line]] = extract.read_lines(path)
    assert line.text == "Values (Bt+1) are updated by a made-up rule"
    assert (line.size, line.y) == (10, 700)


def test_a_sentence_can_start_with_a_greek_letter():
    assert extract.SENTENCE.split("Made-up rates. τ is a time constant.") == [
        "Made-up rates.", "τ is a time constant.",
    ]  # fmt: skip


def test_jats_paragraphs():
    paras = extract.jats_paragraphs(ET.fromstring(JATS))
    got = [(p["section"], p["paragraph"], p["text"]) for p in paras]
    assert got == [
        ("Abstract", 1, "We made up a study."),
        ("Plain language summary", 1, "A plain summary."),
        ("Introduction", 1, "First idea."),
        ("Introduction", 2, "Second idea."),
        ("Results", 1, "Before any subsection."),
        ("Results › Accuracy", 1, "Accuracy was 80% (Figure 1A)."),
        ("Results › Accuracy", 2, "The rate was k20 t."),  # MathML, printed order
        ("Results › Accuracy", 3, "As in [Equation 1] [Equation 2]"),
        ("Acknowledgements", 1, "We thank no one."),
        ("Figure 1 legend", 1, "A made-up figure."),
        ("Figure 1 legend", 2, "Panel A shows accuracy."),
        ("Table 1 caption", 1, "Counts."),
        ("Table 1 rows", 1, "Group N"),
        ("Table 1 rows", 2, "A 12"),
    ]


def test_lead_in_line_with_maths_is_text(tmp_path):
    # a short line leading into a display, with signs in it, and a fraction
    # whose top sits close under it
    lines = read_lines(
        tmp_path,
        [
            [
                ("Methods", 50, 12, 20),
                indented(f"The model {FULL}"),
                body(FULL),
                body("(0 < x < 1):"),
                ("1", 300, 10, 10),
                ("p = ----", 200, 10, 7),
                number("(1)"),
                ("1 + e", 300, 10, 7),
                body("where the rest of the line is made up.", 24),
            ]
            + [body(FULL)] * 10
        ],
    )
    [found] = extract.find_equations(lines, 612)
    assert found.number == "1"
    assert "<" not in found.text
    # no higher than the lead-in line's baseline (its tails are trimmed off)
    assert found.box[3] <= lines[0][3].y


def test_list_items_with_maths_are_text(tmp_path):
    # numbered items set in from the column's edge (not by the indent),
    # with signs in them
    lines = read_lines(
        tmp_path,
        [
            [
                ("Methods", 50, 12, 20),
                indented(f"The tasks {FULL}"),
                body("are as follows:"),
                ("1. the dot sits at x = 0,", 58, 10, 20),
                ("2. the line is at y = 1, so that d = y - x, and", 58, 10, 20),
                body("Then the rule is", 20),
                ("y = a + b x (1)", 200, 10, 20),
                body("where the rest of the line is made up.", 20),
            ]
            + [body(FULL)] * 10
        ],
    )
    [found] = extract.find_equations(lines, 612)
    assert found.number == "1"


def test_a_paragraph_opening_with_a_figure_label_is_body_text(tmp_path):
    lines = [("Results", 50, 12, 20), indented(f"One {FULL}"), body("It ends.")]
    lines += [indented(f"Figure 2. shows the made-up results {FULL}")]
    lines += [body(f"{k} {FULL}") for k in range(6)] + [body("It ends.")]
    lines += [small(f"Figure 3. A made-up legend {FULL}", 30), small("It ends.")]
    paras, _ = extract.pdf_paragraphs(read_lines(tmp_path, [lines]), ())
    got = [(p["section"], p["text"][:16]) for p in paras]
    assert got == [
        ("Results", "One is a full li"),
        ("Results", "Figure 2. shows "),
        ("Figure 3 legend", "A made-up legend"),
    ]


def test_a_legend_set_in_is_text(tmp_path):
    # a legend set in from the column, in a smaller size, with a sign in it
    legend = "Figure 2 legend: the made-up points show each of the made-up cases"
    lines = read_lines(
        tmp_path,
        [
            [("Methods", 50, 12, 20)]
            + [(legend, 58, 9, 11)] * 6
            + [
                (
                    "and the shading is where z = 1 for each of the made-up runs, made up as the rest.",
                    58,
                    9,
                    11,
                )
            ]
            + [body(FULL, 30)]
            + [indented(FULL), body(FULL)] * 10
        ],
    )
    assert extract.layout(lines).indent == 12  # not the legend's 8
    assert extract.find_equations(lines, 612) == []


def test_a_legends_short_last_line_with_maths_is_text(tmp_path):
    # it starts where the wordy legend line above it starts, and ends the
    # sentence; too short to be wordy itself
    legend = "Figure 2 legend: the made-up points show each of the made-up cases"
    lines = read_lines(
        tmp_path,
        [
            [("Methods", 50, 12, 20)]
            + [(legend, 58, 9, 11)] * 6
            + [
                (
                    "and the shading is where the made-up runs end, each made up just as the rest of",
                    58,
                    9,
                    11,
                ),
                ("it, for z = 1.", 58, 9, 11),
            ]
            + [body(FULL, 30)]
            + [indented(FULL), body(FULL)] * 10
        ],
    )
    assert extract.find_equations(lines, 612) == []


def test_a_root_sign_set_high_in_a_legend_is_text(tmp_path):
    # the root sign is a line of its own, above its line's baseline but
    # below the line above: no room there for a display
    legend = "Figure 2 legend: the made-up points show each of the made-up cases, each one made"
    lines = read_lines(
        tmp_path,
        [
            [("Methods", 50, 12, 20)]
            + [(legend, 58, 9, 11)] * 4
            + [(legend, 58, 9, 11), ("= a", 300, 9, -8), (legend, 58, 9, 19)]
            + [(legend, 58, 9, 11)] * 2
            + [body(FULL, 30)]
            + [indented(FULL), body(FULL)] * 10
        ],
    )
    assert extract.find_equations(lines, 612) == []
    # with room, set apart, it is one
    lines = read_lines(
        tmp_path,
        [
            [("Methods", 50, 12, 20)]
            + [(legend, 58, 9, 11)] * 4
            + [("x = a", 300, 9, 24), (legend, 58, 9, 24)]
            + [(legend, 58, 9, 11)] * 2
            + [body(FULL, 30)]
            + [indented(FULL), body(FULL)] * 10
        ],
    )
    assert len(extract.find_equations(lines, 612)) == 1


def test_a_line_a_formula_cuts_in_two_is_judged_whole():
    # the halves of a line, a subscript between them, a root sign set high,
    # and a line in the next column, on the same baseline but far off
    page = [
        extract.Line("the made-up points show each of the", 58, 500, 9),
        extract.Line("i =", 216, 499.4, 5),
        extract.Line("√", 225, 509, 9),
        extract.Line("cases, each made up just as the rest", 230, 500, 9),
        extract.Line("made-up text in the other column", 400, 500, 9),
    ]
    whole = extract._whole_lines(page, [50, 400])
    halves = (
        "the made-up points show each of the i = cases, each made up just as the rest"
    )
    assert whole[0] == whole[1] == whole[3] == halves
    assert whole[2] == "√"
    assert whole[4] == page[4].text


def test_a_display_beside_text_in_the_other_column(tmp_path):
    # the left column's lines run on at the display's height; they do not
    # reach into the right column, so the display has room there
    left = "made-up text in the left column, set close, line after line, to the end"
    right = "made-up text in the right column, set close too"
    page = [(left, 50, 10, 12 if k else 20) for k in range(40)]
    page += [(right, 330, 10, -12 * 39 if k == 0 else 12) for k in range(10)]
    page += [("y = a + b", 400, 10, 24), (right, 330, 10, 24)]
    page += [(right, 330, 10, 12)] * 26
    lines = read_lines(tmp_path, [page])
    [found] = extract.find_equations(lines, 612)
    assert found.text == "y = a + b"


def test_jats_equations():
    # one in a paragraph, one set after it (a picture, with no text)
    assert extract.jats_equations(ET.fromstring(JATS)) == [
        {"number": "1", "section": "Results › Accuracy", "paragraph": 3, "at": 6,
         "text": "y"},
        {"number": "2", "section": "Results › Accuracy", "paragraph": 3, "at": 19,
         "text": ""},
    ]  # fmt: skip


def test_jats_equation_numbers_from_the_id_where_there_is_no_label():
    # bioRxiv's XML: a picture for each, numbered only by its id
    xml = (
        "<article><body><sec><title>Methods</title><p>We fit a model.</p>"
        '<disp-formula id="ueqn1"><graphic/></disp-formula>'
        '<disp-formula id="eqnA2"><graphic/></disp-formula>'
        "</sec></body></article>"
    )
    found = extract.jats_equations(ET.fromstring(xml))
    assert [e["number"] for e in found] == [None, "A2"]


def test_locate_marks_where_a_paragraph_runs_onto_the_next_page():
    text = "Accuracy was 80%. It rose to 90%. Then it fell."
    paras = [{"section": "Results", "paragraph": 1, "text": text}]
    pages = ["Accuracy was 80%.", "It rose to 90%. Then it fell."]
    extract.locate(paras, ManuscriptText(pages))
    assert paras[0]["pages"] == [1, 2]
    assert paras[0]["page_starts"] == [[0, 1], [text.index("It rose"), 2]]


def test_locate_marks_a_page_that_starts_inside_a_sentence():
    text = "Accuracy was 80% and it rose to 90% by the end of training."
    paras = [{"section": "Results", "paragraph": 1, "text": text}]
    pages = ["Accuracy was 80% and it", "rose to 90% by the end of training."]
    extract.locate(paras, ManuscriptText(pages))
    assert paras[0]["pages"] == [1, 2]
    assert paras[0]["page_starts"] == [[0, 1], [text.index("rose"), 2]]


def test_locate_finds_pages_and_lists_what_is_missing():
    paras = [{"section": "Results", "paragraph": 1,
              "text": "Accuracy was 80%. It was not 90%."}]  # fmt: skip
    extract.locate(paras, ManuscriptText(["Intro.", "Accuracy was 80%. Then more."]))
    assert paras[0]["pages"] == [2]
    assert paras[0]["not_in_pdf"] == ["It was not 90%."]


def test_locate_skips_a_page_where_a_sentence_is_also_printed():
    # a legend's sentence also in another legend, on an earlier page
    text = "Lever presses by block. Error bars show the standard error of the mean."
    paras = [{"section": "Figure 2 legend", "paragraph": 1, "text": text}]
    pages = ["Error bars show the standard error of the mean.", "Intro.",
             "Lever presses by block. Error bars show the standard error of the mean."]  # fmt: skip
    extract.locate(paras, ManuscriptText(pages))
    assert paras[0]["pages"] == [3]


def test_locate_places_a_sentence_the_pdf_writes_differently_by_its_words():
    # the PDF writes a symbol differently, and the page turns inside it
    text = (
        "The mean response time was computed for every block of trials "
        "and then the estimate of β was compared across all of the sessions."
    )
    paras = [{"section": "Methods", "paragraph": 1, "text": text}]
    pages = [
        "Intro. The mean response time was computed for every block of trials",
        "Figure 1.",  # a page holding only a figure
        "and then the estimate of b was compared across all of the sessions.",
    ]
    extract.locate(paras, ManuscriptText(pages))
    assert paras[0]["pages"] == [1, 3]
    assert paras[0]["page_starts"] == [[0, 1], [text.index("and then"), 3]]
    assert paras[0]["not_in_pdf"] == [text]


def test_a_formula_given_as_a_picture_is_put_in_from_the_pdf():
    root = ET.fromstring(
        "<article><body><sec><title>Methods</title><p>We fit the sample "
        '<inline-formula><inline-graphic href="f1.gif"/></inline-formula> of '
        "size N to the model [Equation 2] and the fit was then repeated for "
        '<inline-formula><inline-graphic href="f2.gif"/></inline-formula> '
        "every block of trials in the session.</p></sec></body></article>"
    )
    [para] = extract.jats_paragraphs(root)
    text = para["text"]
    assert "sample of size" in text and "for every block" in text
    assert para["formulas"] == [text.index("of size"), text.index("every block")]
    page = (
        "We fit the sample X = {xi} of size N to the model (2) and the fit "
        "was then repeated for b ∈ B every block of trials in the session."
    )
    assert extract.fill_in([para], ManuscriptText([page]), []) == 2
    assert para["text"] == (
        "We fit the sample X={xi} of size N to the model [Equation 2] and the "
        "fit was then repeated for b∈B every block of trials in the session."
    )
    assert "formulas" not in para


def test_fill_in_puts_back_what_the_xml_leaves_out():
    text = (
        "Each group comprised 50 participants. It rose to 90% [Equation 2]. "
        "Each group comprised 60 participants in all."
    )
    paras = [{"section": "Results", "paragraph": 1, "text": text}]
    equations = [{"section": "Results", "paragraph": 1, "at": text.index("[Eq")}]
    page = "Each group comprised ∼50 partic-\nipants. It rose to 90% (2). "
    pages = [page + "Each group comprised 61 participants in all."]
    assert extract.fill_in(paras, ManuscriptText(pages), equations) == 1
    filled = paras[0]["text"]
    assert filled.startswith("Each group comprised ∼50 participants. It rose")
    assert paras[0]["from_pdf"] == ["Each group comprised 50 participants."]
    # the mark moves with the text; a different number is left as it is
    assert filled[equations[0]["at"] :].startswith("[Equation 2]")
    assert filled.endswith("comprised 60 participants in all.")


def workspace(tmp_path, xml=True):
    folder = tmp_path / "materials" / "manuscript"
    folder.mkdir(parents=True)
    (folder / "paper.pdf").write_bytes(make_pdf(PAGES))
    if xml:
        (folder / "paper.xml").write_text(JATS, encoding="utf-8")
    (tmp_path / "audit.yaml").write_text(
        "materials:\n  manuscript:\n    path: manuscript/paper.pdf\n", encoding="utf-8"
    )
    return tmp_path


def test_extract_prefers_the_publishers_xml(tmp_path):
    ws = workspace(tmp_path)
    result = extract.extract(ws, "manuscript/paper.pdf")
    assert (result.route, result.xml, result.paragraphs) == ("xml", "paper.xml", 14)
    assert extract.read_pages(ws / extract.TEXT)[1].startswith(HEADER.format(2))
    outline = json.loads((ws / extract.OUTLINE).read_text(encoding="utf-8"))
    assert outline == {"source": "paper.pdf", "headings": []}
    paras = read_paragraphs(ws / PARAGRAPHS)
    assert [p.label for p in paras][:3] == ["A1.1", "P1.1", "I1.1"]
    assert result.not_found == sum(
        len(p["not_in_pdf"])
        for p in json.loads((ws / PARAGRAPHS).read_text(encoding="utf-8"))
    )
    # the XML's equations; this PDF has none, so they have no pictures
    listed = json.loads((ws / extract.EQUATIONS_FILE).read_text(encoding="utf-8"))
    assert [(e["number"], e["page"], e["picture"]) for e in listed] == [
        ("1", None, None), ("2", None, None),
    ]  # fmt: skip
    assert "None was found in the PDF" in extract.describe(result)
    assert result.sections == [
        "Abstract", "Plain language summary", "Introduction", "Results",
        "Acknowledgements", "Figure … (2 paragraphs)", "Table … (3 paragraphs)",
    ]  # fmt: skip
    assert extract.describe(result).endswith("Results; Acknowledgements; "
        "Figure … (2 paragraphs); Table … (3 paragraphs).")  # fmt: skip


def test_extract_adds_a_supplements_pages(tmp_path):
    ws = workspace(tmp_path)
    result = extract.extract(ws, "manuscript/paper.pdf")
    assert "in figure legends" in extract.describe(result)
    supplement = ws / "materials/manuscript/figures.pdf"
    supplement.write_bytes(
        make_pdf([["Figure 1. A made-up figure.", "Panel A shows accuracy."]])
    )
    result = extract.extract(
        ws, "manuscript/paper.pdf", supplement="manuscript/figures.pdf"
    )
    assert "in figure legends" not in extract.describe(result)
    assert "\n=== PAGE 4 (figures.pdf) ===\n" in (ws / extract.TEXT).read_text(
        encoding="utf-8"
    )
    assert len(extract.read_pages(ws / extract.TEXT)) == 3  # the article's only
    legend = next(
        p for p in read_paragraphs(ws / PARAGRAPHS) if p.section == "Figure 1 legend"
    )
    assert legend.page == 4
    assert extract.read_text(ws / extract.TEXT).name(4) == "page 1 of figures.pdf"


def test_match_equations_by_number_then_in_order():
    def found(page, number):
        return extract.Equation(page, [0], number, "", (0, 1, 2, 3))

    pdf = [found(1, "1"), found(1, None), found(2, None), found(2, "2"),
           found(3, None), found(4, "3")]  # fmt: skip
    xml = [{"number": n} for n in ("1", None, None, "2", None, None, "3", "4")]
    pages = [r["page"] for r in extract.match_equations(xml, pdf)]
    # after (1), two in each; after (2), one in the PDF but two in the XML
    assert pages == [1, 1, 2, 2, None, None, 4, None]
    # an XML without numbers, as many as the PDF has
    pages = [
        r["page"] for r in extract.match_equations([{"number": None} for _ in pdf], pdf)
    ]
    assert pages == [1, 1, 2, 2, 3, 4]


def test_match_equations_by_text_where_the_counts_differ():
    def found(page, text):
        return extract.Equation(page, [0], None, text, (0, 1, 2, 3))

    # a table found as an equation, and one equation not found; the PDF's
    # text has the formula's pieces out of order
    pdf = [found(1, "y = a + b x"), found(2, "group 1 2 3 mean 0.4 0.5"),
           found(3, "( ) exp k t = z")]  # fmt: skip
    xml = [{"number": None, "text": t} for t in ("y=a+bx", "q=r/s", "z=exp(kt)", "w")]
    pages = [r["page"] for r in extract.match_equations(xml, pdf)]
    assert pages == [1, None, 3, None]
    assert extract._alike("y=a+bx", "y = a + b x") == 1


def test_match_equations_a_row_that_goes_on_is_placed_with_the_one_above():
    # the XML sets apart a row of the formula the PDF prints as one
    pdf = [extract.Equation(2, [0], "1", "y = a + b x (1)", (0, 1, 2, 3))]
    xml = [{"number": "1", "text": "y=a"}, {"number": None, "text": "+bx"}]
    assert [r["page"] for r in extract.match_equations(xml, pdf)] == [2, 2]
    # a row that does not go on is not
    xml[1]["text"] = "z=c"
    assert [r["page"] for r in extract.match_equations(xml, pdf)] == [2, None]


def test_extract_from_the_pdf_alone(tmp_path):
    ws = workspace(tmp_path, xml=False)
    result = extract.extract(ws, "manuscript/paper.pdf")
    assert (result.route, result.paragraphs) == ("pdf", 5)
    assert "best guess" in extract.describe(result)
    assert "docs/guide.md" in extract.describe(result)
    assert "1 lines of the References section" in extract.describe(result)
    assert [p.label for p in read_paragraphs(ws / PARAGRAPHS)] == [
        "F1.1", "I1.1", "I1.2", "R1.1", "F2.1",
    ]  # fmt: skip
    assert json.loads((ws / extract.EQUATIONS_FILE).read_text(encoding="utf-8")) == []
    assert "equations" not in extract.describe(result)


def test_extract_lists_display_equations(tmp_path):
    ws = workspace(tmp_path, xml=False)
    (ws / "materials" / "manuscript" / "paper.pdf").write_bytes(make_pdf(EQUATIONS))
    result = extract.extract(ws, "manuscript/paper.pdf")
    listed = json.loads((ws / extract.EQUATIONS_FILE).read_text(encoding="utf-8"))
    assert [e["number"] for e in listed] == ["1", "2", "3", None, "4"]
    # one without a number is known by its page and how far down it is
    assert [e["key"] for e in listed] == ["1", "2", "3", "p1@274", "4"]
    assert listed[0] | {"box": None, "at": None} == {
        "page": 1,
        "number": "1",
        "key": "1",
        "read": "1",
        "note": "",
        "section": "Methods",
        "paragraph": 1,
        "at": None,
        "text": "y = a + b x (1)",
        "box": None,
        "size": 10.0,
        "down": 104,
        "picture": "equations/001.png",
    }
    pictures = sorted((ws / extract.PICTURES).iterdir())
    assert [p.name for p in pictures] == [f"00{n}.png" for n in range(1, 6)]
    assert pictures[0].read_bytes().startswith(b"\x89PNG")
    assert "Listed 5 display equations from the PDF" in extract.describe(result)
    assert "has a picture of each" in extract.describe(result)
    assert "5 lines of display equations" in extract.describe(result)


GROBID_TEI = f"""<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>
<div><head>Introduction</head><p>The first paragraph {FULL} and it ends on this
short line.</p><p>A sentence GROBID took from a figure.</p></div>
<div><head>Results</head><p>Accuracy was measured and this {FULL}</p></div>
<figure><figDesc>A legend for the made-up figure.</figDesc></figure>
</body></text></TEI>""".encode()


def test_extract_with_grobid(tmp_path, monkeypatch):
    ws = workspace(tmp_path, xml=False)
    monkeypatch.setattr(extract.grobid, "request", lambda pdf, server: GROBID_TEI)
    result = extract.extract(ws, "manuscript/paper.pdf", "http://localhost:8070")
    assert (result.route, result.paragraphs, result.not_found) == ("grobid", 4, 1)
    assert "read from the PDF by GROBID" in extract.describe(result)
    assert "could not place 1 paragraphs" in extract.describe(result)
    paras = json.loads((ws / PARAGRAPHS).read_text(encoding="utf-8"))
    assert [(p["section"], p["pages"]) for p in paras] == [
        ("Introduction", [1]), ("Introduction", []), ("Results", [2]),
        ("Unplaced text", [2]),
    ]  # fmt: skip
    assert all(p["approximate"] for p in paras)
    assert (ws / extract.FOLDER / "grobid.tei.xml").read_bytes() == GROBID_TEI


def test_extract_without_an_answer_from_grobid(tmp_path, monkeypatch):
    ws = workspace(tmp_path, xml=False)

    def refuse(pdf, server):
        raise extract.grobid.urllib.error.URLError("connection refused")

    monkeypatch.setattr(extract.grobid, "request", refuse)
    result = extract.extract(ws, "manuscript/paper.pdf", "http://localhost:8070")
    assert (result.route, result.paragraphs) == ("pdf", 5)
    assert "did not answer (URLError" in extract.describe(result)


def test_command_takes_grobid_from_the_manifest(tmp_path, monkeypatch):
    ws = workspace(tmp_path, xml=False)
    with (ws / "audit.yaml").open("a", encoding="utf-8") as f:
        f.write("settings:\n  extract:\n    grobid: http://localhost:8070\n")
    asked = []
    monkeypatch.setattr(
        extract.grobid,
        "request",
        lambda pdf, server: asked.append(server) or GROBID_TEI,
    )
    cli.main(["extract", str(ws)])
    cli.main(["extract", str(ws), "--replace", "--grobid", "http://elsewhere:8070"])
    assert asked == ["http://localhost:8070", "http://elsewhere:8070"]


def test_command_keeps_corrected_paragraphs(tmp_path, capsys):
    ws = workspace(tmp_path, xml=False)
    path = ws / PARAGRAPHS
    path.parent.mkdir(parents=True)
    path.write_text("[]", encoding="utf-8")
    cli.main(["extract", str(ws)])
    assert path.read_text(encoding="utf-8") == "[]"
    assert "--replace" in capsys.readouterr().out
    cli.main(["extract", str(ws), "--replace"])
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 5
