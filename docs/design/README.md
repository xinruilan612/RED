# 多 Agent 图文创作产品 · 软件设计资料 v0.3

> 阅读顺序：当前实现见 [开发进度](../IMPLEMENTATION_STATUS.md)；本轮新方向见文末 v0.4 章节。前文 v0.3 内容保留为创作子流程与历史设计基线。

依据：用户提供的三张架构图片及 docs/agents 角色卡。v0.3 在 v0.2 五层四角色基础上统一执行契约；旧版可从 Git 历史追溯。六角色 starter 的描述依据此前源码核验，本次未修改其运行逻辑；收尾时发现工作区已移除旧原型文件，这些变动不纳入本次提交。

## 设计结论

软件按五层组织：**L1 UI / Runtime Console → L2 Orchestrator → L3 Agents → L4 Tools / Skills → L5 Memory**。五层表示职责分离，不是五台服务器，也不是一次请求必须逐层串行走完。身份、模型适配、数据库和队列是承载这些层的服务设施。

四个 Agent 固定为 **audience（受众洞察）、research（素材研究）、content（内容策划创作）、reviewer（主编审核）**。前两个基于同一输入快照并行；结果汇合后由 content 依次产出 Strategy、Outline、Hook、Title、Body。返修仍由 content 执行，修改后必须重新审核，通过后等待人工确认。

图片中“改稿 → 最终内容”的简略连线按第三张图片的“再次审核”补全；不允许改稿绕过审核和人工确认。无历史数据时可以基于 Brief 做受众假设，但必须注明未验证；素材不足不能凭空补造。

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [Agent 统一执行协议](AGENT_PROTOCOL.md) | 状态、分支、证据与审核守卫、预算及恢复 |
| [四张 Agent Cards](../agents/00_overview_and_all_agents.md) | 角色职责、输入输出、工具技能与验收 |
| [架构与参数](ARCHITECTURE.md) | 五层架构、产品部署、边界、预算、性能与设计参数 |
| [模块与数据接口](MODULES.md) | 角色契约、模块归属、数据库、API、审核规则 |
| [业务与状态流程](FLOWS.md) | 并行汇合、返修循环、人工确认、失败/取消/恢复 |
| [Tools、Skills 与 Memory](TOOLS_SKILLS_MEMORY.md) | 能力/方法/资料的区别、授权、读写与版本 |
| [Runtime Console](RUNTIME_CONSOLE.md) | 状态、输入输出、工具、记忆、耗时、费用、重试事件 |
| [迁移计划](MIGRATION.md) | 六角色原型和旧四角色方案如何过渡到新架构 |
| [参赛附录追踪](APPENDIX_PLAN.md) | 核心代码、测试数据、参考资料与佐证 |
| [离线图册](DESIGN_ATLAS.html) | 五张图，可直接打开、打印 |
| [验证记录](VALIDATION.md) | 本轮实际执行的文档与图件检查 |

## 图件索引

| 图号 | 内容 | SVG | Mermaid |
| --- | --- | --- | --- |
| D1 | 五层软件架构 | [SVG](diagrams/architecture.svg) | [源文件](diagrams/architecture.mmd) |
| D2 | 四 Agent 并行与返修 | [SVG](diagrams/workflow.svg) | [源文件](diagrams/workflow.mmd) |
| D3 | 产品云端部署 | [SVG](diagrams/deployment.svg) | [源文件](diagrams/deployment.mmd) |
| D4 | 任务生命周期 | [SVG](diagrams/lifecycle.svg) | [源文件](diagrams/lifecycle.mmd) |
| D5 | Runtime Console 事件链 | [SVG](diagrams/runtime.svg) | [源文件](diagrams/runtime.mmd) |

## 产品范围与事实状态

目标仍是用户打开网页即可使用的产品。MVP 支持真实素材导入、四角色协作、用户改稿与确认、模板导出和手工回填发布指标；不自动抓取平台、不自动发布、不承诺爆款。

此前核验的 starter 原型是 Streamlit + FastAPI + SQLite、六角色及同步等待结果。新设计含任务队列、持久化暂停恢复、真实工具与记忆、运行控制台；这些能力尚未实现。UI 的“人工确认提醒”不等于已有确认 API。

预算参数为待验证建议，不是费用授权；本轮不调用付费模型。独立测试用例、mock 工作流、真实模型质量和真实用户反馈需要分别报告。

## 维护与复现

机器可读契约：[design_contract.json](design_contract.json)。图件唯一编辑入口为 scripts/build_design_atlas.py；JSON 中的流程与 SVG/Mermaid 必须一致。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/sync_agent_cards.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/build_design_atlas.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

开发阶段按 [迁移计划](MIGRATION.md) 分段实施，每段相关测试通过后提交 Git。当前文档不宣称产品已达到性能目标或参赛成品要求。

## 运营助手 v0.4 设计入口

新版方向已调整为小红书、抖音热点驱动的博主运营助手，暂不接入 Postiz。v0.3 四角色和图件仍表示创作子流程，不表示完整运营闭环；此前“尚未实现”描述为历史设计基线，当前情况以 [开发进度](../IMPLEMENTATION_STATUS.md) 为准。

- [六环节需求、平台边界与技术方案](ARCHITECTURE.md#运营闭环-v04-技术提案)
- [分阶段实施与验收](MIGRATION.md#运营闭环-v04-推进计划)
- [指定参考仓库与国内平台核查](../research/GITHUB_PROJECTS.md#运营助手参考增补)

本轮只修改既有文档并复跑现有 Demo，未更改图件、机器契约或产品代码。热点、发布、指标与学习尚未实现；本目录原有云端部署选型也不能作为当前运行证据。

## v0.4 Demo 实施进展

用户在设计交付后授权功能实现。现在已有选题来源导入、平台创作上下文、发布演练/人工回填、指标录入及经验确认复用；这是本机适配，尚无实时热榜、国内平台API、自动指标回流或模型在线训练。当前能力以 [开发记录](../IMPLEMENTATION_STATUS.md) 和 [实际验证](../WEB_DEMO_VALIDATION.md) 为准，前述“未实现”是设计阶段快照。
