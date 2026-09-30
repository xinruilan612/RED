# 网站后端运行与迁移

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

首版使用 BM25 中文关键词检索，不需要额外 embedding Key，不宣称语义相似检索。创作页可上传或从当前账号资料中选择最多 3 份文件；后端只把最多 3 段、每段不超过 400 字符的相关原文放入任务快照，保留文件名、版本和页码/段落号。真实模型启动前会提示每任务最多 16 次、40,000 Token、$0.10 预算以及每日 $0.50 上限；后端预留预算，超限停止且不自动重试。上传、解析和检索均不调用付费模型。

热点页提供百科背景资料（维基百科公开 API）与公开网页（Bing RSS 实验接口），关键词会发送给所选服务；搜索摘要不可作为已读正文。点击读取正文并保存后，由后端校验链接、读取文本并入库。网站或网络阻断可能导致失败，结果也可能不相关，需要人工筛选。公开网页读取不发送用户模型 Key、账号 Cookie 或资料正文；不读取需要登录的平台后台。任意 URL 的固定 IP 连接与固定搜索服务客户端分开，后者只允许 www.bing.com/search 与 zh.wikipedia.org/w/api.php，禁止重定向。百科正文通过其公开文本接口读取，保留文章来源 URL；百科用于背景知识，不标记为新闻或平台热度。相关接口说明：[MediaWiki Search](https://www.mediawiki.org/wiki/API:Search)、[TextExtracts](https://www.mediawiki.org/wiki/Extension:TextExtracts#API)。

上限：每账号100份有效资料，每份3 MB / PDF最多50页 / 10万提取字符；每次最多3个原文片段，每段400字符；每用户每小时30次搜索、30次网页读取、40次资料写入。网页来源读取仍由请求同步执行；创作后台队列、进度与恢复见 v0.7。公网流量增加前需补充分布式配额、后台任务与压测。

新增前端验证：`node --check frontend/knowledge.js`。角色适配文档更新后执行 `python3 scripts/sync_agent_cards.py`；机器契约 website_extension 与原创作四角色契约分开，Agent 自主联网仍禁用。

## 核心迁移与模型路由

新增核心结构由 backend/migrations.py 顺序、事务升级并记录 checksum，已有迁移不可原地改写。先用 pg_dump 备份，再部署；不通过删除迁移记录强行降级。旧模块 bootstrap 保留兼容，新增核心表统一走 core_migrations。

可选 MODEL_ROUTES_JSON 示例：`{"research":{"model":"deepseek-flash","rate":0.0000012}}`。rate 为每 Token 的保守美元费用上限，改模型前需核对供应商价格；未配置阶段沿用当前默认。新任务固化路由，已创建任务不因环境改变而偷偷换模型。API Key 仍只留服务器环境。新供应商需实现适配器与相同契约测试，不承诺任意模型即插即用。替身测试不访问收费接口。

## v0.7 独立后台 Worker

网站与 Worker 是两个进程，共用同一个 DATABASE_URL 与模型配置。必须分别启动：

```bash
runtime/venv/bin/python -m backend.api --port 8765
runtime/venv/bin/python -m backend.worker
```

网页“后台运行到人工处理”只事务入队，关闭标签页不会停止 Worker。暂停等待当前节点保存；取消阻止后续产物提交，但已发出的模型请求仍可能产生费用。Worker 每次只领取一个任务，角色两支并行；多个 Worker 通过数据库租约和 fencing token 避免重复提交。Worker 宕机后重启，过期租约最多约30秒后重新领取。关闭电脑时任务不会执行，开机并启动服务后恢复。生产环境应由进程管理器守护两个进程。

LangGraph 1.2.11 + PostgreSQL checkpointer 3.1.2 在同数据库持久化检查点，SQL runtime_nodes 与业务状态同事务提交，解决“业务已写入但检查点未写入”的重放窗口。已收到的模型响应可复用；供应商请求发送后、收到响应前进程丢失，系统无法保证供应商执行恰好一次，明确 blocked / 用量未知，不盲目再次收费。暂停/错误/人工操作后点击后台继续；用量未知需先人工核对，目前没有自动对账或绕过入口。

本机兼容 SQLite 使用独立 `.checkpoints` 文件；生产使用 PostgreSQL。检查点表由锁定版本的库自行迁移，启动时以会话锁保护；升级库前备份数据库。没有把检查点当作长期记忆或批准依据，人工确认仍事务核对指定稿件、审核、快照和哈希。旧同步接口保留无后台任务的兼容测试路径；正式网页均走后台队列。
