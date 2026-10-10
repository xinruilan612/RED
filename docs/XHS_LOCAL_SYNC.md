# 本机小红书只读同步

> **2026-10-10 改版阅读顺序**：先读[正式需求](design/CONNECTED_CREATOR_REQUIREMENTS.md)与[六阶段进度及代码核对](CONNECTED_CREATOR_STATUS.md)。主线为主题/产品资料、可选联网与 RAG、四 Agent、对话改稿、发布或导出、选定公开笔记评论反馈。下文旧范围及“已实现/未实现”仅代表相应历史阶段，不作为当前可用性证明；冲突按新需求处理，不新增平台或后台。本轮只改说明，运行时 Prompt、业务、数据库与依赖未改。

当前用户网页入口：`http://127.0.0.1:8775/#connections`。使用已有网站登录会话，进入“账号数据连接”。页面可暂停、恢复、立即核对；自动周期为 15 分钟。手动核对至少间隔 60 秒。不是秒级实时，也不保证全部历史和全部评论。

## 已安装的本机组件

上游：[xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp)，Apache-2.0，v2.5.5 darwin-arm64。二进制 SHA256：`fad3633fda4a8060e66e2941bc8fc5460326c7cb4e58a32485a9e2c9408e95a8`。安装和登录会话位于忽略提交的 `runtime/xhs-local`，不随 Git 交付，连接器监听 `127.0.0.1:18061`。

本项目客户端按用途白名单访问登录状态/二维码、本人资料/笔记详情和已授权有限案例搜索接口；不调用发布、关注、互动工具。开始和结束均检查平台身份，笔记作者必须与绑定身份一致。连接器控制令牌和 Cookie 不进入网站响应、日志或模型上下文。登录由本人完成，遇验证码或访问限制停止处理。

## 本机重启

以下命令在项目根目录执行，分别保持进程运行。现有服务还在运行时不要重复启动，不要关闭其他工作区的服务。未安装开机自启。休眠或退出进程期间不会同步，重启后保留历史。

```sh
runtime/venv/bin/python scripts/xhs_sync.py bridge
runtime/venv/bin/python scripts/xhs_sync.py serve --schema youji_connected_acceptance_20261010
runtime/venv/bin/python scripts/xhs_sync.py worker --schema youji_connected_acceptance_20261010
```

上面 serve 和 worker 使用明确的隔离 PostgreSQL schema，避免误接默认库的较新版本；现有 `.env` 不改。三个命令分别运行本机连接器、网页和统一工作进程。scripts/xhs_sync.py worker 已统一使用 backend.worker.Worker，处理创作、研究及本人同步，数据库租约防止重复领取；不要另启动只负责同步的旧循环而遗漏创作或研究任务。

首次绑定由本机管理员执行，用户必须已经在连接器完成登录。填写网站用户名；有多个小红书档案时必须明确 `--account-id`。不会因浏览器里存在共享登录就让任意网站用户认领。

```sh
runtime/venv/bin/python scripts/xhs_sync.py bind --username 网站用户名 --account-id 项目账号ID --schema youji_connected_acceptance_20261010
runtime/venv/bin/python scripts/xhs_sync.py status --username 网站用户名 --account-id 项目账号ID --schema youji_connected_acceptance_20261010
```

已绑定账号可在网页发起二维码重连：先暂停原同步并撤销租约，再显示官方登录二维码，由本人手机扫码后恢复。二维码已生成且本人扫码成功，随后站内研究完成3份视频文字描述采集、报告下载与检索。首次任意账号自助绑定与多租户会话池仍未实现。恢复不会改变原绑定身份。换号需人工审核迁移，不能覆盖历史。

## 数据与验证边界

原MCP通道读取前 5 篇主页返回笔记，最多 100 条/篇已加载评论；不强制滚动加载评论。新增创作者DOM通道单独读取首页周期汇总及笔记管理可见指标，不改变评论采集。无值保留 null，原始显示数字保留用于核对，不能把“1.2万”虚构成精确数字。按 owner/account_id 隔离，笔记与评论唯一键去重，内容哈希比较变化，轮次快照保留审计。采集时间可核对；平台没有提供准确更新时间时不伪造延迟。

同步结果单独存储，不冒充人工已确认经验或平台官方数据。用户显式选择本人笔记并确认用途后，可导入表达参考案例供RAG使用，正文hash未变化会复用已有版本；评论不随之进入模型。已持久评论以每页50条查看，仅表示历史已观察记录，不表示平台全量。当前网页已绑定本人真实账号；这不表示公开部署、第三方多账号托管或取得平台官方 API 许可。真实内容未纳入 Git，测试数据均为合成。


## 案例研究与当前验证

在“案例研究”选择xhs_local站内视频来源，最多2组查询、3篇文字描述，按最多点赞及半年内范围查找。只取得视频文字描述与可见互动，不是视频音轨/字幕转写；第三方案例仅用于表达参考。本轮扫码重连后，14:44:38发起的站内研究已完成3份视频文字描述及可见互动入库，4164字节报告已实际下载，3份资料可检索召回。

本人笔记到RAG桥接、评论分页、重连隔离、案例版本保护均有针对测试；真实资料→四角色闭环在单独$0.05授权内完成8次调用，停在人工确认。阶段测试计数及预算证据统一见 [当前验收状态](CONNECTED_CREATOR_STATUS.md)。

## 创作者首页与笔记管理读取（2026-10-10 增补）

用户已明确授权定时读取创作者首页和笔记管理。`scripts/xhs_creator_reader.py` 在独立浏览器profile中工作；本机管理员先核对已绑定的24位 `source_id` 和首页显示的 `creator_account_id`。私有绑定与profile保存在忽略提交的 `runtime/xhs-local/creator/<source_id>/`，绑定不可静默换号，文件权限限制为本机用户。凭据、个人指标原始记录和浏览器会话不进入Git。

当前实际采集解释器是 `runtime/mediacrawler/.venv/bin/python`，Playwright 1.61.0及Chromium已安装；只复用该Python/Playwright环境，不依赖MediaCrawler采集代码。新环境可按固定依赖恢复（本机已安装，无需重复安装）：

```sh
python3 -m venv runtime/mediacrawler/.venv
runtime/mediacrawler/.venv/bin/python -m pip install -r requirements-creator.txt
runtime/mediacrawler/.venv/bin/python -m playwright install chromium
```

环境准备后，可按以下方式绑定并核对（替换占位值，不提交真实身份）：

```sh
runtime/mediacrawler/.venv/bin/python scripts/xhs_creator_reader.py --source-id 平台24位ID --bind-account 首页小红书账号号
```

读取器可从已绑定MCP会话bootstrap现有登录到独立profile；源Cookie文件fingerprint变化时可重新bootstrap。独立profile过期或该会话不足以登录时，管理员按需在上述命令加 `--login`，由本人完成手动登录。正常Worker调用不加 `--login`，不自动申请数据权限、不发布、不修改评论。前后均检查公开账号ID与创作者首页账号号；身份不符、验证码、访问限制或未知指标图标时停止本次读数，错误独立显示，原MCP评论同步通道保持独立。

账号汇总保留 `period_start/end`、`period_days`、`period_display`，包括曝光、观看、封面点击率、视频完播率、互动、净涨粉、新增关注、取消关注、主页访客。笔记列表只读首屏最多30张当前DOM卡片，按已核验SVG识别观看、评论、点赞、收藏、分享，单篇曝光仍为null；不按列位置猜测字段。百分比存百分数值，净涨粉可为负值；缩写数值只保留原始展示，不伪造成精确值。读取器不点击周期切换，只校验默认选中近7日并读取稳定快照。账号近7日汇总不能与单篇累计指标混用；`source_method=creator_browser_dom`、`source_updated_at=null`，不宣称官方API数据或准确延迟。

真实读取器已于2026-10-10 16:06:33（北京时间）取得10-03至10-09汇总：曝光25、观看3、封面点击率8.7%；5篇笔记观看数分别24/17/7/8/30。已有MCP会话bootstrap及两种身份DOM校验通过，无需新二维码。证据存于忽略提交的 `runtime/connected_acceptance/creator-reader.json`。随后真实网页点击“立即核对”触发统一Worker，16:12:07完成PostgreSQL持久化、API回传与页面逐值核对；creator观测时间16:12:03，周期2026-10-03至2026-10-09，数值与上述读取器样本一致。下一轮16:27:07，间隔900秒；原MCP保持5篇唯一笔记、0条评论，无重复。完整链路证据为忽略提交的 `runtime/connected_acceptance/creator-integration.json`，含数据库与页面核对。本次本机链路已验收，不代表秒级实时、非空评论或全量历史已验证。

## 2026-10-10 搜索无界面修正

scripts/xhs_sync.py bridge 现在明确传入 `-headless=true`，复用同一 `COOKIES_PATH`，不删除或迁移登录文件。网页登录/重新连接是用户主动入口；普通搜索不会调用二维码登录。此前 `-headless=false` 会让每次连接器读取创建可见页面，已移除。

本机二进制构建revision为 `a5c8f7799980ba1fdd501999843eb2d17e4c9a9f`；启动参数帮助和[上游说明](https://github.com/xpzouying/xiaohongshu-mcp#13-启动-mcp-服务)确认默认无界面。[对应版本会话读取](https://github.com/xpzouying/xiaohongshu-mcp/blob/a5c8f7799980ba1fdd501999843eb2d17e4c9a9f/cookies/cookies.go)确认显式COOKIES_PATH优先。无需改变浏览器指纹、绕过验证或改用用户日常浏览器。

研究取消关闭单个HTTP连接、停止后续采集和本项目重试；不杀整个共享MCP。上游必须传播请求context才能同步停止内部浏览器，具体实测边界见当前状态。

本轮真实取消已观察到上游 context canceled 及该请求浏览器子进程退出。搜索省略 filters，避免非默认排序触发上游筛选浮层等待；本地排序仅覆盖返回集合，仍可能受平台超时和访问限制影响。19:00 同词真实搜索返回20条线索、读取3条，网页确认1条入库并检索命中。
