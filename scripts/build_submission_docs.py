"""Build the reviewed competition PDFs from UTF-8 Markdown sources.

Run with the bundled artifact Python (reportlab), not the application venv.
The source pages deliberately use explicit page breaks for predictable layout.
"""
from pathlib import Path
import re
from xml.sax.saxutils import escape

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable
from reportlab.lib.pagesizes import A4

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/submission'
OUTPUT = ROOT / 'output/pdf'


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


def build():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    pdfmetrics.registerFont(TTFont('CN', '/System/Library/Fonts/STHeiti Light.ttc', subfontIndex=0))
    styles = {
        'body': ParagraphStyle('body', fontName='CN', fontSize=10.5, leading=17, spaceAfter=8, wordWrap='CJK'),
        'h1': ParagraphStyle('h1', fontName='CN', fontSize=20, leading=28, spaceAfter=18),
        'h2': ParagraphStyle('h2', fontName='CN', fontSize=15, leading=22, spaceAfter=12),
        'h3': ParagraphStyle('h3', fontName='CN', fontSize=12, leading=19, spaceBefore=9, spaceAfter=6),
        'cell': ParagraphStyle('cell', fontName='CN', fontSize=9, leading=14, wordWrap='CJK'),
        'code': ParagraphStyle('code', fontName='CN', fontSize=8.5, leading=13, wordWrap='CJK', spaceAfter=5),
    }

    def rich(text):
        text = escape(text)
        text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<link href="\2" color="#234E70">\1</link>', text)
        return text.replace('`', '')

    for path in sorted(SOURCE.glob('[0-9][0-9]_*.md')):
        title = path.read_text().splitlines()[0].lstrip('# ')
        filename = '47191919-AI+软件创新-有迹-' + path.stem.split('_', 1)[1] + '.pdf'
        story = []
        lines = path.read_text().splitlines()
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
