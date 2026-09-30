"""Bounded, isolated text extraction for ordinary Word DOCX documents."""
import json
import sys
import zipfile
from io import BytesIO
from xml.etree import ElementTree


def extract(raw):
    if len(raw) > 3_000_000:
        raise ValueError('文件超过 3 MB')
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > 1200 or sum(item.file_size for item in members) > 20_000_000:
            raise ValueError('文档结构超过解析限制')
        names = {item.filename for item in members}
        if '[Content_Types].xml' not in names or 'word/document.xml' not in names:
            raise ValueError('这不是有效的 DOCX 文档')
        if any(name.startswith('word/vbaProject') for name in names):
            raise ValueError('含宏的文档暂不支持')
        info = archive.getinfo('word/document.xml')
        if info.file_size > 10_000_000 or info.file_size > max(info.compress_size, 1) * 1000:
            raise ValueError('文档正文压缩比例或大小超过限制')
        root = ElementTree.fromstring(archive.read(info))

    ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    paragraphs = []
    for paragraph in root.iter(ns + 'p'):
        pieces = []
        for node in paragraph.iter():
            if node.tag == ns + 't' and node.text:
                pieces.append(node.text)
            elif node.tag == ns + 'tab':
                pieces.append('\t')
            elif node.tag in (ns + 'br', ns + 'cr'):
                pieces.append('\n')
        text = ''.join(pieces).strip()
        if text:
            paragraphs.append([len(paragraphs) + 1, text])
            if len(paragraphs) > 10000 or sum(len(item[1]) for item in paragraphs) > 100_000:
                raise ValueError('正文超过 10 万字符或段落数限制')
    if not paragraphs:
        raise ValueError('没有可提取的正文文字')
    return paragraphs


def main():
    try:
        result = {'paragraphs': extract(sys.stdin.buffer.read(3_000_001))}
    except Exception:
        result = {'error': '无法读取 DOCX；请确认是未加密的 .docx 文档且包含正文文字'}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
