# 四 Agent 统一执行协议

v0.3 · 设计待实现。本文规定路由与校验语义；[design_contract.json](design_contract.json) 是 ID、预算、状态、事件及权限名单的唯一机器来源。角色字段见 [Agent Cards](../agents/00_overview_and_all_agents.md)。发生差异须修订契约并通过测试，不能在提示词中静默覆盖。

## 1. 版本与状态

设计版本为 0.3，WorkflowState/RuntimeEvent 的 schema_version 为整数 2，角色产物的 schema_version 为字符串 1.1.0。这是三个不同版本域，不应相互比较。旧角色 schema 1.0.0 必须显式迁移；未迁移不接入新流程。

agent 固定 audience / research / content / reviewer。产物依次为 AudienceInsight / ResearchPack / ContentDraft / ReviewReport。旧名 ResearchNotes、ContentArtifacts、ReviewResult 不再是对外接口。

运行状态使用 [生命周期](FLOWS.md) 中的八个大写值，WorkflowState 的字段统一为 `run_status`。`current_stage` 表示阶段，不是生命周期；API 返回同名字段。存储 runs.status 是该字段的内部映射。产物的 status 只表示该产物是否可用。节点执行状态可为 pending/running/succeeded/failed/cancelled，不与任务状态混用。

WAITING_USER 用 wait_reason 区分 missing_material、hypothesis_permission、final_confirmation、revision_limit、version_conflict、budget_exhausted、policy_unavailable。FAILED/CANCELLED/EXPIRED/SUCCEEDED 不原地复活。额度耗尽先保存候选并进入 budget_exhausted；只能取消或显式创建受日额度约束的新 run，旧 run 关闭为 CANCELLED，不允许 resume 重置计数。硬执行时限到达则 FAILED。

## 2. 分支可用性与路由（按顺序执行）

先判断取消、权限、版本、工具执行错误和预算；仅执行成功的分支可参与资料充分性判断。两支必须使用相同 snapshot_id（Brief/Profile/Material/History 版本集合）；Agent 不调度另一个 Agent。

| 条件 | 确定动作 | 等待原因 |
| --- | --- | --- |
| 一支传输失败且仍可重试 | RETRY_WAIT，仅重试该支；不把错误变为空结果 | 无 |
| 无历史、allow_hypothesis_mode=true | Audience needs_data 可参与 Join；输出低置信度及假设标签 | 无 |
| 无历史、allow_hypothesis_mode=false | WAITING_USER，补历史或明确授权假设模式 | hypothesis_permission |
| 非核心主张缺证据，可删除且仍满足 Brief | Research partial 可参与 Join；将主张列入 prohibited_claims | 无 |
| 核心主张缺失、受众与素材无法共同满足 Brief | WAITING_USER，列出准确问题及已有证据 | missing_material |
| 规则包核心检查不可用 | WAITING_USER；展示未完成项 | policy_unavailable |
| Content blocked | 映射 missing_material 或需求裁决问题，不进入审核 | missing_material |
| 审核建议不一致或 Schema 错误 | 最多一次格式修复；仍错 FAILED | 无 |
| 有可改的问题且预算/返修次数允许 | 同一 content 生成新版本，再审完整稿 | 无 |
| 审核有效通过 | WAITING_USER；仅允许确认该版本 | final_confirmation |
| 自动返修两轮仍未通过 | WAITING_USER；补料并新建运行或取消 | revision_limit |

核心主张指 Brief 的 must_include 或策略的 core_promise 必需的事实。不能为继续生成而删去用户明确必含项；需要改变 Brief 时先由用户确认。Research 的 ready/partial/insufficient 只是输入，不能用单个状态字代替上述判断。

Join 还检查 Audience 的目标受众与 Research 的 suggested_angles/usable claims 是否能共同兑现 Brief；不匹配时把最少需要补查的问题交用户。MVP 补研究采用图中的 supply → brief 路径，用户明确补料或授权重查后才执行，不新增自主 Agent 对话。一个 run 最多一次补研究，重试不算新轮但调用量照计；达到上限须新建 run 或取消。

补料更新快照后重算两支，保留旧结果供查看但不混入新 Join；预算与已用次数不重置。传输重试输入未变时才复用成功分支。新增研究和返修分别计数；都受同一全局预算约束。

## 3. 创作与证据

逻辑顺序 Strategy → Outline → Hook → Title → Body 不变。策略必须先独立保存并发 artifact.created；其余阶段可合并一次生成后分别记录产物，不能在产物尚不存在时伪造完成事件。模型调用计划记录到 run；全部分开时基础流程八次，合并时按实际调用记账，不宣称已优化到某个耗时。

改稿按 issue_id 和 location 选择受影响字段，保持无关内容不变；改变策略导致下游依赖失效，改变标题需检查正文承诺但不必机械重写全文。完整新稿始终再审。标题默认五个、最少两个，由配置及 Brief 决定，不是平台规则。

Research claims 的 partially_supported 且 usable=true 必须有非空 allowed_wording。不可用主张 allowed_wording=null，不能进入事实表述。用户自述记录 source_type=user_provided、材料 type=user_experience 与授权；即使来源确有该陈述，也不代表经历被独立验证，不可推广为普遍效果。

claim_map 与审核覆盖全部对外字段：selected_title、hook、body:pN、cta、tags:N、cover_text。标题候选若可供用户选择也须检查；选用候选会创建新稿并复审。建议、类比和主观感受标明性质，不强制冒充可验证效果主张。定位需同时绑定版本、原文和段落位置，避免改稿后错指。

## 4. 程序审核门槛

Reviewer 的 decision 仅为建议。编排器先验证角色 Schema、八项检查恰好各一项、输入/来源/规则版本、引用存在性、模板硬规则以及 decision/next_action/issues 一致性；这些检查失败不能当作普通的通过报告。

approved 要求七项 required_pass 全部 pass，originality_risk 允许 pass，或带非空 limitations 的 unknown；不得 fail。所有 issues 不得有未解决 blocker/major，previous_issue_results 不得残留 unresolved/regressed 重要问题，不能通过漏报旧问题让其消失。证据缺口未解决不能通过。未执行的检查必须 unknown，不能补 pass。

严重问题必须产生 issue；重要问题的初次状态 open，复审必须覆盖全部旧问题 ID，并由 Reviewer 验证 Content 的 fixed/removed 声明。resolved 引用旧稿片段时保留旧 draft_ref，不能要求已删除片段仍存在于新稿；新问题必须定位新稿。不存在的旧问题 ID 或不一致决定属于契约错误。

对证据的语义判断由 Reviewer 检查原始文本快照；Tool 做引用/位置/规则的确定性检查。若工具内部另用模型，必须计入统一预算并记录真实调用。审核不得仅相信研究包的 supported 标记。取消、次数上限和预算判断由编排器执行。

模型返回 approved 时 next_action 必须 await_user_confirmation；revision_required 必须 revise；needs_human 必须 request_human 且 human_questions 非空。人工接受需以事务重新核对 run_status、wait_reason、status_version、draft_ref、review_ref、snapshot_id、policy_ref 和内容 hash。用户编辑使旧审核失效；新稿复审前拒绝作为 AI 审核通过的版本接受。用户显式知晓问题后可走下述独立人工采用路径。

## 5. 调用预算、工具与记忆

默认工具超时 10 秒、只读额外重试一次；每角色激活最多 6 次 Tool、全 run 24 次。Agent attempt 最长 180 秒、单模型调用 90 秒、run 有效执行 900 秒；更早到达的上限优先。模型传输额外重试最多两次，格式修复一次；全 run 最多 16 次模型尝试、80000 Token，单次输出最多 3000 Token。Token/金额需要调用前原子预留，并行两支不能同时花同一余额。

自动返修最多两轮不是保证一定跑满；Tool、模型、时间、金额任何预算先耗尽即停止新增调用。策略等阶段合并不改变上限。调用数包含失败和重试；角色激活内的所有阶段共享该次 Tool 额度。重入节点、补研究、格式修复均受全 run 上限约束。

search_public_sources/fetch_source_text 虽属于 research 能力名单，MVP 默认禁用；先使用授权导入素材。部署配置好来源策略和预算后才可启用，页面明确能力是否可用。注册能力不等于当前已实现。角色访问范围是白名单与运行时授权的交集。

统计、Schema 校验、布局检查和事件落盘可由程序自动触发，不必让模型逐次决定。所有被包装为 Tool 的调用（含失败、重试、程序代调）计 Tool 次数；纯本地守卫和事件写入不是 Tool，不计 Tool 次数。不得以程序代调隐藏模型/外部服务费用。导出服务在人工接受后独立执行，不授权 Agent。

六类记忆 namespace 映射到 Profile/Material/History 三域，见机器契约；run_memory 为运行记录。候选记忆必须有来源和版本；去重键为 account/namespace/key，冲突由用户选择，接受/撤销均有审计。假设不能因反复生成升级为事实；授权撤回或资料删除使相关依赖失效。

## 6. 维护与验收

角色卡保持单独编辑，合并部分由 scripts/sync_agent_cards.py 生成；工具/Skill 注册表由同一脚本从角色卡生成，并由测试与机器契约对照。脚本不自动修改机器契约来掩盖差异。AGENTS.md 仅保留入口和协作规则。

必须覆盖：无历史的允许/拒绝假设、非核心/核心证据缺口、工具失败、并行乱序与不同快照、补研究上限、矛盾审核、未映射事实、旧问题遗漏、旧版本确认、用户编辑后复审、取消迟到结果、重复恢复及并发预算。当前文档测试只验证规范一致性，产品实施后仍须运行这些场景的集成测试。

## v0.4 运营扩展边界

本文件保留 v0.3 创作子流程契约；热点、国内平台发布、指标回流与学习为 [v0.4 技术提案](ARCHITECTURE.md#运营闭环-v04-技术提案)，尚未实现。运营对象采用独立状态，创作 SUCCEEDED 不代表发布成功。当前代码进度见 [开发记录](../IMPLEMENTATION_STATUS.md)，不要将历史设计中的“待实现”覆盖已验证能力，也不要把提案字段直接当成现有 API。

## v0.5 账号运营执行扩展（2026-09-21）

用户已授权实施。创作子流程仍为 audience/research/content/reviewer，五阶段、预算、版本与审核守卫不变；新增 analytics 是发布后独立角色，不加入创作 join，也不能确认稿件。机器配置位于 design_contract.json 的 operations_extension，版本与旧创作 schema 分域。

- Operations schema_version=2：accounts、publications、metrics、preferences、competitors、analyses、memories、plans 按本地 owner 隔离；account_id 稳定，不以昵称作关联键。旧 JSON 在读取时兼容，首次写入持久化；原始稿件与来源保留。
- AnalyticsReport schema_version=1：agent_id/agent_version、account_id、publication_id、metric_id、metric_refs、window/elapsed_hours/window_quality、observations、hypotheses、experiment、comparisons、velocity、excluded、flags、limitations、execution；由 backend/analytics.py 的独立规则角色输出。无模型调用，不是已训练预测器。状态 descriptive/insufficient/superseded。
- 统计只用同账号、同平台、同形式、同投流类型、同来源、同窗口的此前作品，且观测时间不得晚于目标快照。观察时长范围为目标至目标的 125%；至少 3 篇有对应指标的历史才显示中位数。未知不补零；账号新增关注不得冒充单篇归因关注。
- 分析只在有比较依据时提交候选经验；人工接受后进入下一次任务快照和周计划。指标或作品分类修正使全部依赖分析与经验 superseded，使依赖计划 needs_review；撤销经验同样使计划失效。历史运行快照保留作审计，不原地改写。
- 计划状态 draft → accepted / revoked；依据失效 → needs_review，只能撤销并重建。任务可改日期/标题/完成状态、关联同账号同来源作品；不执行发布。到期复盘由持久化发布时间推导，服务重启后仍可恢复，但本机关闭时不采集或推送。
- 真实历史导入与模型生成模式分离：imported + manual 表示用户记录，未由平台核实；simulation 永不进入 live 的历史指标或经验。恢复码是本地空间凭证，数据库只存哈希，可重新生成；不是平台 OAuth。

四张角色卡文末明确本机适配字段，不将生产示例字段标成已全面实现。旧 learn 命令为兼容 v0.4 单篇描述性复盘保留，新 UI 使用 analyze。


### 2026-09-30 用户人工采用扩展

用户本次明确授权覆盖原规则“新稿复审前拒绝接受和正式导出”：保留正常审核确认路径，另提供 `adopt_manual`。人工采用绑定用户身份、状态版本、最新稿件引用与内容哈希，要求明确 acknowledge=true；活动后台任务、已结束/取消任务及过期版本不可采用。记录 acceptance.mode=manual_override 及原审核/问题快照，不将问题改为 resolved，不伪造 approved。

自动改稿上限只阻止继续自动改稿，不阻止手动编辑。手动编辑保存新版本，旧审核失效；用户可请求复审，也可单独人工采用该版本。导出必须标明人工采用与审核状态。SUCCEEDED 表示该创作版本已由用户决定采用，不等于 AI 审核通过或已发布；对未来代发操作仍需单独批准准确账号及稿件；以下已发布归档只记录用户已完成的发布，不再走发布前批准。原 workflow 图描述自动审核路径，人工采用扩展见机器契约 manual_adoption_extension。


### 2026-09-30 已发布作品归档

用户确认工作流为“博主先去小红书发布 → 在本系统记录已发布 → 内容归档与数据复盘”。发布页改为发布归档，`archive_published` 在同一事务中关联准确来源稿、保存用户填写的实际标题/正文/话题、作品链接和发布时间，直接生成 MANUAL_REPORTED。不要求准备队列或发布前批准；旧 prepare/approve 演练接口保留兼容，但不再作为发布页主入口。

来源稿件内容及其审核/人工采用记录与实际发布内容分开保存，不把来源稿审核结论转移给改动后的发文。未关联创作稿的作品复用 import_post。记录按平台和账号隔离、防重复，人工记录不等于平台核验，不自动抓取图片；图片通过原作品链接查看。


### 2026-09-30 文案表达对象与标题

发布字段面向目标读者，research.gaps、review.limitations/human_questions 面向创作者，不能互相代写。教程缺必需事实时请求补资料，不能用免责声明掩盖证据缺口。标题与开头强调具体阅读动机，五个候选比较吸引力与可兑现性，最终首段承接选定标题；不推断点击率或效果保证。

本地 editorial_boundary 针对明确内部过程用语补充审核诊断，并保留原始模型响应。命中时保留稿件、进入人工处理，不自动删除句子、伪造来源或开启收费返修。此为有限模式检查，不代表完整语义理解或真实模型质量已验证；人工采用路径仍保留。
