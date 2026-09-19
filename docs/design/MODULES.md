# 五层模块、Agent 与数据接口设计

v0.2 · 根据用户三张图片重规划。目标方案尚未实现；现有六角色 starter 的迁移见 [MIGRATION.md](MIGRATION.md)。

## 1. 模块归属与职责

| ID | 层 / 模块 | 责任与输出 | 边界与异常 |
| --- | --- | --- | --- |
| M01 | L1 创作 UI | Brief、素材、候选稿、编辑、用户确认 | 不能自行判通过，必须提交版本号 |
| M10 | L1 Runtime Console | 状态/输入输出/Tool calls/Memory reads/耗时/Token 成本/错误重试 | 只展示获准事件，不展示隐藏推理或密钥 |
| M02 | L2 API 与身份 | 鉴权、归属、Schema、幂等、错误码 | 拒绝越权和旧版本动作 |
| M04 | L2 调度与恢复 | outbox、队列、租约、取消与恢复 | 不重复已提交分支，不重置费用计数 |
| M05 | L2 Orchestrator | 四 Agent 路由、并行屏障、审核门槛、人工暂停 | 仅程序控制分支，不由 Agent 自由互相调用 |
| M06 | 横向模型网关 | 模型适配、超时、预算预留、用量与格式检查 | 不算 Agent/Skill/Memory；受 L2 约束 |
| A01–A04 | L3 四个 Agent | AudienceInsight、ResearchNotes、ContentArtifacts、ReviewResult | 独立上下文，共享模型，不直接写最终稿 |
| M08 | L4 Tool Registry | 历史分析、检索、依据检查、版式测量、模板渲染 | 名单授权、Schema、超时、审计、无任意脚本执行 |
| M11 | L4 Skill Registry | 版本化方法、输出标准、示例与检查项 | 不能绕过工具权限；不保存用户私有资料 |
| M03 | L5 Profile / Material | 用户确认画像、真实经历、产品资料及来源 | 数据隔离、来源版本、假设不当事实 |
| M07 | L5 History / Version | 已确认稿、候选稿、审稿、发布反馈、版本关联 | 反馈手工回填，记录来源和时间，不自动宣称已发布 |
| M09 | L5 存储设施 | PostgreSQL / 对象存储；另有运行检查点和事件空间 | 运行态与长期 Memory 逻辑分开，按权限访问 |

## 2. 四个 Agent 契约

### A01 audience：受众洞察

输入：Brief、已确认 Profile 快照；工具查询得到的历史指标和相似内容。输出 AudienceInsight：pains、expectations、language_preferences、patterns、hypotheses、sample_size、window、history_refs、confidence_basis。

允许 analyze_history、find_similar_content。历史为空时输出 sample_size=0 和基于 Brief 的假设；工具报错不能伪装为“无历史”。样本不足不做趋势结论，不直接写正文，不虚构平台热点或因果提升。

### A02 research：素材研究

输入：同一 Brief 快照及 Material 引用。输出 ResearchNotes：claims[{id,text,source_id,source_version,quote,status}]、usable_experiences、evidence_gaps、claims_to_avoid。

允许 retrieve_material、check_claim_support。status ∈ supported_by_source/conflicting/insufficient；supported_by_source 只说明资料支持该表述，不保证现实世界真伪。真实经历由用户提供且标 source_type=user_reported；不得编造数字、案例、效果。

### A03 content：内容策划创作

输入：同 snapshot_id 的 audience/research 已验证结果、Profile、Skill 版本及可选 ReviewResult。内部阶段固定 **Strategy → Outline → Hook → Title → Body**，分别保存结构化中间产物与 hash；不是增加五个 Agent。

输出 ContentArtifacts：strategy{angle,promise,proof_plan}、outline{sections}、hook{text}、titles{candidates,selected}、draft{paragraphs,source_refs,tags,cover_text,visual_suggestions}。首版每阶段最多一次模型生成；完整正常流程是 2 个研究调用 + 5 个内容调用 + 1 个审核调用，共 8 次，网络/格式重试另计。

允许 retrieve_material、measure_layout、render_preview；新增检索结果如改变事实集，必须提交 research 增量校验后更新快照，不私自改通过的证据。此路径由 Orchestrator 转补料/重跑控制，不由 content 私自调用 research。

返修模式仍由 content 执行：review.issues 指定 affected_stage / paragraph_id，最早受影响阶段起重算下游；例如修改策略重算全部阶段，正文问题只重写 Body，标题问题重算 Title/Body。保留旧版本，不静默覆盖用户稿；改稿必回 reviewer。

### A04 reviewer：主编审核

输入：Draft 精确版本、对应 Strategy、ResearchNotes、布局检查结果和审核 Skill。输出 ReviewResult：draft_version_id、dimensions、blocking_issues、issues、revision_instructions、decision。

6 维是 hook/specificity/authenticity/readability/interaction/evidence_safety，均 0–100。程序按等权均值四舍五入到整数计算 total_score；模型提供总分时忽略，防止与分项不一致。

通过条件同时满足：total_score >= 82、evidence_safety >= 80、blocking_issues 为空、没有未解决的关键证据缺口、Schema/字数/排版硬规则通过、稿件及来源版本一致。阈值仅内部质量基线，不表示爆款概率。

允许 check_claim_support、validate_draft、measure_layout。仅输出检查结果，由 L2 判断下一步：pass → 人工确认；revise → 同一个 content；need_input → 用户补料。自动返修 2 轮后仍不过，等待用户补料或取消，不得自动通过或直接变最终稿。

## 3. 共享状态与校验

schema_version=2；ID 使用 UUID，时间存 UTC。owner_id 从服务端会话解析。禁止 Agent 凭文字指定他人 Memory 或任意下一节点。

WorkflowState：run_id、snapshot_id、workflow_version、skill_versions、model_config_version、branch_results、content_artifacts、draft_version_id、review、iteration、status、wait_reason、resume_node、status_version、lease_token、usage_totals。

branch_results 的 audience 与 research 各自提交不可变结果；汇合时二者都须成功且 snapshot_id 相同。零条历史是一种有效结果，失败/超时不是。素材缺失则先 WAITING_USER，不生成无依据正文。

AgentEnvelope：agent、stage、input_hash、output_ref、schema_version、source_refs、decision、tool_calls、memory_reads、usage。数据/权限/预算三类校验在 L2/L4 执行，不能仅靠提示词。

ReviewResult 示例（合成契约样例，非真实评测）：

```json
{
  "schema_version": 2,
  "agent": "reviewer",
  "draft_version_id": "example-v3",
  "decision": "revise",
  "issues": [{
    "paragraph_id": "p2",
    "affected_stage": "body",
    "type": "unsupported_experience",
    "source_refs": [],
    "instruction": "删除没有来源的亲测时长，或请求用户补充记录"
  }]
}
```

所有阶段绑定 snapshot_id 和输入 hash；内容阶段输出不是聊天记录拼接。Skill、提示词或输入变化必须生成新执行版本，不把旧节点缓存当新成果。

## 4. 数据模型与约束

| 实体 | 关键字段 | 关系与约束 |
| --- | --- | --- |
| users / sessions | id、password_hash、session_digest、expires_at | Cookie 只持随机会话令牌；数据库存摘要，可撤销 |
| creator_profiles | id、owner_id、audience、style、version | 一个用户多个定位，MVP 每项目绑定一个定位快照 |
| projects | id、owner_id、profile_id、current_version_id、revision | 所有写操作校验 owner 和 revision |
| sources | id、project_id、kind、content/object_key、hash、origin_url | URL 仅元数据；删除遵守版本留存/清理规则 |
| input_snapshots | id、project_id、profile_version、source_refs、content_hash | run 创建时冻结，后续编辑不静默改变执行输入 |
| draft_versions | id、project_id、parent_id、content、actor、status | 不可变；candidate/accepted；人工接受以事务更新当前指针 |
| layouts / reviews | id、draft_version_id、payload、status | 精确绑定稿件版本；稿件变化即 stale |
| runs | id、project_id、status、wait_reason、resume_node、lease_token、deadline | 用户活跃 run 上限事务校验，非仅前端禁按钮 |
| steps | run_id、node、stage、iteration、input_hash、output、usage | 五元唯一，写入检查 token；未确认结果不当成功 |
| checkpoints | thread_id、checkpoint_id、state | 后端映射到 run；与业务结果对账恢复 |
| run_events | run_id、seq、type、payload、created_at | UNIQUE(run_id,seq)，供 SSE 按游标重放 |
| outbox | id、run_id、command_id、dispatched_at | 与业务状态同事务；重复投递安全 |
| idempotency_keys | owner_id、route、key、request_hash、response | 作用域唯一，同 key 不同 body 返回 409；建议保留 24h |
| exports | id、draft_version_id、layout_id、object_key、hash、status | version+layout+render_config_hash 唯一，避免重复渲染 |
| usage_ledger | run_id、call_id、reserved、actual、status | 全局尝试数/Token/金额预留原子更新；unknown 不视为免费 |

核心关系：users → projects → sources/input_snapshots/draft_versions/runs；runs → steps/checkpoints/run_events；draft_versions → layouts/reviews/exports。各外键及复合归属校验由数据库和服务共同约束。删除用户时异步清理关联文件、检查点和个人内容。

## 5. API 契约

统一前缀 /api/v1。GET 默认只读，写接口带 CSRF；任务创建、恢复和导出使用 Idempotency-Key。返回 {data, request_id} 或 {error:{code,message,retryable}, request_id}。

| 方法和路径 | 输入重点 | 返回及语义 |
| --- | --- | --- |
| POST /sessions | 登录凭证 | 200，设置安全 Cookie；失败统一提示 |
| DELETE /sessions/current | CSRF | 204，撤销会话 |
| POST /projects | profile_id、brief | 201，project_id、revision |
| GET /projects/{id} | 会话 | 200，当前版本和 run；越权 404 |
| POST /projects/{id}/sources | 文本或受限 multipart 图片 | 201，source_id；超限 413/422 |
| POST /projects/{id}/runs | base_revision、material_ids、intent | 202，run_id、status_url、events_url；事务创建 outbox |
| GET /runs/{id} | 会话 | 200，状态、节点、wait_reason、可恢复动作 |
| GET /runs/{id}/events | Last-Event-ID | SSE，event_id、type、payload；鉴权和断线重放 |
| POST /runs/{id}/resume | expected_status_version、action、payload | 202，同一确认只能消费一次 |
| POST /runs/{id}/cancel | expected_status_version | 202 或已取消的 200，设置取消标记 |
| POST /runs/{id}/retry | 可恢复失败、相同输入快照 | 202，保留累计用量和计数；终态不重新开启 |
| POST /projects/{id}/versions | base_version_id、content | 201，新人工版本；冲突 409 |
| POST /projects/{id}/accept | candidate_id、base_version_id | 200，原子接受候选稿，旧检查失效 |
| POST /projects/{id}/exports | accepted_version_id、layout_id | 202，export_id，仅当前有效审稿与确认版本 |
| GET /exports/{id} | 会话 | 200，状态；完成时提供 300s 签名链接 |

intent ∈ full/rewrite/layout/review。partial rewrite 另传 paragraph_ids 和 instruction。resume action ∈ supply_material/accept/revise；新增素材生成子快照、更新 input_hash 和待执行节点，保留父快照审计。非法 action 或过期版本返回 409，不能任由客户端指定任意 Agent。

错误码建议：AUTH_REQUIRED、RESOURCE_NOT_FOUND、VERSION_CONFLICT、RUN_ALREADY_ACTIVE、INVALID_INPUT、BUDGET_EXCEEDED、PROVIDER_TIMEOUT、PROVIDER_AUTH_FAILED、MODEL_OUTPUT_INVALID、RENDER_OVERFLOW。可重试与否由类别决定，不把所有异常都统一自动重试。

## 6. 编辑与导出的版本规则

MVP 允许用户随时保存手工稿；后台成果只写 candidate。任务结果基于 v3，但用户已保存 v4 时，保留成果为“基于旧稿的建议”，不能更新 current_version。用户可比较后手动迁移，不自动合并。

接受、重新排版、复审和导出都绑定版本。用户修改通过审查的 v4 得到 v5，则 v4 的排版/审核不能给 v5 背书。人工编辑或 content 返修后必须重新 reviewer 检查，不得直接导出。渲染失败仍可查看稿件和下载单独文本，但完整图文包只能在渲染全部成功后标为完成。

## 7. v0.2 增补实体和接口

| 实体 | 关键字段与限制 |
| --- | --- |
| profile_versions | owner/account/version/confirmed_by/source，仅用户接受后成为有效画像 |
| material_versions | source_type/source_uri/hash/quote/consent，原文与模型解读分开 |
| history_metrics | content_id/published_at/observed_at/views/saves/comments/source，保留每次观测而非覆盖 |
| content_artifacts | run_id/stage/iteration/input_hash/output_ref，五阶段和返修记录不可变 |
| skill_versions | skill_id/version/hash/allowed_agents/input_schema/output_schema，运行固定版本 |
| tool_invocations | call_id/agent/tool/input_summary/output_ref/error/retry/latency，调用身份由后端填写 |
| memory_accesses | run_id/agent/store/query_hash/record_ids/source_versions，按用户鉴权 |

新增 GET /runs/{id}/artifacts、GET /runs/{id}/events?after=seq、GET /runs/{id}/usage 支持 Console；详情须鉴权且只返回当前用户可见成果。统一已有 SSE 的 Last-Event-ID 与 after 游标语义，均按 seq 续读。

POST /profiles/{id}/versions 和 POST /profiles/{id}/accept 用于画像候选和确认；POST /projects/{id}/feedback 保存手工发布指标，要求 observed_at 与来源。聚合分析、只读检索为内部 Tool，不向浏览器开放任意数据库查询。

resume 不再有 choose_topic；接受请求必须带 expected_status_version 和 reviewed_draft_version_id。手工修改变成新版本后重新审核，accept 不接受旧 review。/exports 要求用户已确认且审核仍有效，不能把“审核有风险但执行结束”当成可正式导出。
