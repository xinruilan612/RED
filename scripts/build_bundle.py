"""Build the merged competition deliverables:

1. 47191919-AI+软件创新-有迹-作品方案.pdf   (技术方案 + 软件说明书 + 核心算法说明 + 测试报告)
2. 47191919-AI+软件创新-有迹-佐证材料.pdf

Bootstrap once (ReportLab and pypdf are not part of the app requirements):
    python3 -m venv .venv-pdf && .venv-pdf/bin/pip install reportlab pypdf
    .venv-pdf/bin/python app/scripts/build_bundle.py

Chinese text uses the macOS system Heiti face; ReportLab subsets the font, so the
output stays small. Sources stay in UTF-8 Markdown under docs/submission/.
"""
from pathlib import Path
import re
import sys
import types
from xml.sax.saxutils import escape

# ReportLab imports PIL unconditionally though this build only lays out text.
# Some sandboxes refuse the Pillow binary (code-signature mismatch), so provide a
# minimal stub before ReportLab loads. No image flowable is used by this script.
try:  # pragma: no cover - environment dependent
    import PIL.Image  # noqa: F401
except Exception:
    _pil = types.ModuleType('PIL')
    _img = types.ModuleType('PIL.Image')
    _img.Image = type('Image', (), {})
    _pil.Image = _img
    sys.modules['PIL'] = _pil
    sys.modules['PIL.Image'] = _img

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

APP = Path(__file__).resolve().parents[1]
SOURCE = APP / 'docs/submission'
OUTPUT = APP.parent / 'output' / '提交材料-20261027'

FONT_PATH = '/System/Library/Fonts/STHeiti Light.ttc'
FONT = 'CN'
BODY_W = A4[0] - 2 * 60

TEAM = '47191919'
TRACK = 'AI+软件创新'
WORK = '有迹'
WORK_NAME = '有迹：面向创作者的多智能体创作平台'
VERSION = '0.8.0'
DOC_DATE = '2026年10月27日'

pdfmetrics.registerFont(TTFont(FONT, FONT_PATH, subfontIndex=0))

C_DARK = colors.HexColor('#1B3A57')
C_MID = colors.HexColor('#2F6690')
C_LINE = colors.HexColor('#C9D6E2')
C_HEAD = colors.HexColor('#E8EFF5')
C_SOFT = colors.HexColor('#F5F8FA')

STYLES = {
    'cover_title': ParagraphStyle('cover_title', fontName=FONT, fontSize=34, leading=46,
                                  textColor=C_DARK, spaceAfter=6),
    'cover_sub': ParagraphStyle('cover_sub', fontName=FONT, fontSize=15, leading=24,
                                textColor=C_MID, spaceAfter=4),
    'cover_meta': ParagraphStyle('cover_meta', fontName=FONT, fontSize=10.5, leading=18,
                                 textColor=colors.HexColor('#333333')),
    'part': ParagraphStyle('part', fontName=FONT, fontSize=22, leading=32, textColor=C_DARK,
                           spaceBefore=0, spaceAfter=10),
    'part_sub': ParagraphStyle('part_sub', fontName=FONT, fontSize=10.5, leading=18,
                               textColor=colors.HexColor('#55606B')),
    'h1': ParagraphStyle('h1', fontName=FONT, fontSize=15, leading=23, textColor=C_DARK,
                         spaceBefore=12, spaceAfter=8, keepWithNext=1),
    'h2': ParagraphStyle('h2', fontName=FONT, fontSize=12, leading=19, textColor=C_MID,
                         spaceBefore=10, spaceAfter=6, keepWithNext=1),
    'body': ParagraphStyle('body', fontName=FONT, fontSize=10.2, leading=17.2,
                           spaceAfter=6.6, wordWrap='CJK', firstLineIndent=0),
    'bullet': ParagraphStyle('bullet', fontName=FONT, fontSize=10.2, leading=17.4,
                             spaceAfter=4, leftIndent=14, bulletIndent=2, wordWrap='CJK'),
    'cell': ParagraphStyle('cell', fontName=FONT, fontSize=8.8, leading=13.6, wordWrap='CJK'),
    'cell_head': ParagraphStyle('cell_head', fontName=FONT, fontSize=8.8, leading=13.6,
                                textColor=colors.HexColor('#16324A'), wordWrap='CJK'),
    'code': ParagraphStyle('code', fontName=FONT, fontSize=8.6, leading=13.2, wordWrap='CJK',
                           textColor=colors.HexColor('#1F2933'), spaceAfter=1.2),
    'note': ParagraphStyle('note', fontName=FONT, fontSize=9.2, leading=15,
                           textColor=colors.HexColor('#4A5560'), wordWrap='CJK', spaceAfter=6),
    'toc_title': ParagraphStyle('toc_title', fontName=FONT, fontSize=22, leading=32,
                                textColor=C_DARK, spaceAfter=10),
    'toc0': ParagraphStyle('toc0', fontName=FONT, fontSize=11.4, leading=22, textColor=C_DARK),
    'toc1': ParagraphStyle('toc1', fontName=FONT, fontSize=9.8, leading=17,
                           textColor=colors.HexColor('#2A3A48'), leftIndent=18),
}


class Diagram(Flowable):
    """Simple box/arrow diagram drawn with the canvas."""

    def __init__(self, kind, width=BODY_W):
        Flowable.__init__(self)
        self.kind = kind
        self.width = width
        self.height = 168 if kind == 'architecture' else 196 if kind == 'workflow' else 150

    def _box(self, c, x, y, w, h, label, fill=C_SOFT, size=9.2):
        c.setFillColor(fill)
        c.setStrokeColor(C_LINE)
        c.roundRect(x, y, w, h, 4, fill=1, stroke=1)
        c.setFillColor(colors.HexColor('#16324A'))
        c.setFont(FONT, size)
        c.drawCentredString(x + w / 2, y + h / 2 - 3, label)

    def _arrow(self, c, x1, y1, x2, y2):
        c.setStrokeColor(C_LINE)
        c.setLineWidth(0.9)
        c.line(x1, y1, x2, y2)
        c.line(x2, y2, x2 - 3, y2 + 4.5)
        c.line(x2, y2, x2 + 3, y2 + 4.5)

    def draw(self):
        c = self.canv
        if self.kind == 'architecture':
            labels = ['① 界面与执行控制台   需求输入 · 进度 · 产物 · 人工确认',
                      '② 编排层   FastAPI 接口 / 任务队列 / Worker / LangGraph 检查点',
                      '③ 角色层   audience · research · content · reviewer',
                      '④ 工具层   模型调用入口 / 原文检索 / 来源读取 / 文档导出',
                      '⑤ 数据层   账号 · 资料版本 · 证据快照 · 稿件 · 审核 · 台账']
            for i, label in enumerate(labels):
                y = 132 - i * 30
                self._box(c, 4, y, self.width - 8, 24, label)
        elif self.kind == 'workflow':
            self._box(c, 150, 166, 180, 24, '冻结输入快照 · 账号定位 · 授权资料')
            self._box(c, 6, 120, 200, 24, '受众洞察 audience')
            self._box(c, 268, 120, 200, 24, '素材研究 research')
            self._arrow(c, 200, 166, 108, 146)
            self._arrow(c, 280, 166, 366, 146)
            self._box(c, 6, 72, 462, 26, '内容创作 content   策略 › 提纲 › 开头 › 标题 › 正文')
            self._arrow(c, 106, 120, 150, 100)
            self._arrow(c, 366, 120, 324, 100)
            self._box(c, 6, 26, 200, 26, '主编审核 reviewer')
            self._box(c, 268, 26, 200, 26, '人工确认准确版本')
            self._arrow(c, 106, 72, 106, 54)
            self._arrow(c, 208, 39, 264, 39)
            c.setFont(FONT, 8)
            c.setFillColor(colors.HexColor('#5B6B78'))
            c.drawString(112, 62, '不通过 → 返修 → 复审')
            c.drawString(6, 156, '同一冻结快照下，两个研究角色并行，内容阶段顺序推进')
            c.drawString(6, 6, '返修回边：审核不通过 → 内容角色重写 → 复审；事实缺口 → 等待用户补料')
        else:  # retrieval
            self._box(c, 2, 120, 104, 24, '① 授权过滤')
            self._box(c, 124, 120, 104, 24, '② 证据角色')
            self._box(c, 246, 120, 104, 24, '③ 领域与形式')
            self._box(c, 368, 120, 104, 24, '④ 型号门控')
            for x in (106, 228, 350):
                self._arrow(c, x, 132, x + 16, 132)
            self._box(c, 130, 78, 214, 24, '⑤ 向量召回 / 组内词项降级')
            self._arrow(c, 420, 120, 350, 92)
            self._box(c, 130, 40, 214, 24, '⑥ 确定性二次重排  0.8·cos + 0.2·term')
            self._arrow(c, 237, 78, 237, 66)
            self._box(c, 60, 4, 354, 24, '⑦ 分组配额与上下文预算（方法 2 / 样例 3 / 事实 4）')
            self._arrow(c, 237, 40, 237, 30)


PART_DEFS = [
    ('part1', '第一部分  技术方案', '技术方案', '01_技术方案.md',
     '产品定位、架构、算法创新、功能、开发测试与部署、应用价值与展望'),
    ('part2', '第二部分  软件说明书', '软件说明书', '02_软件说明书.md',
     '账号准备、资料入库、四角色创作、版本确认与导出、部署与故障处理'),
    ('part3', '第三部分  核心算法说明', '核心算法说明', '03_核心算法说明.md',
     '分类证据检索、主张级引用闭环、内容风洞、协作停止控制、评测方法'),
    ('part4', '第四部分  测试报告', '测试报告', '04_测试报告.md',
     '测试环境与方法、覆盖判定、缺陷修复、历史验收、对照实验结果'),
]


def rich(text):
    text = escape(text)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)',
                  r'<link href="\2" color="#1B5E8A">\1</link>', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    return text.replace('`', '')


def col_widths(n):
    if n <= 2:
        return [150, BODY_W - 150]
    if n == 3:
        return [112, 176, BODY_W - 288]
    if n == 4:
        return [BODY_W / 4] * 4
    if n == 5:
        return [BODY_W * 0.2] * 5
    if n == 6:
        return [BODY_W / 6] * 6
    return [BODY_W / n] * n


def markdown_flowables(text, part_key=None):
    lines = text.splitlines()
    out, i = [], 0
    dropped_title = False
    chars_since_break = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue
        if line == '<!-- page -->':
            i += 1
            continue
        elif re.fullmatch(r'-{3,}', line):
            out.append(Spacer(1, 8))
        elif line in ('[[architecture]]', '[[workflow]]', '[[retrieval]]'):
            out.append(Spacer(1, 4))
            out.append(Diagram(line[2:-2]))
            out.append(Spacer(1, 10))
        elif line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r'[-: ]+', c) for c in cells):
                    rows.append(cells)
                i += 1
            if not rows:
                continue
            ncol = max(len(r) for r in rows)
            data = []
            for r_i, r in enumerate(rows):
                style = STYLES['cell_head'] if r_i == 0 else STYLES['cell']
                r = r + [''] * (ncol - len(r))
                data.append([Paragraph(rich(c), style) for c in r])
            table = Table(data, colWidths=col_widths(ncol), repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), C_HEAD),
                ('GRID', (0, 0), (-1, -1), 0.4, C_LINE),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6.5),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6.5),
                ('TOPPADDING', (0, 0), (-1, -1), 5.5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5.5),
            ]))
            if len(data) <= 10:
                out.append(KeepTogether([Spacer(1, 3), table]))
            else:
                out.append(Spacer(1, 3))
                out.append(table)
            out.append(Spacer(1, 11))
            chars_since_break += sum(len(str(c)) for r in rows for c in r)
            continue
        elif line.startswith('```'):
            i += 1
            block = []
            while i < len(lines) and not lines[i].strip().startswith('```'):
                block.append(escape(lines[i]).replace(' ', '&#160;') or '&#160;')
                i += 1
            i += 1
            inner = Table([[Paragraph(b, STYLES['code'])] for b in block],
                          colWidths=[BODY_W - 14], hAlign='LEFT')
            inner.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F2F5F8')),
                ('BOX', (0, 0), (-1, -1), 0.4, colors.HexColor('#DCE4EC')),
                ('LEFTPADDING', (0, 0), (-1, -1), 9),
                ('RIGHTPADDING', (0, 0), (-1, -1), 9),
                ('TOPPADDING', (0, 0), (-1, -1), 1.2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1.2),
            ]))
            out.extend([Spacer(1, 3), inner, Spacer(1, 9)])
            continue
        else:
            if line.startswith('- '):
                out.append(Paragraph(rich(line[2:]), STYLES['bullet'], bulletText='·'))
            elif re.match(r'^\d+\. ', line):
                num, rest = line.split('. ', 1)
                out.append(Paragraph(rich(rest), STYLES['bullet'], bulletText=num + '.'))
            elif line.startswith('### '):
                out.append(Paragraph(rich(line[4:]), STYLES['h2']))
            elif line.startswith('## '):
                out.append(Paragraph(rich(line[3:]), STYLES['h1']))
            elif line.startswith('# '):
                if dropped_title:
                    out.append(Paragraph(rich(line[2:]), STYLES['part_sub']))
                dropped_title = True
            else:
                out.append(Paragraph(rich(line), STYLES['body']))
                chars_since_break += len(line)
        i += 1
    return out


def cover(purpose, subtitle, meta_rows, note_lines):
    flow = [Spacer(1, 54)]
    flow.append(Paragraph('AIC 2026 算法创新赛 · ' + PURPOSE_TRACK, STYLES['cover_sub']))
    flow.append(Spacer(1, 8))
    flow.append(Paragraph(WORK, STYLES['cover_title']))
    flow.append(Paragraph(subtitle, STYLES['cover_sub']))
    flow.append(Spacer(1, 16))
    flow.append(PurposeRule())
    flow.append(Spacer(1, 14))
    flow.append(Paragraph(purpose, ParagraphStyle(
        'purpose', fontName=FONT, fontSize=20, leading=30, textColor=C_DARK)))
    flow.append(Spacer(1, 34))
    data = [[Paragraph(k, STYLES['cover_meta']), Paragraph(v, STYLES['cover_meta'])]
            for k, v in meta_rows]
    table = Table(data, colWidths=[96, 260], hAlign='LEFT')
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
    ]))
    flow.append(table)
    flow.append(Spacer(1, 40))
    for line in note_lines:
        flow.append(Paragraph(line, STYLES['note']))
    flow.append(PageBreak())
    return flow


class PurposeRule(Flowable):
    def __init__(self):
        Flowable.__init__(self)
        self.width = BODY_W
        self.height = 4

    def draw(self):
        self.canv.setStrokeColor(C_MID)
        self.canv.setLineWidth(2)
        self.canv.line(0, 2, 150, 2)


PURPOSE_TRACK = TRACK


def toc_page(title):
    flow = [Paragraph(title, STYLES['toc_title']), Spacer(1, 6)]
    toc = TableOfContents()
    toc.levelStyles = [STYLES['toc0'], STYLES['toc1']]
    toc.dotsMinLevel = 0
    flow.append(toc)
    return flow, toc


class BundleDoc(BaseDocTemplate):
    def __init__(self, filename, title, total_getter, **kw):
        BaseDocTemplate.__init__(self, filename, pagesize=A4, leftMargin=60, rightMargin=60,
                                 topMargin=52, bottomMargin=56, title=title,
                                 author='有迹项目团队', subject=TRACK,
                                 creator='有迹文档构建脚本', **kw)
        frame = Frame(self.leftMargin, self.bottomMargin, BODY_W,
                      A4[1] - self.topMargin - self.bottomMargin, id='body')
        self.addPageTemplates([PageTemplate(id='main', frames=[frame],
                                            onPage=self._decorate)])
        self.running_title = title
        self.total_getter = total_getter

    def _decorate(self, canvas, doc):
        canvas.saveState()
        if doc.page > 1:
            canvas.setStrokeColor(C_LINE)
            canvas.setLineWidth(0.5)
            canvas.line(60, A4[1] - 44, A4[0] - 60, A4[1] - 44)
            canvas.setFont(FONT, 8)
            canvas.setFillColor(colors.HexColor('#6B7A88'))
            canvas.drawString(60, A4[1] - 39, f'{TEAM}-{TRACK}-{WORK_NAME}  |  {self.running_title}')
            canvas.line(60, 46, A4[0] - 60, 46)
            total = self.total_getter()
            label = f'第 {doc.page} 页' + (f' / 共 {total} 页' if total else '')
            canvas.drawRightString(A4[0] - 60, 32, label)
            canvas.drawString(60, 32, f'软件版本 {VERSION}')
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if not isinstance(flowable, Paragraph):
            return
        name = flowable.style.name
        if name == 'part':
            txt = flowable.getPlainText()
            if txt.startswith('第'):
                self.notify('TOCEntry', (0, txt, self.page))
        elif name == 'h1':
            self.notify('TOCEntry', (1, flowable.getPlainText(), self.page))


def build(purpose, subtitle, title, meta_rows, note_lines, story_factory, out_path, toc_title):
    holder = {'total': 0}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        story, toc = story_factory()
        doc = BundleDoc(str(out_path), title, lambda: holder['total'])
        doc.multiBuild(story)
        pages = doc.page
        if pages == holder['total']:
            break
        holder['total'] = pages
    return out_path


def scheme_story():
    def factory():
        flow = []
        flow += cover(
            '作品方案', '面向创作者的多智能体创作平台',
            [('作品名称', WORK_NAME), ('参赛赛题', '算法创新赛 · ' + TRACK),
             ('团队编号', TEAM), ('软件版本', VERSION),
             ('产品基线', '2026-10-13（源码提交 79f53e8）'), ('文档日期', DOC_DATE)],
            ['本方案由技术方案、软件说明书、核心算法说明与测试报告四部分组成，',
             '覆盖产品定位、架构与算法创新、功能实现、开发测试部署与应用价值。',
             '全文不包含机构信息与个人信息；数据与结论均可按附录索引复核。'])
        toc_flow, toc = toc_page('目 录')
        flow += toc_flow
        for key, part_title, short, fname, part_sub in PART_DEFS:
            flow.append(PageBreak())
            flow.append(Spacer(1, 120))
            flow.append(Paragraph(part_title, STYLES['part']))
            flow.append(Paragraph(part_sub, STYLES['part_sub']))
            flow.append(Spacer(1, 10))
            flow.append(PurposeRule())
            flow.append(PageBreak())
            flow += markdown_flowables((SOURCE / fname).read_text(), key)
        return flow, toc
    return factory


def evidence_story():
    def factory():
        flow = []
        flow += cover(
            '佐证材料', '作品真实性与技术效果的原始记录',
            [('作品名称', WORK_NAME), ('参赛赛题', '算法创新赛 · ' + TRACK),
             ('团队编号', TEAM), ('软件版本', VERSION),
             ('证据范围', '测试 1189+256 项 / 真实验证 18 次运行 / 风洞实验'),
             ('文档日期', DOC_DATE)],
            ['本文件按「证明什么 → 数据 → 原始文件 → 复现方式」组织，',
             '只列可指向原始记录的事实；不能由所附数据支持的推断不写入。',
             '全文不包含机构信息与个人信息。'])
        toc_flow, toc = toc_page('目 录')
        flow += toc_flow
        flow.append(PageBreak())
        flow += markdown_flowables((SOURCE / '06_佐证材料.md').read_text(), 'evidence')
        return flow, toc
    return factory


if __name__ == '__main__':
    a = build('作品方案', '', '有迹作品方案',
              None, None, scheme_story(),
              OUTPUT / f'{TEAM}-{TRACK}-{WORK_NAME}-作品方案.pdf', '目 录')
    b = build('佐证材料', '', '有迹佐证材料',
              None, None, evidence_story(),
              OUTPUT / f'{TEAM}-{TRACK}-{WORK_NAME}-佐证材料.pdf', '目 录')
    for path in (a, b):
        print(path, path.stat().st_size, 'bytes')
