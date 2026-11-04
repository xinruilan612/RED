# GitHub 相近项目调研

检索日期：2026-09-20。通过用户指定的 GitHub 连接器搜索并读取仓库元数据、README、部分源码和许可证，网页搜索补充定位。检索词：xiaohongshu agent、小红书 图文 生成、social media agent langgraph。

本次为静态调研，未安装、运行、压测或安全审计第三方项目。README 功能是作者描述，不是本项目的验证结果。公开可读的仓库不一定具备允许商业复用的开源许可证。

## 1. 推荐顺序与对照

| 项目 | 与本项目的相似点 | 主要差异 / 建议用途 | 许可核对 |
| --- | --- | --- | --- |
| [EthanYoQ/agent-xiaohongshu-workbench](https://github.com/EthanYoQ/agent-xiaohongshu-workbench) | 账号定位、研究、选题、文稿、配图、人工预览 | 流程参考最接近；依赖本地 Codex、Chrome 和 Browser Bridge，不是用户直接用网页的托管产品 | 根 LICENSE 为 MIT；第三方 Skill 和 Logo 有独立边界 |
| [langchain-ai/social-media-agent](https://github.com/langchain-ai/social-media-agent) | 内容生成、人工修改/接受/拒绝、多步骤图编排 | 最值得读工作流代码；面向 Twitter/LinkedIn，不能直接当小红书成品 | 根 LICENSE 为 MIT |
| [HisMax/RedInk](https://github.com/HisMax/RedInk) | 大纲编辑、封面、多页图文、单页重生成 | 图文交互和输出组织参考；依赖生成式图片，MVP 采用固定模板以控制范围 | 根 LICENSE 为 CC BY-NC-SA 4.0，另有商业授权路径 |
| [Aaronwn/ai-xiaohs](https://github.com/Aaronwn/ai-xiaohs) | 标题正文、风格、编辑、卡片导出 | 轻量 UI 参考；README 未体现完整多 Agent 后台与任务恢复 | README 声明修改版 GPLv3 和商业限制；根 LICENSE URL 返回 404，不能按标准 GPL 推断 |
| [kvnZero/xhs-agent](https://github.com/kvnZero/xhs-agent) | 小红书与 AI Agent 场景 | 主要是 Selenium 浏览、点赞、收藏、评论自动化；不是创作产品底座 | API 未识别许可证，README 限学习用途、不允许商业使用 |

我的建议：参考前两个项目的流程与接口设计，借鉴 RedInk 的可编辑分页体验；自行实现云端身份、项目隔离、版本、任务恢复和模板导出。暂不整体 fork 任何项目，也不引入浏览器自动互动。

## 2. 值得阅读的具体位置

### 2.1 小红书工作台：用户流程与结构化提案

已读取 [README](https://github.com/EthanYoQ/agent-xiaohongshu-workbench/blob/main/README.md)、[修订 Schema](https://github.com/EthanYoQ/agent-xiaohongshu-workbench/blob/main/server/schemas/revise.schema.json)、[LICENSE](https://github.com/EthanYoQ/agent-xiaohongshu-workbench/blob/main/LICENSE) 和目录树。

可以研究“完整预览后确认”和结构化修改成果。其单一修订结构包含文案、卡片和视觉方向，本项目将文案与布局分开并绑定版本，以支持局部重做。其本地运行方式不能直接满足我们的零配置网页用户体验，需独立设计服务端模型调用、鉴权和持久化。

### 2.2 Social Media Agent：工作流与人工反馈

已读取 [生成工作流源码](https://github.com/langchain-ai/social-media-agent/blob/main/src/agents/generate-post/generate-post-graph.ts)、README、LICENSE 和目录树。源码具有内容验证、报告、写帖、图片、人工反馈及重写等节点，并使用条件边连接。

可借鉴状态图、人工反馈和失败分支的组织方式；其中平台授权、调度发布等集成不属于本 MVP。存在测试目录只说明有测试代码，本次未验证测试是否通过。

### 2.3 RedInk：分页、重生成与图文体验

已读取 [README](https://github.com/HisMax/RedInk/blob/main/README.md)、[依赖声明](https://github.com/HisMax/RedInk/blob/main/pyproject.toml)、[LICENSE](https://github.com/HisMax/RedInk/blob/main/LICENSE) 和目录树。其 Python/Flask、Vue 前后端适合研究图文生成交互，但本项目不因此更换所建议的技术栈。

作者许可明确包括非商业限制及相同方式共享条件，并单列商业授权。因此本轮仅作产品体验参考，不复制代码或素材作为商业产品底座。后续如要复用，先核对拟用文件、依赖与具体授权。

### 2.4 其余两个项目的边界

[ai-xiaohs README](https://github.com/Aaronwn/ai-xiaohs/blob/main/README.md) 有卡片样式和编辑流程，可做界面对照；许可描述非标准，应先澄清再复用。

[xhs-agent README](https://github.com/kvnZero/xhs-agent/blob/main/README.md) 的主要能力是平台交互自动化，且有用途限制。本 MVP 只做用户确认后的图文导出，不采用其自动点赞评论方向。

## 3. 活跃度快照

以下是 GitHub API 的 pushed_at（最近推送时间，不等于最后一个功能提交）和归档状态。动态信息仅代表本次查询，详见 [机器可读快照](repository_snapshot.json)。

| 项目 | 最近推送 UTC 日期 | 已归档 |
| --- | --- | --- |
| EthanYoQ/agent-xiaohongshu-workbench | 2026-09-07 | 否 |
| langchain-ai/social-media-agent | 2026-09-18 | 否 |
| HisMax/RedInk | 2026-06-30 | 否 |
| Aaronwn/ai-xiaohs | 2026-03-03 | 否 |
| kvnZero/xhs-agent | 2025-04-20 | 否 |

不以星数证明质量；未做全 GitHub 穷尽搜索，也不能证明不存在完全同类产品。表中的相似度和推荐顺序是本次设计判断。

## 4. 本项目可以验证的差异化

1. 用户无需本地 Agent/浏览器运行环境，直接通过网页完成创作。
2. 四角色共享有来源的素材，但仅获得所需上下文；审稿能精确返回问题段落。
3. 用户稿、候选稿、排版和审稿绑定版本，旧结果不能覆盖新编辑。
4. 任务可恢复、费用有硬上限、导出可重试，支撑持续使用。
5. 用同一批任务比较普通生成和协作流程，记录采用率、修改量、耗时与成本。

这些是拟实现和待验证的方向，不能宣称全行业首次。将竞赛创新点写成实际实现及对照证据，不将开源框架自身功能包装为团队原创算法。

## 5. 后续复用记录

若实际复用，新增第三方清单：仓库 URL、固定 commit、文件路径、许可证全文、改动说明、在本项目的用途、测试结果；同时核对依赖及图片/字体许可。当前没有复制这些项目的代码或下载运行它们，也没有产生模型调用费用。

## 运营助手参考增补

核查日期：2026-09-20。用户明确指定 [Klaudiusz321/social-media-agents](https://github.com/Klaudiusz321/social-media-agents)，不是前文的 langchain-ai/social-media-agent。以下新增项不属于前述五仓库历史元数据快照。本轮未安装、运行该第三方项目，也未进行端到端发布验证。

README 描述 TrendScannerAgent、ContentCreatorAgent、SchedulerAgent 和 Orchestrator，主要目标是 Twitter、Instagram、LinkedIn；可以借鉴趋势到创作到排程的分层思路。仓库简介提到广告/分析/互动等角色，与 README 主链路不完全一致，不能只凭简介认定能力完整。

读取 [orchestrator.py](https://github.com/Klaudiusz321/social-media-agents/blob/main/orchestrator.py) 发现 human_review 默认 False，启用后通过命令行 input 获取同意；内容池和发布历史采用 JSON 路径。它不是我们需要的默认人工审批、版本绑定、多人隔离的网页发布系统。本轮只静态读取部分代码，没有证据证明完整指标回流、受控学习和多版本审核闭环已经实现。借鉴流程划分，自有状态与权限保持现有守卫。

README 声明 MIT，但本次仓库根目录展示未见独立 LICENSE 全文；实际复制代码前须取得并核对许可文本、固定 commit 及拟用文件。本轮未复制第三方实现、未打开其 .env，也未下载运行。此前 langchain-ai 项目继续作为图编排的独立参考。

[Postiz 官方平台列表与 Analytics 介绍](https://postiz.com/agent)可用于了解发布和数据适配方式；所读列表未显示小红书/抖音，不能据此认定可直接使用。用户已明确暂不接入 Postiz，因此本期设计无其运行时依赖。

## 国内平台接入核查

| 来源 | 已核查事实 | 本项目边界 |
| --- | --- | --- |
| [抖音创建视频](https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/video-management/douyin/create-video/video-create) | 需要 video.create.bind 能力申请和用户授权；创建后会有平台审核 | 有公开文档不代表本项目已获权；回执 ID 不等于公开发布成功 |
| [抖音发布能力使用规范](https://developer.open-douyin.com/docs/resource/zh-CN/dop/operation-standard/platform-capabilities/useclue) | 存在 App、H5/Web 等投稿路径，需申请对应能力 | 选择适合本项目应用类型的接入方式，不把不同路径混为一套 API |
| [抖音视频数据查询](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/server/basic-abilities/video-id-convert/user-video-data/video-data) | 所读页面是小程序接口，ma.video.bind，需申请和授权；仅返回公开视频数据 | 不能直接作为当前 Web 产品已可用接口；先核对网站应用对应通道 |
| [抖音数据权限调整公告](https://developer.open-douyin.com/forum/bulletin/post/672d828be9f6234d658c8dd2) | 2024-11-08 公告涉及 hotsearch 等能力 | 公告是历史调整证据，不证明现在一定能申请；以实际控制台审批为准 |
| [抖音用户互动数据](https://developer.open-douyin.com/capacity-center-page/capacity-detail/7180284622729658424) | 授权后可获取账号部分指标，并有用途与数据延迟说明 | 不将账号级数据当单篇归因；接入前核对本产品场景适用性 |
| [小红书小程序开放平台](https://miniapp.xiaohongshu.com/) | 搜索索引出现“笔记发布能力及入口”；本轮页面正文获取失败 | 仅作为官方核查入口；尚不能确认通用 Web 代发、热点和作品指标权限 |

本轮未登录开发者控制台、申请能力或连接用户账号。无法确认的小红书能力保持 unknown；抖音公开接口保持 documented_not_verified。人工发布和手工指标导入属于产品过渡设计，不冒充官方自动接入。

技术建议与阶段取舍由 [v0.4 技术方案](../design/ARCHITECTURE.md#运营闭环-v04-技术提案) 维护。接入前再次核对对应官方文档、实际账号类型与授权范围，不硬编码本轮未验证的配额。

## 2026-10-11：小红书 RAG 与多模型的最小借鉴

本节补充最新用户需求的技术来源，当前产品范围以 [正式需求](../design/CONNECTED_CREATOR_REQUIREMENTS.md) 为准，实际完成状态以 [代码与验收记录](../CONNECTED_CREATOR_STATUS.md) 为准；前文图文、抖音及旧 MVP 取舍保留为历史，不扩大本轮范围。已阅读上游公开 README、下列源码及官方接口文档；本次调研没有安装或升级第三方依赖，没有读取真实平台账号，没有执行模型调用、采集或发布。链接指向查询时的上游文件，不代表本仓库已经采用相同版本，未来复制实现仍须固定 commit 并登记许可。

### 小红书：有来源的有限研究，而非全量实时接口

- [xiaohongshu-mcp 搜索实现](https://github.com/xpzouying/xiaohongshu-mcp/blob/main/xiaohongshu/search.go)提供关键词、最多点赞/收藏/评论、类型与时间筛选，使用浏览器读取页面状态。筛选等待超时可能返回旧结果，不能据此承诺全站最高互动或完整召回；本项目应记录实际查询、筛选、范围与采集时间。
- [详情请求类型](https://github.com/xpzouying/xiaohongshu-mcp/blob/main/types.go)要求 `feed_id` 与 `xsec_token`；评论可限制加载数量。[返回结构](https://github.com/xpzouying/xiaohongshu-mcp/blob/main/xiaohongshu/types.go)含赞、收藏、评论、分享，以及评论分页状态，不含净涨粉、新增关注、取消关注或主页访客。未知值保持 null，缩写保留原展示；没有读取到不能写 0。
- [路由](https://github.com/xpzouying/xiaohongshu-mcp/blob/main/routes.go)区分搜索、详情、账号、通知和发布，未见评论/流量实时推送订阅。研究按用户选定的公开笔记范围进行；私密内容及“已同步笔记与评论”块不展示，不能为此删掉后台表或历史。身份隔离所需的后台核对与展示私人账号内容是两回事。
- 定时更新必须显示间隔、最近成功及过期状态，并绑定具体笔记 ID/链接，不能把公开互动称为后台流量或秒级实时数据。`xsec_token` 等来源访问参数按必要范围处理，不写日志、公共报告或提交包；用户主动打开原文需要的可访问链接与对外脱敏资料分别处理。
- [README](https://github.com/xpzouying/xiaohongshu-mcp)描述图文/视频发布能力，不证明本项目已接通或获准发布。本轮不自动发布，不做图像或视频生成、下载、转写扩展；优先提供复制正文和文字稿导出。不得为了使用上游发布器擅自增加配图或发送帖子。

代码许可为 [Apache-2.0](https://github.com/xpzouying/xiaohongshu-mcp/blob/main/LICENSE)，不等于平台数据访问许可；平台登录、验证码和访问限制不得绕过。既有渠道核对见 [连接可行性](XHS_CONNECTION_FEASIBILITY.md)，既有安装历史见 [工具选择记录](TOOL_SELECTION_20261010.md)，本节不把历史安装重新记为新增工作。

### RAG 与四角色：复用现有链路

沿用 `audience / research / content / reviewer` 四个 ID 与现有审核、预算、人工确认，不以新增“编辑 Agent”替换 reviewer。audience 从目标受众和获准使用的评论问题形成选题；research 检索核对事实与案例来源；content 基于检索快照原创写作并在对话中改稿；reviewer 核查主张、参考边界和稿件问题。Markdown 角色卡与 `backend/live.py::messages_for` 的运行提示词须分别对齐，不声称改文档就已改变模型行为。

产品事实、表达案例和受众问题分开；只学习样例结构、信息组织和表达方法，不复制整篇、不伪造亲历或产品功效。候选须用户确认后入正式库；正文/摘要/视频说明分别标注，任务保存来源版本和定位。用户关闭自动参考或评论时不得隐式注入；空评论样本不代表全平台没有评论。继续复用现有 RAG、队列和四角色，而非增加 Dify、n8n 或另一套工作流系统。

### 模型选择：预设、连接测试与明确恢复

| 来源 | 可借鉴的最小部分 | 不直接引入的内容与许可边界 |
| --- | --- | --- |
| [CC Switch](https://github.com/farion1231/cc-switch)、[预设类型源码](https://github.com/farion1231/cc-switch/blob/main/src/config/geminiProviderPresets.ts) | 厂商名称、官方申请入口、Base URL、模型和协议预设；选择、检测、保存、切换 | 不搬桌面配置改写、订阅接管或赞助中转商目录；[MIT](https://github.com/farion1231/cc-switch/blob/main/LICENSE) |
| [LiteLLM 兼容接口](https://docs.litellm.ai/docs/providers/openai_compatible) | 统一内部调用、按协议适配、参数兼容 | 不额外部署复杂网关后台；[普通代码 MIT，enterprise 另有许可](https://github.com/BerriAI/litellm/blob/main/LICENSE) |
| [one-api](https://github.com/songquanpeng/one-api)、[适配器入口](https://github.com/songquanpeng/one-api/blob/main/relay/adaptor.go) | 厂商渠道和模型映射分离 | 不增加充值、分销或渠道管理平台；[MIT](https://github.com/songquanpeng/one-api/blob/main/LICENSE)，实际复用还需核对项目归属说明 |
| [LobeHub（原 lobe-chat）](https://github.com/lobehub/lobehub) | 网页模型配置与会话界面的交互参考 | 不复制整站；[Community License](https://github.com/lobehub/lobehub/blob/main/LICENSE)含商业衍生附加条件，不能写成无附加条件的 Apache-2.0 |

当前最小配置是厂商、协议、模型 ID、Base URL、用户 Key，加“测试连接 / 保存 / 启用”。平台默认 DeepSeek 仅使用后端密钥；其他模型使用用户自己的配置，按 owner 隔离与加密，Key 不回显、不进日志或仓库。BYOK 失败不能静默换平台 Key 或改变资料接收厂商；用户可明确选择回退默认模式。自定义地址仍需现有 URL/主机、内网访问及重定向校验。

- [阿里云 Base URL 总览](https://help.aliyun.com/zh/model-studio/base-url)区分地域、计费方案及业务空间；Key 与地址必须匹配，不能把所有端点硬改成同一 `/v1`。旧公共域名和新业务空间域名的可用性按该文档核对。
- [火山方舟接入文档](https://docs.volcengine.com/docs/ark/integrate-third-party-tools?lang=zh)区分普通 OpenAI 兼容 `/api/v3`、Coding Plan `/api/plan/v3` 与 Anthropic `/api/compatible`；协议名相近不代表请求体和地址相同。
- [DeepSeek 模型列表](https://api-docs.deepseek.com/api/list-models/)提供当前模型与能力元数据。优先按实际端点查询并允许手填；单独 `/models` 失败不等于生成接口不可用，陈旧预设也不能保证模型仍可调用。
- [LiteLLM 错误分类](https://docs.litellm.ai/docs/exception_mapping)与[重试说明](https://docs.litellm.ai/docs/completion/reliable_completions)可借鉴：鉴权、余额/权限、模型名、参数、超时、限流分别给出修正入口；仅瞬时错误有限重试。保留输入和草稿，提供修改配置、重新测试、返回、重试或跳过可选搜索；不承诺任何上游永不失败，内容限制不能通过切换模型规避。

本期验收应证明：有有效配置时能完成文本调用；配置和外部失败时用户能在产品内部恢复；模型身份、费用、来源及失败状态可追溯。上述能力调查不是生产验证，本节不新增依赖、不安装清单中的全部 Skills、不自动发布、不开展图像视频功能。
