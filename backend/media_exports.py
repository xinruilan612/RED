"""Real local typesetting and silent slide video from confirmed draft snapshots."""
from io import BytesIO
from pathlib import Path
import hashlib
import json
import os
import subprocess
import tempfile
import zipfile

from backend.contracts import require
from backend.workflow import digest

WIDTH, HEIGHT = 1080, 1440
MARGIN, BODY_SIZE, LINE_HEIGHT = 90, 42, 68
MAX_PAGES = 24


def font_path():
    candidates = [os.environ.get('YOUJI_CJK_FONT', ''),
                  '/System/Library/Fonts/STHeiti Medium.ttc',
                  '/System/Library/Fonts/PingFang.ttc',
                  'C:/Windows/Fonts/msyh.ttc',
                  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    return next((str(Path(p)) for p in candidates if p and Path(p).is_file()), None)


def capabilities():
    try:
        from PIL import ImageFont
        path = font_path()
        if path:
            ImageFont.truetype(path, BODY_SIZE)
        images = bool(path)
    except (ImportError, OSError):
        images = False
    video = False
    if images:
        try:
            import imageio_ffmpeg
            result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-version'], capture_output=True, timeout=5)
            video = result.returncode == 0
        except (ImportError, OSError, RuntimeError, subprocess.TimeoutExpired):
            pass
    return {'images_available': images, 'storyboard_available': True, 'video_available': video,
            'images_message': '下载封面和正文图片，无需模型费用。' if images else '图文导出需要 Pillow 和中文字体，请先配置运行环境。',
            'video_message': '生成无声图文翻页视频，可在剪辑软件中添加自己的配音。' if video else '视频成片暂不可用；可以先下载分镜与字幕。'}


def confirmed_snapshot(run):
    require(run.workflow_type == 'creation' and run.run_status == 'SUCCEEDED' and run.accepted_ref,
            'INVALID_TRANSITION', '请先确认或人工采用准确稿件版本，再制作成品')
    draft = next((d for d in run.drafts if d['ref'] == run.accepted_ref), None)
    acceptance = run.acceptance or {}
    require(draft and acceptance.get('draft_ref') == run.accepted_ref and
            acceptance.get('content_hash') == digest(draft['content']) == draft['content_hash'] and
            draft['snapshot_id'] == acceptance.get('snapshot_id') == run.snapshot_id,
            'VERSION_CONFLICT', '已确认稿件版本发生变化，请重新确认')
    return {'schema_version': 1, 'run_id': run.run_id, 'snapshot_id': run.snapshot_id,
            'draft_ref': draft['ref'], 'content_hash': draft['content_hash'],
            'mode': run.context.get('mode', 'simulation'), 'acceptance': acceptance,
            'source_refs': [{k: source.get(k) for k in ('source_id', 'document_id', 'version', 'url', 'source_url', 'page')}
                            for source in run.context.get('evidence', []) + run.context.get('web_research', {}).get('sources', [])],
            'content': draft['content'],
            'notice': '排版导出不表示平台发布成功；图片仅为文字排版，无生成插画。'}


def wrap_text(text, font, max_width):
    lines = []
    for paragraph in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        current = ''
        for char in paragraph:
            if current and font.getlength(current + char) > max_width:
                lines.append(current)
                current = char
            else:
                current += char
        lines.append(current)
    return lines


def render_images(snapshot):
    require(capabilities()['images_available'], 'MEDIA_UNAVAILABLE', '图文导出需要 Pillow 和可用的中文字体')
    from PIL import Image, ImageDraw, ImageFont
    path = font_path()
    title_font, body_font, small_font = (ImageFont.truetype(path, n) for n in (70, BODY_SIZE, 28))
    c = snapshot['content']
    title = c['selected_title']
    body = c['body'] + ('\n\n' + c['cta'] if c.get('cta') else '')
    require(len(title) <= 500 and len(body) <= 30000, 'INVALID_INPUT', '稿件太长，请缩短后再制作图片')
    title_width = WIDTH - 2 * MARGIN
    measured = title_font.getlength(title)
    if measured > title_width:
        import math
        title_width = min(title_width, math.ceil(measured / math.ceil(measured / title_width)) + 20)
    title_lines = wrap_text(title, title_font, title_width)
    require(len(title_lines) <= 10, 'INVALID_INPUT', '标题太长，请先缩短标题')
    lines = wrap_text(body, body_font, WIDTH - 2 * MARGIN)
    per_page = (HEIGHT - 370) // LINE_HEIGHT
    chunks = [lines[i:i + per_page] for i in range(0, len(lines), per_page)]
    require(len(chunks) + 1 <= MAX_PAGES, 'INVALID_INPUT', '正文超过 24 页，请先缩短稿件')
    pages = []
    for index, chunk in enumerate([None] + chunks):
        im = Image.new('RGB', (WIDTH, HEIGHT), '#f8f5ee')
        draw = ImageDraw.Draw(im)
        draw.rectangle((MARGIN, 150, MARGIN + 130, 162), fill='#32705b')
        draw.text((MARGIN, 75), '有迹 · ' + ('封面' if index == 0 else '正文'), font=small_font, fill='#32705b')
        if index == 0:
            y = max(260, (HEIGHT - len(title_lines) * 100) // 2 - 100)
            for line in title_lines:
                draw.text((MARGIN, y), line, font=title_font, fill='#203d32')
                y += 100
            draw.text((MARGIN, min(HEIGHT - 190, y + 70)), '向左滑动，查看完整内容 →', font=small_font, fill='#5b6b63')
        else:
            draw.text((MARGIN, 205), '正文 · 第 ' + str(index) + ' 页', font=small_font, fill='#5b6b63')
            for row, line in enumerate(chunk):
                draw.text((MARGIN, 295 + row * LINE_HEIGHT), line, font=body_font, fill='#253c34')
        draw.text((WIDTH - MARGIN - 120, HEIGHT - 85), f'{index + 1}/{len(chunks) + 1}', font=small_font, fill='#5b6b63')
        data = BytesIO()
        im.save(data, format='PNG')
        pages.append((f'{index + 1:02d}.png', data.getvalue()))
    return pages


def _timestamp(seconds):
    return f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d},000'


def _storyboard(snapshot):
    c = snapshot['content']
    text = c['selected_title'] + '\n' + c['body'] + ('\n' + c['cta'] if c.get('cta') else '')
    segments = []
    for paragraph in text.splitlines():
        for i in range(0, len(paragraph), 24):
            if paragraph[i:i+24].strip():
                segments.append(paragraph[i:i+24])
    srt, board, start = [], ['# 可编辑分镜与字幕', '', '这是文字制作素材，不是视频成片；字幕时长为建议值，请配合自己的录音调整。', ''], 0
    for i, segment in enumerate(segments, 1):
        duration = max(3, (len(segment) + 3) // 4)
        srt.append(f'{i}\n{_timestamp(start)} --> {_timestamp(start+duration)}\n{segment}\n')
        board.append(f'{i}. {start}–{start+duration} 秒：{segment}')
        start += duration
    return [('subtitles.srt', '\n'.join(srt).encode()), ('storyboard.md', '\n'.join(board).encode())]


def _video(snapshot):
    require(capabilities()['video_available'], 'MEDIA_UNAVAILABLE', '视频编码器或中文字体不可用，请先下载图文包')
    import imageio_ffmpeg
    pages = render_images(snapshot)
    require(len(pages) <= 15, 'INVALID_INPUT', '视频最多 15 页（120 秒），请缩短稿件或下载图文包')
    with tempfile.TemporaryDirectory(prefix='youji-media-') as folder:
        base = Path(folder)
        for name, data in pages:
            (base / name).write_bytes(data)
        (base / f'{len(pages) + 1:02d}.png').write_bytes(pages[-1][1])
        output = base / 'video.mp4'
        command = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y',
                   '-framerate', '1/8', '-i', str(base / '%02d.png'),
                   '-vf', 'scale=720:960,fps=24', '-t', str(8 * len(pages)),
                   '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '24', '-pix_fmt', 'yuv420p',
                   '-movflags', '+faststart', '-an', str(output)]
        try:
            result = subprocess.run(command, capture_output=True, timeout=90, cwd=base)
        except (OSError, subprocess.TimeoutExpired):
            require(False, 'MEDIA_UNAVAILABLE', '视频制作超时或编码器不可用，请下载图文包后重试')
        require(result.returncode == 0 and output.is_file(), 'MEDIA_UNAVAILABLE', '视频制作失败，请下载图文包')
        snapshot['video'] = {'duration_seconds': len(pages) * 8, 'width': 720, 'height': 960,
                             'audio': False, 'kind': 'silent_text_slideshow', 'page_count': len(pages)}
        return [('video.mp4', output.read_bytes()), ('README.txt', '这是无声图文翻页视频，每页8秒；长文可暂停阅读。请在剪辑软件中添加自己的配音或调整翻页速度。不是AI口播或真人素材剪辑。'.encode())]


def export_run(run, kind='images'):
    require(kind in ('images', 'storyboard', 'video'), 'INVALID_INPUT', '请选择图文包、分镜字幕或无声图文视频')
    snapshot = confirmed_snapshot(run)
    require(sum(len(str(snapshot['content'].get(k, ''))) for k in ('selected_title', 'body', 'cta')) <= 30500,
            'INVALID_INPUT', '稿件太长，请缩短后再制作成品')
    files = render_images(snapshot) if kind == 'images' else (_video(snapshot) if kind == 'video' else _storyboard(snapshot))
    c = snapshot['content']
    caption = c['selected_title'] + '\n\n' + c['body'] + '\n\n' + c.get('cta', '') + '\n\n' + ' '.join('#' + t for t in c.get('tags', []))
    files.append(('caption.txt', caption.encode()))
    snapshot.update(export_kind=kind, files=[{'name': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in files])
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files:
            archive.writestr(name, data)
        archive.writestr('manifest.json', json.dumps(snapshot, ensure_ascii=False, indent=2))
    return output.getvalue(), 'application/zip', f'youji-{kind}-{run.run_id[:8]}.zip'
