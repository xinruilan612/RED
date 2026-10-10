# 网站后端运行与迁移

> **当前实现与实际验收**：[2026-10-10 状态说明](CONNECTED_CREATOR_STATUS.md)。本地 RAG、案例研究与多模型配置已接入；本人小红书账号已接入本机 MCP 有限轮询，非全量或实时推送。当前验收在 8775 独立环境，默认数据库存在 SCHEMA_TOO_NEW 版本不匹配，不能称默认启动已通过。

> **当前需求（2026-10-10，已授权实施）**：[小红书连接、研究资料库与多模型](design/CONNECTED_CREATOR_REQUIREMENTS.md)。新增能力以该基线为准；下文旧阶段限制和完成记录保留其日期与实现边界，不作为拒绝新需求的依据。

云端前置文件、条件清单与 Linux 内测交接见 [云部署准备](PRODUCTION_PREPARATION.md)。这些模板尚未在云服务器执行，不代表公网部署完成。

Windows 本机运行请使用 [Windows 安装与启动](WINDOWS.md) 的 `.cmd` 入口，以下 shell 示例面向 macOS/Linux。跨平台启动器 `scripts/local_dev.py` 支持 `setup`、`doctor`、`start`，启动时同时管理 API 和 Worker。

下文基础配置始于 v0.6，新增能力与本轮实际环境按页首当前状态说明核对。当前在本机 PostgreSQL 验证；尚未购买云服务、绑定域名或公网部署。前端布局沿用原 Demo。

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

首版使用 BM25 中文关键词检索，不需要额外 embedding Key，不宣称语义相似检索。创作页可上传或从当前账号资料中选择最多 3 份文件；后端只把最多 3 段、每段不超过 400 字符的相关原文放入任务快照，保留文件名、版本和页码/段落号。真实模型启动前会提示每任务最多 16 次、80,000 Token、$0.10 预算以及每日 $0.50 上限；后端预留预算，超限停止且不自动重试。上传、解析和检索均不调用付费模型。

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


## 2026-10-10 新增配置与启动前检查

本地语义模型按 [本地 RAG 部署](LOCAL_RAG.md) 显式安装；默认不开外部收费向量服务。模型与搜索设置页支持用户 BYOK 与预算配置，平台 DeepSeek Key 仍只保存在服务端。公网运行需要配置 MODEL_CREDENTIAL_KEY 加密主密钥并妥善备份，不能将密钥或连接串写进文档、日志或资料库；本轮未完成公网验收。

先检查目标端口对应的实际 worktree、代码版本及数据库迁移版本。当前本机8765与原默认数据库属于其他worktree的较高版本；当前checkout访问原默认库会触发SCHEMA_TOO_NEW。不要通过删除迁移记录、降级数据库或改动已应用SQL来绕过保护。本轮8775独立schema仅用于隔离验收，正式切换与原默认库兼容尚待明确迁移路线。


## 后续统一Worker与网页重连（2026-10-10）

scripts/xhs_sync.py worker 现调用统一Worker，处理创作、研究和账号同步；按 [本机同步运行说明](XHS_LOCAL_SYNC.md) 与serve使用同一隔离schema。提交4876323后API8775和统一Worker已重启。只启动MCP连接器不能执行项目后台研究或创作。

已绑定账号的二维码重连在网页进行，发起时先暂停同步，由本人手机扫码；原绑定身份继续校验。二维码已实际生成且用户扫码重连成功；本人同步已恢复，站内案例研究3份文字描述已实际入库、下载报告并检索召回。

本人已保存笔记可显式导入RAG，评论分页只读取已持久记录；案例普通编辑受保护，专用编辑保留版本，研究报告按冻结版本导出。一次授权真实模型验收使用8次调用、15378 tokens、保守账本$0.0184536，未超过单次授权$0.05且未发布。详见 [当前验收状态](CONNECTED_CREATOR_STATUS.md)，不将本次结果外推为所有模型已验证。


### 创作者指标读取器

用户授权定时读取已有权限的创作者首页与笔记管理后，新增 `scripts/xhs_creator_reader.py`。运行依赖本机 `runtime/mediacrawler/.venv` Python/Playwright环境（Playwright 1.61.0及Chromium），不依赖MediaCrawler采集代码；固定依赖见 `requirements-creator.txt`，环境恢复命令见下方本机同步指南。首次由管理员校验并私有绑定 `source_id` 与 `creator_account_id`，使用已有MCP会话bootstrap独立profile，按需添加 `--login` 由本人手动登录。Worker正常执行不发起手动登录、不自动申请权限、不发布，原MCP评论通道独立。具体命令、私有文件位置与边界见 [本机同步](XHS_LOCAL_SYNC.md)。

真实网页触发统一Worker后，首页7日汇总及5篇笔记观看数已完成PostgreSQL入库、API返回和页面逐值核对；16:12:07成功、下轮16:27:07。账号汇总不等于单篇累计流量，单篇曝光未知保留null，原始展示与实际采集时间保留，平台更新时间不伪造。读取器仅校验默认近7日、读取稳定快照，不切换周期；Cookie源fingerprint变化可重新bootstrap，独立profile过期按需 `--login`。仅首屏最多30张创作者笔记，非秒级同步。完整证据见私有 `runtime/connected_acceptance/creator-integration.json` 与 [当前验收状态](CONNECTED_CREATOR_STATUS.md)；新增代码的全量回归计数另记，不能沿用上一阶段622项结果。
