# 有迹 · RED 小红书多 Agent 创作工作台

当前改版主线：**输入主题或产品资料 → 可选联网搜索 → RAG 资料库 → 四 Agent 创作 → 对话改稿 → 发布或导出 → 评论反馈改进下一篇**。

先读 [正式改版需求](docs/design/CONNECTED_CREATOR_REQUIREMENTS.md)，再读 [阶段进度、代码依据与冲突裁决](docs/CONNECTED_CREATOR_STATUS.md)。2026-10-11 从兰昕睿分支 b50c628 继续：先统一 AI 参考资料，再补产品差距。历史验收和本轮补丁分开记录；不扩展图片、视频、预测或新平台。

## 开发入口

教师Windows便携包使用根目录“一键启动.cmd”；无需安装Python/PostgreSQL，首次创建独立SQLite，真实模型在网页内另配。构建入口 `scripts/package_teacher.py`，说明源文件 [评审包使用说明](packaging/teacher/README.txt)。它与下文开发用PostgreSQL启动器不同；包内不带作者密钥、已有账号库或平台登录状态。macOS不运行Windows二进制，原生Mac仍未验收。

- [协作与工程约束](AGENTS.md)、[参赛要求](docs/CONTEST_REQUIREMENTS.md)
- [架构与设计](docs/design/README.md)、[统一执行协议](docs/design/AGENT_PROTOCOL.md)
- [四 Agent 说明](docs/agents/00_overview_and_all_agents.md)
- [部署说明](docs/DEPLOYMENT.md)、[Windows 启动](docs/WINDOWS.md)、[本机连接说明](docs/XHS_LOCAL_SYNC.md)

继续维护现有 FastAPI、PostgreSQL、LangGraph 与 Worker、原生网页和四角色，不另建项目。正式入口为 backend.api 与 backend.worker；backend.web 为旧兼容服务。启动前核对当前数据库和端口，继承基线曾在8775独立环境验证；不代表本轮或本机服务已启动，默认库兼容性未复验。

```bash
runtime/venv/bin/python scripts/local_dev.py start
```

该命令为现有启动入口，历史验收使用8775独立环境，不能由该历史记录推定本轮默认启动命令通过。不要删除数据库来排查启动；不要打印或提交 .env、Cookie、API Key、恢复码或 runtime 数据。

## 当前代码与差距

现有代码包含有限小红书读取、公开来源研究与候选确认、文档入库、BM25/可选混合检索、平台 DeepSeek/BYOK、四角色与 Markdown 导出。工作台不展示私密账号内容及“已同步笔记与评论”块，后台存储保留。观测关联具体笔记与时间，未知指标不填零；来源配置不证明当前接通，京东/淘宝域名过滤不等于商城专用接口。

本轮核对并补齐：模型配置自助恢复、文档解析预览和格式保真、可选能力开关、对话改稿和选定公开笔记评论指导下一篇。已有部分不重做；逐项状态以证据页为准。平台自动发布不作为本轮已完成能力，保留复制、文字导出与用户自行发布后归档；人工归档不等于发布成功。

运行提示词实际由 backend/live.py 的 messages_for 构造，经 backend.runtime 和 model_router.Calls 执行；角色卡只提供规范。已存在的 [原创创作](docs/design/ORIGINAL_CREATION.md) 将通用方法、相关领域样例和独立产品事实分组冻结；借鉴结构，不复制别人的表达、经历或功效，不承诺爆款。

基础模式使用服务端配置的 DeepSeek，用户可自带模型；未配置或未实测时显示实际状态。保存模型配置不等于测试成功，测试与真实创作遵守独立费用预算。免费模拟与真实结果分开；图片、视频和预测保留历史资料，不是本轮主流程。

## 后续推进与验证

说明对齐 → 已有能力复核 → 模型与资料输入 → 四 Agent 与评论反馈 → 完整验收。每阶段更新测试、按实际范围验证并独立记录；旧“停在第二阶段”的限制不再适用于本轮授权。

文档阶段只运行文档测试、角色卡同步检查、git diff --check；实现阶段按 AGENTS.md 运行真实 PostgreSQL 临时 schema 集成测试、前端和恢复测试。收费模型、真实数据采集、公开发布及公网部署分别记录，不以替身测试代替。

## 历史设计与兼容能力

[内容试飞台方案](docs/design/GROWTH_CAMPAIGN_PRODUCT.md)、[风洞](docs/windtunnel/README.md)、[接单推广](docs/design/SKILL_SERVICE_PROMOTION.md)、[v0.4 技术方案](docs/design/ARCHITECTURE.md#运营闭环-v04-技术提案)、[历史开发记录](docs/IMPLEMENTATION_STATUS.md) 保留为参考。已有抖音兼容不扩大为本轮平台范围；不新增管理后台、客户端或技能市场，暂不接入 Postiz。旧“平台自动取数全未实现”或“实时同步”等概括不作为当前结论，逐项以代码核对及后续实测为准。
