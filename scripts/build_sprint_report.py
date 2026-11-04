"""Aggregate local sprint evidence without manufacturing human outcomes."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys

APP=Path(__file__).resolve().parents[1]
ROOT=APP.parent
sys.path.insert(0,str(APP))
from scripts.build_original_creation_report import sanitize


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'output/冲刺提升验收-20261102')
    args=parser.parse_args();out=args.output
    logs=out/'测试日志';logs.mkdir(parents=True,exist_ok=True)
    backend=(APP/'runtime/sprint-backend-final.log').read_text()
    matches=re.findall(r'Ran (\d+) tests in ([\d.]+)s',backend)
    if not matches or 'FAILED (' in backend or not re.search(r'\nOK(?: \(skipped=\d+\))?\s*$',backend):
        raise ValueError('Final complete backend suite not passed')
    count=int(matches[-1][0]);skip=int(re.findall(r'OK \(skipped=(\d+)\)',backend)[-1])
    frontend=(APP/'runtime/sprint-frontend-release.log').read_text()
    front=int(re.search(r'tests (\d+)',frontend)[1])
    if not re.search(r'fail 0\b',frontend):raise ValueError('Frontend not passed')
    for name in ('sprint-backend-final.log','sprint-frontend-release.log','sprint-live-ledger-tests.log'):
        (logs/name).write_text((APP/'runtime'/name).read_text().replace(str(ROOT),'[项目目录]'))
    cases=[]
    live=out/'真实对照';live.mkdir(parents=True,exist_ok=True)
    for batch in ('sprint-live', 'sprint-live-native', 'sprint-live-native2', 'sprint-live-final'):
        folder=APP/'runtime'/batch
        if not folder.exists():continue
        dest=live/batch;dest.mkdir(exist_ok=True)
        for path in folder.glob('*.json'):
            if path.name=='private-state.json':continue
            payload=json.loads(path.read_text())
            (dest/path.name).write_text(json.dumps(sanitize(payload),ensure_ascii=False,indent=2))
        state_path=folder/'private-state.json'
        if state_path.exists():
            state=json.loads(state_path.read_text())
            cases.extend({'batch':batch,**c} for c in state.get('cases',[]))
            (dest/'导入说明.json').write_text(json.dumps(state.get('reference_imports',{}),ensure_ascii=False,indent=2))
    ledger=APP/'runtime/algorithms-live/budget.sqlite'
    with sqlite3.connect(ledger) as db:
        totals=[dict(zip(('state','attempts','tokens','upper_micro'),r)) for r in db.execute('SELECT state,count(*),coalesce(sum(tokens),0),sum(coalesce(billed,reserved)) FROM attempts GROUP BY state')]
    upper=sum(r['upper_micro'] for r in totals)
    if upper>5_000_000:raise ValueError('Budget cap exceeded')
    bench=json.loads((out/'受控实验/benchmark.json').read_text())
    summary={'backend':{'total':count,'passed':count-skip,'skipped':skip,'failures':0,'sqlite_and_postgres':True},
             'frontend':{'total':front,'passed':front,'failed':0},'live_cases':cases,'cumulative_upper_cny':upper/1e6,
             'ledger':totals,'human_quality_evaluation':None,'real_creator_trial':None,'windows_native_test':None,
             'structure_macro_f1':None,'score_or_award_probability':None}
    (out/'验收数据.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    final=[c for c in cases if c['batch']=='sprint-live-final']
    good=sum(bool(c.get('completed')) for c in final)
    rows='\n'.join('| '+str(c['id'])+' | '+('已成稿' if c.get('completed') else '未成稿')+' | '+str(c.get('review_decision') or '无结论')+' |' for c in final)
    text=f'''# 有迹冲刺修订验收成果

本轮已完成能在本机开发、计算与留证的部分。交付范围是算法补强、独立实验开关、受控消融、评价工具、答辩文件及一致运行包。真人评价与Windows实机验收未完成；不宣称已获得70-80分。

## 1. 验收结论

| 文件建议 | 本轮完成情况 | 验收依据 |
| --- | --- | --- |
| 源码/Windows包一致 | 由同一个干净提交构建，所有源码成员逐字相同比对 | 交付校验.json、每包MANIFEST、SHA256 |
| 小规模精确搜索 | <=12合法候选枚举，>12贪心回退；最优范围受候选池约束 | planning.py；受控实验/REPORT.md |
| 算法一消融 | 已完成同预算/无权重/无证据门控 | 24个构造任务、完整输入与独立枚举 |
| 算法二成本验证 | 规则机制对照已完成，真人成本未校准 | 固定标准答案实验；真人计时与负担空表 |
| 算法三消融 | 已完成提取/领域/证据适配四组机制对照 | 结构消融/80条轨迹；非质量评测 |
| 20任务与30样本 | 已备齐数码7、家居7、学习6；30篇156段 | 自编受控资料，拟定需求待人工审核 |
| 五组模型探索 | 最终批次{len(final)}组尝试，{good}组已成稿，失败未隐藏 | 真实对照/，详见下节 |
| 独立盲评与用户研究 | 工具和空表完成，真人结果未获得 | 评价工具/、真人验收/ |
| 12页答辩文件 | 可编辑PPTX+展示PDF、5分钟讲稿、8题问答 | 答辩材料/ |
| 实际演示视频 | 已完成录制脚本，尚未录制连贯真人操作视频 | 不把脚本或幻灯片当实操视频 |
| Windows原生验证 | 未在Mac伪装执行；空表已备 | Windows实机验收-空表.csv |

原交付核对：当前目录上一轮两个ZIP的5个核心算法文件相互一致，planning.py均为16842字节。参考附件描述的另一份22598字节修订包未在当前目录找到；不能认定已复现其不一致问题。本轮确实新增精确求解，故重新打包；新一致性结论以新交付校验为准。

## 2. 本轮实际改变

**先决定写什么。** 权重覆盖目标减去0.15倍重复覆盖权重；证据门控和预算约束不变。最多12个合法候选时枚举最多4096子集，超过12回退密度贪心。输出objective、候选召回、贪心差距和耗时；steps明确标为贪心对照，不能拿它冒充精确搜索取舍轨迹。

**分别验证三个模块。** API新增coverage/structure独立布尔开关，形成A原四角色、B仅覆盖、C仅提问、D仅结构、E全部。旧任务与缺省保持兼容；关闭的模块不进入模型计划，前端也不把诊断计算展示成启用结果。

**修复标题阻塞。** 小红书候选按Unicode字符最多20，英文、数字、标点和emoji按字符计。保留合规的原样候选与对应理由；已选标题合规则不换，已选超长则选合法备用并记审计。无合法标题仍拒绝。不任意截断、不编造标题、不复制补足五个。部分超长时可能少于五个备选。原始模型响应和实际用量保留，后续正文仍须与选定标题一致，并经过审核。

## 3. 已测数据及可得结论

24个构造任务：输入顺序覆盖242/359，贪心326/359，正式精确解333/359；目标值分别230.90、316.85、328.65。精确解相对独立枚举目标差距0，相对贪心目标总增益11.80；候选需求召回115/118。去权重329/359；去证据门控356/359但选入23个无依据模块，正式版本0。不能用虚高覆盖掩盖证据错误。

固定两问下，顺序询问解决84/168依赖块，价值排序120/168；这些依赖与答案是自编固定机制，不代表真人价值或完成率。成本参数未经过真人耗时校准。

结构四组：A不移入结构，其污染/缺证据比例不适用；B只提取时异领域20/20、缺证据54/128槽；C加领域筛选后异领域0/20、缺证据38/109；D加证据适配后异领域0/20、缺证据0/109。这里刻意把异领域干扰放在首位，替换规则也会按定义清零，不能外推真实检索污染率、Macro-F1或写作自然度。

以上均为受控机制结果，不是真实用户、真实商品评测或独立事实真值。

## 4. 真实模型记录

最终批次使用同一个D01虚构鼠标任务和qwen-plus连接，五组控制同初始事实、参考库与300字预算；C/E仅在实际提问后提供统一密封标准答案。它们可能获得额外信息和更多研究调用，不能将其效果全部归为纯算法质量提升。

| 最终批次 | 流程 | 模型主编判断（不是人工结论） |
| --- | --- | --- |
{rows}

本轮没有完成完整五组质量对照。最终E组在正文调用前因剩余额度不足以预留而停止，未发送该正文请求，不存在最终E组成稿。四份最终稿可先逐篇人工核对，但正式五组盲评需要补齐同条件E组并取得后续费用授权。

前期记录完整保留：沙箱内请求未发送；第一批实验适配器误将所有输出上限设为3000，策略需要6000导致预发送阻断；修正后第二批A/B因未选中的超长备用标题阻断，C/D/E成稿。由此补上标题合法候选筛选。它们不混进最终同版本批次，也不删除失败以提高完成率。

第二批参考样本在BM25中未命中，实际走基础结构回退；不能把它说成真实结构迁移成功。最终批次在隔离测试账号导入带明确“资料标签（非正文）”头的自编派生参考，保留原受控正文、原始/导入哈希及头部文字，验证真实词项召回与结构分支；不是未修改真实文章，也不证明生产检索质量。原30样本文件未改。

累计费用保守上界 **{upper/1e6:.6f}元**，含上轮1.605664元以及本轮所有失败和成功尝试；上限5元。完整账本分类见验收数据.json。计费采用8元/百万总Token，未知用量持有全额预留并阻断；这不是供应商最终账单。价格核对来源：https://help.aliyun.com/zh/model-studio/model-pricing 。

模型审核approved只表示模型给出此判断；WAITING_USER仍需要人工确认。未替用户批准或发布，没有真实用户采用率、质量提升百分比或获奖分数。真实模型运行不等于独立真人评价。

## 5. 工程回归

最终完整后端 **{count}项：{count-skip}通过、{skip}条件跳过、0失败**，包含SQLite和真实隔离PostgreSQL schema、Worker与检查点。4跳过为2可选本地BGE测试、2Windows原生进程容器测试，不能算通过。前端 **{front}/{front}通过**。日志收录于测试日志/；旧版本1189/256、上一轮1256/284仅是带日期历史，不作为当前总数。

纯算法、协议/权限、回放、费用、UI测试证明的是程序行为；不能替代收费生成质量或真人试用。语法/角色卡与交付包检查另见复核结果.json。

## 6. 如何验收

先读00_验收导航.md，再看受控实验和结构消融的完整输入。Windows请解压新运行包按一键启动.cmd运行；Mac不要执行Windows嵌入Python。真人验收只分别分发对应评委文件夹，研究者映射与密封答案不得在创作前泄漏。空表保持空值，0不能代替未测。

免费复算从app执行：

```bash
runtime/venv/bin/python scripts/algorithm_bench.py --output ../output/机制复算
runtime/venv/bin/python scripts/structure_ablation.py --help
runtime/venv/bin/python scripts/sprint_evaluation.py --help
```

真实模型脚本仅为本次授权执行；以后重新运行需要新预算，不从零新建累计账本。源码运行依赖见requirements.txt，当前Mac的runtime/venv仅是本地验证环境，不打入源包。

## 7. 需要你参与完成的部分

1. 找3-5位独立评审盲评；目前质量分、差异区间都未测，单任务也不能给区间。
2. 找8-12位创作者每人两任务，记录回答耗时、跳过、负担、实际修改与采用；填写授权和匿名反馈。
3. 两人独立标注30篇156段，经仲裁后计算结构Macro-F1/逐类Precision/Recall与Kappa。当前0.75只是未来目标。
4. 用Windows 10/11实机按空表验证启动、创作、补料/跳过、导出与关闭子进程；本Mac不能代签。
5. 按脚本录制连续真实操作视频，并练习五分钟讲稿。本人贡献须依实际分工说明AI辅助范围。

这些缺口需要真人、额外设备或独立授权，不能由本机脚本造出。此包把可执行的准备、代码与现有证据交齐。
'''
    (out/'验收成果报告.md').write_text(text)
    return summary


if __name__=='__main__':main()
