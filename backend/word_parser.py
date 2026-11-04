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
        relationships = {}
        if 'word/_rels/document.xml.rels' in names:
            for item in ElementTree.fromstring(archive.read('word/_rels/document.xml.rels')):
                target = item.get('Target', '')
                if item.get('Type', '').endswith('/hyperlink') and target.startswith(('https://', 'http://', 'mailto:')):
                    relationships[item.get('Id')] = target

    ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    rel_ns = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

    def inline(node):
        if node.tag == ns + 't':
            return node.text or ''
        if node.tag == ns + 'tab':
            return '\t'
        if node.tag in (ns + 'br', ns + 'cr'):
            return '\n'
        text = ''.join(inline(child) for child in node)
        if node.tag == ns + 'hyperlink':
            target = relationships.get(node.get(rel_ns + 'id'))
            if target and target not in text:
                return text + ' (' + target + ')'
        return text

    def blocks(node):
        for child in node:
            if child.tag == ns + 'p':
                yield inline(child)
            elif child.tag == ns + 'tbl':
                # One chunkable block per row keeps headers, order and units.
                for row in child.findall(ns + 'tr'):
                    cells = [' / '.join(blocks(cell)) for cell in row.findall(ns + 'tc')]
                    yield '\t'.join(cells)
            elif child.tag not in (ns + 'sectPr', ns + 'tcPr'):
                yield from blocks(child)

    paragraphs = []
    total = 0
    for text in blocks(root):
        # TABs delimit table cells, including empty first/last cells. Do not
        # collapse their positions while removing paragraph edge whitespace.
        text = text.strip(' \r\n')
        if text.strip():
            paragraphs.append([len(paragraphs) + 1, text])
            total += len(text)
            if len(paragraphs) > 10000 or total > 100_000:
                raise ValueError('正文超过 10 万字符或段落数限制')
    if not paragraphs:
        raise ValueError('没有可提取的正文文字')
    return paragraphs


def main():
    try:
        result = {'paragraphs': extract(sys.stdin.buffer.read(3_000_001))}
    except Exception:
        result = {'error': '无法读取 DOCX；请确认是未加密的 .docx 文档且包含正文文字'}
    # Parent decodes JSON bytes as UTF-8, independently of Windows' code page.
    sys.stdout.write(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
