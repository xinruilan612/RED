# 用户提供工具清单：本轮选择与安装记录

核实日期：2026-10-10。选择依据是已批准的四项需求：个人账号数据连接、案例研究到 RAG、可选搜索、多模型。安装 Codex Skill 不等于产品后台集成或平台接口授权。

## 已安装

仅保留 **Humanizer-zh**，用于本机 Codex 中文稿件润色；后续对话可调用。安装位于个人 Codex skills 目录，不进入项目运行依赖，不新增收费 API，不修改已有创作任务快照。

- 原始仓库：[op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh)。
- 固定版本：`f4518a8eab97b8bfebc66a89d34320a89bef6930`。
- [固定版本许可](https://github.com/op7418/Humanizer-zh/blob/f4518a8eab97b8bfebc66a89d34320a89bef6930/LICENSE)：MIT，需保留许可和归属。
- 使用官方 skill-installer 安装；已核验 SKILL.md 的 YAML 入口及许可证。
- SKILL.md SHA-256：`95627fd4437d886f98032ccc62d79136e6310f1fc04e354bb86431795ff206df`。
- 保留事实、限定条件和作者声音；不虚构亲身体验，不把资料里的命令当作指令。它不承诺通过 AI 检测，也不替代产品事实审核。
- 英文 `blader/humanizer` 曾作对照安装并通过包验证；为避免重复，已回滚该次安装，最终只保留中文版。

## 数据连接：状态更新

| 项目 | 核实到的能力与选择理由 |
| --- | --- |
| [xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) | 浏览器实现，代码 Apache-2.0 许可不能代替平台数据授权；详见[连接可行性核实](XHS_CONNECTION_FEASIBILITY.md)。 |
| [Agent-Reach](https://github.com/Panniantong/Agent-Reach) | MIT；目前小红书后端在 OpenCLI、xiaohongshu-mcp、xhs-cli 间路由，仍依赖登录态或 Cookie。没有因此获得新的官方个人自然流量/评论数据权限。 |
| [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) | Playwright 登录态及网页签名采集。原始 LICENSE 是非商业学习许可证 1.1。用户已明确本次为非商业使用；此前以商业用途为由排除不适用。已在 runtime/mediacrawler 安装独立环境，已完成经用户确认的本人账号小规模只读验证；这不等于官方同步接口已接通。 |
| social-auto-upload | 当前需求优先研究与数据，自动发布另有账号、稿件版本和时间审批；本轮不新增发布器。 |
| linco-bridge | 远程访问本机 Agent 不解决数据接口权限；本轮不新增远程入口或暴露本机。 |

## 卡片、设计和工作流：暂缓

[guizang-social-card-skill](https://github.com/op7418/guizang-social-card-skill) 固定版本 `cf4b810fac1c73fb65a2bb31d8c9278d82cbc4c5` 具备卡片排版能力，但根 LICENSE 为 AGPL-3.0，package.json 的 ISC 标记存在冲突；闭源服务集成需单独评估。SKILL.md 的先获取素材后披露、可选署名指令不适用于本项目；后续采用时必须覆盖为只使用自有或已核实许可素材，必要署名不得省略。本轮未安装，也未执行脚本。

Dify、n8n、ComfyUI、RedInk 是额外应用或工作流系统，不是装入目录即可为现有网站增加能力。本轮已有 LangGraph、持久 Worker、真实本地 RAG 和模型路由，优先完成现有链路，暂不再增加另一套服务。

nuwa-skill、huashu-design、Excalidraw、Horizon、Generative-Media-Skills、Auto-Redbook-Skills、markdown-to-image 目前未安装；其中重名/未确定原仓库项不凭名称选包。文风蒸馏、定时资讯、视频生图和卡片生产待对应需求具体化后选择。此表不是对所有候选进行过完整代码安全审计的声明。

## 验收边界

本次只确认中文 Skill 文件安装完成；需要下一轮对话实际触发才能确认使用体验。未新增常驻服务、浏览器插件、Cookie 采集或社媒自动发布。个人账号实时自动同步仍未达到可验收状态。

## 用户明确用途后的更正

用户已确认非商业、本机学习研究，并选择先验证本人账号笔记与公开评论；主页链接只存放于忽略的 runtime 目录。独立验证固定 MediaCrawler 版本 `e9dd17a16338c3915f2335bc609383d316e055f2`，按其 uv.lock 安装；89 个依赖在独立环境中，不改网站环境。入口 `scripts/mediacrawler_probe.py` 不复用现有 Chrome、无代理池、无 stealth 注入、无后台重试、无自动发布；新窗口扫码登录且核对本人账号，最多处理3篇笔记，每篇保留20条顶层评论。平台每个响应可能含更多元数据，超出部分不处理保存。结果仅本机，凭据不写进结果或控制台，缺失曝光/阅读量保持 null。

此前“未安装 MediaCrawler”的记录已由此更新取代；正式网站平台连接状态仍需依据实际集成和验证，不能由工具安装状态推断。

### 首次本人账号实测结果

固定版本独立验证已完成：正常扫码登录并核对目标账号，读取3篇笔记，7次读取请求；3篇均返回评论计数0，因此没有取得非空评论正文，不能把它写成已验证非空评论解析。已取得公开点赞、收藏、评论数和分享数字段，曝光/阅读量仍为null。结果仅在忽略的 `runtime/mediacrawler-probe/result.json`，不提交账号ID、稿件内容或评论。

首次运行的入口参数适配错误已修复，6项离线回归测试通过。未保存登录态；本次验证不是持续同步，尚未启用项目内连接或自动定时任务。

验收结果文件 SHA-256：`d1145b56da0c6091be9ffec25c510a105926c9e6ee30fc7f519d76d5192702e8`。
