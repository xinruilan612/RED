"""Real local typesetting and silent slide video from confirmed draft snapshots."""
from io import BytesIO
from pathlib import Path
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile

from backend.contracts import require
from backend.workflow import digest
from backend.product_photos import resolve_options, attribution, photo_identity

WIDTH, HEIGHT = 1080, 1440
MARGIN, BODY_SIZE, LINE_HEIGHT = 90, 42, 68
MAX_PAGES = 24
TEMPLATES = {
    'classic': {'id': 'classic', 'version': 3, 'label': '清爽图文'},
    'checklist': {'id': 'checklist', 'version': 3, 'label': '重点清单'},
}


def template_config(template):
    require(isinstance(template, str) and template in TEMPLATES,
            'INVALID_INPUT', '请选择清爽图文或重点清单模板')
    return dict(TEMPLATES[template])


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
    return {'templates': [dict(item) for item in TEMPLATES.values()], 'images_available': images, 'storyboard_available': True, 'complete_available': True, 'video_available': video,
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
            'source_refs': [{k: source.get(k) for k in ('source_id', 'document_id', 'version', 'url', 'source_url', 'page', 'title')}
                            for source in run.context.get('evidence', []) + run.context.get('web_research', {}).get('sources', [])] + _material_sources(run.context.get('material')),
            'user_material_provided': bool(run.context.get('material')),
            'content': draft['content'],
            'notice': '排版导出不表示平台发布成功；产品照片来自标注来源或用户上传，无生成插画。'}


def wrap_text(text, font, max_width):
    from backend.card_layout import wrap
    return wrap(text, font, max_width)


def render_images(snapshot, template='classic', options=None):
    template_config(template)
    require(capabilities()['images_available'], 'MEDIA_UNAVAILABLE', '图文导出需要 Pillow 和可用的中文字体')
    from backend.card_layout import compose
    options, photo = resolve_options(snapshot, options)
    snapshot['product_photo'] = photo
    pages, metadata, normalized = compose(snapshot, template, font_path(), options)
    snapshot['design_options'] = normalized
    snapshot['page_details'] = metadata
    return pages


def design_identity(snapshot, template, options):
    from backend.card_layout import normalize_options
    options, photo = resolve_options(snapshot, options)
    snapshot['product_photo'] = photo
    normalized, _ = normalize_options(options)
    photo_identity(normalized, photo)
    style = template_config(template)
    return normalized, digest({'content_hash': snapshot['content_hash'], 'template': style, 'options': normalized})


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


def _video(snapshot, pages=None, template='classic', options=None):
    template_config(template)
    require(capabilities()['video_available'], 'MEDIA_UNAVAILABLE', '视频编码器或中文字体不可用，请先下载图文包')
    import imageio_ffmpeg
    pages = pages if pages is not None else render_images(snapshot, template=template, options=options)
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



def _safe_source(source):
    from urllib.parse import urlsplit, urlunsplit
    result = {key: source.get(key) for key in ('source_id', 'document_id', 'version', 'page') if source.get(key) is not None}
    if isinstance(source.get('title'), str):
        result['title'] = ' '.join(source['title'].split())[:300]
    for key in ('url', 'source_url'):
        value = source.get(key)
        if not isinstance(value, str): continue
        try:
            parsed = urlsplit(value)
            if parsed.scheme in ('https', 'http') and parsed.hostname:
                # No URL credential, query token or private fragment in exported evidence.
                host = parsed.hostname
                if ':' in host: host = '[' + host + ']'
                result[key] = urlunsplit((parsed.scheme, host, parsed.path, '', ''))
        except ValueError:
            pass
    return result



def _material_sources(material):
    """Extract explicitly labelled links only; never infer a source from copy."""
    if not isinstance(material, str):
        return []
    sources = []
    for line in material.splitlines():
        match = re.match(r'^\s*(?:[-*]\s*)?(?:资料来源|来源|sources?)\s*[:：]\s*(.*)$', line, re.I)
        if not match:
            continue
        for url in re.findall(r'https?://[^\s<>"\)\]]+', match.group(1)):
            safe = _safe_source({'url': url.rstrip('。，；,;')})
            if safe.get('url'):
                sources.append({**safe, 'source_id': 'material-link-' + str(len(sources) + 1),
                    'title': '用户提供的来源链接（未独立核验）'})
    return sources


def _source_instructions(sources, user_material_provided=False):
    """List only saved task sources, not inferred brands or invented provenance."""
    lines, seen = [], set()
    for source in sources:
        url = source.get('url') or source.get('source_url')
        document = source.get('document_id')
        identity = ('url', url) if url else ('document', document, source.get('version')) if document else ('source', source.get('source_id'))
        if not any(identity[1:]) or identity in seen:
            continue
        seen.add(identity)
        label = source.get('title') or ('任务资料 ' + str(document or source.get('source_id')))
        detail = url
        if not detail and source.get('version') is not None:
            detail = '资料版本：' + str(source['version'])
        lines.append('- ' + label + (' — ' + detail if detail else '（未记录公开链接）'))
    return ('资料来源（本任务保存的证据快照，供核对）：\n' + '\n'.join(lines) if lines else
            ('资料来源：用户提供素材未记录可列出的来源链接，请发布前补充核对。' if user_material_provided else
             '资料来源：本任务未保存可列出的来源，请发布前补充核对。'))


def execution_evidence(run, snapshot, execution=None):
    """Explicit allowlist: no raw prompts, diagnostics, owners or runtime secrets."""
    execution = execution or {}
    numeric = lambda value: value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    usage = execution.get('usage', {})
    summaries = {key: numeric(usage.get(key)) for key in ('model_calls', 'tokens', 'unknown_calls', 'cost_upper_estimate_usd')}
    if snapshot['mode'] != 'live':
        summaries.update(model_calls=0, tokens=0, unknown_calls=0, cost_upper_estimate_usd=0)
    calls = []
    for call in execution.get('calls', []):
        if not isinstance(call, dict): continue
        item = {key: call.get(key) for key in ('id', 'agent', 'stage', 'status', 'provider', 'model', 'route_version', 'prompt_version', 'input_hash', 'snapshot_id') if isinstance(call.get(key), str)}
        item.update({key: numeric(call.get(key)) for key in ('tokens', 'input_tokens', 'output_tokens', 'duration_ms')})
        item['audit_legacy'] = call.get('audit_legacy') is True
        item['inherited'] = call.get('inherited') is True
        calls.append(item)
    review_execution = execution.get('review_execution') or {}
    accepted = snapshot['acceptance']
    review = run.review or {}
    final_review_passed = (accepted.get('mode') == 'reviewed' and review.get('decision') == 'approved' and
        review.get('draft_ref') == snapshot['draft_ref'] and review.get('content_hash') == snapshot['content_hash'] and
        review.get('snapshot_id') == snapshot['snapshot_id'] and accepted.get('review_ref') == review.get('ref'))
    return {'schema_version': 1, 'run_id': run.run_id, 'snapshot_id': snapshot['snapshot_id'],
        'draft_ref': snapshot['draft_ref'], 'draft_version': next(i + 1 for i, d in enumerate(run.drafts) if d['ref'] == snapshot['draft_ref']),
        'content_hash': snapshot['content_hash'], 'mode': snapshot['mode'],
        'acceptance_mode': accepted.get('mode'), 'final_ai_review_passed': bool(final_review_passed),
        'usage': summaries, 'calls': calls,
        'review_calls': {key: numeric(review_execution.get(key)) for key in ('used', 'limit', 'remaining')},
        'review_calls_exhausted': review_execution.get('exhausted') is True,
        'sources': snapshot['source_refs'],
        'notice': '执行记录来自保存的任务与调用台账；模拟流程不算真实 AI 调用。人工采用不等于 AI 最终复审通过。导出不表示已经发布，未证明传播、成交或涨粉效果。'}


def _complete_files(run, snapshot, execution, template='classic', options=None):
    from backend.contracts import DomainError
    # Do not forward arbitrary future acceptance/audit fields to the shareable package.
    snapshot['acceptance'] = {key: value for key, value in snapshot['acceptance'].items() if key in
        ('mode', 'draft_ref', 'content_hash', 'snapshot_id', 'review_ref', 'acknowledged_review_ref', 'acknowledged_at')}
    snapshot['source_refs'] = [_safe_source(source) for source in snapshot['source_refs']]
    files, media_status = [], {}
    pages = None
    try:
        pages = render_images(snapshot, template=template, options=options)
        files.extend(('images/' + name, data) for name, data in pages)
        media_status['images'] = {'status': 'generated', 'page_count': len(pages)}
    except DomainError as error:
        if error.code != 'MEDIA_UNAVAILABLE': raise
        media_status['images'] = {'status': 'unavailable', 'reason': str(error)}
        files.append(('images/未生成说明.txt', str(error).encode()))
    try:
        video = _video(snapshot, pages=pages, template=template)
        files.extend(('video/' + name, data) for name, data in video)
        media_status['video'] = {'status': 'generated', **snapshot['video']}
    except DomainError as error:
        if error.code not in ('MEDIA_UNAVAILABLE', 'INVALID_INPUT'): raise
        media_status['video'] = {'status': 'unavailable', 'reason': str(error)}
        files.append(('video/未生成说明.txt', str(error).encode()))
    files.extend(('storyboard/' + name, data) for name, data in _storyboard(snapshot))
    media_status['storyboard'] = {'status': 'generated', 'subtitle_timing': 'editable_suggestion_not_audio_alignment'}
    snapshot['media_status'] = media_status
    evidence = execution_evidence(run, snapshot, execution)
    files.append(('execution-evidence.json', json.dumps(evidence, ensure_ascii=False, indent=2).encode()))
    acceptance_label = '人工采用；没有有效最终 AI 复审通过' if evidence['acceptance_mode'] == 'manual_override' else ('已通过准确版本审核并人工确认' if evidence['final_ai_review_passed'] else '已人工确认；最终审核是否通过请核对执行证据')
    media_lines = '\n'.join(('图文' if key == 'images' else '视频') + '：' + ('已生成' if media_status[key]['status'] == 'generated' else '未生成，' + media_status[key]['reason']) for key in ('images', 'video'))
    instructions = f'''完整发布前成品包 · 使用说明

你确认的稿件：第 {evidence['draft_version']} 版
确认方式：{acceptance_label}
制作模式：{'真实 AI 创作记录' if snapshot['mode'] == 'live' else '模拟创作流程，不是真实 AI 创作'}

1. 先解压 ZIP，查看 images 文件夹中的封面和正文图片，检查事实与文字。
2. caption.txt 是标题、正文、互动引导与标签，可复制到平台发布框。
3. video/video.mp4 是无声图文翻页视频，每页 8 秒，不含真人口播或自动生成插画。长文需暂停阅读，或在剪辑软件中调整速度和添加自己的配音。
4. storyboard/subtitles.srt 与 storyboard.md 是可编辑剪辑素材，时长是建议值，不是根据配音对齐，也不与无声翻页视频逐页同步；录音后请手动调整字幕。
5. 如果媒体未生成，查看对应文件夹的“未生成说明.txt”，解决依赖或稿件长度问题后重试。此包不会伪造缺失文件。
6. execution-evidence.json 可核对稿件版本、人工采用方式、真实调用统计和复审次数；缺少台账字段保持未知，不补造。
7. manifest.json 记录每份文件的 SHA256，可用于核验下载后是否被改变。
8. 人工检查完成后，由你登录平台发布。再回到网页“记录已发布”，填写实际链接和发布时间。

{attribution(snapshot.get('product_photo'))}
{_source_instructions(snapshot['source_refs'], snapshot['user_material_provided'])}
来源仅列在本说明中，不自动追加到已确认正文；有来源记录不等于已核实全部事实。
品牌合作关系：由创作者按实际情况填写，系统不自动声明合作或非合作。

本次媒体状态：
{media_lines}

导出不等于社媒发布成功；没有保证增长、成交或爆款。人工采用不表示最终 AI 复审通过。包内没有用户身份、密码、API 密钥、Cookie 或原始模型请求。
'''
    files.append(('使用说明.txt', instructions.encode()))
    return files


def export_run(run, kind='images', execution=None, template='classic', options=None, expected_design_hash=None):
    style = template_config(template)
    require(kind in ('images', 'storyboard', 'video', 'complete'), 'INVALID_INPUT', '请选择图文包、分镜字幕或无声图文视频')
    snapshot = confirmed_snapshot(run)
    snapshot.update(template_id=style['id'], template_version=style['version'])
    normalized, design_hash = design_identity(snapshot, template, options)
    require(expected_design_hash is None or expected_design_hash == design_hash, 'VERSION_CONFLICT', '图卡设置已变化，请重新预览后下载')
    snapshot.update(design_options=normalized, design_hash=design_hash)
    require(sum(len(str(snapshot['content'].get(k, ''))) for k in ('selected_title', 'body', 'cta')) <= 30500,
            'INVALID_INPUT', '稿件太长，请缩短后再制作成品')
    files = _complete_files(run, snapshot, execution, template=template, options=options) if kind == 'complete' else (render_images(snapshot, template=template, options=options) if kind == 'images' else (_video(snapshot, template=template, options=options) if kind == 'video' else _storyboard(snapshot)))
    c = snapshot['content']
    caption = c['selected_title'] + '\n\n' + c['body'] + '\n\n' + c.get('cta', '') + '\n\n' + ' '.join('#' + t for t in c.get('tags', []))
    files.append(('caption.txt', caption.encode()))
    if snapshot.get('product_photo'):
        files.append(('图片来源与许可.txt', attribution(snapshot['product_photo']).encode()))
    snapshot.update(export_kind=kind, files=[{'name': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in files])
    output = BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files:
            archive.writestr(name, data)
        archive.writestr('manifest.json', json.dumps(snapshot, ensure_ascii=False, indent=2))
    return output.getvalue(), 'application/zip', f'youji-{kind}-{run.run_id[:8]}.zip'


def preview_run(run, template='classic', options=None):
    """Return the exact export PNG bytes, with no model call or content changes."""
    style = template_config(template)
    snapshot = confirmed_snapshot(run)
    pages = render_images(snapshot, template=template, options=options)
    return {'schema_version': 1, 'run_id': snapshot['run_id'],
            'snapshot_id': snapshot['snapshot_id'], 'draft_ref': snapshot['draft_ref'],
            'content_hash': snapshot['content_hash'], 'template_id': style['id'],
            'template_version': style['version'], 'page_count': len(pages),
            'width': WIDTH, 'height': HEIGHT, 'design_hash': design_identity(snapshot, template, options)[1],
            'options': snapshot['design_options'], 'product_photo': snapshot.get('product_photo'),
            'pages': [{**snapshot['page_details'][index], 'name': name, 'sha256': hashlib.sha256(data).hexdigest(),
                       'data_url': 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')}
                      for index, (name, data) in enumerate(pages)]}
