"""Offline editorial poster renderer. Source pixels and confirmed text stay intact."""
import base64
from io import BytesIO
import json
from pathlib import Path
import random
import re
from PIL import Image, ImageDraw, ImageFont, ImageOps, PngImagePlugin
from backend.contracts import require
from backend.media_exports import font_path

WIDTH, HEIGHT = 1080, 1800
STYLES = {'zine': ('#e8dfc6', '#25271f', '#2449a8'),
          'editorial': ('#f4f1e9', '#25231f', '#a74c37'),
          'minimal': ('#fcfcf8', '#23372f', '#728e7b')}


def confirmed_text(snapshot):
    require(isinstance(snapshot, dict) and isinstance(snapshot.get('content'), dict), 'INVALID_INPUT', '确认稿件格式无效')
    content = snapshot['content']
    title, body, cta = content.get('selected_title'), content.get('body'), content.get('cta', '')
    require(all(isinstance(t, str) for t in (title, body, cta)) and bool(title.strip()) and bool(body.strip()),
            'INVALID_INPUT', '确认稿件缺少标题或正文')
    require(len(title) <= 500 and len(body) + len(cta) <= 6000, 'INVALID_INPUT', '单张海报文字过多，请使用分张图卡')
    return title, body, cta


def _font(size, serif=False):
    path = '/System/Library/Fonts/Supplemental/Songti.ttc' if serif else font_path()
    if not path or not Path(path).is_file(): path = font_path()
    require(bool(path), 'MEDIA_UNAVAILABLE', '本机缺少中文字体，无法生成海报')
    return ImageFont.truetype(path, size)


def _wrap(text, font, width):
    # Preserve all source characters, including whitespace and paragraph breaks.
    lines = []
    for paragraph in text.split('\n'):
        current = ''
        for char in paragraph:
            if current and font.getlength(current + char) > width:
                lines.append(current); current = ''
            current += char
        lines.append(current)
    return lines


def _fit(text, width, height, maximum, minimum, serif=False):
    for size in range(maximum, minimum - 1, -1):
        font = _font(size, serif)
        lines = _wrap(text, font, width)
        spacing = int(size * 1.48)
        if len(lines) * spacing <= height:
            return font, lines, spacing
    require(False, 'INVALID_INPUT', '确认稿件文字无法完整放入单张海报，请使用分张图卡；未截断文字')


def _draw_lines(draw, xy, lines, font, spacing, color):
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=color, anchor='lt')
        y += spacing


def brief_options(brief):
    """A small explicit local control vocabulary, not an LLM interpretation."""
    clean = re.sub(r'[，,。.!！；;\s]+', '', brief)
    for word in ('帮我', '请', '改成', '改为', '设置为', '使用', '采用', '生成', '制作', '海报', '风格', '纸感', '档案', '极简', '编辑刊物', '保留原文', '不改文字', '保留产品', '强调色', '背景', '更大留白', '增加留白', '蓝色', '红色', '绿色', '米色', '白色', '蓝', '红', '绿'):
        clean = clean.replace(word, '')
    require(not clean, 'INVALID_INPUT', '本地排版支持蓝色/红色/绿色强调色、米色/白色背景、增加留白；其他自由修改需要图像模型，未擅自忽略要求')
    colors = [color for word, color in (('蓝', '#2449a8'), ('红', '#a74c37'), ('绿', '#486c50')) if word in brief]
    require(len(colors) <= 1, 'INVALID_INPUT', '请只选择一种强调色')
    require(not ('米色' in brief and '白色' in brief), 'INVALID_INPUT', '请只选择一种背景颜色')
    return {'accent': colors[0] if colors else None, 'paper': '#ffffff' if '白色' in brief else ('#e8dfc6' if '米色' in brief else None), 'whitespace': '增加留白' in brief or '更大留白' in brief}


def render(source_image, snapshot, brief, style='zine'):
    from backend.posters import normalize_image
    require(style in STYLES, 'INVALID_INPUT', '不支持的本地海报风格')
    require(isinstance(brief, str) and len(brief) <= 4000, 'INVALID_INPUT', '海报说明过长或无效')
    source = normalize_image(source_image)
    title, body, cta = confirmed_text(snapshot)
    options = brief_options(brief)
    paper, ink, accent = STYLES[style]
    paper, accent = options['paper'] or paper, options['accent'] or accent
    canvas = Image.new('RGB', (WIDTH, HEIGHT), paper)
    if style != 'minimal':
        rng = random.Random(27)
        grain = Image.new('RGB', (270, 450))
        base = tuple(int(paper[i:i+2], 16) for i in (1, 3, 5))
        noise = [rng.randrange(-9, 10) for _ in range(270 * 450)]
        grain.putdata([tuple(max(0, min(255, c + delta)) for c in base) for delta in noise])
        canvas = Image.blend(canvas, grain.resize(canvas.size, Image.Resampling.BICUBIC), .42)
    draw = ImageDraw.Draw(canvas)
    small = _font(20)
    draw.text((74, 54), '有迹 / 物件档案', font=small, fill=ink)
    draw.text((876, 54), '01 / 01', font=small, fill=ink)
    draw.line((74, 98, 1006, 98), fill=ink, width=1)
    headline, headline_lines, lead = _fit(title, 910, 286, 79, 36, serif=style != 'minimal')
    _draw_lines(draw, (74, 139), headline_lines, headline, lead, ink)
    photo_top, photo_height = 466, 588
    photo_left, photo_width = (74, 770) if style == 'zine' else (74, 932)
    if options['whitespace']:
        photo_left += 60; photo_width -= 120; photo_top += 40; photo_height -= 80
    if style == 'zine':
        draw.rectangle((photo_left - 20, photo_top + 116, photo_left + 230, photo_top + photo_height + 29), fill=accent)
        rng = random.Random(11)
        x0, y0, x1, y1 = photo_left - 8, photo_top - 8, photo_left + photo_width + 8, photo_top + photo_height + 8
        points = [(x, y0 + rng.randrange(-3, 4)) for x in range(x0, x1, 10)]
        points += [(x1 + rng.randrange(-3, 4), y) for y in range(y0, y1, 10)]
        points += [(x, y1 + rng.randrange(-3, 4)) for x in range(x1, x0, -10)]
        points += [(x0 + rng.randrange(-3, 4), y) for y in range(y1, y0, -10)]
        draw.polygon(points, fill='#faf6e9')
        draw.text((889, 480), '实物', font=small, fill=ink)
        draw.text((889, 997), '图 01', font=small, fill=ink)
    else:
        draw.rectangle((photo_left, photo_top-15, photo_left+104, photo_top-9), fill=accent)
    with Image.open(BytesIO(base64.b64decode(source['data_url'].split(',', 1)[1]))) as original:
        original = original.convert('RGBA')
        fitted = ImageOps.contain(original, (photo_width, photo_height), Image.Resampling.LANCZOS)
        # Contain preserves the whole photographed subject rather than cropping it.
        photo = Image.new('RGB', (photo_width, photo_height), '#f6f2e7')
        photo.paste(fitted, ((photo_width-fitted.width)//2, (photo_height-fitted.height)//2), fitted)
        canvas.paste(photo, (photo_left, photo_top))
    draw = ImageDraw.Draw(canvas)
    draw.line((74, 1110, 1006, 1110), fill=accent, width=2)
    full_body = body + ('\n\n' + cta if cta else '')
    body_font, body_lines, spacing = _fit(full_body, 932, 548, 34, 20)
    _draw_lines(draw, (74, 1140), body_lines, body_font, spacing, ink)
    draw.line((74, 1718, 1006, 1718), fill=ink, width=1)
    draw.text((74, 1742), '有迹 · 已确认稿件', font=small, fill=ink)
    draw.text((788, 1742), {'zine':'纸感档案','editorial':'编辑刊物','minimal':'极简留白'}[style], font=small, fill=accent)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('youji_confirmed_text', json.dumps({'selected_title': title, 'body': body, 'cta': cta}, ensure_ascii=False))
    metadata.add_text('youji_renderer', 'local-pillow-v1/' + style)
    output = BytesIO(); canvas.save(output, format='PNG', pnginfo=metadata)
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode()
