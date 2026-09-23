# 有迹 · 热点驱动的博主运营助手

无 API Key 的独立本地体验：先看 [启动独立演示](START_DEMO.md)。该入口使用单独演示数据库与会话，不读取作者的 `.env`。

产品新方向：面向小红书、抖音，将选题发现、四 Agent 创作、版本评审、人工审核与发布、指标回流、历史学习连成运营闭环。

**当前可用：v0.9 服务推广闭环、可解释运营实验、账号网站、资料库、公开检索与持久多 Agent 后台（本机验证，尚未公网部署）。**

v0.9 新增“接单推广”：在当前社媒账号下保存版本化服务档案和作品记录，服务名称默认公开，其他字段只有明确允许公开且作品确认可公开后才能进入推广简报。简报携带服务/作品版本进入原有创作与发布流程；人工发布后可回填匿名咨询，区分明确关联、多触点和来源未知，再用确定性规则生成下一轮内容建议。真实人工记录与模拟演示数据分开统计；缺失反馈不记为零，咨询修正会使依赖复盘失效。系统不自动私信、不管理订单或支付，也不把咨询写成成交、收入或因果证明。

项目自身提供“一句话极速出稿”：一次生成初稿、一次独立审核；重要内容可切换到完整多 Agent 专业流程。它还会用可解释 UCB1 在账号历史上规划下一次可控实验，把单次生成继续延伸到发布、指标回流和跨期学习。算法、证据边界与演示路径见 [核心算法创新](docs/ALGORITHM_INNOVATION.md)。

新增 FastAPI、用户名/密码登录、一次性恢复码、PostgreSQL 与 SQLite 兼容存储及逐行迁移校验。启动与迁移见 [部署说明](docs/DEPLOYMENT.md)。下文 v0.5 命令保留为旧 Demo 的兼容入口，当前网站应运行虚拟环境中的 `python -m backend.api`。

新入口增加资料库：上传 TXT/Markdown/文本型 PDF 或粘贴原文，保存版本与页码，按账号检索，创建任务时可把片段送入四角色。首版使用 BM25 中文关键词检索，尚未接语义向量模型。热点页可以手动搜索公开网页、读取正文并保存；搜索摘要不作为已读证据。搜索提供百科背景资料（维基百科公开 API）与公开网页（Bing RSS 实验接入），可能超时或返回不相关结果；不是小红书/抖音实时热榜。

**v0.5 功能：** 新增本周运营、账号与历史，保留原五页。四个创作角色接入账号上下文，新增独立的规则分析角色。页面默认免费模拟模式；DeepSeek 需用户显式选择后才调用。

## 建议先体验

打开 http://127.0.0.1:8765/#overview → 注册并保存一次性网站恢复码 → 点击“体验穿搭演示账号” → 数据复盘 → 分析最新作品 → 经验记忆中接受建议 → 本周运营生成并采用周计划。演示数据始终隔离，不代表真实增长。

接单推广可从侧栏进入：新建服务并勾选允许公开字段 → 添加且确认可公开的作品 → 填写客户问题及其来源 → 生成推广简报 → 带入原有创作、审核与发布 → 回填匿名咨询 → 生成观察窗口复盘。没有真实咨询时可以用演示账号验证流程，但必须保留演示标识。

顶部切换当前账号；账号与历史页面可维护定位、导入真实旧作品、调整栏目/流量类型、查看改稿差异。新版使用网站用户名和密码登录，账号数据保存在服务端 PostgreSQL；服务尚未公网部署。首次注册时可选择绑定当前浏览器的旧 Demo 空间。旧 Demo 恢复码只适用于旧服务，不是网站恢复码。

分析角色首版使用确定性统计规则，不调用模型。比较同账号、平台、形式、流量类型、来源和窗口；不足 3 篇可比历史不展示基线。3 篇仅为展示门槛，不保证统计充分性。待办根据持久化发布时间生成，需打开运行中的本机服务查看；不包含后台采集或通知。

## 可以体验的运营闭环

1. 在“热点与选题”选择示例，或导入带链接和观察时间的选题；按平台/关键词筛选。
2. 进入创作工作台，选小红书笔记或抖音脚本、选择顶部账号并填写素材，运行原有四 Agent 流程。
3. 审核、返修、版本对比、复审，人工确认准确版本。
4. 点击“进入发布中心”，确认稿件与账号。模拟稿可演练发布；真实 AI 稿可在自行发布后回填平台链接。
5. 在数据复盘按作品与观察窗口录入指标；未知留空，修正保留历史快照。
6. 生成带证据的历史比较；有可比依据时产生候选实验建议，接受或拒绝；接受后供同平台、同账号、同运行模式的后续创作读取，可以撤销。

| 能力 | 当前实现 | 尚未接通 |
| --- | --- | --- |
| 热点与选题 | 公开搜索与正文入库、固定示例、用户来源导入、时间与过期标识、筛选、选入创作 | 实时热榜、自动抓取与热度排序 |
| 创作 | 极速模式为 1 次生成 + 1 次独立审核；专业模式为四角色、五阶段；支持 DeepSeek 或免费模拟 | 视频成片、图文渲染 |
| 版本评审 | 返修、手动改稿、版本对比、复审与准确版本确认 | 独立完整稿件的随机对照实验 |
| 人工审核与发布 | 版本绑定的发布确认、模拟演练、真实稿人工发布回填 | 官方平台自动发布与回执核验 |
| 指标回流 | 用户录入、缺失值、窗口与修订快照；演示数据隔离 | 平台自动取数、CSV 导入 |
| 历史学习 | 指标计算、描述性复盘、经验接受/撤销/失效、后续上下文读取 | 因果结论、在线训练、自动优化权重 |

用户确认首期为小红书、抖音，**暂不接入 Postiz**。指定参考：[Klaudiusz321/social-media-agents](https://github.com/Klaudiusz321/social-media-agents)。后续完整目标见 [技术方案](docs/design/ARCHITECTURE.md#运营闭环-v04-技术提案) 与 [推进计划](docs/design/MIGRATION.md#运营闭环-v04-推进计划)；正式网站已接 LangGraph、PostgreSQL 检查点和独立 Worker，旧同步路径保留兼容。

沿用已有文件夹，协作规则为根目录 AGENTS.md；不建立另一套 AGENT.md 或 MVP README。

## 打开方式

项目支持 Python 3.12+ 的 Windows、macOS 和 Linux。移动端和纯浏览器设备作为客户端访问运行中的网站，不直接运行 Python 后端。

先在项目目录创建虚拟环境并安装依赖：

```powershell
# Windows PowerShell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```bash
# macOS / Linux
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

开发体验可以使用默认 SQLite；父目录会在首次启动时自动创建。正式网站仍建议按部署说明使用 PostgreSQL。

启动 API 和 Worker：

```powershell
# Windows PowerShell，分别在两个终端运行
.\.venv\Scripts\python.exe -m backend.api --port 8765
.\.venv\Scripts\python.exe -m backend.worker
```

```bash
# macOS / Linux，分别在两个终端运行
.venv/bin/python -m backend.api --port 8765
.venv/bin/python -m backend.worker
```

然后打开 http://127.0.0.1:8765/ 。首次环境与数据库安装见 [部署说明](docs/DEPLOYMENT.md)。保持终端运行；关闭后用相同命令再次启动。更换端口时也要同步修改 `.env` 的 PUBLIC_ORIGIN。

## 填写 DeepSeek Key

源码不包含作者的 `.env` 或密钥。需要真实模型时，在项目根目录自行创建 `.env`（Git 克隆可参考 `.env.example`），按部署说明填写 `DEEPSEEK_API_KEY` 和本机配置，再启动普通 API 与 Worker。新建创作时选择“真实 AI · DeepSeek”，旧任务保持原运行方式。密钥不提交 Git，不发送到浏览器。`scripts/start_demo.py` 是无密钥隔离演示，刻意不读取 `.env`，重启该入口也不会启用付费模型。

完整步骤、限制与图片/PDF 扩展方式见 [DeepSeek 使用说明](docs/DEEPSEEK_SETUP.md)。

## 可以测试什么

1. 填写主题、读者、风格和素材，选择演示场景，点击“创建工作流”。
2. 点击“后台运行到人工处理”，可暂停或关闭页面，Worker 会继续到人工处理。点击角色或创作阶段查看输入和产物。
3. 选择“审核发现问题”场景：后台会自动返修并复审，最终等待你确认；你也可编辑后再次复审，旧版本保留。
4. 选择“资料不足”场景且不填素材：流程会要求你补充，再重新分析。
5. 最后由你确认准确版本，下载 Markdown 文稿。确认后可进入发布中心；当前支持演练或人工发布回填，没有自动发帖。

普通网站的任务存储由 `DATABASE_URL` 配置决定；干净克隆默认使用本地 SQLite，不附带 PostgreSQL 服务或作者数据。需要 PostgreSQL 时按部署说明自行安装和配置。独立演示固定使用 `runtime/review-demo/demo.sqlite`。清除 Cookie 后重新登录同一网站用户即可读取该数据库里的记录；不要删除数据库来重启服务，`runtime/` 不应提交或分享。

## 目前的边界

模拟模式使用固定模板；真实模式由 DeepSeek 执行四角色，正常首次 8 次请求，改稿后复审。旧 backend.web 不提供资料库与联网搜索；新 backend.api 已接资料导入、原文检索与主动公开搜索。平台自动取数、CSV 导入、图片/OCR、图片生成和图文包导出仍未实现。运营指标支持逐条表单录入。审核不代表事实、原创或平台合规已独立验证。

旧 backend.web 服务只绑定本机回环地址，不可直接部署公网。新 backend.api 已完成 FastAPI、网站账号、PostgreSQL 和持久队列本机联调，公网部署仍待推进。前端沿用原生 HTML/CSS/JS，没有重写成 Next.js。

- [实际开发进度](docs/IMPLEMENTATION_STATUS.md)
- [本轮验证记录](docs/WEB_DEMO_VALIDATION.md)
- [设计入口](docs/design/README.md)
- [Agent 规范](docs/agents/00_overview_and_all_agents.md)

## 开发验证

```bash
TEST_DATABASE_URL=postgresql:///youji_operations PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
node --check frontend/app.js
node --check frontend/operations.js
node --check frontend/account.js
node --check frontend/auth.js
node --check frontend/knowledge.js
git diff --check
```

集成测试在临时本机端口启动 HTTP 服务，需要允许监听回环端口，不请求外网。当前测试不调用收费模型。

仓库的跨平台 CI 在 Windows、macOS、Linux 上使用 Python 3.12 运行兼容性套件，并在独立 PostgreSQL 服务上运行完整数据库套件。PostgreSQL 服务本身可以位于本机、容器、WSL 或远程服务器；应用代码不依赖某一种宿主方式。

## 旧 Demo 的兼容入口与存档

改动前基线 a62c349。源码和原有两份 Demo 数据库已在已有 runtime/ 中存档，不含 .env。存档与验证见 [验证记录](docs/WEB_DEMO_VALIDATION.md)。

以下仅用于回看旧版演示，不能与新版网站同时占用 8765 端口；新版资料库和搜索使用上方 backend.api 入口。旧演示数据库保留原有历史：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m backend.web --port 8765 --db runtime/hotspot-review-demo.sqlite
```

旧服务打开 http://127.0.0.1:8765/#overview 查看演示首页。backend.web 默认启动命令会打开 runtime/demo.sqlite，两个旧数据库的历史互不合并。所有记录按本地空间隔离。保留原 Cookie 或使用提前保存的恢复码，可访问原空间；不同数据库之间不合并。

## 核心后台执行（v0.7）

正式网站在 FastAPI + PostgreSQL 上运行；启动网站后还需用同一虚拟环境独立启动 `python -m backend.worker`。网页提交任务后可关闭，Worker 继续；重启 Worker 后从数据库检查点恢复。受众和研究分支、创作各阶段独立落盘，人工确认绑定精确版本。Model Router 为每次新模型调用记录用量、模型和来源，未知用量不自动重发。

部署与已知边界见 [部署说明](docs/DEPLOYMENT.md#v07-独立后台-worker)，阶段验收见 [实施记录](docs/IMPLEMENTATION_STATUS.md)。默认模拟模式不收费；没有接通真实小红书/抖音账号发布或私有数据同步。
