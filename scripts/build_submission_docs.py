"""Build the reviewed competition PDFs from UTF-8 Markdown sources.

Run with the bundled artifact Python (reportlab), not the application venv.
The source pages deliberately use explicit page breaks for predictable layout.
Optionally set SUBMISSION_CJK_FONT to an installed Chinese TrueType font path.
The first face of a TrueType collection is used; fonts are never downloaded.
"""
from pathlib import Path
import os
import re
from xml.sax.saxutils import escape

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFError
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable
from reportlab.lib.pagesizes import A4

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/submission'
OUTPUT = ROOT / 'output/pdf'
FIXED_RENDER_TEXT = (
    '用户界面与执行控制台 编排层 API / 队列 / Worker / LangGraph '
    '角色层 audience / research / content / reviewer '
    '工具层 模型调用 / 原文检索 / 来源读取 / 导出 '
    '数据层 账号 / 证据快照 / 稿件 / 审核 / 运营记录 '
    '输入需求与证据快照 受众洞察 audience 素材研究 research '
    '内容创作 策略 > 提纲 > 开头 > 标题 > 正文 '
    '主编审核 不通过则返修 通过后人工确认准确版本 有迹 | 0123456789'
)


def cjk_font_candidates():
    windows_fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    return (
        Path('/System/Library/Fonts/STHeiti Light.ttc'),
        windows_fonts / 'msyh.ttc', windows_fonts / 'simsun.ttc',
        windows_fonts / 'simhei.ttf',
        Path('/System/Library/Fonts/PingFang.ttc'),
        Path('/Library/Fonts/Arial Unicode.ttf'),
        Path('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc'),
        Path('/usr/share/fonts/truetype/wqy/wqy-microhei.ttc'),
        Path('/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf'),
        Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
    )


def register_cjk_font(font_path=None, required_text=''):
    configured = font_path if font_path is not None else (os.environ.get('SUBMISSION_CJK_FONT') or None)
    explicit = configured is not None
    candidates = (Path(configured).expanduser(),) if explicit else cjk_font_candidates()
    required = {ord(char) for char in ('中文有迹软件创新' + FIXED_RENDER_TEXT + required_text) if not char.isspace()}
    for path in candidates:
        if not path.is_file():
            continue
        try:
            font = TTFont('CN', str(path), subfontIndex=0)
        except (OSError, ValueError, TTFError):
            continue
        if any(not font.face.charToGlyph.get(codepoint) for codepoint in required):
            continue
        pdfmetrics.registerFont(font)
        return path
    reason = 'Configured font is missing, unsupported or lacks required glyphs.' if explicit else 'No suitable installed Chinese TrueType font was found.'
    raise ValueError(reason + ' Set SUBMISSION_CJK_FONT to a readable .ttf or TrueType .ttc file containing the source characters. No fonts were downloaded.')


class SystemDiagram(Flowable):
    def __init__(self, kind):
        Flowable.__init__(self)
        self.kind = kind
        self.width = 475
        self.height = 155 if kind == 'architecture' else 185

    def draw(self):
        c = self.canv
        c.setFont('CN', 9)
        def box(x, y, w, h, label):
            c.setFillColor(colors.HexColor('#F3F6F8'))
            c.setStrokeColor(colors.HexColor('#738596'))
            c.roundRect(x, y, w, h, 3, fill=1)
            c.setFillColor(colors.black)
            c.drawCentredString(x+w/2, y+h/2-3, label)
        def arrow(x1, y1, x2, y2):
            c.setStrokeColor(colors.HexColor('#738596'))
            c.line(x1, y1, x2, y2)
            c.line(x2, y2, x2-3, y2+5)
            c.line(x2, y2, x2+3, y2+5)
        if self.kind == 'architecture':
            labels = ['用户界面与执行控制台', '编排层  API / 队列 / Worker / LangGraph',
                      '角色层  audience / research / content / reviewer',
                      '工具层  模型调用 / 原文检索 / 来源读取 / 导出',
                      '数据层  账号 / 证据快照 / 稿件 / 审核 / 运营记录']
            for i, label in enumerate(labels):
                y = 126-i*29
                box(5,y,465,23,label)
                if i < 4: arrow(237,y,237,y-6)
        else:
            box(135,155,205,24,'输入需求与证据快照')
            box(25,112,190,24,'受众洞察 audience')
            box(260,112,190,24,'素材研究 research')
            arrow(180,155,120,136)
            arrow(295,155,355,136)
            box(25,66,425,27,'内容创作  策略 > 提纲 > 开头 > 标题 > 正文')
            arrow(120,112,170,93)
            arrow(355,112,305,93)
            box(25,19,190,27,'主编审核  不通过则返修')
            box(260,19,190,27,'通过后人工确认准确版本')
            arrow(120,66,120,46)
            c.line(215,32,260,32)
            c.line(255,35,260,32)
            c.line(255,29,260,32)


def build(font_path=None):
    sources = [(path, path.read_text(encoding='utf-8'))
               for path in sorted(SOURCE.glob('[0-9][0-9]_*.md'))]
    register_cjk_font(font_path, ''.join(text for _, text in sources))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    styles = {
        'body': ParagraphStyle('body', fontName='CN', fontSize=10.5, leading=17, spaceAfter=8, wordWrap='CJK'),
        'h1': ParagraphStyle('h1', fontName='CN', fontSize=20, leading=28, spaceAfter=18, keepWithNext=True),
        'h2': ParagraphStyle('h2', fontName='CN', fontSize=15, leading=22, spaceAfter=12, keepWithNext=True),
        'h3': ParagraphStyle('h3', fontName='CN', fontSize=12, leading=19, spaceBefore=9, spaceAfter=6, keepWithNext=True),
        'cell': ParagraphStyle('cell', fontName='CN', fontSize=9, leading=14, wordWrap='CJK'),
        'code': ParagraphStyle('code', fontName='CN', fontSize=8.5, leading=13, wordWrap='CJK', spaceAfter=5),
    }

    def rich(text):
        text = escape(text)
        text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<link href="\2" color="#234E70">\1</link>', text)
        return text.replace('`', '')

    for path, source in sources:
        title = source.splitlines()[0].lstrip('# ')
        filename = '47191919-AI+软件创新-有迹-' + path.stem.split('_', 1)[1] + '.pdf'
        story = []
        lines = source.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            if line == '<!-- page -->':
                story.append(PageBreak())
            elif line in ('[[architecture]]', '[[workflow]]'):
                story.extend([SystemDiagram(line[2:-2]), Spacer(1, 12)])
            elif line.startswith('|'):
                rows = []
                while i < len(lines) and lines[i].strip().startswith('|'):
                    values = [v.strip() for v in lines[i].strip().strip('|').split('|')]
                    if not all(re.fullmatch(r'[-: ]+', v) for v in values):
                        rows.append([Paragraph(rich(v), styles['cell']) for v in values])
                    i += 1
                cols = len(rows[0])
                widths = [115, 360] if cols == 2 else [110, 175, 190] if cols == 3 else [475 / cols] * cols
                table = Table(rows, colWidths=widths, repeatRows=1, hAlign='LEFT')
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E7EDF2')),
                    ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#D9D9D9')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                    ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
                ]))
                story.extend([table, Spacer(1, 12)])
                continue
            elif line.startswith('```'):
                i += 1
                while i < len(lines) and not lines[i].startswith('```'):
                    story.append(Paragraph(escape(lines[i]).replace(' ', '&#160;') or ' ', styles['code']))
                    i += 1
            else:
                kind = 'h3' if line.startswith('### ') else 'h2' if line.startswith('## ') else 'h1' if line.startswith('# ') else 'body'
                story.append(Paragraph(rich(re.sub(r'^#{1,3} ', '', line)), styles[kind]))
            i += 1

        def footer(canvas, doc):
            canvas.saveState()
            canvas.setFont('CN', 8)
            canvas.setFillColor(colors.HexColor('#555555'))
            canvas.drawString(60, 29, '有迹  |  ' + title)
            canvas.drawRightString(A4[0] - 60, 29, str(doc.page))
            canvas.restoreState()

        doc = SimpleDocTemplate(str(OUTPUT / filename), pagesize=A4, leftMargin=60, rightMargin=60,
            topMargin=48, bottomMargin=50, title=title, author='有迹项目团队', subject='AI+软件创新', pageCompression=1)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
        print(filename)


if __name__ == '__main__':
    build()
