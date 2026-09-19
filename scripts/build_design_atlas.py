"""Build offline SVG/HTML and editable Mermaid diagrams. Standard library only."""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/design'
# Each node: id, x, y, width, title, subtitle, kind. Height is always 78.
# Each edge: source, target, label, explicit polyline, dashed.
H = 78

def n(id, x, y, title, subtitle='', kind='service', w=380):
    return dict(id=id, x=x, y=y, w=w, title=title, subtitle=subtitle, kind=kind)

def e(a, b, label, points, dashed=False):
    return dict(source=a, target=b, label=label, points=points, dashed=dashed)

GRAPHS = [
 dict(id='architecture', title='五层软件架构', subtitle='D1 · 职责分层，不是五台服务器；横向设施承载权限、模型和事件', width=1200, height=1140,
 nodes=[
 n('L1',160,120,'L1 · UI / Runtime Console','Brief / 编辑 / 人工确认 / 状态与输入输出 / Tool calls / Memory reads / 耗时和成本','human',880),
 n('L2',160,300,'L2 · Orchestrator','API / 快照 / 并行汇合 / 分支 / 有界返修 / 预算 / 暂停与恢复','service',880),
 n('L3',160,480,'L3 · 四个 Agents','Audience 受众洞察 / Research 素材研究 / Content 策划创作 / Reviewer 主编审核','agent',880),
 n('tools',160,660,'L4 · Tools 能力','历史分析 / 素材检索 / 依据检查 / 渲染','service',420),
 n('skills',620,660,'L4 · Skills 方法','分析方法 / 策略与写作 / 审核标准','service',420),
 n('L5',160,900,'L5 · Memory','Profile 账号画像 / Material 真实素材 / History 历史内容与表现','data',880)],
 edges=[
 e('L1','L2','请求、确认；事件回传到 Console',[(600,198),(600,300)]),
 e('L2','L3','受控调度与结果校验',[(600,378),(600,480)]),
 e('L3','tools','获准工具调用',[(370,558),(370,660)]),
 e('skills','L3','加载固定版本方法',[(830,660),(830,558)]),
 e('tools','L5','按身份与来源版本读取',[(370,738),(370,900)]),
 e('L2','L5','运行检查点 / 事件独立存储',[(160,339),(70,339),(70,939),(160,939)],True)],
 notes=['Skills 不保存用户资料、不赋予权限；Memory 的画像更新须由用户确认。',
        '模型网关、认证、队列为横向设施；所有层输出事件，Console 展示可审计成果而非隐藏推理。']),
 dict(id='workflow',title='四 Agent 并行与返修流程',subtitle='D2 · Audience + Research 并行；同一个 Content 负责策划、创作和改稿',width=1200,height=1800,
 nodes=[
 n('brief',410,110,'用户 Brief + 输入快照','固定 Profile / Material / History','human'),
 n('audience',20,270,'① Audience · 受众洞察','历史分析 / 相似内容 / 画像与历史','agent',360),
 n('research',820,270,'② Research · 素材研究','素材检索 / 依据检查 / 证据缺口','agent',360),
 n('join',410,440,'Join · 同快照汇合','两分支有效成功；失败不当空结果'),
 n('content',410,600,'③ Content · 内容策划创作','Strategy → Outline → Hook → Title → Body','agent'),
 n('reviewer',410,780,'④ Reviewer · 主编审核','分项分数 / 阻断问题 / 修改指令','agent'),
 n('revise',850,600,'Content.revise','最早受影响阶段起重算','agent',330),
 n('supply',20,1060,'补充资料 / 新快照','重新验证两分支；预算不静默清零','human',330),
 n('limit',850,960,'自动返修上限','等待补料新运行或取消','human',330),
 n('human',410,1060,'人工确认当前已审版本','接受 / 请求改稿 / 取消','human'),
 n('final',410,1220,'最终内容版本','用户接受后进入 History','data'),
 n('export',410,1380,'模板工具导出','确认版本 / 图片 / manifest'),
 n('done',410,1540,'完成交付','发布由人决定，指标手工回填','human'),
 n('cancelled',850,1540,'取消 / 保留候选稿','不升级为最终内容','data',330)],
 edges=[
 e('brief','audience','并行分支',[(410,149),(200,149),(200,270)]),
 e('brief','research','并行分支',[(790,149),(1000,149),(1000,270)]),
 e('audience','join','AudienceInsight',[(200,348),(200,479),(410,479)]),
 e('research','join','ResearchNotes',[(1000,348),(1000,479),(790,479)]),
 e('join','content','完整性 / 版本通过',[(600,518),(600,600)]),
 e('join','supply','关键资料不足',[(410,499),(160,499),(160,1060)],True),
 e('content','reviewer','Draft + 阶段产物',[(600,678),(600,780)]),
 e('reviewer','revise','不通过，有额度',[(790,819),(1015,819),(1015,678)],True),
 e('revise','content','改稿',[(850,639),(790,639)],True),
 e('reviewer','human','通过门槛',[(600,858),(600,1060)]),
 e('reviewer','supply','关键证据不足',[(410,819),(185,819),(185,1060)],True),
 e('reviewer','limit','返修 2 轮仍不过',[(790,839),(810,839),(810,925),(1015,925),(1015,960)],True),
 e('limit','supply','补料后明确新建 run',[(1015,1038),(1015,1190),(185,1190),(185,1138)],True),
 e('supply','brief','新快照重新分析',[(20,1099),(10,1099),(10,90),(600,90),(600,110)],True),
 e('limit','cancelled','取消',[(1180,999),(1190,999),(1190,1579),(1180,1579)],True),
 e('human','revise','用户请求改稿',[(790,1080),(830,1080),(830,560),(1015,560),(1015,600)],True),
 e('human','cancelled','取消',[(790,1118),(825,1118),(825,1579),(850,1579)],True),
 e('human','final','接受且版本有效',[(600,1138),(600,1220)]),
 e('final','export','有效审核版本',[(600,1298),(600,1380)]),
 e('export','done','文件齐全',[(600,1458),(600,1540)])],
 notes=['没有历史只能标注假设；补料入口也用于汇合前发现关键资料不足，见 FLOWS.md。',
        '改稿后必回 Reviewer；修改过的稿件必须复审。图中的业务恢复不重置旧 run 累计费用。']),
 dict(id='deployment',title='云端部署拓扑',subtitle='D3 · 单节点起步，模型通过 API 调用，无需自备 GPU',width=1200,height=1160,
 nodes=[
 n('browser',410,110,'用户浏览器','无需 CLI / API Key / 扩展','human'),
 n('gateway',410,270,'HTTPS 网关','TLS / 请求大小 / SSE 代理'),
 n('web',20,430,'Web 服务','Next.js','service',330),
 n('api',410,430,'API 服务','FastAPI / Session / 归属校验'),
 n('redis',850,430,'Redis','任务传输 / 限额协调','data',330),
 n('jobs',410,610,'Worker + Dispatcher','Celery / LangGraph / outbox'),
 n('model',850,610,'外部模型 API','服务端密钥；有额度限制','external',330),
 n('db',20,800,'PostgreSQL','持久卷或托管数据库','data',330),
 n('renderer',410,800,'隔离的模板渲染器','禁止任意 HTML 和外网访问'),
 n('object',850,800,'私有对象存储','用户图片 / 图文导出','data',330),
 n('backup',20,970,'备份与恢复','RPO 24h / RTO 4h 待验证','data',330)],
 edges=[
 e('browser','gateway','公网 HTTPS',[(600,188),(600,270)]),
 e('gateway','web','页面',[(410,309),(185,309),(185,430)]),
 e('gateway','api','/api',[(600,348),(600,430)]),
 e('api','redis','任务通知',[(790,469),(850,469)]),
 e('redis','jobs','领取任务',[(1015,508),(1015,550),(600,550),(600,610)]),
 e('jobs','model','调用',[(790,649),(850,649)]),
 e('api','db','业务事务',[(410,469),(375,469),(375,740),(185,740),(185,800)]),
 e('jobs','db','检查点',[(410,649),(185,649),(185,800)]),
 e('jobs','renderer','渲染任务',[(600,688),(600,800)]),
 e('renderer','object','上传',[(790,839),(850,839)]),
 e('db','backup','每日 / 演练',[(185,878),(185,970)])],
 notes=['初始资源建议：4 vCPU / 8 GiB；模型并发 2。均为待验证配置，不代表性能实测。',
        '仅网关暴露公网；API/队列/数据库/Worker 走私网；对象下载使用短效授权链接。']),
 dict(id='lifecycle',title='任务生命周期',subtitle='D4 · 终态不回退，恢复保留累计用量及重试计数',width=1200,height=1150,
 nodes=[
 n('QUEUED',410,110,'QUEUED · 等待执行','任务和 outbox 已落库'),
 n('RUNNING',410,300,'RUNNING · 正在执行','租约 120s / 心跳 20s','agent'),
 n('WAITING_USER',20,510,'WAITING_USER · 等待用户','保存检查点，释放 Worker','human',330),
 n('RETRY_WAIT',850,510,'RETRY_WAIT · 等待重试','短暂故障，有界退避','service',330),
 n('SUCCEEDED',410,690,'SUCCEEDED · 目标完成','成果可查询','data'),
 n('EXPIRED',20,880,'EXPIRED · 等待过期','7 天后关闭，保留草稿','data',330),
 n('CANCELLED',410,880,'CANCELLED · 已取消','不接受迟到成果','data'),
 n('FAILED',850,880,'FAILED · 执行失败','配置 / 预算 / 不可恢复错误','data',330)],
 edges=[
 e('QUEUED','RUNNING','领取',[(600,188),(600,300)]),
 e('RUNNING','WAITING_USER','需确认 / 补料',[(410,339),(185,339),(185,510)]),
 e('WAITING_USER','QUEUED','用户恢复',[(20,549),(10,549),(10,149),(410,149)],True),
 e('RUNNING','RETRY_WAIT','短暂故障',[(790,339),(1015,339),(1015,510)],True),
 e('RETRY_WAIT','QUEUED','重试',[(1180,549),(1190,549),(1190,149),(790,149)],True),
 e('RUNNING','SUCCEEDED','目标达成',[(600,378),(600,690)]),
 e('RUNNING','CANCELLED','取消请求',[(450,378),(390,378),(390,825),(600,825),(600,880)],True),
 e('WAITING_USER','EXPIRED','超期',[(185,588),(185,880)],True),
 e('RETRY_WAIT','FAILED','不可继续',[(1015,588),(1015,880)],True),
 e('RUNNING','FAILED','不可恢复',[(790,360),(815,360),(815,850),(1015,850),(1015,880)],True)],
 notes=['所有非终态均可 CANCELLED；RUNNING 也可直接 FAILED。完整转换表见 design_contract.json。',
        'SUCCEEDED 代表本次请求目标达成；full 流程需用户接受。导出任务有独立状态。']),
 dict(id='runtime',title='Runtime Console 事件链',subtitle='D5 · 真实事件驱动的观察与干预，不模拟 Agent 思考',width=1200,height=1120,
 nodes=[
 n('producer',200,120,'Orchestrator / Agents / Tools / Memory','统一 event_id / run_id / seq / agent / stage / snapshot_id','agent',800),
 n('events',200,310,'鉴权、脱敏与事件持久化','PostgreSQL 先落库，再通知；call_id 用量去重','data',800),
 n('transport',200,500,'API · SSE / 状态快照','15s 心跳 / Last-Event-ID 续读 / 5s 补偿轮询','service',800),
 n('console',200,690,'UI · Runtime Console','状态 / 输入输出 / Tool calls / Memory reads / 耗时 / Token成本 / 错误重试','human',800),
 n('action',200,900,'允许的用户操作 → 服务端校验','补料 / 改稿 / 接受 / 取消；幂等键 + 状态与稿件版本','human',800)],
 edges=[
 e('producer','events','步骤、工具与记忆事件',[(600,198),(600,310)]),
 e('events','transport','按用户与游标读取',[(600,388),(600,500)]),
 e('transport','console','事件重放去重',[(600,578),(600,690)]),
 e('console','action','allowed_actions',[(600,768),(600,900)]),
 e('action','producer','恢复命令',[(200,939),(60,939),(60,159),(200,159)],True)],
 notes=['默认摘要 240 字符，事件保留 30 天；过期游标返回快照并标记历史不完整。',
        '成本 unknown 不记作 0；不展示密钥、完整系统提示或隐藏推理；管理员默认只能看脱敏指标。'])

]

COLORS = {'service':('#f0f5ff','#4763b6'), 'human':('#eaf8f3','#15816a'),
          'agent':('#eeebff','#7354bd'), 'data':('#f4f6f9','#65748c'),
          'external':('#fff4e4','#bc791d')}

def svg(g):
    esc = html.escape
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{g["width"]}" height="{g["height"]}" viewBox="0 0 {g["width"]} {g["height"]}" role="img" aria-labelledby="title desc">',
      f'<title id="title">{esc(g["title"])}</title><desc id="desc">{esc(g["subtitle"])}</desc>',
      '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="#71809c"/></marker></defs>',
      '<rect width="100%" height="100%" fill="#ffffff"/>',
      '<g font-family="PingFang SC, Microsoft YaHei, sans-serif">',
      f'<text x="28" y="40" font-size="26" font-weight="700" fill="#182841">{esc(g["title"])}</text>',
      f'<text x="28" y="71" font-size="16" fill="#65748c">{esc(g["subtitle"])}</text>']
    for edge in g['edges']:
        pts=edge['points']; p=' '.join(f'{x},{y}' for x,y in pts)
        dash=' stroke-dasharray="7 5"' if edge['dashed'] else ''
        pieces.append(f'<polyline points="{p}" fill="none" stroke="#71809c" stroke-width="2"{dash} marker-end="url(#arrow)"/>')
        # Label the longest segment, offset to avoid the connector itself.
        a,b=max(zip(pts,pts[1:]),key=lambda ab:abs(ab[0][0]-ab[1][0])+abs(ab[0][1]-ab[1][1]))
        x=(a[0]+b[0])/2; y=(a[1]+b[1])/2
        if a[0]==b[0]:
            if x > g['width']-160: x-=8; anchor='end'
            else: x+=8; anchor='start'
        else: y-=9; anchor='middle'
        overrides = {('workflow', 'reviewer', 'revise'): (1023, 735, 'start'),
                     ('workflow', 'human', 'revise'): (838, 720, 'start'),
                     ('workflow', 'limit', 'supply'): (320, 1170, 'middle')}
        x, y, anchor = overrides.get((g['id'], edge['source'], edge['target']), (x, y, anchor))
        pieces.append(f'<text x="{x}" y="{y}" font-size="14" text-anchor="{anchor}" fill="#53627d" stroke="white" stroke-width="5" paint-order="stroke">{esc(edge["label"])}</text>')
    for node in g['nodes']:
        fill,stroke=COLORS[node['kind']];x=node['x'];y=node['y'];w=node['w']
        pieces.append(f'<rect x="{x}" y="{y}" width="{w}" height="{H}" rx="13" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        pieces.append(f'<text x="{x+w/2}" y="{y+31}" text-anchor="middle" font-size="19" font-weight="600" fill="#182841">{esc(node["title"])}</text>')
        pieces.append(f'<text x="{x+w/2}" y="{y+57}" text-anchor="middle" font-size="14" fill="#53627d">{esc(node["subtitle"])}</text>')
    for i,note in enumerate(g['notes']):
        pieces.append(f'<text x="28" y="{g["height"]-50+i*24}" font-size="15" fill="#65748c">{esc(note)}</text>')
    pieces.append('</g></svg>')
    return '\n'.join(pieces)+'\n'

def mermaid(g):
    lines=['flowchart TD']
    for node in g['nodes']:
        label=html.escape(node['title']+' / '+node['subtitle'],quote=True)
        lines.append(f'    {node["id"]}["{label}"]')
    for edge in g['edges']:
        arrow='-.->' if edge['dashed'] else '-->'
        lines.append(f'    {edge["source"]} {arrow}|"{edge["label"]}"| {edge["target"]}')
    if g['id']=='lifecycle':
        contract=json.loads((OUT/'design_contract.json').read_text())
        present={(e['source'],e['target']) for e in g['edges']}
        for source,targets in contract['transitions'].items():
            for target in targets:
                if (source,target) not in present:
                    lines.append(f'    {source} -.-> {target}')
    return '\n'.join(lines)+'\n'

def build():
    (OUT/'diagrams').mkdir(parents=True,exist_ok=True)
    cards=[]
    for graph in GRAPHS:
        text=svg(graph)
        (OUT/'diagrams'/f'{graph["id"]}.svg').write_text(text)
        (OUT/'diagrams'/f'{graph["id"]}.mmd').write_text(mermaid(graph))
        cards.append(f'<section id="{graph["id"]}">{text}<p><a href="diagrams/{graph["id"]}.svg">打开 SVG</a> · <a href="diagrams/{graph["id"]}.mmd">Mermaid 源文件</a></p></section>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>多 Agent 图文创作 · 软件设计图册</title>
<style>*{box-sizing:border-box}body{margin:0;background:#edf1f8;color:#182841;font-family:"PingFang SC",sans-serif}header,main{max-width:1240px;margin:auto;padding:32px 20px}header{padding-bottom:8px}h1{font-size:32px;margin:12px 0}p{line-height:1.8;color:#53627d}nav{display:flex;gap:12px;flex-wrap:wrap}a{color:#355cb5}nav a{padding:10px 16px;background:white;border-radius:10px;text-decoration:none}section{background:white;border-radius:18px;margin:24px 0;padding:20px;box-shadow:0 4px 22px #1a34500a}svg{display:block;width:100%;height:auto}section p{margin:0;padding:8px}small{letter-spacing:2px;color:#7354bd}@media print{body{background:white}header{padding:0}nav{display:none}section{box-shadow:none;break-before:page;padding:0}main{padding:0}svg{max-height:245mm}section p{font-size:10px}}</style>
<header><small>SOFTWARE DESIGN / v0.2</small><h1>多 Agent 图文创作产品</h1><p>五层架构 · 四 Agent 协作 · 云端部署 · 任务状态 · Runtime Console<br>2026-09-20 · 设计方案，尚未实现；参数为建议配置及待测目标。</p><nav><a href="#architecture">01 总体架构</a><a href="#workflow">02 创作流程</a><a href="#deployment">03 云端部署</a><a href="#lifecycle">04 任务状态</a><a href="#runtime">05 Runtime Console</a><a href="README.md">设计文档索引</a></nav></header><main>'''+''.join(cards)+'</main></html>\n'
    (OUT/'DESIGN_ATLAS.html').write_text(page)

if __name__=='__main__':
    build()
