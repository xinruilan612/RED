# 有迹 · RED 小红书多 Agent 创作工作台

当前改版主线：**输入主题或产品资料 → 可选联网搜索 → RAG 资料库 → 四 Agent 创作 → 对话改稿 → 发布或导出 → 评论反馈改进下一篇**。

先读 [正式改版需求](docs/design/CONNECTED_CREATOR_REQUIREMENTS.md)，再读 [阶段进度、代码依据与冲突裁决](docs/CONNECTED_CREATOR_STATUS.md)。第二轮已完成工作台与 RAG 的核心实现及工程验证；真实模型质量与未实测来源保留边界，详见原进度文档。

## 开发入口

- [协作与工程约束](AGENTS.md)、[参赛要求](docs/CONTEST_REQUIREMENTS.md)
- [架构与设计](docs/design/README.md)、[统一执行协议](docs/design/AGENT_PROTOCOL.md)
- [四 Agent 说明](docs/agents/00_overview_and_all_agents.md)
- [部署说明](docs/DEPLOYMENT.md)、[Windows 启动](docs/WINDOWS.md)、[本机连接说明](docs/XHS_LOCAL_SYNC.md)

继续维护现有 FastAPI、PostgreSQL、LangGraph 与 Worker、原生网页和四角色，不另建项目。正式入口为 backend.api 与 backend.worker；backend.web 为旧兼容服务。启动前核对当前数据库和端口，本轮已重启并验证8775独立环境；默认库兼容性未复验。

```bash
runtime/venv/bin/python scripts/local_dev.py start
```

该命令仅为现有启动入口，本轮验收使用8775独立环境，没有验证该默认启动命令。不要删除数据库来排查启动；不要打印或提交 .env、Cookie、API Key、恢复码或 runtime 数据。

## 当前代码与差距

现有代码包含有限小红书读取、公开来源研究、文档入库、BM25/可选混合检索、平台 DeepSeek/BYOK、四角色与 Markdown 导出。已绑定账号页已有隐藏同步笔记/评论块的代码，后台存储仍在；未绑定展示和全部指标归属尚需清理。来源配置不证明当前接通，京东/淘宝域名过滤不等于商城专用接口。

待补主链包括：所有观测逐篇归属、来源真实可用状态、文档解析预览和表格/链接保真、可选能力开关、完整对话改稿、选定公开笔记评论指导下一篇、发布能力核实及图片/素材包替代。平台真实发布目前未发现项目适配，人工归档不等于发布成功。

运行提示词实际由 backend/live.py 的 messages_for 构造，经 backend.runtime 和 model_router.Calls 执行；角色卡只提供规范。当前仍有精简测试输出限制，后续“四 Agent 协作”阶段联动修改，本轮未改 Prompt。

基础模式目标是平台服务端 DeepSeek，用户可自带模型；当前代码默认/连接状态不能由目标推定。保存模型配置不等于测试成功，测试与真实创作遵守独立费用预算。图片理解、图片生成、视频生成分别核实，免费练习和预测为后续附加需求。

## 后续推进与验证

说明对齐 → 工作台与 RAG → 模型与资料输入 → 四 Agent 协作 → 评论复盘与发布 → 完整验收。每阶段更新测试、按实际范围验证并独立提交；本轮停在第二阶段，未自动进入第三阶段。

文档阶段只运行文档测试、角色卡同步检查、git diff --check；实现阶段按 AGENTS.md 运行真实 PostgreSQL 临时 schema 集成测试、前端和恢复测试。收费模型、真实数据采集、公开发布及公网部署分别记录，不以替身测试代替。

## 历史设计与兼容能力

[内容试飞台方案](docs/design/GROWTH_CAMPAIGN_PRODUCT.md)、[风洞](docs/windtunnel/README.md)、[接单推广](docs/design/SKILL_SERVICE_PROMOTION.md)、[v0.4 技术方案](docs/design/ARCHITECTURE.md#运营闭环-v04-技术提案)、[历史开发记录](docs/IMPLEMENTATION_STATUS.md) 保留为参考。已有抖音兼容不扩大为本轮平台范围；不新增管理后台、客户端或技能市场，暂不接入 Postiz。旧“平台自动取数全未实现”或“实时同步”等概括不作为当前结论，逐项以代码核对及后续实测为准。
