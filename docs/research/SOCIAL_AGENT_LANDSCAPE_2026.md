# 2024–2026 多智能体/AI Agent 社媒内容创作与运营 · 全景调研报告

> 调研执行：调研子 agent。数据快照日期：**2026-09-27**（GitHub Search/REST API 当日实时查询）。
> 检索覆盖：GitHub API 关键词搜索（social media agent / automation、xiaohongshu、小红书、douyin、抖音、tiktok/twitter/instagram/linkedin agent、short video、video repurpose、multi-agent marketing 等 16 组）+ 网页搜索（Product Hunt、即刻、知乎、腾讯云/CSDN 中文社区、厂商官网）。
> 证据等级标注：[API]=GitHub API 快照；[README]=我亲自读过的 README/源码；[WS]=工作区上一轮调研已核实；[WEB]=网页搜索来源描述（未逐一实测产品）；[推断]=我的判断，无直接证据。
> 星数只表示社区关注度，不代表质量或可用性；未对任何第三方仓库做安装、运行或安全审计。

## 一句话结论（TL;DR）

- 这个赛道 2025–2026 已经非常拥挤：**"选题→文案→配图→排期→发布"的流水线是烂大街标配**，开源的（Postiz、Easel、各类 Skill 包）和商业的（HubSpot Breeze、Zapier、Coze 模板）都在做。
- 真正接近本项目"运营闭环"野心的开源对手是 **ZJU-REAL/Easel**（浙大 REAL Lab + 北大 OpenDCAI Lab，113 个技能，声称含"归因/复盘/画像记忆"，但归因深度存疑）和 **Xiangyu-CAS/xiaohongshu-ops-skill**（有"复盘知识库沉淀"，但只是 Markdown 文本，不是统计学习）。
- **发布后真实数据因果归因、评论区运营闭环、受众仿真校准、多账号实验设计、可撤销的经验学习**——这五项在开源世界里基本空白，商业产品也只摸到皮毛；这是本项目最值钱的差异化空间。

---

## A. 开源项目（GitHub，按赛道分组）

### A1. 全流程多智能体工作台（通用/英文向）

| 名称 | URL | 一句话定位 | 核心功能 | 开源 | Star | 最后活跃(pushed_at) |
|---|---|---|---|---|---|---|
| **Postiz** (gitroomhq/postiz-app) | https://github.com/gitroomhq/postiz-app | 最火的"agentic 社媒排程工具"，开源底座 + 商业 SaaS | AI Agents + MCP 排程发布 20+ 渠道；内容生成、排程、分析、协作 | ✅ AGPL-3.0 | 36,381 [API] | 2026-09-26 [API] |
| **Easel** (ZJU-REAL/Easel) | https://github.com/ZJU-REAL/Easel | 浙大 REAL Lab+北大 OpenDCAI 出品的"持续进化的社媒运营助手"，最接近全闭环 | 五段流程：发现(热搜/竞品/缺口)→策划(定位/选题/日历)→创作(图文/视频/音频/短剧)→发布(7 个中文平台登录发布+质量门禁+敏感检查)→归因(数据回收/评论洞察/复盘/ROI/画像记忆)；113 个技能；OpenClaw 底座 | ✅ Apache-2.0 | 1,689 [API] | 2026-09-24 [API] |
| **langchain-ai/social-media-agent** | https://github.com/langchain-ai/social-media-agent | LangChain 官方示例级 Twitter/LinkedIn 内容 Agent（用户指定参考） | LangGraph 状态图：验证→报告→写帖→配图→human-in-the-loop 审批→重写；调度发布 | ✅ MIT | 2,808 [API] | 2026-09-25 [API] |
| **Klaudiusz321/social-media-agents** | https://github.com/Klaudiusz321/social-media-agents | 模块化多 Agent 社媒系统（用户指定参考） | Orchestrator 协调 TrendScanner/ContentCreator/Scheduler + Ad/Analytics/Engagement 角色；human_review 默认 False（命令行 input 确认）；内容池与发布历史用 JSON 文件 | ⚠️ README 声称 MIT 但仓库未见 LICENSE 文件 [WS] | 36 [API] | 2026-04-03 [API] |
| **autopost-ai** (rayane-rhsn) | https://github.com/rayane-rhsn/autopost-ai | LangGraph 六 Agent 全自动社媒流水线+周报 | 趋势研究→周计划→平台化文案→Unsplash 配图→排期→邮件周报；**注意：周报基于排程与内部状态，不接真实表现数据** [README] | ✅ MIT | ≈0 [API] | 2026-03-28 [API] |
| **microsoft/content-generation-solution-accelerator** | https://github.com/microsoft/content-generation-solution-accelerator | 微软官方多智能体营销内容加速器 | 基于 Azure AI Foundry 的多 Agent 营销内容生产模板 | ✅ MIT | 258 [API] | 2026-09-21 [API] |
| **growchief/growchief** | https://github.com/growchief/growchief | all-in-one 社媒自动化(外联向) | 多平台自动化、外联、内容 | ✅ AGPL-3.0 | 3,475 [API] | 2025-10-13 [API] |
| **Agentfy-io/Agentfy** | https://github.com/Agentfy-io/Agentfy | 模块化微服务多平台 Agent 工作流 | "Ask once, agent does the rest"，多社媒平台工作流 | ✅ Apache-2.0 | 581 [API] | 2025-05-05 [API] |
| **LocoreMind/locoagent** | https://github.com/LocoreMind/locoagent | 真浏览器自动化的社媒 Agent | 浏览器自动化发帖/运营 | ✅ MIT | 1,059 [API] | 2026-06-27 [API] |
| **stevenflanagan1/social-ai-team** | https://github.com/stevenflanagan1/social-ai-team | Claude Code 社媒团队技能包（SMB 向） | 品牌设定、内容日历、文案、创意、**表现复盘(performance review)** | ✅ 未见 license 文件 | 222 [API] | 2026-08-24 [API] |
| **Socheli/socheli** | https://github.com/Socheli/socheli | 端到端"无人脸视频"工厂 | 一个想法→调研→脚本→**QA 门禁**→渲染→发布 | ✅ AGPL-3.0 | 7 [API] | 2026-06-16 [API] |
| **kisinad/langgraph-mem0-ai-social-media-manager** | https://github.com/kisinad/langgraph-mem0-ai-social-media-manager | LangGraph+Mem0 记忆的 Facebook 互动系统 | 内容+互动+长期记忆 | ✅ 未见 license | ≈0 [API] | 2025-10-10 [API] |
| **jfbfb/GrowthOS-AI-Agent-** | https://github.com/jfbfb/GrowthOS-AI-Agent- | 中文企业六角色运营系统（个人项目，早期） | 市场情报/用户画像(评论区/私信分析)/内容策划/设计素材/投放优化/客服成交六 Agent；面向抖音/小红书/微博 | ✅ 未见 license | 11 [API] | 2026-04-29 [API] |

### A2. 中文平台（小红书/抖音/公众号）创作与运营

| 名称 | URL | 一句话定位 | 核心功能 | 开源 | Star | 最后活跃 |
|---|---|---|---|---|---|---|
| **xiaohongshu-viral-note-agent-skill** (xuboboo) | https://github.com/xuboboo/xiaohongshu-viral-note-agent-skill | 五年 XHS 运营方法论做成的 49 工具 MCP Skill | 智能选题、内容生成/爆款仿写、热点趋势、封面设计、短视频脚本、**合规校验**、账号分析、扫码登录一键发布、**发后复盘**；接入 Cursor/Claude/WorkBuddy/OpenClaw [README] | ✅ MIT | 15 [API] | 2026-07-19 [API] |
| **xiaohongshu-ops-skill** (Xiangyu-CAS) | https://github.com/Xiangyu-CAS/xiaohongshu-ops-skill | 把 OpenClaw 变成小红书运营助手，可"全面托管" | 推荐流分析(为何高赞)、账号分析、选题灵感、**知识库沉淀(Markdown 复盘)**、自动发布(CDP)、**自动回复评论**、爆款复刻、persona 人设 [README] | ✅ 未见 license 文件 | 2,379 [API] | 2026-03-19 [API] |
| **Beav** (Jamailar) | https://github.com/Jamailar/Beav | "小红书版 OpenClaw"全域运营工作台 | 采集、**评论区下载**、素材库、选题、AI 写作+图片自动编排、一键安装 | ⚠️ 无标准 license(NOASSERTION) | 1,749 [API] | 2026-09-26 [API] |
| **xhs_ai_publisher** (BetaStreetOmnis) | https://github.com/BetaStreetOmnis/xhs_ai_publisher | AI 小红书内容创作+发布桌面工具 | PyQt 桌面 + FastAPI；登录态复用、预览发布、浏览器自动化 | ✅ Apache-2.0 | 2,085 [API] | 2026-06-28 [API] |
| **XiaohongshuSkills** (white0dew) | https://github.com/white0dew/XiaohongshuSkills | 小红书自动发布/评论/检索 Skill | 自动发布、自动评论、自动检索；支持 OpenClaw/Codex/CC | ✅ MIT | 3,456 [API] | 2026-09-27 [API] |
| **xhs_matrix_system** (Admin6016) | https://github.com/Admin6016/xhs_matrix_system | 小红书矩阵自动化运营系统 | 多账号管理、定时批量智能发文、素材二创 | ✅ Apache-2.0 | 424 [API] | 2026-08-05 [API] |
| **xiaohongshu-matrices-cli** (alanl1234) | https://github.com/alanl1234/xiaohongshu-matrices-cli | 受治理的小红书矩阵 CLI（fork jackwener/xiaohongshu-cli） | 多账号登录、搜索/阅读/互动、Markdown 转多图卡片发布、**速率限制+去重+责任追溯**、**发布可强制人工审核**、反检测指纹 [README] | ✅ Apache-2.0 | 24 [API] | 2026-08-08 [API] |
| **Little-Red-Ant** (magicCzc) | https://github.com/magicCzc/Little-Red-Ant | 小红书全栈运营辅助（AI 创作+RPA 发布+数据趋势+矩阵） | AI 内容创作、RPA 自动化发布、数据趋势分析、账号矩阵管理 | ✅ MIT | 42 [API] | 2026-08-04 [API] |
| **agent-xiaohongshu-workbench** (EthanYoQ) | https://github.com/EthanYoQ/agent-xiaohongshu-workbench | 小红书图文工作台（账号定位→研究→选题→文稿→配图→预览确认） | 与父项目流程最接近的参考；依赖本地 Codex/Chrome [WS] | ✅ MIT | 145 [API] | 2026-09-07 [API] |
| **RedInk** (HisMax) | https://github.com/HisMax/RedInk | "一句话一张图"小红书图文生成器 | 大纲编辑、封面、多页图文、单页重生成；依赖生成式图片模型 | ⚠️ CC BY-NC-SA 4.0（禁商用，另售授权）[WS] | 5,587 [API] | 2026-06-30 [API] |
| **MoneyPrinterPlus** (ddean2009) | https://github.com/ddean2009/MoneyPrinterPlus | AI 批量生成+混剪短视频并自动发布 | 一键批量短视频、混剪、自动发布抖音/快手/小红书/视频号；本地 TTS/生图 | ✅ GPL-3.0 | 7,143 [API] | 2025-03-07 [API] |
| **ChatGPT-On-CS** (cs-lazy-tools) | https://github.com/cs-lazy-tools/ChatGPT-On-CS | 多平台 AI 客服机器人（含小红书） | 自动回复咨询/售后申诉；微信/小红书/京东/抖音/B站/微博统一接待；接 DeepSeek/通义 | ✅ AGPL-3.0 | 4,420 [API] | 2026-08-27 [API] |
| **AI-Media2Doc** (hanshuaikang) | https://github.com/hanshuaikang/AI-Media2Doc | 音视频一键转小红书/公众号风格文档 | 音视频→小红书/公众号/知识笔记/思维导图/字幕 | ✅ MIT | 4,032 [API] | 2026-02-05 [API] |
| **guizang-social-card-skill** (op7418) | https://github.com/op7418/guizang-social-card-skill | 小红书图文卡片+公众号封面生成 Skill | 28 布局/10 主题，HTML→PNG，Claude Code/Codex 可用 | ✅ AGPL-3.0 | 7,273 [API] | 2026-07-01 [API] |
| **wechat-skills** (gainubi) | https://github.com/gainubi/wechat-skills | 写公众号的 Skills 包 | 公众号写作技能 | ⚠️ 未见 license | 168 [API] | 2026-05-21 [API] |
| **deep_search_write** (liangdabiao) | https://github.com/liangdabiao/deep_search_write | 双智能体合作写作（公众号/小红书/博客） | 写作智能体 + 知识库智能体，图文并茂帖子 | ⚠️ 未见 license | 31 [API] | 2025-06-08 [API] |
| **ai-xiaohs** (Aaronwn) / **xhs-agent** (kvnZero) | https://github.com/Aaronwn/ai-xiaohs · https://github.com/kvnZero/xhs-agent | 卡片笔记生成器 / 点赞收藏评论自动化 | 详见上一轮调研；许可均不标准/限学习用途 [WS] | ⚠️ | 42 / 84 [API] | 2026-03-03 / 2025-04-20 [API] |

### A3. 数据采集 / 发布基础设施（运营 Agent 的"手脚"）

| 名称 | URL | 定位 | 开源 | Star | 最后活跃 |
|---|---|---|---|---|---|
| **MediaCrawler** (NanmiCoder) | https://github.com/NanmiCoder/MediaCrawler | 小红书/抖音/快手/B站/微博/知乎/贴吧笔记与评论爬虫+AI 分析 | ⚠️ NOASSERTION | 65,798 [API] | 2026-09-19 [API] |
| **xiaohongshu-mcp** (xpzouying) | https://github.com/xpzouying/xiaohongshu-mcp | 小红书官方接口 MCP（Agent 数据入口） | ✅ Apache-2.0 | 16,004 [API] | 2026-09-22 [API] |
| **social-auto-upload** (dreammis) | https://github.com/dreammis/social-auto-upload | 抖音/小红书/视频号/TikTok/YouTube/B站自动上传 | ✅ MIT | 15,204 [API] | 2026-09-02 [API] |
| **XHS-Downloader** (JoeanAmier) | https://github.com/JoeanAmier/XHS-Downloader | 小红书链接提取/作品采集 | ✅ GPL-3.0 | 12,848 [API] | 2026-09-20 [API] |
| **Spider_XHS** (cv-cat) | https://github.com/cv-cat/Spider_XHS | 小红书逆向/私信/直播/全域运营 | ⚠️ 未见 license | 7,888 [API] | 2026-09-27 [API] |
| **xiaohongshu-cli** (jackwener) | https://github.com/jackwener/xiaohongshu-cli | 小红书逆向 API CLI | ⚠️ 未见 license | 2,634 [API] | 2026-03-21 [API] |
| **MultiPost-Extension** (leaperone) | https://github.com/leaperone/MultiPost-Extension | 一键多发多平台浏览器扩展 | ✅ Apache-2.0 | 3,546 [API] | 2026-09-14 [API] |
| **postbot** (gitcoffee-os) | https://github.com/gitcoffee-os/postbot | 开源多平台内容同步分发（微信/头条/小红书/知乎/百家号/企鹅号/视频号/抖音/快手/B站+X/IG/TikTok 等） | ✅ Apache-2.0 | 1,465 [API] | 2026-09-20 [API] |
| **creatorhub** (3441293738) | https://github.com/3441293738/creatorhub | 抖音/小红书/快手内容监控·采集·搬运面板 | ⚠️ 未见 license | 2,143 [API] | 2026-09-27 [API] |
| **Agent-Reach** (Panniantong) | https://github.com/Panniantong/Agent-Reach | Agent 的"全网之眼"：读搜 Twitter/Reddit/YouTube/B站/小红书 | ✅ MIT | 85,680 [API] | 2026-09-15 [API] |
| **social-media-research-skills** (ScrapeCreators) | https://github.com/ScrapeCreators/social-media-research-skills | 社媒调研技能包：**异常爆款帖、评论挖掘、竞品拆解、广告库**、趋势（TikTok/IG/YouTube/Reddit/X/LinkedIn） | ✅ MIT | 2,839 [API] | 2026-08-26 [API] |
| **OpenBiliClaw** (whiteguo233) | https://github.com/whiteguo233/OpenBiliClaw | 自进化跨平台内容发现 Agent（先理解你，再主动找内容） | ✅ MIT | 3,356 [API] | 2026-09-26 [API] |
| **60s** (vikiboss) | https://github.com/vikiboss/60s | 小红书/B站/微博/抖音/知乎热搜聚合开放 API | ✅ MIT | 5,766 [API] | 2026-09-10 [API] |
| **yupi-hot-monitor** (liyupi) | https://github.com/liyupi/yupi-hot-monitor | AI 热点监控（7+ 平台聚合、AI 真假识别、Agent Skill 封装） | ✅ 未见 license | 718 [API] | 2026-04-16 [API] |

### A4. 视频/评论向（与图文互补）

| 名称 | URL | 定位 | 开源 | Star | 最后活跃 |
|---|---|---|---|---|---|
| **open-clip-studio** (paragbml) | https://github.com/paragbml/open-clip-studio | 开源 Opus Clip 替代：长视频→爆款切片（本地 Whisper、病毒片段发现、动态字幕） | ✅ MIT | ≈0（新仓库）[API] | 2026-09-22 [API] |
| **short-video-generator-AI** (yukitorido) | https://github.com/yukitorido/short-video-generator-AI | LLM+Whisper 竖屏短视频流水线 | ✅ MIT | 721 [API] | 2026-09-23 [API] |
| **AI-Short-Video-Engine** (chenwr727) | https://github.com/chenwr727/AI-Short-Video-Engine | 文章→爆款短视频 Reels | ⚠️ 未见 license | 245 [API] | 2025-06-14 [API] |
| **youtube_yapper_trapper** (tonykipkemboi) | https://github.com/tonykipkemboi/youtube_yapper_trapper | CrewAI 采集分析 YouTube 评论反哺内容创作 | ⚠️ 未见 license | 68 [API] | 2024-06-10 [API] |
| **shortVideoCommentAndAgents** (yuer01) | https://github.com/yuer01/shortVideoCommentAndAgents | LLM 自动回复短视频评论 | ⚠️ 未见 license | 27 [API] | 2025-03-07（已停更）[API] |

### A5. Skills/角色包生态（2025–2026 新范式）

| 名称 | URL | 定位 | 开源 | Star | 最后活跃 |
|---|---|---|---|---|---|
| **openclaw/openclaw** | https://github.com/openclaw/openclaw | 通用 AI Agent 网关（"the AI that really does things"），大量中文社媒 Skill 的运行宿主 | ⚠️ NOASSERTION | 390,626 [API] | 2026-09-27 [API] |
| **VoltAgent/awesome-openclaw-skills** | https://github.com/VoltAgent/awesome-openclaw-skills | OpenClaw 技能精选（5,400+，含大量社媒运营技能） | ✅ MIT | 52,818 [API] | 2026-09-22 [API] |
| **agency-agents-zh** (jnMetaCode) | https://github.com/jnMetaCode/agency-agents-zh | 277 个即插即用 AI 专家角色，含 64 个中国市场智能体（小红书/抖音/微信等）+ DAG 编排器 | ✅ MIT | 20,960 [API] | 2026-09-17 [API] |
| **social-media-skills** (blacktwist) | https://github.com/blacktwist/social-media-skills | 社媒内容策略/创作/分析 Agent 技能集 | ✅ MIT | 530 [API] | 2026-05-01 [API] |
| **Crewm8-Social-Media-Manager-Skill-Graph** (gokulsvision) | https://github.com/gokulsvision/Crewm8-Social-Media-Manager-Skill-Graph | 37 技能×12 函数的社媒运营 playbook（X/LinkedIn/IG/TikTok） | ✅ MIT | 15 [API] | 2026-05-01 [API] |
| **XActions** (nirholas) | https://github.com/nirholas/XActions | X/Twitter 自动化全套：爬虫、MCP、**Tweet A/B Tester 示例**、实时分析 | ✅ Apache-2.0 | 546 [API] | 2026-09-24 [API] |
| **twitter** (wordware-ai) | https://github.com/wordware-ai/twitter | X 账号人格分析 Agent | ⚠️ 未见 license | 1,450 [API] | 2026-08-02 [API] |
| **social-push** (jihe520) | https://github.com/jihe520/social-push | "自我进化工作流"的社媒自动化 Skill | ⚠️ 未见 license | 529 [API] | 2026-06-28 [API] |
| **AiToEarn** (yikart) | https://github.com/yikart/AiToEarn | AI 内容变现工作流（中文社区热门） | ✅ MIT | 26,464 [API] | 2026-09-18 [API] |
| **postiz-agent** (gitroomhq) | https://github.com/gitroomhq/postiz-agent | Postiz 官方 CLI，接 Claude/OpenClaw 排程发帖 | ⚠️ NOASSERTION | 495 [API] | 2026-09-22 [API] |
| **build-xhs-content-pack** (Kimberlying) | https://github.com/Kimberlying/build-xhs-content-pack | X 长文/书籍→小红书发布包/公众号的 Codex Skill | 未核实 | 新仓库 [WEB] | 未核实 |

---

## B. 商业产品（闭源/SaaS，未实测，依据官网/新闻/PH 描述）

### B1. 国际

| 名称 | URL | 一句话定位 | 关键点 | 证据 |
|---|---|---|---|---|
| **HubSpot Breeze Social Agent** | https://knowledge.hubspot.com/social/use-social-agent-to-generate-social-posts | 大厂把"社媒 Agent"做进 CRM 主产品 | 从简报生成帖子、学习品牌声音、排期+监控 | [WEB] |
| **Zapier Agents（Social Media Manager）** | https://zapier.com/blog/orchestrate-zapier-agents/ | 无代码 Agent 团队里的社媒经理 Agent | 模板化生成→审批→发布，接 7,000+ 应用 | [WEB] |
| **Meta Business AI agents** | https://www.marketingdive.com/news/meta-streamlines-ai-use-brands-new-business-agent-creative-tools/801763/ | 平台方亲自下场做商家 AI 客服/营销 Agent | 2025 年推出，实验性，平台数据优势 | [WEB] |
| **Postiz（SaaS）** | https://postiz.com/agent | 开源项目的商业化版本 | AI Agents + MCP，20+ 渠道；PH 多轮发布 | [WEB] |
| **Mixpost** | https://mixpost.app/ | 自托管"无订阅费"的 Buffer 替代 | 排期/发布/分析；2026 新增 Threads | [WEB] |
| **Sprout Social AI Assist / Hootsuite OwlyWriter / Buffer AI Assistant** | 官方产品页 | 老牌 SMM 工具补 AI 写作 | 生成、改写、最佳发送时间建议、Alt-text | [推断]（能力属行业常识，具体功能未逐一验证） |
| **Feedhive / Typefully / Ocoya / Publer** | 官方站 | 独立 AI 社媒 SaaS | 内容生成+排期+轻度分析；X 向工具更多"成长型分析" | [推断] |
| **Currents AI** | https://hunted.space/dashboard/currents-2/launches/currents-ai | "24/7 AI 社媒深度调研" | 持续监控+研究，PH 发布 | [WEB] |
| **Soshi** | https://hunted.space/product/soshi-v0/launches/soshi | X 的 AI 社媒经理 | PH 发布 | [WEB] |
| **Spira AI** | https://www.producthunt.com/p/spira-ai | 创作者节奏 AI | PH AMA | [WEB] |
| **Cracked.ai** | https://hunted.space/product/cracked-ai/launches/cracked-ai-2 | "AI 网红"批量生成 | 虚拟人设账号矩阵（合规灰色地带） | [WEB] |
| **Stormy（虎之穴）** | https://news.mynavi.jp/techplus/article/techtopia-40/ | 日本 AI 网红营销 | 虚拟网红+商业合作撮合 | [WEB] |
| **Handpicked（荷兰）** | https://www.emerce.nl/nieuws/handpicked-lanceert-aiplatform-om-doelgroepen-virtueel-bevragen | **虚拟受众访谈平台**（空白点证据） | 用 AI 合成目标受众做前置调研 | [WEB] |
| **Minds (getminds.ai)** | https://getminds.ai/blog/synthetic-audience-research | 合成受众研究服务（空白点证据） | synthetic audience research 方法论 | [WEB] |
| **KAWO 科握** | https://kawo.com/ | 中国团队做的海外社媒管理 SaaS | 一站式社媒管理+数智化洞察，主打出海品牌 | [WEB] |

### B2. 国内

| 名称 | URL | 一句话定位 | 证据 |
|---|---|---|---|
| **OpenClaw 生态**（openclaw/openclaw + VoltAgent 技能库） | https://github.com/openclaw/openclaw | 中文自媒体圈的"Agent 操作系统"：社区用 16 个 Agent 运营 13 个平台成为流行玩法 | [API]+[WEB]（腾讯云开发者文章、即刻帖子） |
| **扣子 Coze** | https://developer.volcengine.com/articles/7526781265102995497 | 字节系 Agent 平台，"一天仿写 1000 条小红书热门笔记"工作流在此流行 | [WEB] |
| **社媒虾 MediaClaw** | https://microsoftedge.microsoft.com/addons/detail/…（Edge 插件页） | 小红书/抖音 AI 运营浏览器插件 | [WEB] |
| **薯AI小蜜（百度千帆市场）** | https://qianfanmarket.baidu.com/product/detail/1b62a7c7-424a-40fc-9470-7bb9b2c7cb63 | 小红书 AI 运营助手（千帆市场商品） | [WEB] |
| **餐赞** | https://www.canzan.com/ | 抖音本地生活 AI 营销（数字人/碰一碰等） | [WEB] |
| **蚁小二 / 易媒 / 微小宝 等老牌多平台分发** | 各官方站 | 一键分发+轻 AI 润色 | [推断]（行业常识，未逐一验证） |
| **新榜 / 千瓜 / 灰豚 等数据工具** | 各官方站 | 榜单/竞品数据，不提供 Agent 创作闭环 | [推断] |

### 社区讨论佐证（中文）

- 即刻热帖《用AI做社媒有那么难吗，随便研究一下就有正反馈》——印证 2026 年国内"个人用 Agent 做社媒"已成流行 [WEB]：https://m.okjike.com/originalPosts/6aaf60e6bd0563695b217f6b （正文 404，仅存于搜索引擎索引）
- 腾讯云开发者文章《用OpenClaw搭了16个AI Agent，一个人运营13个自媒体平台》[WEB]：https://cloud.tencent.cn/developer/article/2633959
- 知乎专栏《一人组建一支 Agent 军团，狂揽 11.9 万 Star》[WEB]：https://zhuanlan.zhihu.com/p/2055704731293593975
- 火山引擎开发者《扣子Coze实战：一天仿写1000条小红书热门笔记》[WEB]：https://developer.volcengine.com/articles/7526781265102995497
- 阿里云开发者《运营团队的知识管理：用 Agent 记忆来解决"经验随人走"的问题》[WEB]：https://developer.aliyun.com/article/1763130

---

## C. 格局总结

### (a) 已经烂大街的标配（人人都有，几乎无法差异化）

| 功能 | 开源证据（亲眼看到） | 商业证据 |
|---|---|---|
| 文案生成/润色/仿写/去 AI 味 | xuboboo Skill、Easel、Xiangyu-CAS、langchain、几乎所有 A1/A2 仓库 [README/API] | HubSpot Breeze、Sprout、Buffer、Coze 模板 |
| 多平台改写与格式适配 | Easel（同一素材→卡片/短视频/知乎长文）、Postiz、postbot、autopost-ai [README/API] | Zapier、Publer、Ocoya |
| 排期/定时发布/多平台分发 | Postiz、Mixpost、MultiPost、postbot、dreammis、Admin6016 [API] | 老牌 SMM 全线 |
| 热点/热搜聚合选题 | Easel、MediaCrawler、60s、yupi-hot-monitor、ScrapeCreators、OpenBiliClaw [API] | 新榜/千瓜、Postiz |
| 配图/封面/卡片生成 | RedInk、guizang-social-card-skill、xuboboo、op7418 [README/API] | Canva AI、稿定 AI |
| 简单风控/合规检查 | xuboboo 合规校验、Easel 敏感检查+发布门禁、alanl1234 反检测指纹 [README] | 商业矩阵工具内置 |
| 账号画像/persona 记忆 | Easel 画像记忆、Xiangyu-CAS persona.md、kisinad Mem0 [README] | HubSpot brand voice |
| 多 Agent 编排骨架 | LangGraph/CrewAI 全家桶：langchain、autopost-ai、tonykipkemboi、GrowthOS [README] | Zapier Agents |

> 判断依据：以上每一项都有 ≥2 个我亲眼核实元数据或 README 的仓库支撑，且多为 2024 下半年～2026 年的"技能包"爆发式供给，边际成本趋近于零。

### (b) 几乎没人做/存在空白的领域（本项目差异化机会）

按"空白程度"从大到小：

1. **真实数据的因果归因复盘（最大空白）。** 几乎所有项目停在"排期/发布"，发布后只做"浏览量报表"级别展示。
   - 亲眼看到的证据：autopost-ai 的"weekly report"基于内部排程状态而非真实表现数据 [README]；Easel 声称有"归因"层（数据回收/复盘/ROI/画像记忆），但 README 表格只是能力清单，**归因是否做"变量→效果"级别的因果分析未核实** [README]；Xiangyu-CAS 的"复盘"是把分析结论写成 Markdown 存档，不是统计学习 [README]。商业侧 Sprout/Hootsuite 的"建议发送时间"是聚合统计，不是单篇归因 [推断]。
   - 机会：发布→回收→**在账号/内容变量层面做归因**（标题结构、发布时间、封面风格、话题标签对互动的边际贡献），并按归因结果自动更新创作策略。

2. **评论区运营自动化（很空）。** 评论是小红书/抖音起量的核心杠杆，但工具供给极弱。
   - 亲眼看到的证据：yuer01/shortVideoCommentAndAgents（27★，2025-03 已停更，只是 LLM 回评论原型）[API]；white0dew 自动评论（机械回复）[API]；Xiangyu-CAS 有"通知评论逐个回复" [README]；cs-lazy-tools 是客服向不是运营向 [API]；ScrapeCreators 提供评论挖掘（研究向，不闭环）[API]。
   - 机会：评论→用户画像→选题反哺→人设一致回复→评论区转化漏斗的完整闭环，基本无人做。

3. **受众仿真与校准（几乎只有学术界和广告研究在做）。**
   - 证据：Deepsona（学术，multi-trait synthetic audiences）[WEB]；Minds、Handpicked（商业合成受众访谈）[WEB]；博报堂 Virtual Sei-katsu-sha（广告研究）[WEB]。**开源社媒创作工具里一个都没有**（我检索的 16 组 GitHub 查询结果中未出现任何受众仿真功能）[API]。
   - 机会：用真实粉丝画像+历史互动数据校准的"模拟受众"，在发布前预演内容反应，并用发布后真实数据回灌校准——这是硬核且几乎无对手的方向。

4. **多账号实验设计 / 对照测试（几乎没有）。**
   - 证据：XActions 有一个 "Tweet A/B Tester" 示例脚本（单平台、粗粒度）[WEB]；LOLA（Marketing Science Institute 学术项目，LLM 辅助内容实验在线学习）[WEB]；小红书生态里"矩阵测号"是民间手工实践，无系统化工具 [推断]。现有矩阵工具（Admin6016、alanl1234、creatorhub）全部是"批量发文"，不是"实验设计" [API]。
   - 机会：把账号矩阵当实验平台——同主题多版本、随机化、对照账号、最小样本量判断、显著度报告——完全空白。

5. **经验闭环学习（有萌芽，但极浅）。**
   - 证据：Easel"把有效结构沉淀回账号画像" [README]；Xiangyu-CAS 知识库 Markdown 沉淀 [README]；jihe520/social-push 自称"self-evolution workflows" [API 描述]；rabden/X-twitter-social-manager-skill 自称 self-evolving（提取声线模式）[API 描述]。但这些都是**文本记忆/规则**，不是统计学习；没有任何一个做"经验失效管理"（指标修正→关联经验作废）——而父项目 AGENTS.md 已要求这一机制，是真实先发优势。
   - 机会：可追踪、可撤销、按（平台,账号,来源）隔离的经验库 + 指标修正联动失效 + 发布后自动回写验证。

6. **国内平台官方授权发布（结构性空白）。** 几乎所有中文工具用逆向 API/浏览器自动化/CDP（alanl1234、Xiangyu-CAS、BetaStreetOmnis、kvnZero 均为逆向 [README/WS]），官方开放平台代发权限难以申请（上一轮已核实抖音需能力申请、小红书能力未确认 [WS]）。**谁先做到合规官方接入，谁就有护城河**；否则只能靠"人工确认+导出发布"过渡。

### 对父项目的三点结论

1. **最直接对标物是 ZJU-REAL/Easel**（全流程+归因声称，Apache-2.0，浙大/北大背书，社区增长快）。差异化不要押在"流程更全"，要押在 Easel 没做实的部分：**归因深度、实验设计、受众校准、经验失效管理、官方授权**。
2. "Skill 包"形态（xuboboo、Xiangyu-CAS、Crewm8）已经证明：**中文运营方法论 + MCP/Agent 接口**是 2026 年最容易被分发和传播的形态，父项目的四角色设计可以此形态对外，但核心数据闭环留在自己服务端。
3. 上一轮调研的 5 个仓库仍是流程设计的好参考，但格局判断需要更新：2026-09 时点，生成侧供给严重过剩，**运营后链路（归因/评论区/实验/校准）是唯一无人占领的高地**。

## D. 数据与诚实性说明

- 本报告所有 star 数、pushed_at、license 均来自 2026-09-27 GitHub API 实时快照 [API]；星数会变动。
- 我亲自读了 README 的仓库：Easel、Xiangyu-CAS/xiaohongshu-ops-skill、alanl1234/xiaohongshu-matrices-cli、xuboboo/xiaohongshu-viral-note-agent-skill、rayane-rhsn/autopost-ai；langchain-ai/social-media-agent、RedInk、EthanYoQ、ai-xiaohs、kvnZero、Klaudiusz321 由工作区上一轮调研核实 [WS]。
- 商业产品全部未登录实测，功能描述来自官网/新闻/PH 页面 [WEB]；标注 [推断] 的条目是我的行业判断而非核实结论。
- 搜索受限说明：GitHub 无鉴权限流（10 次搜索/分钟、60 次核心/小时），已按限流分批复跑并补齐；Product Hunt 与部分国内站点在本环境无法直接抓取（JS 渲染/网络策略），其信息来自搜索引擎索引。
- 未做穷尽搜索，不保证不存在我未发现的同类项目；"空白"结论=检索范围内未见，非数学证明。
