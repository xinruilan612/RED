"""Collect licensed public Python documentation; never invokes a model."""
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parent
BASE = 'https://docs.python.org/3.12/'
SAMPLES = [
    ('字符串基础', 'tutorial/introduction.html', 'text'),
    ('列表基础', 'tutorial/introduction.html', 'lists'),
    ('定义函数', 'tutorial/controlflow.html', 'defining-functions'),
    ('列表推导式', 'tutorial/datastructures.html', 'list-comprehensions'),
    ('字典', 'tutorial/datastructures.html', 'dictionaries'),
    ('文本文件读写', 'tutorial/inputoutput.html', 'reading-and-writing-files'),
    ('JSON保存结构化数据', 'tutorial/inputoutput.html', 'saving-structured-data-with-json'),
    ('处理异常', 'tutorial/errors.html', 'handling-exceptions'),
    ('pathlib基础使用', 'library/pathlib.html', 'basic-use'),
    ('argparse可选参数', 'howto/argparse.html', 'introducing-optional-arguments'),
]

class Node:
    def __init__(self, tag='', attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.parts = []
    def text(self):
        return ''.join(p.text() if isinstance(p, Node) else p for p in self.parts)

class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()
        self.ids = {}
    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.parts.append(node)
        if node.attrs.get('id'): self.ids[node.attrs['id']] = node
        if tag not in {'meta', 'link', 'img', 'br', 'hr', 'input', 'wbr', 'source'}:
            self.current = node
    def handle_endtag(self, tag):
        cursor = self.current
        while cursor.parent is not None and cursor.tag != tag: cursor = cursor.parent
        if cursor.parent is not None:
            if tag in {'p','pre','li','h1','h2','h3','h4','section','div','table'}:
                cursor.parts.append('\n\n')
            self.current = cursor.parent
    def handle_data(self, data): self.current.parts.append(data)

def digest(data): return sha256(data).hexdigest()
def timestamp(): return datetime.now(timezone.utc).isoformat()
def download(url, path):
    subprocess.run(['curl','--silent','--show-error','--fail','--location','--max-time','45',url,'-o',str(path)], check=True)
    data = path.read_bytes()
    parser = Tree(); parser.feed(data.decode('utf-8'))
    return data, parser, timestamp()
def text(node):
    value = '\n'.join(line.rstrip() for line in node.text().replace('¶','').strip().splitlines()).strip()
    return re.sub(r'\n{3,}', '\n\n', value)+'\n'

def main():
    raw = ROOT/'sources'; raw.mkdir(exist_ok=True)
    license_data, license_tree, license_time = download(BASE+'license.html', ROOT/'license.html')
    license_body = license_tree.ids['history-and-license']
    (ROOT/'LICENSE_SOURCE.txt').write_text(text(license_body), encoding='utf-8')
    psf = text(license_tree.ids['python-software-foundation-license-version-2'])
    # Keep the exact notice and complete section, rather than paraphrasing the grant.
    (ROOT/'LICENSE_PSF.txt').write_text(psf, encoding='utf-8')
    bsd_id = next(k for k in license_tree.ids if 'zero-clause' in k)
    (ROOT/'LICENSE_0BSD.txt').write_text(text(license_tree.ids[bsd_id]), encoding='utf-8')
    cache = {}; records=[]
    for index, (title, page, anchor) in enumerate(SAMPLES, 1):
        identity = f'S{index:02d}'
        if page not in cache:
            file = raw/page.replace('/','_')
            data, tree, fetched = download(BASE+page, file)
            cache[page] = (data, tree, fetched, file)
        data, tree, fetched, file = cache[page]
        section = text(tree.ids[anchor])
        folder = ROOT/identity; folder.mkdir(exist_ok=True)
        url = BASE+page+'#'+anchor
        copyright_notice = 'Copyright © 2001-2023 Python Software Foundation; All Rights Reserved.'
        metadata = (f'# {identity}：{title}\n\n来源：{url}\n\n采集时间（UTC）：{fetched}\n\n'
            f'来源性质：Python 3.12 官方英文文档公开章节，非用户投稿或真实创作者私稿。\n\n'
            f'许可：文档正文 PSF License Version 2；代码示例同时可按 0BSD 使用。\n\n'
            f'{copyright_notice}\n\n许可全文见 ../LICENSE_PSF.txt、../LICENSE_0BSD.txt 与 ../LICENSE_SOURCE.txt。\n\n')
        support = metadata+'## 官方章节全文\n\n```text\n'+section+'```\n'
        draft = metadata+('改编说明：保留官方英文教程章节原文，未翻译、未人为植入错误、未添加真实作者反馈；'
            '仅添加来源与许可说明、删除网页段落锚点符号并整理空白。此为公开教程节选候选输入，'
            '不是 baseline 或风洞最终改稿。\n\n## 待检查教程节选\n\n```text\n'+section+'```\n')
        (folder/'support.md').write_text(support, encoding='utf-8')
        (folder/'draft.md').write_text(draft, encoding='utf-8')
        records.append(dict(id=identity, sample_id=identity, topic=title, language='en', scenario='Python 3.12 初学实用教程',
            split='exploration' if index<=3 else 'candidate_holdout', cohort_candidate='exploratory' if index<=3 else 'holdout_candidate', strict_hidden=False,
            selected_by_reader=True, frozen=False, source_url=url, source_section=anchor, license_ref='LICENSE_PSF.txt', code_license_ref='LICENSE_0BSD.txt', page_url=BASE+page,
            fetched_at_utc=fetched, source_html=str(file.relative_to(ROOT)), source_html_sha256=digest(data),
            section_text_sha256=digest(section.encode()), support_path=f'{identity}/support.md',
            support_sha256=digest(support.encode()), draft_path=f'{identity}/draft.md', draft_sha256=digest(draft.encode()),
            draft_kind='public_official_tutorial_excerpt', adaptation='layout and attribution only; original English text',
            license='PSF-2.0 for documentation; code examples dual PSF-2.0/0BSD',
            author_feedback=None, human_results=None, baseline_result=None, windtunnel_result=None))
    manifest=dict(schema_version=1, collected_at_utc=timestamp(), python_docs_series='3.12',
        source_kind='official_public_documentation', purpose='candidate sampling only',
        split_note='3 exploration + 7 candidate holdout; selector has read all, not strictly hidden or frozen',
        license_source_url=BASE+'license.html', license_fetched_at_utc=license_time,
        license_html_sha256=digest(license_data), samples=records)
    (ROOT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'samples':len(records),'pages':len(cache),'license':bsd_id},ensure_ascii=False))

if __name__ == '__main__': main()
