"""Editable Word export using only the standard library, including portable Windows."""
from io import BytesIO
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZIP_DEFLATED, ZipFile

MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
XML = 'http://www.w3.org/XML/1998/namespace'

def tag(name):return '{'+W+'}'+name

def render(markdown):
    doc=Element(tag('document'));body=SubElement(doc,tag('body'))
    markdown=''.join(c for c in markdown if c in '\t\n\r' or 0x20<=ord(c)<=0xD7FF or 0xE000<=ord(c)<=0xFFFD or 0x10000<=ord(c)<=0x10FFFF)
    lines=markdown.splitlines()
    # Existing export starts with the confirmation label and the actual title.
    label=lines[0][2:] if lines and lines[0].startswith(('# AI 创作稿','# 模拟创作稿')) else ''
    if label:lines=lines[1:]
    title_seen=False
    for line in lines:
        if not line.strip():continue
        heading=line.startswith('# ')
        text=line[2:] if heading else line
        p=SubElement(body,tag('p'));props=SubElement(p,tag('pPr'))
        SubElement(props,tag('pStyle'),{tag('val'):'Title' if heading and not title_seen else 'Normal'})
        r=SubElement(p,tag('r'));t=SubElement(r,tag('t'),{'{'+XML+'}space':'preserve'})
        # Word XML cannot contain control characters, but retain text and emoji.
        t.text=''.join(c for c in text if c in '\t\n\r' or 0x20<=ord(c)<=0xD7FF or 0xE000<=ord(c)<=0xFFFD or 0x10000<=ord(c)<=0x10FFFF)
        if heading and not title_seen:
            title_seen=True
            if label:
                note=SubElement(body,tag('p'));pr=SubElement(note,tag('pPr'))
                SubElement(pr,tag('pStyle'),{tag('val'):'Status'})
                SubElement(SubElement(note,tag('r')),tag('t')).text=label
    section=SubElement(body,tag('sectPr'))
    SubElement(section,tag('pgSz'),{tag('w'):'11906',tag('h'):'16838'})
    SubElement(section,tag('pgMar'),{tag('top'):'1134',tag('bottom'):'1134',tag('left'):'1134',tag('right'):'1134'})
    styles=Element(tag('styles'))
    for name,size,color in [('Normal','24','000000'),('Title','36','000000'),('Status','18','666666')]:
        style=SubElement(styles,tag('style'),{tag('type'):'paragraph',tag('styleId'):name})
        SubElement(style,tag('name'),{tag('val'):name})
        pr=SubElement(style,tag('pPr'));SubElement(pr,tag('spacing'),{tag('after'):'120',tag('line'):'440' if name=='Title' else '320',tag('lineRule'):'exact'})
        if name=='Title':SubElement(pr,tag('keepNext'))
        rp=SubElement(style,tag('rPr'));SubElement(rp,tag('rFonts'),{tag('ascii'):'Arial',tag('hAnsi'):'Arial',tag('eastAsia'):'Microsoft YaHei'})
        SubElement(rp,tag('sz'),{tag('val'):size});SubElement(rp,tag('color'),{tag('val'):color})
        if name=='Title':SubElement(rp,tag('b'))
    parts={
        '[Content_Types].xml':'''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>''',
        '_rels/.rels':'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>''',
        'word/_rels/document.xml.rels':'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''',
        'word/document.xml':tostring(doc,encoding='utf-8',xml_declaration=True),
        'word/styles.xml':tostring(styles,encoding='utf-8',xml_declaration=True),
    }
    output=BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as package:
        for path,content in parts.items():package.writestr(path,content)
    return output.getvalue()
