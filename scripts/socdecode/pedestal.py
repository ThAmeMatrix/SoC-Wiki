"""Compose a character pixel figure standing on the legendary pedestal.

Placement is measured, not guessed: every legendary sprite in the BWIKI
archive is 128x160 and every one of them is the client's 128x128 figure plus
the same pedestal.  Cross-checking the archive against the client figures
(work/pedestal/fit_base.py, fit_figure.py) gives a single answer for 82 of 98
sprites:

    canvas 128x160
    pedestal (96x82, supplied file) at x=16 (= (128-96)/2), y=78 (= 160-82)
    figure  (128x128, icon/character/...) at x=0, y=0

Rebuilding 爱莎 / 内尔伽勒 that way differs from the archived sprite by 1 and
12 pixels of 20480 (0.05%); the pedestal colour matches exactly (246,234,229).
"""
from __future__ import annotations
import io
import json
from pathlib import Path

from PIL import Image

CANVAS = (128, 160)
FIGURE_SIZE = (128, 128)
BUNDLED = Path(__file__).resolve().parent / 'data' / 'legendary-base.png'
PROVENANCE = Path(__file__).resolve().parent / 'data' / 'legendary-base.json'


def _placement(base: Image.Image):
    """Centre the pedestal horizontally, sit it on the bottom edge."""
    return ((CANVAS[0] - base.width) // 2, CANVAS[1] - base.height)


def pedestal_image(source: Path | None = None):
    """Return (pedestal RGBA image, provenance dict).

    `source` overrides the bundled copy (data/legendary-base.png, taken from
    the Wiki editor's supplied base_ssr.png).
    """
    path = Path(source) if source else BUNDLED
    if not path.is_file():
        raise ValueError('缺少底座素材：' + str(path))
    image = Image.open(path).convert('RGBA')
    provenance = {'source': str(path), 'size': list(image.size), 'placement': list(_placement(image))}
    if PROVENANCE.is_file():
        provenance.update(json.loads(PROVENANCE.read_text('utf8')))
    return image, provenance


def compose(figure: Image.Image, pedestal: Image.Image) -> Image.Image:
    """Paste the plain client figure onto the pedestal, pedestal behind."""
    figure = figure.convert('RGBA')
    if figure.size != FIGURE_SIZE:
        raise ValueError('像素小人尺寸异常：%s（应为 128x128）' % (figure.size,))
    canvas = Image.new('RGBA', CANVAS, (0, 0, 0, 0))
    canvas.alpha_composite(pedestal.convert('RGBA'), _placement(pedestal))
    canvas.alpha_composite(figure, (0, 0))
    return canvas


def encode(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format='WEBP', lossless=True, method=4)
    return stream.getvalue()
