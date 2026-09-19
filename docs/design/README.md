# 多 Agent 图文创作产品 · 软件设计资料 v0.1

日期：2026-09-20。性质：开发前设计基线；未实现、未部署，参数均为建议值或待实测目标。

本设计面向 AIC AI+软件创新的软件设计附录，按“用户通过网页使用”的产品形态编写。仓库当前只有文档和文档验证代码，不把设计图当作产品完成证明。

## 阅读入口

1. [软件架构与关键参数](ARCHITECTURE.md)：系统边界、技术选型、部署、数据一致性、成本与性能。
2. [模块与数据接口设计](MODULES.md)：模块职责、四个 Agent 契约、数据表、API、权限及错误处理。
3. [流程与状态设计](FLOWS.md)：业务流程、运行状态、用户确认、返修、重试、版本冲突。
4. [附录交付与验证计划](APPENDIX_PLAN.md)：核心代码、原始测试数据、参考资料和佐证材料的后续交付路径。
5. [GitHub 相近项目调研](../research/GITHUB_PROJECTS.md)：可借鉴能力、许可和产品形态差异。
6. [离线图册](DESIGN_ATLAS.html)：无需联网即可查看四张矢量图，可从浏览器打印。

## 图件

| 图号 | 内容 | 可插入报告的矢量图 | 可编辑 Mermaid 源文件 |
| --- | --- | --- | --- |
| D1 | 软件总体架构 | [SVG](diagrams/architecture.svg) | [Mermaid](diagrams/architecture.mmd) |
| D2 | 创作及返修流程 | [SVG](diagrams/workflow.svg) | [Mermaid](diagrams/workflow.mmd) |
| D3 | 云端部署拓扑 | [SVG](diagrams/deployment.svg) | [Mermaid](diagrams/deployment.mmd) |
| D4 | 任务生命周期 | [SVG](diagrams/lifecycle.svg) | [Mermaid](diagrams/lifecycle.mmd) |

图中的常规路径为实线；异常、恢复或控制路径为虚线。模块 ID 与模块文档对应。图示为逻辑关系，不代表每个节点都需要独立机器。

## 设计决策

- 采用 Next.js 前端、FastAPI 业务 API、LangGraph 四 Agent 工作流、PostgreSQL、Redis/Celery、对象存储的建议组合；具体版本在编码时兼容性验证并锁定。
- 服务器调用模型 API；用户无需本地 CLI、模型密钥或浏览器扩展。
- MVP 使用用户提供的真实素材和固定图文模板；不包含平台自动发布、热点爬取或 AI 生图。
- 用户控制选题和最终稿；建议稿与用户稿分离，局部改稿必须展示差异。
- 全局预算、超时、重试与路由规则由程序执行，不依赖提示词遵守。
- 四个 Agent 为独立职责和上下文，可共用模型；编排器是程序，不额外增加一个每步都调用模型的主管。

开发前仍需确定首个内容领域、试用人数、云服务商、模型供应商及付费预算。这里给出可执行的默认设计，不代表已购买或已获预算批准。

## 可重复检查

在仓库根目录运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/build_design_atlas.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

图件由脚本统一生成。修改图时编辑脚本中的节点和边，重新生成并检查；运行状态的权威集合在 [design_contract.json](design_contract.json)。文档测试不能代替真实软件测试。
