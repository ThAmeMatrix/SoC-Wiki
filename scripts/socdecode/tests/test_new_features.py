"""Tests for range diagrams and pedestal composition."""
import io
import tempfile
from pathlib import Path
from unittest import TestCase, main

from PIL import Image

from socdecode import ranges
from socdecode.pedestal import compose, pedestal_image


def skill(**kwargs):
    base = {'range_min': 1, 'range_max': 2, 'range_width': 1, 'target_select': 1,
            'target_width': 1, 'target_param': '', 'target_method': 1, 'target_type': 2,
            'hit_method': 2, 'type': 1, 'class_type': 1, 'desc': '（普攻）造成80%伤害。'}
    base.update(kwargs)
    return base


class RangeTests(TestCase):
    def test_single_target_hit_method(self):
        plan = ranges.plan(skill(target_width=2, hit_method=2))
        self.assertEqual(plan['label'], '单体')
        self.assertEqual(plan['area'], {(0, 2)})

    def test_diamond_area_from_target_width(self):
        plan = ranges.plan(skill(range_min=1, range_max=3, target_width=3, hit_method=3))
        self.assertEqual(plan['label'], '菱形2格')
        self.assertEqual(len(plan['area']), 13)

    def test_desc_cross_with_width(self):
        desc = '（魔法伤害）选择地形格，对目标十字范围3格（宽3格）内敌人，造成100%范围伤害。'
        plan = ranges.plan(skill(target_width=1, hit_method=3, desc=desc, range_min=0, range_max=3))
        self.assertEqual(plan['label'], '十字3格（宽3格）')
        self.assertIn((0, 6), plan['area'])
        self.assertIn((1, 3), plan['area'])
        self.assertNotIn((2, 5), plan['area'])

    def test_desc_rect_forward(self):
        desc = '（魔法伤害）选择方向，对正前方3*5区域（含自身本行）造成160%范围伤害。'
        plan = ranges.plan(skill(range_min=0, range_max=0, target_width=1, hit_method=3, desc=desc))
        self.assertEqual(plan['label'], '3×5区域')
        self.assertIn((0, 0), plan['area'])
        self.assertIn((1, 4), plan['area'])
        self.assertNotIn((0, 5), plan['area'])

    def test_passive_has_no_diagram(self):
        self.assertIsNone(ranges.plan(skill(type=3)))
        self.assertIsNone(ranges.plan(skill(class_type=2)))

    def test_unresolvable_shape_keeps_text(self):
        self.assertIsNone(ranges.plan(skill(target_select=5, target_width=2, hit_method=3)))

    def test_render_png_is_lossless_webp(self):
        plan = ranges.plan(skill(range_min=1, range_max=3, target_width=3, hit_method=3))
        data = ranges.render_png(plan)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.format, 'WEBP')
            self.assertTrue(image.size[0] > 0)

    def test_render_uses_client_tiles_when_supplied(self):
        plan = ranges.plan(skill(range_min=1, range_max=3, target_width=3, hit_method=3))
        tiles = {name: Image.new('RGBA', (128, 128), (10 + i, 20, 30, 255))
                 for i, name in enumerate(('cast', 'area', 'target', 'self'))}
        plain = ranges.render_png(plan)
        tiled = ranges.render_png(plan, tiles)
        self.assertNotEqual(plain, tiled)
        with Image.open(io.BytesIO(tiled)) as image:
            self.assertEqual(image.format, 'WEBP')


def make_pedestal():
    """A stand-in for the supplied base file: 96x82, opaque block."""
    image = Image.new('RGBA', (96, 82), (0, 0, 0, 0))
    for y in range(10, 82):
        for x in range(4, 92):
            image.putpixel((x, y), (246, 234, 229, 255))
    return image


class PedestalTests(TestCase):
    CANVAS = (128, 160)

    def test_compose_places_figure_at_origin_and_base_at_measured_offset(self):
        figure = Image.new('RGBA', (128, 128), (0, 0, 0, 0))
        for y in range(60, 128):
            for x in range(50, 80):
                figure.putpixel((x, y), (255, 0, 0, 255))
        canvas = compose(figure, make_pedestal())
        self.assertEqual(canvas.size, self.CANVAS)
        pixels = canvas.load()
        self.assertEqual(pixels[64, 60], (255, 0, 0, 255))        # figure drawn at (0,0)
        self.assertEqual(pixels[20, 90], (246, 234, 229, 255))    # base at x=16, y=78
        self.assertEqual(pixels[4, 90], (0, 0, 0, 0))             # left margin kept empty

    def test_figure_size_is_validated(self):
        with self.assertRaises(ValueError):
            compose(Image.new('RGBA', (96, 96), (0, 0, 0, 0)), make_pedestal())

    def test_bundled_pedestal_shipped(self):
        image, provenance = pedestal_image()
        self.assertEqual(image.size, (96, 82))
        self.assertEqual(provenance['placement'], [16, 78])


if __name__ == '__main__':
    main()
