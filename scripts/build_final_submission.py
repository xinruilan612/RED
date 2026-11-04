#!/usr/bin/env python3
"""Build the formal editable report from its Markdown source.

Run with the Codex bundled Python runtime. PDF/PNG conversion is deliberately
separate so the approved bundled LibreOffice renderer can be used for QA.
"""
import argparse
from pathlib import Path
import re
import os
import shutil
import subprocess
import sys

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.opc.constants import RELATIONSHIP_TYPE as RT

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent


def font(run, size=11, bold=False, face='Arial Unicode MS'):
    run.font.name = face
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(0, 0, 0)
    prop=run._element.get_or_add_rPr()
    fonts=prop.find(qn('w:rFonts'))
    if fonts is None:
        fonts=OxmlElement('w:rFonts');prop.insert(0,fonts)
    for key in ('ascii','hAnsi','eastAsia','cs'):
        fonts.set(qn('w:'+key),face)


def inline(paragraph, text, size=11):
    pattern=re.compile(r'(\[[^\]]+\]\([^)]+\)|\*\*.+?\*\*|`[^`]+`)')
    for chunk in pattern.split(text):
        if not chunk:continue
        link=re.fullmatch(r'\[([^\]]+)\]\(([^)]+)\)',chunk)
        if link:
            hyperlink=OxmlElement('w:hyperlink')
            hyperlink.set(qn('r:id'),paragraph.part.relate_to(link[2],RT.HYPERLINK,is_external=True))
            run=OxmlElement('w:r');rpr=OxmlElement('w:rPr')
            fonts=OxmlElement('w:rFonts')
            for key in ('ascii','hAnsi','eastAsia'):fonts.set(qn('w:'+key),'Arial Unicode MS')
            rpr.append(fonts)
            color=OxmlElement('w:color');color.set(qn('w:val'),'000000');rpr.append(color)
            under=OxmlElement('w:u');under.set(qn('w:val'),'single');rpr.append(under)
            sz=OxmlElement('w:sz');sz.set(qn('w:val'),str(int(size*2)));rpr.append(sz)
            run.append(rpr);node=OxmlElement('w:t');node.text=link[1];run.append(node)
            hyperlink.append(run);paragraph._p.append(hyperlink)
        else:
            bold=chunk.startswith('**') and chunk.endswith('**')
            if bold:chunk=chunk[2:-2]
            code=chunk.startswith('`') and chunk.endswith('`')
            if code:chunk=chunk[1:-1]
            font(paragraph.add_run(chunk),size=size,bold=bold,face='Arial Unicode MS' if not code else 'Menlo')


def table(document, rows):
    content=[row for row in rows if not re.fullmatch(r'\s*\|?[\s|:\-]+\|?\s*',row)]
    values=[[cell.strip() for cell in row.strip().strip('|').split('|')] for row in content]
    table=document.add_table(rows=len(values),cols=len(values[0]))
    table.alignment=WD_TABLE_ALIGNMENT.CENTER
    table.autofit=False
    if len(values[0])==3:
        widths=[3.7,5.6,7.0]
    else:
        widths=[3.7]+[(16.3-3.7)/(len(values[0])-1)]*(len(values[0])-1)
    for column,width in zip(table.columns,widths):column.width=Cm(width)
    props=table._tbl.tblPr
    borders=OxmlElement('w:tblBorders')
    for name in ('top','left','bottom','right','insideH','insideV'):
        node=OxmlElement('w:'+name);node.set(qn('w:val'),'single');node.set(qn('w:sz'),'4');node.set(qn('w:color'),'D9D9D9');borders.append(node)
    props.append(borders)
    for i,row in enumerate(table.rows):
        # Each row remains intact, while a long table may continue with header.
        cant=OxmlElement('w:cantSplit');row._tr.get_or_add_trPr().append(cant)
        if i==0:
            repeat=OxmlElement('w:tblHeader');row._tr.get_or_add_trPr().append(repeat)
        for j,cell in enumerate(row.cells):
            cell.width=Cm(widths[j]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tcpr=cell._tc.get_or_add_tcPr();margin=OxmlElement('w:tcMar')
            for side,amount in [('top',75),('left',95),('bottom',75),('right',95)]:
                node=OxmlElement('w:'+side);node.set(qn('w:w'),str(amount));node.set(qn('w:type'),'dxa');margin.append(node)
            tcpr.append(margin)
            if i==0:
                shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'DDEBF7');tcpr.append(shade)
            p=cell.paragraphs[0];p.paragraph_format.first_line_indent=Pt(0)
            p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=Pt(14)
            if len(values[i][j])<20:p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            inline(p,values[i][j],size=10)
            if i==0:
                for run in p.runs:run.bold=True
    spacer=document.add_paragraph();spacer.paragraph_format.space_after=Pt(2)
    spacer.paragraph_format.line_spacing=0.5
    font(spacer.add_run(''),size=4)


def build(source, output):
    document=Document()
    section=document.sections[0]
    section.page_width=Cm(21);section.page_height=Cm(29.7)
    section.top_margin=Cm(1.8);section.bottom_margin=Cm(1.7)
    section.left_margin=Cm(2.2);section.right_margin=Cm(2.2)
    section.footer_distance=Cm(0.7)
    styles=document.styles
    for name in ('Normal','Title','Subtitle','Heading 1','Heading 2','Heading 3'):
        style=styles[name];style.font.name='Arial Unicode MS';style.font.color.rgb=RGBColor(0,0,0)
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'),'Arial Unicode MS')
    normal=styles['Normal'];normal.font.size=Pt(11)
    normal.paragraph_format.line_spacing=Pt(15.5)
    normal.paragraph_format.space_after=Pt(4)
    normal.paragraph_format.first_line_indent=Pt(22)
    for name,size in [('Heading 1',15),('Heading 2',12)]:
        styles[name].font.size=Pt(size);styles[name].font.bold=True
        styles[name].paragraph_format.first_line_indent=Pt(0)
        styles[name].paragraph_format.space_before=Pt(9)
        styles[name].paragraph_format.space_after=Pt(6)
        styles[name].paragraph_format.keep_with_next=True
        styles[name].paragraph_format.line_spacing=Pt(size+5)
    styles['Title'].font.size=Pt(23);styles['Title'].font.bold=True
    styles['Title'].paragraph_format.first_line_indent=Pt(0)
    styles['Title'].paragraph_format.space_after=Pt(10)
    styles['Title'].paragraph_format.line_spacing=Pt(30)
    # Remove inherited title rules/theme residue from the bundled blank template.
    for style in document.styles:
        for node in list(style.element.iter(qn('w:pBdr'))):
            node.getparent().remove(node)
    document.core_properties.title='有迹技术方案与核心算法说明'
    document.core_properties.subject='AI软件创新省赛技术材料'
    document.core_properties.author='团队47191919'
    document.core_properties.keywords='有迹 需求覆盖 提问排序 结构迁移'
    # Explicit page-number footer only; no decorative header rules.
    footer=section.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
    footer.paragraph_format.first_line_indent=Pt(0)
    font(footer.add_run('第 '),size=9)
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    font(footer.add_run(' 页'),size=9)
    lines=source.read_text(encoding='utf-8').splitlines();i=0
    while i<len(lines):
        line=lines[i].strip();i+=1
        if not line:continue
        if line=='<!-- page -->':document.add_page_break();continue
        if line.startswith('|'):
            rows=[line]
            while i<len(lines) and lines[i].strip().startswith('|'):
                rows.append(lines[i].strip());i+=1
            table(document,rows);continue
        if line.startswith('# '):
            p=document.add_paragraph(style='Title');inline(p,line[2:],size=23)
            for run in p.runs:run.bold=True
        elif line.startswith('## '):
            p=document.add_paragraph(style='Heading 1');inline(p,line[3:],size=15)
            for run in p.runs:run.bold=True
        elif line.startswith('### '):
            p=document.add_paragraph(style='Heading 2');inline(p,line[4:],size=12)
            for run in p.runs:run.bold=True
        else:
            p=document.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY
            if line.startswith('`'):
                p.paragraph_format.first_line_indent=Pt(0)
                p.paragraph_format.space_before=Pt(3);p.paragraph_format.space_after=Pt(6)
                inline(p,line,size=10)
            else:inline(p,line,size=11)
            if re.match(r'^\d+\.',line):p.paragraph_format.first_line_indent=Pt(0)
    output.parent.mkdir(parents=True,exist_ok=True);document.save(output)
    return output


def render_bundled(output, renderer):
    """Use only the dependency-loader-selected runtime and bundled LibreOffice."""
    dependencies=Path(sys.executable).parent.parent.parent
    bundled=dependencies/'bin/override/soffice'
    if dependencies.name!='dependencies' or not bundled.is_file():
        raise RuntimeError('Render with the dependency-loader-selected bundled Python; system LibreOffice fallback is forbidden')
    qa=output.parent/'_qa'/output.stem;qa.mkdir(parents=True,exist_ok=True)
    config=qa/'fonts.conf'
    fontdirs=['/System/Library/Fonts/Supplemental','/System/Library/Fonts',
              str(dependencies/'native/libreoffice-headless/libreoffice/LibreOfficeDev.app/Contents/Resources/fonts/truetype')]
    config.write_text('<?xml version="1.0"?><fontconfig>'+''.join('<dir>'+p+'</dir>' for p in fontdirs)+
                      '<cachedir>/private/tmp/youji-final-fontcache</cachedir></fontconfig>')
    env={**os.environ,'FONTCONFIG_FILE':str(config.resolve()),'SAL_FONTPATH':fontdirs[0]}
    subprocess.run([sys.executable,str(renderer),str(output),'--output_dir',str(qa),'--emit_pdf'],env=env,check=True)
    pdf=qa/(output.stem+'.pdf');shutil.copyfile(pdf,output.with_suffix('.pdf'))
    from pypdf import PdfReader
    pages=len(PdfReader(pdf).pages)
    for old in qa.glob('page-*.png'):
        if int(old.stem.split('-')[-1])>pages:old.unlink()
    return pages


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=APP/'docs/submission-final-20261103.md')
    parser.add_argument('--output',type=Path,default=ROOT/'output/有迹-省赛最终交付-20261103/01提交文档/有迹-技术方案与核心算法说明-20261103.docx')
    parser.add_argument('--render',action='store_true',help='Render and emit PDF with bundled runtime only')
    parser.add_argument('--renderer',type=Path,default=Path('/Users/lanxinrui/.codex/plugins/cache/openai-primary-runtime/documents/26.1026.10807/skills/documents/render_docx.py'))
    args=parser.parse_args();print(build(args.source,args.output))
    if args.render:print('Rendered pages:',render_bundled(args.output,args.renderer))
