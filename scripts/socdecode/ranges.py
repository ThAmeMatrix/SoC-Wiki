"""Render skill range diagrams from the client's own range fields.

The client encodes cast geometry in ``target_select`` (range_select table) plus
``range_min``/``range_max``/``target_width``/``hit_method``.  Descriptions also
use a small set of recurring phrases (十字范围N格（宽M格）, 范围N格内, N*M区域)
for geometry that is applied by game code.  A diagram is only produced when the
shape follows from those sources; anything else keeps the plain-text 范围.
"""
from __future__ import annotations
import io
import re

# range_select.type for the shapes we can draw confidently.
DIAMOND, CROSS, SECTOR, DIRECTION, RECT, PATTERN, ALL = 1, 2, 3, 4, 5, 6, 7
DRAW_LIMIT = 9          # largest distance drawn; 99 means whole field
PASSIVE_CLASS_TYPES = {2, 3, 6, 7}

# Grid rendering
CELL = 22
PADDING = 14
COLOR_RANGE = (59, 130, 246, 110)      # castable selection
COLOR_AREA = (239, 68, 68, 150)        # area of effect
COLOR_LINE = (30, 41, 59, 255)
COLOR_SELF = (250, 204, 21, 255)


def is_passive(item) -> bool:
    return item['type'] == 3 or item['class_type'] in PASSIVE_CLASS_TYPES


def _diamond(radius: int):
    return {(dx, dz) for dx in range(-radius, radius + 1)
            for dz in range(-radius, radius + 1) if abs(dx) + abs(dz) <= radius}


def _cross(radius: int, width: int = 1):
    arm = max(0, (width - 1) // 2)
    cells = set()
    for d in range(-radius, radius + 1):
        for o in range(-arm, arm + 1):
            cells.add((d, o))
            cells.add((o, d))
    return cells


def _strip(length: int, width: int):
    half = max(0, (width - 1) // 2)
    return {(dx, dz) for dz in range(0, max(0, length)) for dx in range(-half, half + 1)}


def _rect(width: int, length: int):
    half = max(0, (width - 1) // 2)
    return {(dx, dz) for dz in range(0, max(0, length)) for dx in range(-half, half + 1)}


AREA_RULES = (
    # 十字范围3格（宽3格）/ 十字范围N格
    (re.compile(r'十字范围(\d+)格(?:（宽(\d+)格）)?'), lambda m: {'shape': 'cross', 'radius': int(m[1]), 'width': int(m[2] or 3)}),
    # 范围2格内 / 范围2圈内
    (re.compile(r'范围(\d+)[格圈]内'), lambda m: {'shape': 'diamond', 'radius': int(m[1])}),
    # 正前方3*5区域 / 3*5区域内
    (re.compile(r'(?:正前方|前方)?(\d+)\*(\d+)区域'), lambda m: {'shape': 'rect', 'width': int(m[1]), 'length': int(m[2])}),
)


def parse_area(desc: str):
    """Geometry stated by the description, first matching rule wins."""
    for pattern, build in AREA_RULES:
        match = pattern.search(desc or '')
        if match:
            return build(match)
    return None


def plan(item) -> dict | None:
    """Resolve the diagram plan, or None when the client data is not decisive.

    Returns {'cast': cells, 'area': cells, 'target': (dx,dz), 'label': str,
    'note': str|None} with the caster at (0, 0) and +z pointing forward.
    """
    if is_passive(item):
        return None
    rmin, rmax = int(item['range_min'] or 0), int(item['range_max'] or 0)
    width = int(item['target_width'] or 1)
    select = int(item['target_select'] or 1)
    hit = int(item['hit_method'] or 0)
    text = re.sub(r'<[^>]+>', '', item.get('desc') or '')
    whole_field = rmax >= 99
    reach = min(DRAW_LIMIT, 6) if whole_field else rmax

    cast = set()
    shape_ok = True
    if select == DIAMOND:
        cast = {(dx, dz) for dx in range(-reach, reach + 1) for dz in range(-reach, reach + 1)
                if rmin <= abs(dx) + abs(dz) <= reach}
    elif select == CROSS:
        cast = {(d, 0) for d in range(-reach, reach + 1) if rmin <= abs(d) <= reach}
        cast |= {(0, d) for d in range(-reach, reach + 1) if rmin <= abs(d) <= reach}
    elif select == DIRECTION:
        cast = _strip(reach - rmin + 1, width)
        cast = {(dx, dz + rmin) for dx, dz in cast}
    else:
        shape_ok = False

    area_rule = parse_area(text)
    single = hit == 2 or width <= 1
    target = (0, 0)
    area = {(0, 0)}
    label = ''
    if area_rule:
        rule = area_rule
        if rule['shape'] == 'cross':
            area = _cross(rule['radius'], rule.get('width', 3))
            label = f"十字{rule['radius']}格" + (f"（宽{rule.get('width', 3)}格）" if rule.get('width', 3) > 1 else '')
        elif rule['shape'] == 'diamond':
            area = _diamond(min(rule['radius'], DRAW_LIMIT))
            label = f"菱形{rule['radius']}格"
        elif rule['shape'] == 'rect':
            area = _rect(min(rule['width'], DRAW_LIMIT * 2), min(rule['length'], DRAW_LIMIT * 2))
            label = f"{rule['width']}×{rule['length']}区域"
        target = (0, min(reach, DRAW_LIMIT)) if cast else (0, 0)
        if not cast and whole_field:
            target = (0, 0)
    elif single:
        label = '单体'
        target = (0, min(reach, DRAW_LIMIT)) if cast else (0, 0)
    elif select == DIAMOND and width > 1 and shape_ok:
        area = _diamond(min(width - 1, DRAW_LIMIT))
        label = f"菱形{width - 1}格"
        target = (0, min(reach, DRAW_LIMIT)) if cast else (0, 0)
    elif select == CROSS and width > 1 and shape_ok:
        area = _cross(reach, width)
        label = f"十字{reach}格（宽{width}格）"
        target = (0, min(reach, DRAW_LIMIT)) if cast else (0, 0)
    else:
        return None

    if not area_rule and select == DIAMOND and width > 1 and not single:
        # 客户端字段给出行数与描述惯例（范围N格）一致时才算可靠；
        # 描述里出现与字段矛盾的形状词时退回文本。
        if re.search(r'十字|扇形|直线|矩形|区域', text):
            return None
    area = {(dx + target[0], dz + target[1]) for dx, dz in area}
    note = '全图选择' if whole_field else None
    return {'cast': cast, 'area': area, 'target': target, 'label': label or '见技能说明', 'note': note}


def bounds(cells_sets):
    xs = [x for cells in cells_sets for x, _ in cells]
    zs = [z for cells in cells_sets for _, z in cells]
    return min(xs), max(xs), min(zs), max(zs)


def render_png(plan_data, tiles=None) -> bytes:
    """Draw the range with the client's own battle-grid art when available.

    tiles = {'cast','area','target','self'} images (see socdecode.rangetiles);
    missing entries fall back to flat colours so the diagram is still produced.
    """
    from PIL import Image, ImageDraw
    import io
    tiles = tiles or {}
    x0, x1, z0, z1 = bounds([plan_data['cast'] or plan_data['area'], plan_data['area']])
    if not plan_data['cast']:
        z0 = min(z0, 0)
    grid_w, grid_h = x1 - x0 + 1, z1 - z0 + 1
    width = grid_w * CELL + PADDING * 2
    height = grid_h * CELL + PADDING * 2 + 16
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    def origin(cell):
        x, z = cell
        px = PADDING + (x - x0) * CELL
        py = PADDING + (z1 - z) * CELL          # forward (+z) points up
        return px, py

    def tile(kind, size=CELL):
        picture = tiles.get(kind)
        if picture is None:
            return None
        return picture.resize((size, size), Image.LANCZOS)

    def layer(cells, kind, colour):
        picture = tile(kind)
        for cell in cells:
            px, py = origin(cell)
            if picture is not None:
                image.alpha_composite(picture, (px, py))
            else:
                draw.rectangle([px, py, px + CELL - 1, py + CELL - 1], fill=colour)

    layer(sorted(plan_data['cast']), 'cast', COLOR_RANGE)
    layer(sorted(plan_data['area']), 'area', COLOR_AREA)
    if not tiles.get('cast') and not tiles.get('area'):
        for cell in sorted(set(plan_data['cast']) | set(plan_data['area'])):
            px, py = origin(cell)
            draw.rectangle([px, py, px + CELL - 1, py + CELL - 1], outline=COLOR_LINE)
    marker = tile('self')
    px, py = origin((0, 0))
    if marker is not None:
        image.alpha_composite(marker, (px, py))
    else:
        draw.ellipse([px + 5, py + 5, px + CELL - 6, py + CELL - 6], outline=COLOR_SELF, width=3)
    marker = tile('target')
    px, py = origin(plan_data['target'])
    if marker is not None:
        image.alpha_composite(marker, (px, py))
    else:
        draw.rectangle([px + 2, py + 2, px + CELL - 3, py + CELL - 3], outline=(255, 255, 255, 255), width=2)
    label = plan_data['label'] + ('（' + plan_data['note'] + '）' if plan_data['note'] else '')
    try:
        from PIL import ImageFont
        font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 13)
        draw.text((PADDING, height - 17), label, fill=(30, 41, 59, 255), font=font)
    except OSError:
        pass
    stream = io.BytesIO()
    image.save(stream, format='WEBP', lossless=True, method=4)
    return stream.getvalue()
