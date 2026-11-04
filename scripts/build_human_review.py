"""Build a human blind-review kit from recorded arm drafts, or decode the answers.

The reviewer receives only PACKET.md and ANSWER_SHEET.csv. Which side is the
single-shot baseline (A) and which is the multi-agent + retrieval draft (C) is
kept in KEY_RESEARCHER_ONLY.json and is never printed in the packet.

No model call, no network. Everything is reproducible from the stored results.
"""
import argparse
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / 'docs/evidence/evaluation/human-review'
SIDES = ('版本一', '版本二')
# Reviewers type whatever is natural: 版本一/版本1/一/1 and the same for 二.
SIDE_ALIASES = {'版本一': '版本一', '版本1': '版本一', '一': '版本一', '1': '版本一',
                '版本二': '版本二', '版本2': '版本二', '二': '版本二', '2': '版本二'}
TIES = ('差不多', '都不愿意', '都差不多', '一样')


def load_pairs(results_path, item_ids=None):
    document = json.loads(Path(results_path).read_text(encoding='utf-8'))
    by_item = {}
    for record in document.get('records') or []:
        draft = record.get('draft') or {}
        if not draft.get('body'):
            continue
        by_item.setdefault(record['item_id'], {})[record['arm']] = draft
    pairs = []
    for item_id in sorted(by_item):
        if item_ids and item_id not in item_ids:
            continue
        row = by_item[item_id]
        if not {'A', 'C'} <= set(row):
            continue
        pairs.append({'item_id': item_id, 'A': row['A'], 'C': row['C']})
    if not pairs:
        raise SystemExit('no items have both an A and a C draft')
    return pairs


def shuffle_sides(pairs, seed=20261019):
    """Deterministic, balanced sides: half the items put A on the left."""
    rng = random.Random(seed)
    order = [pair['item_id'] for pair in pairs]
    rng.shuffle(order)
    half = len(pairs) // 2
    a_first = set(order[:half]) if len(pairs) % 2 == 0 else set(order[:half + 1])
    out = []
    for pair in pairs:
        left_arm = 'A' if pair['item_id'] in a_first else 'C'
        right_arm = 'C' if left_arm == 'A' else 'A'
        out.append({**pair, 'left_arm': left_arm, 'right_arm': right_arm,
                    'left': pair[left_arm], 'right': pair[right_arm]})
    return out


def write_packet(rows, path):
    lines = [
        '# 小红书笔记盲评：请帮我看看哪一版更好',
        '',
        '**这是什么**：我在做一个内容创作辅助工具的课程项目，想请你看几组笔记。'
        '每组有两个版本，来自两种不同的写法，但**不告诉你哪版是哪种**。',
        '',
        '**背景说明**：这些笔记写的是课程项目里编的**虚构产品**（不是真实商品）。'
        '有的版本会明确写出这一点，有的不会——**请忽略这个差异**，只比较写法本身好不好。',
        '',
        '**要花多久**：6 组，每组两篇短笔记（100–230 字），大约 10 分钟。',
        '',
        '**怎么答**：每组读完回答 3 个问题，填到随附的 `ANSWER_SHEET.csv` 里'
        '（用 Excel 或 WPS 打开）。没有标准答案，凭第一感觉就行。',
        '',
        '**隐私**：完全匿名，不收集姓名、账号或联系方式；你的选择只用于统计，'
        '不会单独展示。',
        '',
        '---',
        '',
    ]
    for index, row in enumerate(rows, start=1):
        item = row['item_id']
        lines += ['## 第 %d 组' % index, '']
        for side in ('left', 'right'):
            draft = row[side]
            label = SIDES[0] if side == 'left' else SIDES[1]
            lines += ['### %s' % label, '',
                      '**标题**：%s' % (draft.get('selected_title') or '（无标题）'), '',
                      str(draft.get('body') or '').strip(), '']
        lines += [
            '**请回答**：',
            '',
            '1. 哪一版更容易看懂？（版本一 / 版本二 / 差不多）',
            '2. 哪一版更让你愿意相信它说的是真的？（版本一 / 版本二 / 差不多）',
            '3. 如果这是一篇小红书笔记，你更愿意用哪一版？（版本一 / 版本二 / 都不愿意）',
            '',
            '---',
            '',
        ]
    path.write_text('\n'.join(lines), encoding='utf-8')
    return path


def write_html(rows, path):
    """Self-contained page: reviewers can open it on a phone and just read."""
    from html import escape

    def block(draft):
        title = escape(str(draft.get('selected_title') or '（无标题）'))
        body = escape(str(draft.get('body') or '').strip()).replace('\n', '<br>')
        return f'<h3>{title}</h3><p class="body">{body}</p>'

    cards = []
    for index, row in enumerate(rows, start=1):
        cards.append(
            f'<section class="card"><h2>第 {index} 组</h2>'
            f'<div class="cols"><div class="col"><h4>版本一</h4>{block(row["left"])}</div>'
            f'<div class="col"><h4>版本二</h4>{block(row["right"])}</div></div>'
            f'<ol class="q"><li>哪一版更容易看懂？<span>版本一 / 版本二 / 差不多</span></li>'
            f'<li>哪一版更让你愿意相信它说的是真的？<span>版本一 / 版本二 / 差不多</span></li>'
            f'<li>如果这是一篇小红书笔记，你更愿意用哪一版？<span>版本一 / 版本二 / 都不愿意</span></li>'
            '</ol></section>')
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>小红书笔记盲评</title>
<style>
 body{{margin:0;padding:24px 16px 64px;background:#f6f5f2;color:#1f2328;
   font:16px/1.75 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}}
 .wrap{{max-width:880px;margin:0 auto}}
 h1{{font-size:24px;margin:0 0 8px}}
 .intro{{background:#fff;border:1px solid #e6e2d9;border-radius:12px;padding:16px 20px;margin:16px 0 28px}}
 .intro p{{margin:6px 0}}
 .card{{background:#fff;border:1px solid #e6e2d9;border-radius:12px;padding:20px;margin:0 0 22px}}
 .card h2{{font-size:18px;margin:0 0 14px;color:#8a6d3b}}
 .cols{{display:flex;gap:16px;flex-wrap:wrap}}
 .col{{flex:1 1 320px;background:#faf9f6;border:1px solid #eee9df;border-radius:10px;padding:14px 16px}}
 .col h4{{margin:0 0 8px;font-size:14px;color:#6b7280;letter-spacing:.05em}}
 h3{{font-size:16px;margin:0 0 8px}}
 .body{{margin:0;font-size:15px}}
 .q{{margin:16px 0 0;padding-left:20px;font-size:15px}}
 .q li{{margin:6px 0}}
 .q span{{color:#8a6d3b}}
 .hint{{font-size:13px;color:#6b7280;margin-top:10px}}
 @media print{{body{{background:#fff}} .card{{break-inside:avoid}}}}
</style></head><body><div class="wrap">
<h1>小红书笔记盲评</h1>
<div class="intro">
<p>我在做一个内容创作辅助工具的课程项目，想请你看 6 组笔记。每组有两个版本，来自两种写法，但<strong>不告诉你哪版是哪种</strong>。</p>
<p><strong>背景</strong>：这些笔记写的是项目里编的<strong>虚构产品</strong>（不是真实商品）。有的版本会写明、有的不会——<strong>请忽略这个差异</strong>，只比较写法。</p>
<p><strong>怎么做</strong>：看完每组，按随附答题表填写 3 个问题。没有标准答案，凭第一感觉。</p>
<p><strong>隐私</strong>：完全匿名，不收集姓名或联系方式。</p>
</div>
{''.join(cards)}
<p class="hint">共 {len(rows)} 组 · 约 10 分钟 · 感谢帮忙</p>
</div></body></html>"""
    path.write_text(page, encoding='utf-8')
    return path


def write_answer_sheet(rows, path):
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['读者编号', '组号', '题目ID',
                         'Q1_哪版更容易看懂', 'Q2_哪版更可信', 'Q3_更愿意用哪版', '备注（可选）'])
        for index, row in enumerate(rows, start=1):
            writer.writerow(['', index, row['item_id'], '', '', '', ''])
    return path


def write_key(rows, path):
    key = {'note': '研究者专用，不要发给评审人',
           'sides': [{'item_id': row['item_id'], 'left_arm': row['left_arm'],
                      'right_arm': row['right_arm']} for row in rows]}
    path.write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def write_readme(rows, path, seed):
    text = f"""# 盲评执行说明（给研究者，不要发给评审人）

## 一 你需要发出去的文件

- `PACKET.html`：**最推荐发这个**，手机/电脑直接打开，排版好、可打印
- `PACKET.md`：同一份题目的纯文本版
- `ANSWER_SHEET.csv`：评审人填的答题表

**不要发** `KEY_RESEARCHER_ONLY.json`。

## 二 怎么发

把 `PACKET.md` 转成 PDF 或直接发 Word/Markdown 都行；
`ANSWER_SHEET.csv` 用 Excel/WPS 打开填写。

建议找 **3–5 位同学**，每人独立完成，不要互相讨论。

## 三 回收后怎么算

1. 让每位同学把 CSV 里的「读者编号」填成 1、2、3……
2. 把所有人的答案**复制到同一个 CSV**（保留表头，追加行）
3. 运行：

```bash
runtime/venv/bin/python scripts/build_human_review.py --decode 填写好的.csv
```

会输出 `RESULTS.md`：每组各版本被选为"更清楚/更可信/更愿意用"的次数，
以及按盲底还原后的 A 组（单次直写）与 C 组（多 Agent+检索）对比。

## 四 样本与随机化

- 共 {len(rows)} 组，来自 2026-10-18 三组对照实验的真实成稿
- 左右位置按固定随机种子 `{seed}` 生成，A/C 各占一半，**可复现**
- 评审人看不到任何组别标签

## 五 结果怎么用

- 这是**真人偏好**数据，与自动指标（事实支撑率等）互补，不互相替代
- n<30 只能表述为「初步观察」，不得写成统计显著
- 无论结果偏向哪一组，都如实写入材料
"""
    path.write_text(text, encoding='utf-8')
    return path


def decode(csv_path, key_path=None, out_dir=None):
    key_path = Path(key_path) if key_path else OUT / 'KEY_RESEARCHER_ONLY.json'
    key = json.loads(Path(key_path).read_text(encoding='utf-8'))
    side_of = {row['item_id']: row for row in key['sides']}

    # Arm for a given answer label, given which arm sat on the left.
    def arm_for(item_id, answer):
        answer = SIDE_ALIASES.get((answer or '').strip())
        if answer is None:
            return None
        sides = side_of[item_id]
        return sides['left_arm'] if answer == '版本一' else sides['right_arm']

    tallies = {'Q1': {}, 'Q2': {}, 'Q3': {}}
    readers = set()
    rows_read = 0
    with Path(csv_path).open(encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            item_id = (row.get('题目ID') or '').strip()
            if item_id not in side_of:
                continue
            rows_read += 1
            if (row.get('读者编号') or '').strip():
                readers.add(row['读者编号'].strip())
            for question, column in (('Q1', 'Q1_哪版更容易看懂'),
                                     ('Q2', 'Q2_哪版更可信'),
                                     ('Q3', 'Q3_更愿意用哪版')):
                answer = (row.get(column) or '').strip()
                answer = SIDE_ALIASES.get(answer, answer)
                if answer in TIES:
                    tallies[question][answer] = tallies[question].get(answer, 0) + 1
                    continue
                arm = arm_for(item_id, answer)
                if arm:
                    tallies[question][arm] = tallies[question].get(arm, 0) + 1

    lines = ['# 真人盲评结果', '',
             '有效记录：%d 条；参与读者：%d 人；题目组：%d 组' % (rows_read, len(readers), len(side_of)),
             '', '| 问题 | A 单次直写 | C 多Agent+检索 | 平手/都不愿意 |',
             '| --- | ---: | ---: | ---: |']
    for question, label in (('Q1', '哪一版更容易看懂'),
                            ('Q2', '哪一版更可信'),
                            ('Q3', '更愿意用哪一版')):
        bucket = tallies[question]
        tie = sum(value for name, value in bucket.items() if name in ('差不多', '都不愿意'))
        lines.append('| %s | %d | %d | %d |' % (label, bucket.get('A', 0), bucket.get('C', 0), tie))
    lines += ['', '> n 很小，只能表述为初步观察，不构成统计结论。']
    target = Path(out_dir or OUT) / 'RESULTS.md'
    target.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return target, tallies


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--results', default=str(
        ROOT / 'docs/evidence/evaluation/results-20261018-221902.scored.json'))
    parser.add_argument('--seed', type=int, default=20261019)
    parser.add_argument('--items', default='', help='comma separated item ids')
    parser.add_argument('--decode', metavar='FILLED.csv')
    parser.add_argument('--key', default='')
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if args.decode:
        target, tallies = decode(args.decode, args.key or None)
        print(json.dumps({'results': str(target), 'tallies': tallies}, ensure_ascii=False, indent=2))
        return

    item_ids = [part.strip() for part in args.items.split(',') if part.strip()] or None
    pairs = load_pairs(args.results, item_ids)
    rows = shuffle_sides(pairs, args.seed)
    left_arms = [row['left_arm'] for row in rows]
    print(json.dumps({'packet': str(write_packet(rows, OUT / 'PACKET.md')),
                      'answer_sheet': str(write_answer_sheet(rows, OUT / 'ANSWER_SHEET.csv')),
                      'key': str(write_key(rows, OUT / 'KEY_RESEARCHER_ONLY.json')),
                      'readme': str(write_readme(rows, OUT / 'README.md', args.seed)),
                      'html': str(write_html(rows, OUT / 'PACKET.html')),
                      'items': len(rows), 'A_on_left': left_arms.count('A')},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
