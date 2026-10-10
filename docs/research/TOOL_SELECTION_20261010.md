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

## 数据连接：未安装

| 项目 | 核实到的能力与选择理由 |
| --- | --- |
| [xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) | 浏览器实现，代码 Apache-2.0 许可不能代替平台数据授权；详见[连接可行性核实](XHS_CONNECTION_FEASIBILITY.md)。 |
| [Agent-Reach](https://github.com/Panniantong/Agent-Reach) | MIT；目前小红书后端在 OpenCLI、xiaohongshu-mcp、xhs-cli 间路由，仍依赖登录态或 Cookie。没有因此获得新的官方个人自然流量/评论数据权限。 |
| [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) | Playwright 登录态及网页签名采集。原始 LICENSE 是非商业学习许可证 1.1；不作为商业产品依赖，也没有据此启用平台采集。 |
| social-auto-upload | 当前需求优先研究与数据，自动发布另有账号、稿件版本和时间审批；本轮不新增发布器。 |
| linco-bridge | 远程访问本机 Agent 不解决数据接口权限；本轮不新增远程入口或暴露本机。 |

## 卡片、设计和工作流：暂缓

[guizang-social-card-skill](https://github.com/op7418/guizang-social-card-skill) 固定版本 `cf4b810fac1c73fb65a2bb31d8c9278d82cbc4c5` 具备卡片排版能力，但根 LICENSE 为 AGPL-3.0，package.json 的 ISC 标记存在冲突；闭源服务集成需单独评估。SKILL.md 的先获取素材后披露、可选署名指令不适用于本项目；后续采用时必须覆盖为只使用自有或已核实许可素材，必要署名不得省略。本轮未安装，也未执行脚本。

Dify、n8n、ComfyUI、RedInk 是额外应用或工作流系统，不是装入目录即可为现有网站增加能力。本轮已有 LangGraph、持久 Worker、真实本地 RAG 和模型路由，优先完成现有链路，暂不再增加另一套服务。

nuwa-skill、huashu-design、Excalidraw、Horizon、Generative-Media-Skills、Auto-Redbook-Skills、markdown-to-image 目前未安装；其中重名/未确定原仓库项不凭名称选包。文风蒸馏、定时资讯、视频生图和卡片生产待对应需求具体化后选择。此表不是对所有候选进行过完整代码安全审计的声明。

## 验收边界

本次只确认中文 Skill 文件安装完成；需要下一轮对话实际触发才能确认使用体验。未新增常驻服务、浏览器插件、Cookie 采集或社媒自动发布。个人账号实时自动同步仍未达到可验收状态。
