"""Local-only document preview and conservative, auditable text cleanup."""
import base64
import hashlib
import json
import re
from backend.contracts import require

MAX_TEXT = 100_000
INPUT_FIELDS = {'account_id', 'title', 'text', 'filename', 'file_base64',
                'document_id', 'expected_version', 'classification'}


def normalize_text(text):
    # Preserve punctuation, Markdown, decimal values, units, tabs and links.
    # Do not use NFKC or strip emoji joiners / mathematical symbols.
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\u2028', '\n').replace('\u2029', '\n')
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text).lstrip('\ufeff')


def pages_hash(pages):
    return hashlib.sha256(json.dumps(pages, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def read_input(data):
    from backend.knowledge import parse_file
    name = data.get('filename', data.get('title', '资料') + '.txt')
    require(not ('file_base64' in data and 'text' in data), 'INVALID_INPUT', '请只选择文件或粘贴文本一种来源')
    if 'file_base64' in data:
        encoded = data['file_base64']
        require(isinstance(encoded, str) and len(encoded) <= 4_000_000, 'INVALID_INPUT', '文件超过 3 MB')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ValueError('文件编码无效') from None
        pages = parse_file(name, raw)
    else:
        text = data.get('text')
        require(isinstance(text, str) and len(text) <= MAX_TEXT and text.strip(),
                'INVALID_INPUT', '资料正文不能为空且不能超过 100000 字')
        raw = text.encode('utf-8')
        pages = [(1, text)]
    return name, raw, pages


def preview(data):
    name, raw, original = read_input(data)
    cleaned = [(page, normalize_text(text)) for page, text in original]
    require(any(text.strip() for _, text in cleaned), 'INVALID_INPUT', '清理后没有可用正文，请换文件或粘贴文字')
    warnings = ['仅清理换行和不可见控制字符；请核对数值、单位、链接与表格。']
    if name.lower().endswith('.pdf'):
        warnings.append('PDF 复杂表格和多栏可能顺序错乱；不支持扫描件 OCR，请逐页校对。')
    if name.lower().endswith('.docx'):
        warnings.append('Word 表格以行和制表符保留，合并单元格、浮动对象请对照原文件检查。')
    return {'source_sha256': hashlib.sha256(raw).hexdigest(), 'filename': name,
            'pages': [{'page': page, 'text': text, 'original_text': dict(original)[page]}
                      for page, text in cleaned], 'warnings': warnings,
            'normalized': any(text != normalize_text(text) for _, text in original), 'stored': False}


def reviewed_pages(data, raw, original):
    review = data['input_review']
    require(isinstance(review, dict) and set(review) == {'confirmed', 'source_sha256', 'pages', 'confirmation_id'}
            and review['confirmed'] is True, 'INVALID_INPUT', '请先预览并明确确认校对后的资料')
    require(review['source_sha256'] == hashlib.sha256(raw).hexdigest(),
            'VERSION_CONFLICT', '原始输入已变化，请重新解析预览')
    token = review['confirmation_id']
    require(isinstance(token, str) and re.fullmatch(r'[a-f0-9-]{36}', token), 'INVALID_INPUT', '确认编号无效，请重新预览')
    pages = review['pages']
    require(isinstance(pages, list) and len(pages) == len(original), 'INVALID_INPUT', '校对页数不一致，请重新预览')
    result = []
    for item, (page, _) in zip(pages, original):
        require(isinstance(item, dict) and set(item) == {'page', 'text'} and type(item['page']) is int
                and item['page'] == page and isinstance(item['text'], str) and len(item['text']) <= MAX_TEXT,
                'INVALID_INPUT', '校对页码或文字无效')
        result.append((page, normalize_text(item['text'])))
    require(sum(len(text) for _, text in result) <= MAX_TEXT and any(text.strip() for _, text in result),
            'INVALID_INPUT', '校对正文不能为空且不能超过 100000 字')
    fingerprint = pages_hash(result)
    request_hash = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    return result, {'confirmed': True, 'confirmation_id': token, 'request_sha256': request_hash,
                    'source_sha256': review['source_sha256'], 'extracted_sha256': pages_hash(original),
                    'reviewed_sha256': fingerprint, 'normalization': 'conservative-text-v1'}
