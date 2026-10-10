# 本机小红书只读同步

当前用户网页入口：`http://127.0.0.1:8775/#connections`。使用已有网站登录会话，进入“账号数据连接”。页面可暂停、恢复、立即核对；自动周期为 15 分钟。手动核对至少间隔 60 秒。不是秒级实时，也不保证全部历史和全部评论。

## 已安装的本机组件

上游：[xpzouying/xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp)，Apache-2.0，v2.5.5 darwin-arm64。二进制 SHA256：`fad3633fda4a8060e66e2941bc8fc5460326c7cb4e58a32485a9e2c9408e95a8`。安装和登录会话位于忽略提交的 `runtime/xhs-local`，不随 Git 交付，连接器监听 `127.0.0.1:18061`。

本项目客户端仅允许 login/status、user/me、feeds/detail 三个只读接口；不调用发布、关注、互动工具。开始和结束均检查平台身份，笔记作者必须与绑定身份一致。连接器控制令牌和 Cookie 不进入网站响应、日志或模型上下文。登录由本人完成，遇验证码或访问限制停止处理。

## 本机重启

以下命令在项目根目录执行，分别保持进程运行。现有服务还在运行时不要重复启动，不要关闭其他工作区的服务。未安装开机自启。休眠或退出进程期间不会同步，重启后保留历史。

```sh
runtime/venv/bin/python scripts/xhs_sync.py bridge
runtime/venv/bin/python scripts/xhs_sync.py serve --schema youji_connected_acceptance_20261010
runtime/venv/bin/python scripts/xhs_sync.py worker --schema youji_connected_acceptance_20261010
```

上面 serve 和 worker 使用明确的隔离 PostgreSQL schema，避免误接默认库的较新版本；现有 `.env` 不改。三个命令分别用于本机连接器、网页和专用同步工作进程。原创作/研究仍由 `backend.worker` 执行；升级后的通用 Worker 也能在空闲时领取同步任务，数据库租约防止重复领取。

首次绑定由本机管理员执行，用户必须已经在连接器完成登录。填写网站用户名；有多个小红书档案时必须明确 `--account-id`。不会因浏览器里存在共享登录就让任意网站用户认领。

```sh
runtime/venv/bin/python scripts/xhs_sync.py bind --username 网站用户名 --account-id 项目账号ID --schema youji_connected_acceptance_20261010
runtime/venv/bin/python scripts/xhs_sync.py status --username 网站用户名 --account-id 项目账号ID --schema youji_connected_acceptance_20261010
```

网页内尚无自助扫码重连流程。登录过期会停用任务，需本人通过本机连接器重新登录后在网页恢复。恢复不会改变原绑定身份。换号需人工审核迁移，不能覆盖历史。

## 数据与验证边界

前 5 篇主页返回笔记，最多 100 条/篇已加载评论；不强制滚动加载评论。不读取创作者后台流量，无值保留 null，原始显示数字保留用于核对，不能把“1.2万”虚构成精确数字。按 owner/account_id 隔离，笔记与评论唯一键去重，内容哈希比较变化，轮次快照保留审计。采集时间可核对；平台没有提供准确更新时间时不伪造延迟。

同步结果单独存储，不冒充人工已确认经验或平台官方数据，不自动喂给创作模型。当前网页已绑定本人真实账号；这不表示公开部署、第三方多账号托管或取得平台官方 API 许可。真实内容未纳入 Git，测试数据均为合成。
