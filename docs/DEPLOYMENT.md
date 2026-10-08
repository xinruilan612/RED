# 网站后端运行与迁移

Windows 本机运行请使用 [Windows 安装与启动](WINDOWS.md) 的 `.cmd` 入口，以下 shell 示例面向 macOS/Linux。跨平台启动器 `scripts/local_dev.py` 支持 `setup`、`doctor`、`start`，启动时同时管理 API 和 Worker。

适用于 v0.6。当前在本机 PostgreSQL 验证；尚未购买云服务、绑定域名或公网部署。前端布局沿用原 Demo。

## 环境与启动

使用 Python 3.12+ 和 PostgreSQL。项目根目录安装锁定依赖：

```bash
python3 -m venv runtime/venv
runtime/venv/bin/pip install -r requirements.txt
```

在已有 `.env` 保留 DeepSeek Key，增加以下配置（不要提交真实密码）：

```dotenv
DATABASE_URL=postgresql:///youji_operations
PUBLIC_ORIGIN=http://127.0.0.1:8765
```

创建本项目专用数据库后运行：

```bash
runtime/venv/bin/python -m backend.api
```

服务器网址必须与 PUBLIC_ORIGIN 完全一致。默认只监听本机。公网前需设置 HTTPS 域名、至少16位 REGISTRATION_INVITE、数据库最小权限用户、TLS 反向代理及服务托管，并完成单独部署验收。数据库连接信息与密钥仅在服务器。当前首次注册可绑定本浏览器旧 Demo Cookie 对应空间；不自动合并两个用户空间。

## 保留旧数据并迁移

先停止旧 Demo 写入，用 SQLite backup API 保存一致性快照。原文件不得删除。目标应为空的专用数据库：

```bash
runtime/venv/bin/python -m backend.migrate --source runtime/before-web-foundation-hotspot-review-demo.sqlite
```

迁移逐行核对原始表，保留确认状态、来源模式和 owner；失败回滚业务导入。重复运行对同一未变化目标逐行检查，目标产生新业务后拒绝再次覆盖。依赖表的建表操作可以保留，不影响原 SQLite。回退时停止新服务，使用原 SQLite 启动 backend.web；新站期间新增的数据不会自动回流到旧库。

新注册和重设密码要求 8–20 个字符，并同时包含英文大写与小写字母；不额外强制数字或符号。登录继续核验已保存的密码，因此旧规则下的账号仍可登录。

网站密码恢复使用注册时显示的一次性网站恢复码，重设后所有旧会话失效。网站没有短信/邮件发送服务，旧 Demo 的恢复码与网站恢复码不同。切勿把旧 backend.web 暴露公网。

## 数据库与测试

SQL 层保留有版本的业务聚合，并有 social_accounts/account_records 关系目录。PostgreSQL 短写事务使用事务咨询锁，网络和模型调用在事务外。此为小范围内测设计，不宣称已完成高并发优化。

```bash
TEST_DATABASE_URL=postgresql:///youji_operations PYTHONDONTWRITEBYTECODE=1 runtime/venv/bin/python -m unittest discover -s tests -v
node --check frontend/app.js
node --check frontend/operations.js
node --check frontend/account.js
node --check frontend/auth.js
node --check frontend/knowledge.js
git diff --check
```

数据库测试自动建立唯一的 youji_test_ 临时 schema，结束后清理；没有 TEST_DATABASE_URL 会跳过 PostgreSQL 集成测试，不能据此宣称数据库已验收。HTTP 测试需要允许监听本机端口。测试使用模型替身，不产生模型费用。

备份应覆盖数据库及 `.env` 的安全保管。可用 PostgreSQL 自带 pg_dump 导出到 runtime，恢复到单独测试库并核对后再用于线上回退。不要把凭证、数据库和运行日志加入 Git。

## 资料库与公开搜索

登录后进入“资料库”，上传 UTF-8 TXT、Markdown、文本型 PDF、Word DOCX 或粘贴资料。DOCX 与 PDF 正文在服务端解析，不调用模型；扫描 PDF 不做 OCR。每份最多 3 MB、10 万提取字符，PDF 最多 50 页。选择更新时创建新版本，移出后不再用于新检索。原文件及历史版本仍在私有数据库中保留审计；这是检索停用，不是彻底擦除个人数据。正式数据删除策略需在公网阶段补齐。

首版使用 BM25 中文关键词检索，不需要额外 embedding Key，不宣称语义相似检索。创作页可上传或从当前账号资料中选择最多 3 份文件；后端只把最多 3 段、每段不超过 400 字符的相关原文放入任务快照，保留文件名、版本和页码/段落号。真实模型启动前会提示每任务最多 20 次、160,000 Token、$0.20 预算以及每日 $0.50 上限；后端预留预算，超限停止且不自动重试。上传、解析和检索均不调用付费模型。

热点页提供百科背景资料（维基百科公开 API）与公开网页（Bing RSS 实验接口），关键词会发送给所选服务；搜索摘要不可作为已读正文。点击读取正文并保存后，由后端校验链接、读取文本并入库。网站或网络阻断可能导致失败，结果也可能不相关，需要人工筛选。公开网页读取不发送用户模型 Key、账号 Cookie 或资料正文；不读取需要登录的平台后台。任意 URL 的固定 IP 连接与固定搜索服务客户端分开，后者只允许 www.bing.com/search 与 zh.wikipedia.org/w/api.php，禁止重定向。百科正文通过其公开文本接口读取，保留文章来源 URL；百科用于背景知识，不标记为新闻或平台热度。相关接口说明：[MediaWiki Search](https://www.mediawiki.org/wiki/API:Search)、[TextExtracts](https://www.mediawiki.org/wiki/Extension:TextExtracts#API)。

上限：每账号100份有效资料，每份3 MB / PDF最多50页 / 10万提取字符；每次最多3个原文片段，每段400字符；每用户每小时30次搜索、30次网页读取、40次资料写入。网页来源读取仍由请求同步执行；创作后台队列、进度与恢复见 v0.7。公网流量增加前需补充分布式配额、后台任务与压测。

新增前端验证：`node --check frontend/knowledge.js`。角色适配文档更新后执行 `python3 scripts/sync_agent_cards.py`；机器契约 website_extension 与原创作四角色契约分开，Agent 自主联网仍禁用。

### 用户授权的创作前联网调查

新建真实 AI 任务时可勾选“启动时联网调查”，明确填写 1–2 个公开搜索词。后台 Worker 在两个分析角色执行前，调用现有免费 Bing RSS 搜索最多 2 次、读取候选网页最多 3 个；仅搜索词发送给搜索服务，不发送账号档案或上传文件。每个已读网页最多 400 字符的原文进入共享证据快照（最多额外 1,200 字符），保留 URL、读取时间、页面声明时间、正文哈希与位置。完整搜索线索只用于界面审计，不作为已读事实送入模型。角色不得从搜索排名推断平台热度；受众 observations 的原文引用须通过校验。

网络步骤自身不调用模型。未读到相关正文时，任务停在任何付费模型调用之前；接口失败或进程中断不自动重搜，刷新复用已保存记录。用户可检查失败信息，取消后调整搜索词新建任务。此功能走持久后台，旧同步执行接口不支持它；既有任务不会自动开启联网。

2026-09-30 实际免费网络探测：`新手护肤 洗脸 防晒`、`新手护肤`、`摄影技巧` 均未获得相关结果，备用公开搜索页面连接失败。此记录说明当前网络/免费搜索渠道尚未验证可稳定提供中文研究资料；不能标为小红书/抖音实时热榜已接通。平台权限及可靠搜索数据源仍需补齐；本轮没有使用付费搜索或真实模型调用。

## 核心迁移与模型路由

新增核心结构由 backend/migrations.py 顺序、事务升级并记录 checksum，已有迁移不可原地改写。先用 pg_dump 备份，再部署；不通过删除迁移记录强行降级。旧模块 bootstrap 保留兼容，新增核心表统一走 core_migrations。

可选 MODEL_ROUTES_JSON 示例：`{"research":{"model":"deepseek-flash","rate":0.0000012}}`。rate 为每 Token 的保守美元费用上限，改模型前需核对供应商价格；未配置阶段沿用当前默认。新任务固化路由，已创建任务不因环境改变而偷偷换模型。API Key 仍只留服务器环境。新供应商需实现适配器与相同契约测试，不承诺任意模型即插即用。替身测试不访问收费接口。

## v0.7 独立后台 Worker

网站与 Worker 是两个进程，共用同一个 DATABASE_URL 与模型配置。必须分别启动：

```bash
runtime/venv/bin/python -m backend.api --port 8765
runtime/venv/bin/python -m backend.worker
```

网页“执行下一步，看结果”只执行一个阶段并暂停；联网调查独立成步，受众与素材两分支合为一个分析阶段。策略、提纲、开头、标题、正文、审核分别停下展示结果。“连续运行到人工处理”是另外的显式入口。两者均事务入队，关闭标签页不会停止正在执行的 Worker。暂停等待当前节点保存；取消阻止后续产物提交，但已发出的模型请求仍可能产生费用。Worker 每次只领取一个任务，角色两支并行；多个 Worker 通过数据库租约和 fencing token 避免重复提交。Worker 宕机后重启，过期租约最多约30秒后重新领取。关闭电脑时任务不会执行，开机并启动服务后恢复。生产环境应由进程管理器守护两个进程。

LangGraph 1.2.11 + PostgreSQL checkpointer 3.1.2 在同数据库持久化检查点，SQL runtime_nodes 与业务状态同事务提交，解决“业务已写入但检查点未写入”的重放窗口。已收到的模型响应可复用；供应商请求发送后、收到响应前进程丢失，系统无法保证供应商执行恰好一次，明确 blocked / 用量未知，不盲目再次收费。暂停/错误/人工操作后点击后台继续；用量未知需先人工核对，目前没有自动对账或绕过入口。

本机兼容 SQLite 使用独立 `.checkpoints` 文件；生产使用 PostgreSQL。检查点表由锁定版本的库自行迁移，启动时以会话锁保护；升级库前备份数据库。没有把检查点当作长期记忆或批准依据，人工确认仍事务核对指定稿件、审核、快照和哈希。旧同步接口保留无后台任务的兼容测试路径；正式网页均走后台队列。


## 2026-09-30 实验参考预算

用户明确希望约 0.30 元写 3 轮，金额与轮数均为软目标，超过只提示、不拦截。当前未完成流程计为第 1 轮，续跑、返修及恢复子任务共享原轮次。通过 `backend.testing_budget.initialize` 显式启用账号级持久记账，含指定旧任务费用，不按天刷新，不允许重复初始化覆盖或清零。新迁移版本 5 记录参考金额、轮次及调用预留。

当前估价限定 deepseek-flash，按官方高峰价输入 2 元/百万 Token、输出 8 元/百万 Token，不假定缓存折扣；价格依据：https://api-docs.deepseek.com/zh-cn/quick_start/pricing/ 。账本估算不等于供应商账单。未决调用按输入 UTF-8 字节加余量和最大输出预估占用，返回后按输入/输出用量结算；未知用量保守占用。预估与调用台账在同一事务，金额或轮数超过目标不阻止新调用。

创作 Token 安全上限从 40,000 调为 80,000，原 16 次调用、任务/日美元安全上限继续适用。约 3 轮是期望，实际费用受输入和返修影响。没有触发自动收费测试。

## 2026-10-08 显式实验硬预算

需要人民币硬上限时，由管理员对指定owner调用 `backend.testing_budget.initialize(store, owner, 5, hard_limit=True)`。需先由正常启动流程应用迁移8；不要直接修改旧迁移。省略hard_limit保留原软目标。硬模式不可通过重复初始化降级或清零；轮数仍为参考目标，人民币金额才是硬限。所有本轮调用须经同一数据库、同一owner的Calls入口，创作、返修、恢复与明确授权的对照共享。

每次请求前在事务锁内检查已计入费用和最高费率保守预留；未知用量不释放预留，已失败未知用量会阻断owner的新收费调用。费率仅支持deepseek-flash，按输入2元/百万、输出8元/百万（2026-10-08官方峰值）估算，模型或价格变化必须重新核对。账本不是供应商账单，不约束项目外部消费。实际本轮记录见[第一天验收](validation/DAY1_REVIEW_RECOVERY_20261008.md)。

2026-10-08 五次改稿配套：当前创作最多 20 次模型调用、160,000 Token、默认每任务 $0.20，每日仍 $0.50。初稿与每次改稿在审核后等待用户，不自动连续改完五次；所有已有用量保留。以上是上限，先达到的限制优先生效。


## MIT 图卡模板渲染（2026-10-09）

新图卡使用固定版本的本地 HTML/CSS，通过 Playwright Chromium 渲染；不调用图片生成模型，不需要外网字体。先安装 requirements.txt，再用同一虚拟环境执行：

    runtime/venv/bin/python -m playwright install chromium

macOS 有可用的 Google Chrome 时可复用本机浏览器；Linux/Windows 使用 Playwright Chromium。也可用环境变量 YOUJI_CHROMIUM_EXECUTABLE 指定部署者管理的浏览器绝对路径。Linux 需按 Playwright 提示安装系统依赖。浏览器必须由 API 进程所在的运行用户访问。缺少渲染器应报错，不把纯文案包冒充图卡生成成功。

升级前按本文件备份 PostgreSQL；新增模板目录、轮换位置和稿件选择使用追加式核心迁移，保留已确认正文及旧媒体版本。模板代码与许可在 backend/vendor/xhs_article，使用与人工验收见 [图卡模板说明](MEDIA_TEMPLATES.md)。

## 本地看图交互试用

追加核心迁移 10 建立本地图像调用台账，启动前备份数据库。Ollama 与 API 在同一台机器，模型固定为 qwen3-vl:4b；没有服务时普通模板预览和下载仍可使用。安装、使用及边界见 [本地看图交互说明](MULTIMODAL_TRIAL.md)。
