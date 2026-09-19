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
 dict(id='architecture', title='软件总体架构', subtitle='D1 · 模块化服务 + 持久化的四 Agent 工作流', width=1200, height=1120,
 nodes=[
 n('web',410,110,'M01 网页工作台','定位 / 素材 / 编辑 / 预览 / 导出','human'),
 n('api',410,270,'M02 业务 API','认证、权限、幂等、版本校验'),
 n('project',20,430,'M03 + M07 内容与版本','素材快照 / 用户稿 / 候选稿','data',340),
 n('queue',410,430,'M04 调度与任务队列','outbox → Redis / Celery'),
 n('worker',410,590,'M05 四 Agent 工作流','策划 → 写作 → 编排 → 审稿','agent'),
 n('model',860,590,'M06 模型网关','额度预留 / API / 计量','external',320),
 n('render',410,750,'M08 模板渲染与导出','固定模板 / PNG / ZIP'),
 n('data',20,910,'M09 PostgreSQL','项目 / 任务 / 检查点 / 事件','data',340),
 n('files',410,910,'M09 私有对象存储','原始图片 / 导出文件','data'),
 n('observe',860,910,'M09 运行观测','脱敏日志 / 指标 / 用量','data',320)],
 edges=[
 e('web','api','HTTPS / SSE',[(600,188),(600,270)]),
 e('api','project','素材与版本',[(410,309),(190,309),(190,430)]),
 e('api','queue','异步任务',[(600,348),(600,430)]),
 e('queue','worker','领取与续跑',[(600,508),(600,590)]),
 e('worker','model','服务端调用',[(790,629),(860,629)]),
 e('worker','render','确认版本',[(600,668),(600,750)]),
 e('project','data','业务持久化',[(190,508),(190,910)]),
 e('worker','data','检查点与状态',[(410,629),(375,629),(375,869),(190,869),(190,910)]),
 e('render','files','图片与清单',[(600,828),(600,910)]),
 e('model','observe','用量与错误',[(1020,668),(1020,910)])],
 notes=['私有网络：API、Worker、数据库及队列均在服务端；仅 HTTPS 网关对外。',
        '状态事件由 API 鉴权后提供给网页；模型密钥不下发。编号对应模块设计。']),
 dict(id='workflow',title='创作与返修流程',subtitle='D2 · 用户控制选题和最终版本；系统执行有界协作',width=1200,height=1660,
 nodes=[
 n('input',410,110,'填写需求与真实素材','账号定位 / 本次主题 / 图片','human'),
 n('plan',410,260,'策划 Agent · planner','3 个角度 + 素材缺口','agent'),
 n('select',410,410,'用户选择选题','持久化暂停，不占 Worker','human'),
 n('write',410,560,'写作 Agent · writer','标题 / 正文 / 来源编号','agent'),
 n('design',410,710,'编排 Agent · designer','模板 / 分页 / 配图','agent'),
 n('review',410,860,'审稿 Agent · reviewer','内容依据 / 标题兑现 / 版式','agent'),
 n('supply',20,410,'补充真实资料','更新快照后恢复请求节点','human',330),
 n('revise',850,860,'返修路由','文案 → writer；排版 → designer','service',330),
 n('limit',850,1110,'达到 2 轮自动返修上限','暂停，请用户处理问题','human',330),
 n('confirm',410,1110,'用户编辑与定稿','候选稿和差异，明确接受','human'),
 n('export',410,1320,'模板渲染与导出','有效审核版本 + 图文预览'),
 n('done',410,1470,'获得可发布素材','用户手动发布；不预测爆款','human')],
 edges=[
 e('input','plan','提交',[(600,188),(600,260)]),
 e('plan','select','资料充分',[(600,338),(600,410)]),
 e('plan','supply','资料不足',[(410,299),(185,299),(185,410)],True),
 e('select','write','确认',[(600,488),(600,560)]),
 e('write','design','候选稿',[(600,638),(600,710)]),
 e('design','review','稿件 + 排版',[(600,788),(600,860)]),
 e('review','confirm','通过',[(600,938),(600,1110)]),
 e('review','supply','缺少依据',[(410,899),(185,899),(185,488)],True),
 e('review','revise','有问题',[(790,899),(850,899)],True),
 e('revise','write','文案返修',[(1015,860),(1015,599),(790,599)],True),
 e('revise','design','排版返修',[(850,920),(820,920),(820,749),(790,749)],True),
 e('revise','limit','上限',[(1015,938),(1015,1110)],True),
 e('confirm','export','接受版本',[(600,1188),(600,1320)]),
 e('export','done','成功',[(600,1398),(600,1470)])],
 notes=['补料、返修上限和用户要求改稿：按服务端保存的 resume_node 恢复，见 FLOWS.md。',
        '导出失败只重试渲染；用户修改稿件后旧排版与审核失效，需重新检查。']),
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
        'SUCCEEDED 代表本次请求目标达成；full 流程需用户接受。导出任务有独立状态。'])
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
<header><small>SOFTWARE DESIGN / v0.1</small><h1>多 Agent 图文创作产品</h1><p>架构 · 协作流程 · 云端部署 · 任务状态<br>2026-09-20 · 设计方案，尚未实现；参数为建议配置及待测目标。</p><nav><a href="#architecture">01 总体架构</a><a href="#workflow">02 创作流程</a><a href="#deployment">03 云端部署</a><a href="#lifecycle">04 任务状态</a><a href="README.md">设计文档索引</a></nav></header><main>'''+''.join(cards)+'</main></html>\n'
    (OUT/'DESIGN_ATLAS.html').write_text(page)

if __name__=='__main__':
    build()
