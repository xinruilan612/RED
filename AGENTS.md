# 注意事项

1. 每次改动完成后，都必须创建一个对应的Git commit，以便后续追踪和回滚。
2. 每次改动后，都必须编写或更新相关测试，并在交付给用户前，确保所有测试和验证全部通过。

## 参赛要求入口

开展产品设计、实现、验收或参赛材料编写前，阅读 [参赛要求与交付对照](docs/CONTEST_REQUIREMENTS.md)。详细规则在该文档维护，不在此重复。

区分官网要求、待核实的截图材料与项目建议；未确认适用性的其他赛题规则不得作为本项目硬性要求。提交前复核最新官方通知，产品完成状态和测试结论必须有实际证据。

文档检查命令：`python3 -m unittest discover -s tests -v`；空白检查命令：`git diff --check`。有产品代码后，还需执行对应的产品测试。

软件设计入口：[架构、模块与流程](docs/design/README.md)；开源参考：[GitHub 项目调研](docs/research/GITHUB_PROJECTS.md)。这些是开发前方案，尚不能作为实现或性能证据。修改图件后运行 `python3 scripts/build_design_atlas.py` 并验证生成物一致。

当前设计基线为 v0.3 五层（UI/Runtime Console、Orchestrator、Agents、Tools/Skills、Memory）与 audience/research/content/reviewer 四角色。实现前阅读 [迁移计划](docs/design/MIGRATION.md)，不要混用旧版角色契约。

角色卡入口：[四 Agent 规范](docs/agents/00_overview_and_all_agents.md)。运行协议以 [统一执行协议](docs/design/AGENT_PROTOCOL.md) 和机器契约为准；编辑独立卡片后运行 `python3 scripts/sync_agent_cards.py`，不要手动维护合并部分。

## 运营助手 v0.4 设计增补（2026-09-20）

用户确认目标平台为小红书、抖音，暂不接入 Postiz。指定参考为 Klaudiusz321/social-media-agents；与 langchain-ai/social-media-agent 分开记录。

上一轮仅完成设计；用户随后已明确授权在现有 Demo 增加功能并整理排版。沿用已有文件夹，不额外建立 AGENT.md。v0.3 机器契约与四角色继续作为当前创作基线；v0.4 运营扩展见 [技术提案](docs/design/ARCHITECTURE.md#运营闭环-v04-技术提案) 和 [推进计划](docs/design/MIGRATION.md#运营闭环-v04-推进计划)，未实现条目不得写成已完成。

未来发布必须绑定用户批准的账号、平台、稿件/媒体版本和计划时间；创作 SUCCEEDED 不表示发布成功。指标缺失不得填零，模拟受众反应不得写入真实历史；经验更新可追踪、可撤销，不能绕过人工确认。平台能力须以适用的官方接口、账号授权和实测为准。

## v0.4 本机 Demo 实现约定

运营状态由 backend/operations.py 与 /api/operations 管理，沿用本地会话、CSRF、SQLite 事务、版本校验与幂等。此为创作 schema 外的演示适配，不代表完成生产机器契约迁移。平台 API 未接通；示例趋势不标实时、SIMULATED 不等于真实发布、MANUAL_REPORTED 不等于核实成功。模拟指标/经验不得进入真实 AI 上下文；经验只复用于同平台同账号，指标修正使关联经验失效。

## v0.5 账号运营约定

用户已授权账号档案/历史、四角色升级、独立分析角色及周运营循环。创作子流程仍为四角色；发布后 analytics 在 backend/analytics.py 独立执行确定性规则，不调用收费模型。扩展机器契约为 design_contract.json.operations_extension，Operations schema_version=2；本机角色字段适配见卡片文末。

账号关联使用 account_id，不用昵称；真实历史导入与 AI 模式分开。指标或分类修正须使依赖分析、经验与计划失效；撤销经验后计划也需重新生成。新上下文只读取当前有效且同来源的经验；旧任务快照保留审计。前端新增 account.js，修改后需运行 node --check；原有四角色及 HTTP 回归测试继续执行。
