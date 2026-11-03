# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause
"""Pictures of parts of a PDF's pages, as PNG files.

Used to show a display equation as printed (:mod:`rigoraudit.extract`),
for checking by eye against a typed-in version. Pages are drawn by PDFium
(the PDF engine in Chrome, through :mod:`pypdfium2`), in shades of grey,
and the picture is trimmed to what is printed in the box.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pypdfium2 as pdfium

SCALE = 3
"""Pixels per point: 216 pixels to the inch, enough to zoom in on a
subscript."""
INK = 250
"""A pixel darker than this (of 255, white) is printed."""
MARGIN = 6
"""White pixels kept around what is printed."""
SLIVER = 4 * SCALE
"""Print at the top or bottom edge less tall than this (in pixels), with
white below or above it, is the edge of the text outside the box."""


def trim(pixels: bytes, width: int, height: int, stride: int) -> tuple[int, ...]:
    """The part of a picture with something printed in it, and a margin:
    ``(left, top, right, bottom)`` in pixels, right and bottom exclusive.
    The whole picture if nothing is. Slivers at the top and bottom edges
    (:data:`SLIVER`) are left out."""
    rows = [
        r for r in range(height) if min(pixels[r * stride : r * stride + width]) < INK
    ]
    # runs of rows with print in them
    runs = [[rows[0]]] if rows else []
    for r in rows[1:]:
        if r == runs[-1][-1] + 1:
            runs[-1].append(r)
        else:
            runs.append([r])
    if len(runs) > 1 and runs[0][0] == 0 and len(runs[0]) < SLIVER:
        runs.pop(0)
    if len(runs) > 1 and runs[-1][-1] == height - 1 and len(runs[-1]) < SLIVER:
        runs.pop()
    rows = [r for run in runs for r in run]
    if not rows:
        return 0, 0, width, height
    first, last = rows[0], rows[-1] + 1
    cols = [
        c
        for c in range(width)
        if min(pixels[first * stride + c : last * stride : stride]) < INK
    ]
    if not cols:
        return 0, 0, width, height
    return (
        max(cols[0] - MARGIN, 0),
        max(rows[0] - MARGIN, 0),
        min(cols[-1] + 1 + MARGIN, width),
        min(rows[-1] + 1 + MARGIN, height),
    )


def png(pixels: bytes, width: int, height: int) -> bytes:
    """A greyscale PNG file of ``height`` rows of ``width`` bytes each."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(
        b"\x00" + pixels[r * width : (r + 1) * width] for r in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def draw(
    pdf: Path, boxes: list[tuple[int, tuple[float, float, float, float]]]
) -> list[bytes]:
    """A PNG picture of each ``(page, box)``: the box (left, bottom, right,
    top, in points from the page's bottom left; pages from 1) as printed,
    trimmed."""
    out = []
    document = pdfium.PdfDocument(pdf)
    try:
        for number, (left, bottom, right, top) in boxes:
            page = document[number - 1]
            x0, y0, x1, y1 = page.get_cropbox()
            crop = (
                max(left - x0, 0),
                max(bottom - y0, 0),
                max(x1 - right, 0),
                max(y1 - top, 0),
            )
            bitmap = page.render(scale=SCALE, crop=crop, grayscale=True)
            page.close()
            pixels = bytes(bitmap.buffer)
            a, b, c, d = trim(pixels, bitmap.width, bitmap.height, bitmap.stride)
            kept = b"".join(
                pixels[r * bitmap.stride + a : r * bitmap.stride + c]
                for r in range(b, d)
            )
            out.append(png(kept, c - a, d - b))
    finally:
        document.close()
    return out
