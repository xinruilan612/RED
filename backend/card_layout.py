"""Deterministic card pagination, raster input validation and visual composition."""
import base64
import hashlib
import re
from io import BytesIO
from backend.contracts import require

CLOSING = '，。！？；：、）】》”’,.!?;:)]％%'
PALETTES = {'green': ('#205c4b', '#e7f0e9'), 'orange': ('#a54424', '#fae9db'), 'blue': ('#28598e', '#e4edf8')}

def normalize_options(options):
    from PIL import Image, ImageOps
    options = {} if options is None else options
    require(isinstance(options, dict) and not set(options) - {'page_styles', 'global_style', 'cover_image', 'product_photo'}, 'INVALID_INPUT', '图卡设置无效')
    styles = options.get('page_styles', {})
    require(isinstance(styles, dict) and len(styles) <= 24, 'INVALID_INPUT', '页面设置无效')
    normalized = {}
    for key, value in styles.items():
        require(isinstance(key, str) and re.fullmatch(r'0|[1-9]\d?', key) and isinstance(value, dict) and not set(value) - {'size', 'accent'}, 'INVALID_INPUT', '页面设置无效')
        size, accent = value.get('size', 'normal'), value.get('accent', 'green')
        require(isinstance(size, str) and isinstance(accent, str) and size in ('normal', 'large') and accent in PALETTES, 'INVALID_INPUT', '字号或强调色无效')
        normalized[key] = {'size': size, 'accent': accent}
    photo_mode = options.get('product_photo', 'auto')
    require(isinstance(photo_mode, str) and photo_mode in ('auto', 'none'), 'INVALID_INPUT', '产品图片设置无效')
    result, image = {'page_styles': normalized, 'product_photo': photo_mode}, None
    if 'global_style' in options:
        style = options['global_style']
        require(isinstance(style, dict) and not set(style) - {'size', 'accent'}, 'INVALID_INPUT', '整套图片设置无效')
        size, accent = style.get('size', 'normal'), style.get('accent', 'green')
        require(isinstance(size, str) and size in ('normal', 'large') and isinstance(accent, str) and accent in (*PALETTES, 'default'), 'INVALID_INPUT', '字号或强调色无效')
        result['global_style'] = {'size': size, 'accent': accent}
    data = options.get('cover_image')
    if data is not None:
        require(isinstance(data, str) and len(data) <= 4200000 and re.match(r'^data:image/(png|jpeg);base64,', data), 'INVALID_INPUT', '产品图片只接受不超过3MB的PNG或JPEG图片')
        try:
            raw = base64.b64decode(data.split(',', 1)[1], validate=True)
            require(len(raw) <= 3 * 1024 * 1024, 'INVALID_INPUT', '产品图片超过3MB')
            with Image.open(BytesIO(raw)) as probe:
                require(probe.format in ('PNG', 'JPEG') and probe.width * probe.height <= 12000000 and probe.width > 0 and probe.height > 0, 'INVALID_INPUT', '产品图片格式无效或超过1200万像素')
                probe.verify()
            with Image.open(BytesIO(raw)) as original:
                image = ImageOps.exif_transpose(original).convert('RGB')
                image.thumbnail((1600, 1600))
            result['image_sha256'] = hashlib.sha256(raw).hexdigest()
        except (ValueError, OSError, Image.DecompressionBombError):
            require(False, 'INVALID_INPUT', '无法读取产品图片，请选择有效PNG或JPEG')
    return result, image

def wrap(text, font, width):
    lines = []
    for paragraph in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        current = ''
        # Words remain whole; CJK breaks between characters.
        for token in re.findall(r'[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*|[^A-Za-z0-9]', paragraph):
            if current and font.getlength(current + token) > width:
                if token in CLOSING and len(current) > 1:
                    # Move a whole trailing Latin word, or one CJK character, with punctuation.
                    tail = re.search(r'[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$', current)
                    split = tail.start() if tail else len(current) - 1
                    if split:
                        lines.append(current[:split]); current = current[split:] + token
                    else:
                        current += token
                else:
                    lines.append(current); current = token
            else:
                current += token
        lines.append(current)
    return lines

def paginate(body, font, width=840, capacity=970, line_height=62):
    """Keep ordinary paragraphs together; split only paragraphs taller than a page."""
    paragraphs = re.split(r'\n\s*\n|\n(?=[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.、])', body.replace('\r\n', '\n').replace('\r', '\n'))
    pages, blocks, used = [], [], 0
    limit = lambda: capacity(len(pages)) if callable(capacity) else capacity
    for paragraph in paragraphs:
        if not paragraph.strip(): continue
        lines = wrap(paragraph, font, width)
        # Move an intact paragraph to the next page when it fits there. Only
        # oversized paragraphs split, and later no-photo pages use their full height.
        while lines:
            height = len(lines) * line_height + 48
            if blocks and used + height > limit():
                pages.append(blocks); blocks, used = [], 0
                continue
            count = max(1, (limit() - used - 48) // line_height)
            part, lines = lines[:count], lines[count:]
            blocks.append(''.join(part)); used += len(part) * line_height + 48
            if lines:
                pages.append(blocks); blocks, used = [], 0
    if blocks: pages.append(blocks)
    return pages or [['']]

def compose(snapshot, template, font_path, options, width=1080, height=1440):
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    normalized, cover = normalize_options(options)
    from backend.product_photos import catalog_images, photo_identity
    photo = snapshot.get('product_photo')
    pictures = catalog_images(photo) if photo and photo.get('photos') else ([cover] if cover else [])
    photo_identity(normalized, photo)
    font = lambda n: ImageFont.truetype(font_path, n)
    c = snapshot['content']
    title, body = c['selected_title'], c['body'] + ('\n\n' + c['cta'] if c.get('cta') else '')
    require(len(title) <= 500 and len(body) <= 30000, 'INVALID_INPUT', '稿件太长，请缩短后再制作图片')
    # A dedicated photo band keeps text away from product imagery. Stable normal-size
    # pagination means changing one page's font never moves its image or paragraphs.
    body_pages = paginate(body, font(40), capacity=lambda n: 700 if n + 1 < len(pictures) else 970)
    require(len(body_pages) + 1 <= 24, 'INVALID_INPUT', '正文超过24页，请先缩短稿件')
    require(all(int(k) < len(body_pages) + 1 for k in normalized['page_styles']), 'INVALID_INPUT', '页面已变化，请重新预览后调整')
    pages, metadata = [], []
    for index, blocks in enumerate([None] + body_pages):
        cover = pictures[index] if index < len(pictures) else None
        body_capacity = 700 if cover else 970
        page_photo = ((photo.get('photos') or [photo])[index] if photo and index < len(pictures) else None)
        setting = normalized.get('global_style', normalized['page_styles'].get(str(index), {}))
        accent, tint = PALETTES['green' if setting.get('accent', 'green') == 'default' else setting.get('accent', 'green')]
        large = setting.get('size') == 'large'
        im = Image.new('RGB', (width, height), '#f8f6ef' if template == 'classic' else tint)
        draw = ImageDraw.Draw(im)
        small = font(25)
        draw.text((70, 52), '有迹 / ' + ('图文笔记' if template == 'classic' else '重点清单'), font=small, fill=accent)
        draw.text((875, 52), f'{index + 1:02d} / {len(body_pages) + 1:02d}', font=small, fill=accent)
        draw.line((70, 108, 1010, 108), fill=accent, width=2)
        notice = ''
        if index == 0:
            title_size = 88 if large else 78
            available = 510 if cover else 820
            while title_size > 30 and (len(wrap(title, font(title_size), 870)) * int(title_size * 1.45) > available or any(font(title_size).getlength(line) > 870 for line in wrap(title, font(title_size), 870))):
                title_size -= 2
            lines = wrap(title, font(title_size), 870)
            require(len(lines) * int(title_size * 1.45) <= available and all(font(title_size).getlength(line) <= 870 for line in lines), 'INVALID_INPUT', '标题太长，请先缩短标题')
            if title_size < (88 if large else 78): notice = '标题较长，已自动适配字号以完整显示。'
            draw.rounded_rectangle((70, 160, 330, 213), radius=26, fill=accent)
            draw.text((93, 167), '重点内容 · 一起看', font=font(26), fill='white')
            y = 270
            for line in lines:
                draw.text((70, y), line, font=font(title_size), fill='#17382e' if template == 'classic' else accent)
                y += int(title_size * 1.45)
            if cover:
                fitted = ImageOps.contain(cover, (940, 440), method=Image.Resampling.LANCZOS)
                draw.rounded_rectangle((70, 820, 1010, 1260), radius=24, fill=tint)
                im.paste(fitted, (70 + (940 - fitted.width) // 2, 820 + (440 - fitted.height) // 2))
            else:
                headings = re.findall(r'(?:^|\n)\s*[①②③④⑤⑥⑦⑧⑨⑩]\s*([^：:\n]{1,12})[：:]', body)[:3]
                if headings and y < 700:
                    if template == 'classic':
                        for n, label in enumerate(headings):
                            x = 70 + n * 320
                            draw.rounded_rectangle((x, 790, x + 295, 1130), radius=22, fill=accent if n == 0 else tint)
                            ink = 'white' if n == 0 else accent
                            draw.text((x + 24, 815), f'{n + 1:02d}', font=font(94), fill=ink)
                            for row, line in enumerate(wrap(label, font(36), 248)):
                                draw.text((x + 24, 992 + row * 49), line, font=font(36), fill=ink)
                    else:
                        for n, label in enumerate(headings):
                            top = 720 + n * 166
                            draw.rounded_rectangle((70, top, 1010, top + 144), radius=24, fill='white')
                            draw.text((100, top + 22), f'{n + 1:02d}', font=font(72), fill=accent)
                            draw.text((265, top + 43), label, font=font(42), fill=accent)
                elif y < 950:
                    draw.ellipse((700, 800, 1010, 1110), outline=accent, width=22)
                    draw.rounded_rectangle((70, 990, 1010, 1250), radius=28, fill=accent)
                    draw.text((102, 1080), '把重要的信息，留在这一页', font=font(36), fill='white')
            page_title = '封面'
        else:
            size = 47 if large else 40
            def measured(s):
                return [(text, wrap(text, font(s), 840)) for text in blocks]
            layout = measured(size)
            while size > 26 and (sum(len(lines) * int(size * 1.55) + 48 for _, lines in layout) > body_capacity or any(font(size).getlength(line) > 840 for _, lines in layout for line in lines)):
                size -= 1; layout = measured(size)
            require(all(font(size).getlength(line) <= 840 for _, lines in layout for line in lines), 'INVALID_INPUT', '单个英文词或链接过长，请缩短后制作图卡')
            if large and size < 47: notice = '本页文字较多，已自动适配字号，保留全部内容。'
            draw.text((70, 154), ('阅读笔记' if template == 'classic' else '逐项看清楚'), font=font(38), fill=accent)
            y = 240
            if cover:
                draw.rounded_rectangle((70, 220, 1010, 510), radius=24, fill='white' if template == 'checklist' else tint)
                fitted = ImageOps.contain(cover, (410, 260), method=Image.Resampling.LANCZOS)
                im.paste(fitted, (90 + (410 - fitted.width) // 2, 235 + (260 - fitted.height) // 2))
                # Topic labels are literal excerpts, never generated product claims.
                match = re.match(r'\s*[①②③④⑤⑥⑦⑧⑨⑩]\s*([^：:\n]{1,12})[：:]', blocks[0])
                label = page_photo.get('view_label', '产品图片') if page_photo else (match.group(1) if match else '产品图片')
                draw.text((545, 275), f'{index:02d}', font=font(66), fill=accent)
                for row, line in enumerate(wrap(label, font(38), 410)):
                    draw.text((545, 367 + row * 52), line, font=font(38), fill=accent)
                y = 555
            for block_index, (text, lines) in enumerate(layout):
                h = len(lines) * int(size * 1.55) + 32
                if template == 'checklist':
                    draw.rounded_rectangle((70, y - 6, 1010, y + h), radius=22, fill='white')
                    draw.rounded_rectangle((70, y - 6, 82, y + h), radius=5, fill=accent)
                else:
                    draw.line((80, y, 80, y + h - 16), fill=accent, width=4)
                for line in lines:
                    draw.text((112, y + 8), line, font=font(size), fill='#253830')
                    y += int(size * 1.55)
                y += 48
            page_title = f'正文 · {index}'
        draw.text((70, 1340), '滑动阅读  →' if index < len(body_pages) else '保存这份笔记，按需核对', font=small, fill=accent)
        if cover and page_photo:
            draw.text((70, 1390), f"图片：{page_photo['author']} / {page_photo['license']} · 等比缩放", font=font(20), fill=accent)
        data = BytesIO(); im.save(data, format='PNG')
        pages.append((f'{index + 1:02d}.png', data.getvalue()))
        metadata.append({'title': page_title, 'notice': notice, 'photo_id': page_photo.get('id') if page_photo else ('user-upload' if cover else None), 'photo_sha256': page_photo.get('sha256') if page_photo else (normalized.get('image_sha256') if cover else None), 'photo_source_url': page_photo.get('source_url') if page_photo else None})
    return pages, metadata, normalized
