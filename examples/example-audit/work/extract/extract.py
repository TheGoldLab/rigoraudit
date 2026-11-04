"""Extract the manuscript's pages and paragraphs (step 2).

A real audit runs `miragold extract`, which reads the published PDF. This
example's manuscript is plain text instead (a PDF is not kept in the tool's
repository), with pages separated by form feeds and headings marked "##"
(section) and "###" (subsection), so this script stands in for it. It
writes, beside itself, the same three files `miragold extract` does:

- published.txt: the text of each page; quotes are checked against it.
- outline.json: the headings and their pages; the report is laid out by
  them.
- paragraphs.json: each paragraph with its section ("Results › Learning"),
  its number within that section (from 1), its page, and its text; claim
  anchors give character offsets into these.

    uv run python examples/example-audit/work/extract/extract.py
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
WORKSPACE = HERE.parents[1]
SEPARATOR = " › "

pages = (WORKSPACE / "materials" / "manuscript.txt").read_text().split("\f")

paragraphs, headings = [], []
major = sub = None
count = 0
for page_no, page in enumerate(pages, start=1):
    for block in page.split("\n\n"):
        block = block.strip()
        if block.startswith("### "):
            sub, count = block[4:], 0
            headings.append({"title": sub, "level": 1, "page": page_no})
        elif block.startswith("## "):
            major, sub, count = block[3:], None, 0
            headings.append({"title": major, "level": 0, "page": page_no})
        elif block and major and not block.startswith("#"):
            count += 1
            section = SEPARATOR.join(s for s in (major, sub) if s)
            paragraphs.append(
                {"section": section, "paragraph": count, "page": page_no, "text": block}
            )

(HERE / "published.txt").write_text(
    "".join(f"\n=== PAGE {i} ===\n{page}" for i, page in enumerate(pages, 1))
)
(HERE / "outline.json").write_text(json.dumps({"headings": headings}, indent=1) + "\n")
(HERE / "paragraphs.json").write_text(
    json.dumps(paragraphs, indent=1, ensure_ascii=False) + "\n"
)
print(f"{len(pages)} pages, {len(paragraphs)} paragraphs")
