# Copyright (c) 2026, Joshua I. Gold
# SPDX-License-Identifier: BSD-2-Clause

import struct
import zlib

from conftest import make_pdf

from miragold import pictures


def size(image: bytes) -> tuple[int, int]:
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", image[16:24])


def test_trim_keeps_what_is_printed_and_a_margin():
    width, height, stride = 40, 30, 44  # rows padded to 44 bytes
    pixels = bytearray(b"\xff" * stride * height)
    for r in range(10, 15):
        pixels[r * stride + 20 : r * stride + 25] = b"\x00" * 5
    pixels[stride - 2] = 0  # in the padding past a row's end: not a pixel
    m = pictures.MARGIN
    assert pictures.trim(bytes(pixels), width, height, stride) == (
        20 - m, 10 - m, 25 + m, 15 + m,
    )  # fmt: skip
    # a sliver of the line above at the top edge, and white below it
    pixels[0:40] = b"\x00" * 40
    pixels[stride : stride + 40] = b"\x00" * 40
    assert pictures.trim(bytes(pixels), width, height, stride)[1] == 10 - m
    blank = b"\xff" * stride * height
    assert pictures.trim(blank, width, height, stride) == (0, 0, width, height)


def test_png_is_a_greyscale_image():
    image = pictures.png(bytes(range(6)), 3, 2)
    assert size(image) == (3, 2)
    start = image.index(b"IDAT") + 4
    assert zlib.decompress(image[start:]) == b"\x00\x00\x01\x02\x00\x03\x04\x05"


def test_draw_a_box_of_a_page(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(make_pdf([[("y = a + b", 200, 10, 100)], [("z", 50, 10, 100)]]))
    # the line is at y = 664, from x = 200; the box is the page's width
    (image,) = pictures.draw(pdf, [(1, (0, 650, 612, 690))])
    width, height = size(image)
    s, m = pictures.SCALE, pictures.MARGIN
    assert 30 * s < width - 2 * m < 60 * s  # the text, not the box
    assert 5 * s < height - 2 * m < 12 * s
