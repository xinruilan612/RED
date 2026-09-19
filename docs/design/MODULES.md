# 模块、Agent 与数据接口设计

v0.1 · 2026-09-20 · 开发前设计。所有接口和数据结构均待实现。

## 1. 模块职责

| ID / 模块 | 输入与输出 | 职责与持久化 | 失败处理 |
| --- | --- | --- | --- |
| M01 网页工作台 | 创作需求、人工编辑 → API；事件 → 状态和预览 | 账号定位、素材、选题、编辑器、版本对比、导出入口；服务器状态为准 | 断线重连、显示未保存状态、冲突时保留本地输入 |
| M02 身份与业务 API | Session + JSON → 资源或任务编号 | 鉴权、CSRF、归属校验、输入校验、幂等、限额；写 run/outbox | 401/404/409/422/429，错误可追踪 |
| M03 项目与素材 | 账号定位、文本、图片 → 不可变输入快照 | 来源编号、素材哈希、图片校验、版本管理；存数据库及私有对象 | 拒绝不支持类型、超限及失效引用 |
| M04 调度与恢复 | outbox → 队列 → Worker | 任务租约、取消、暂停、超时回收；记录状态和事件 | 重复投递去重；僵尸 Worker 写入被 fencing_token 拒绝 |
| M05 Agent 编排 | 输入快照/已确认草稿 → 候选成果/待确认项 | 四角色、路由白名单、输出 Schema、检查点、返修次数 | 缺资料转人工；非法路由拒绝；上限后暂停 |
| M06 模型与用量网关 | Prompt + Schema + 预算 → 结构化结果和用量 | 模型适配、超时、格式检查、配额预留和结算；无用户可控任意 endpoint | 统一重试；未知费用记账；凭证错误立即停止 |
| M07 草稿与审稿协作 | 版本/修改建议 → 新版本与审查标记 | 用户稿不覆盖、段落 ID、差异、Review 的版本绑定 | 乐观锁冲突 409；旧审查失效 |
| M08 模板渲染与导出 | 确认版本 + 模板 + 图片 → PNG/ZIP/文本 | 字段转义、字体和布局验证、导出清单及内容哈希 | 可重试渲染，不重复模型调用；失败不标完成 |
| M09 存储与运行观测 | 状态、事件、文件、用量 → 查询/审计 | PostgreSQL、私有对象、SSE 事件、脱敏指标、备份 | 状态事件持久化补偿、恢复演练、失败告警 |

模块之间通过明确服务接口调用；M09 是横向能力，不赋予 Agent 任意数据库访问。M04 执行调度，M05 决定业务节点；两者不可各自维护相互冲突的状态机。

## 2. 四个 Agent 的输入输出与能力边界

### A1 planner：选题策划

- 输入：账号定位、目标读者、素材摘要及 source_id、主题、可选历史标题。
- 输出：3 个 TopicOption，含 topic_id、angle、audience、value、source_ids、missing_inputs。
- 判断：素材不足时提出具体问题；没有联网检索时不声称发现实时热点。
- 工具：只读当前项目素材/定位；不能发布、改用户稿或访问其他用户。
- 后继：WAITING_USER(topic_selection)；资料不足为 WAITING_USER(missing_material)。

### A2 writer：内容创作

- 输入：已选选题、用户真实素材、风格、可选段落范围、审稿问题。
- 输出：DraftProposal，含 title_candidates、paragraphs[{id,text,source_ids}]、tags、unverified_claims。
- 判断：将来源支持的事实与建议/观点分开；没有真实经历依据不能生成“亲测”等断言。
- 工具：读取快照和指定版本；通过服务保存候选稿，不能直接接受自己的提案。
- 后继：designer；缺资料返回人工；修改限定在请求段落，超范围变更作为另行建议。

### A3 designer：图文编排

- 输入：确定的候选稿版本、模板列表、图片素材及用户说明。
- 输出：LayoutProposal，含 template_id、cover、pages[{headline,body,asset_id}]、draft_version_id。
- 判断：分页、封面重点和阅读节奏；不得把内部提示词、思考说明写入读者可见图片。
- 工具：模板测量/预览；不执行任意代码、不访问任意网页。
- 后继：reviewer。前稿变化后旧排版失效，必须基于新版重排。

### A4 reviewer：内容审稿

- 输入：稿件、排版、源素材及该版本的渲染检查结果。
- 输出：ReviewResult，decision ∈ pass/revise/need_input，target ∈ writer/designer/user/none，issues 含段落定位、原因、建议和来源。
- 判断：标题是否兑现、内容价值、素材依据、风格和排版一致性；通过表示内部检查完成，不是平台审核保证。
- 工具：素材交叉检查、字数和溢出规则；不具备发布权限。
- 后继：通过转最终人工确认；文案问题回 writer 并重排、重审；仅排版问题回 designer 后重审；资料不足转用户。

四角色各有独立系统提示和最小上下文。第一版共享一个可配置模型；不用模型扮演第五个调度员。设计不保证多 Agent 一定优于单次生成，需对照评测。

## 3. 共享数据契约

所有消息使用 schema_version=1。业务 ID 为 UUID，时间为 UTC ISO 8601，展示按用户时区转换。owner_id 从认证会话解析，不能相信模型或客户端传入的归属。

RunContext 至少包括：run_id、project_id、input_snapshot_id、base_draft_version_id、workflow_version、prompt_version、model_config_version、current_node、iteration、status、wait_reason、resume_node、lease_token、attempt_count、token_usage、budget_reserved。

AgentEnvelope 至少包括：schema_version、run_id、agent、input_hash、draft_version_id、decision、payload、source_ids。校验未知字段、枚举、长度和资源归属；纯 JSON 合法不等于内容可信。

审稿示例（仅合成契约样例，不是真实模型结果）：

```json
{
  "schema_version": 1,
  "agent": "reviewer",
  "decision": "revise",
  "target": "writer",
  "draft_version_id": "example-v3",
  "issues": [{
    "paragraph_id": "p2",
    "type": "unsupported_experience",
    "source_ids": [],
    "message": "缺少亲测时长的来源",
    "suggestion": "删除该表述，或请用户补充真实记录"
  }]
}
```

路由校验矩阵：pass 仅允许 target=none；revise 仅允许 writer/designer；need_input 仅允许 user。writer 修改后必须经过 designer 和 reviewer，不能直接最终通过。文字检查与渲染溢出由确定性规则承担。

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
| steps | run_id、node、iteration、input_hash、output、usage | 四元唯一，写入检查 token；未确认结果不当成功 |
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

intent ∈ full/rewrite/layout/review。partial rewrite 另传 paragraph_ids 和 instruction。resume action ∈ choose_topic/supply_material/accept/revise；新增素材生成子快照、更新 input_hash 和待执行节点，保留父快照审计。非法 action 或过期版本返回 409，不能任由客户端指定任意 Agent。

错误码建议：AUTH_REQUIRED、RESOURCE_NOT_FOUND、VERSION_CONFLICT、RUN_ALREADY_ACTIVE、INVALID_INPUT、BUDGET_EXCEEDED、PROVIDER_TIMEOUT、PROVIDER_AUTH_FAILED、MODEL_OUTPUT_INVALID、RENDER_OVERFLOW。可重试与否由类别决定，不把所有异常都统一自动重试。

## 6. 编辑与导出的版本规则

MVP 允许用户随时保存手工稿；后台成果只写 candidate。任务结果基于 v3，但用户已保存 v4 时，保留成果为“基于旧稿的建议”，不能更新 current_version。用户可比较后手动迁移，不自动合并。

接受、重新排版、复审和导出都绑定版本。用户修改通过审查的 v4 得到 v5，则 v4 的排版/审核不能给 v5 背书。渲染失败仍可查看稿件和下载单独文本，但完整图文包只能在渲染全部成功后标为完成。
