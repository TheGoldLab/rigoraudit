# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import xml.etree.ElementTree as ET

from rigoraudit import grobid

TEI = """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text>
<front/>
<body>
 <div><head>Introduction</head><p>First idea.</p><p>Second idea.</p></div>
 <div><head>Results</head></div>
 <div><head>Accuracy</head>
  <p>Accuracy was set by</p>
  <formula>y = k t (1)</formula>
  <p>where k is a rate.</p>
  <formula>z = 2 (2)</formula>
  <p>A new paragraph starts here.</p>
 </div>
 <div><head>(legend continued on next page)</head><p>Stray legend text.</p></div>
 <div><head>Methods</head><p>We made it up.</p></div>
 <div><head>Method Details</head><p>In detail.</p></div>
 <figure><head>Figure 1.</head><label>1</label>
  <figDesc>Figure 1. A made-up figure. Panel A shows accuracy.</figDesc></figure>
 <figure type="table"><head>Table 1</head><label>1</label>
  <figDesc>Counts.</figDesc></figure>
 <figure><figDesc>Text GROBID set aside.</figDesc></figure>
</body>
<back>
 <div type="acknowledgement"><div><p>We thank no one.</p></div></div>
 <div type="annex"><div><head>More methods</head><p>Placed late.</p></div></div>
 <div type="references"><listBibl><biblStruct/></listBibl></div>
</back>
</text></TEI>"""
ABSTRACT = """<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><profileDesc>
<abstract><div><p>We made up a study.</p></div></abstract>
</profileDesc></teiHeader><text><body/></text></TEI>"""


def sections(tei, majors=()):
    paras = grobid.tei_paragraphs(ET.fromstring(tei), majors)
    return [(p["section"], p["paragraph"], p["text"]) for p in paras]


def test_tei_paragraphs():
    assert sections(TEI) == [
        ("Introduction", 1, "First idea."),
        ("Introduction", 2, "Second idea."),
        ("Results › Accuracy", 1,
         "Accuracy was set by y = k t (1) where k is a rate. z = 2 (2)"),
        ("Results › Accuracy", 2, "A new paragraph starts here."),
        ("Results › Accuracy", 3, "Stray legend text."),
        ("Methods", 1, "We made it up."),
        ("Methods › Method Details", 1, "In detail."),
        ("Acknowledgements", 1, "We thank no one."),
        ("Methods › More methods", 1, "Placed late."),
        ("Figure 1 legend", 1, "A made-up figure."),
        ("Figure 1 legend", 2, "Panel A shows accuracy."),
        ("Table 1 caption", 1, "Counts."),
        ("Unplaced text", 1, "Text GROBID set aside."),
    ]  # fmt: skip
    assert sections(ABSTRACT) == [("Abstract", 1, "We made up a study.")]


def test_the_outline_names_the_major_sections():
    # "Accuracy" is in the outline's top level; "Methods" is not, but the
    # outline has no section of that kind, so it is major too
    got = {s for s, _, _ in sections(TEI, ("Introduction", "Results", "Accuracy"))}
    assert {"Accuracy", "Methods", "Methods › Method Details"} <= got
    # an outline that does not name GROBID's headings is not used
    got = {s for s, _, _ in sections(TEI, ("Made-Up Title",))}
    assert "Results › Accuracy" in got


def test_request_sends_the_pdf(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-made-up")
    sent = {}

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b"<TEI/>"

    def urlopen(req, timeout):
        sent.update(
            url=req.full_url, body=req.data, type=req.get_header("Content-type")
        )
        return Answer()

    monkeypatch.setattr(grobid.urllib.request, "urlopen", urlopen)
    assert grobid.request(pdf, "http://localhost:8070/") == b"<TEI/>"
    assert sent["url"] == "http://localhost:8070/api/processFulltextDocument"
    assert sent["type"].startswith("multipart/form-data; boundary=")
    assert b"%PDF-made-up" in sent["body"]
    assert b'name="consolidateCitations"\r\n\r\n0' in sent["body"]
