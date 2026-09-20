# v0.3 迁移与实施计划

本轮只修订设计资料与验证，不改变已运行的 starter。依据为用户三张图片和本轮早期的源码静态检查；收尾时工作区已移除旧 starter 文件，以下记录为移除前的实现状态。

## 1. 两条历史基线

| 原始位置 / 角色 | 新归属 | 迁移方法 |
| --- | --- | --- |
| starter audience_agent | audience | 保留洞察，新增历史 Tool、Memory 引用与冷启动说明 |
| starter research_agent | research | 保留素材边界，增加来源片段、版本、冲突检查 |
| starter strategy_agent | content.strategy | 策略仍是独立产物，但不再是独立 Agent |
| starter writer_agent | content.outline/hook/title/body | 分阶段成果与失效规则 |
| starter revision_agent | content.revise | 同角色返修，保留阶段/段落定位并回 reviewer |
| starter review_agent | reviewer | 八项检查及程序守卫、阻断项检查、版本绑定 |
| 旧设计 planner | audience + research + content.strategy | 取消前置强制选题确认，主题在 Brief 指定 |
| 旧设计 writer | content | 合并策划与返修能力 |
| 旧设计 designer | L4 版式测量/渲染 Tool | 图文建议来自 content，不新增第五个角色 |
| 旧设计 reviewer | reviewer | 保留审稿，统一新版门槛和返修目标 |

## 2. 现有代码与目标差距

此前 app/orchestrator.py 使用 asyncio.gather 做受众/素材并行，之后策略、写作、审核、独立改稿；app/schemas.py 的状态仅 running/completed/failed。循环结束无论是否审核达标都标 completed，不能直接映射新设计 SUCCEEDED。

现有 ui.py 展示 traces 和“发布前请人工确认”文字，尚无持久化确认 API。SQLite 存运行结果不等于 Profile/Material/History 检索系统；已有模型输出和 JSON 校验不等于实现工具调用。Streamlit / FastAPI / SQLite 原型可继续用于流程验证。

此前解压后的大部分 starter 源码未纳入 Git；收尾时已发现旧目录移除。本轮不恢复、提交这些删除或批量加入用户的其他文件。正式迁移前应排除 .env、数据库、缓存和虚拟环境，建立可复现源码基线，再变更运行逻辑。

## 3. 分阶段实施

| 阶段 | 范围 | 交付与通过条件 |
| --- | --- | --- |
| A 契约与源码基线 | schema v2、四角色名、五阶段、状态机、Memory/Tool/Skill 接口 | 本地单元测试、旧数据读取适配，未审核完成记录标 needs_review |
| B 四 Agent mock | 并行汇合、content 合并、reviewer 回路、人工确认 | 同快照汇合、改稿必复审、上限暂停、不同版本不能接受 |
| C Tools/Skills/Memory | 首先接手工素材/历史，加入确定性检索聚合 | 来源可追踪、权限拒绝、冷启动、Skill 版本固定 |
| D Runtime 与后台任务 | 事件流、队列、租约、恢复、取消、预算 | 断线重放、单支恢复、费用记账、按钮幂等 |
| E 产品 UI 与导出 | 网页编辑、候选稿对比、固定模板、确认与导出 | 外部用户无需 CLI；越权、渲染和并发测试 |
| F 真实模型与参赛证据 | 小额预算配置后验证模型适配及真人任务 | 原始样本、失败、耗时、成本、版本和同条件对照 |

每阶段相关测试和验证通过后独立 Git commit；用户本轮授权的是设计重规划，实施阶段按后续开发范围执行。不要先把六角色全部删除再补功能；通过版本化接口逐步迁移。

## 4. 数据与兼容

旧 WorkflowState 保留 schema_version=1 只读映射：strategy → content_artifacts.strategy，draft → legacy_candidate；traces 保留 legacy 标记。旧 completed 不推断人工接受或发布；缺少 evidence/confirmation 时需新审核。

新增 API 使用 /api/v1；WorkflowState/RuntimeEvent 使用 schema_version=2，角色产物使用 1.1.0，原 /api/runs 在迁移期保持旧契约或明确废弃日期，不静默改变字段含义。数据库先备份并做迁移演练，配置和模型密钥不写进迁移脚本。

## 5. 开发启动记录

用户已于 2026-09-20 确认开发。新源码位于 backend/；阶段进度及运行验证以 [开发记录](../IMPLEMENTATION_STATUS.md) 为准。本文前面的“尚未实现”描述是设计时基线，不能代替当前实现清单。
