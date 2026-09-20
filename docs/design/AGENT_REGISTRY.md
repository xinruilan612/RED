# Tool / Skill 注册表

由 scripts/sync_agent_cards.py 从独立角色卡生成，请勿直接编辑。所有接口均为设计，尚未实现。权限另由 design_contract.json 校验。

## Tools

| 角色 | ID | 行为 | 限制 |
| --- | --- | --- | --- |
| audience | `read_account_profile` | 读取当前账号已确认画像 | 只读；不读取其他用户账号 |
| audience | `query_authorized_post_metrics` | 查询授权历史笔记及统计数据 | 必须带账号、窗口和字段范围 |
| audience | `compute_content_metrics` | 去重、分组、计算比率及描述统计 | 记录公式、分母和过滤规则 |
| audience | `read_memory` | 读取允许的记忆空间 | 按用户、账号隔离 |
| audience | `propose_memory_update` | 提交候选受众假设或模式 | 不直接覆盖长期记忆 |
| research | `search_public_sources` | 检索允许的公开来源 | 保存查询词、检索时间和结果引用 |
| research | `fetch_source_text` | 获取可访问正文 | 不绕过登录、付费或访问限制 |
| research | `read_user_material` | 读取当前任务授权材料 | 不扩大到其他目录或账户 |
| research | `extract_document_text` | 提取文本与页码 | 扫描识别结果须标注可靠性 |
| research | `verify_quote_match` | 校验引文与已取得文本是否一致 | 文本匹配不等于事实正确 |
| research | `read_memory` | 读取允许的素材记忆 | 过期内容须重新核实 |
| research | `propose_memory_update` | 提交来源与主张缓存候选 | 不自动存为永久事实 |
| content | `read_run_artifact` | 读取当前任务明确传入的洞察、研究、审核和 Draft 版本 | 不读取其他任务 |
| content | `validate_draft_schema` | 检查字段与引用完整性 | 结构正确不等于内容正确 |
| content | `check_text_constraints` | 检查长度、必含项、禁用词等可计算约束 | 规则须带版本 |
| content | `render_draft_preview` | 生成用户可见笔记预览 | 仅预览，不发布 |
| content | `diff_draft_versions` | 生成改稿差异 | 保留前版，不覆盖 |
| content | `read_memory` | 读取获准风格与内容记忆 | 不取得账号全量数据 |
| content | `propose_memory_update` | 提交风格偏好候选 | 仅候选，不自动生效 |
| reviewer | `read_run_artifact` | 读取当前任务指定稿件、来源原文快照及前轮审核 | 输入版本须固定 |
| reviewer | `validate_draft_schema` | 复核结构及引用存在性 | 不代替语义检查 |
| reviewer | `check_text_constraints` | 检查 Brief 的可计算要求 | 记录规则版本 |
| reviewer | `verify_claim_mapping` | 核对文本主张、研究证据和措辞范围 | 确定性引用检查加角色语义审核，覆盖全部对外文本；不能只相信创作自报列表，也不隐藏额外模型调用 |
| reviewer | `compare_supplied_texts` | 对照提供的素材检查明显照搬 | 不冒充全网查重 |
| reviewer | `read_review_policy` | 读取维护好的规则包 | 过期需标记，不能自创平台规则 |
| reviewer | `read_memory` | 读取已接受的审核标准 | 不读无关用户数据 |
| reviewer | `propose_memory_update` | 提交通用问题模式候选 | 不改写事实或用户偏好 |

export_bundle 仅允许 Orchestrator 服务身份，在有效审核及用户确认后调用；不属于 Agent 权限。公开搜索/抓取默认禁用，启用条件见 [执行协议](AGENT_PROTOCOL.md)。

## Skills

| 角色 | ID | 方法 |
| --- | --- | --- |
| audience | `audience_segmentation` | 按需求和场景细分受众，标注假设。 |
| audience | `historical_performance_analysis` | 按可比窗口分析内容表现及异常值。 |
| audience | `evidence_based_insight` | 把结论连接到指标、来源和限制。 |
| audience | `cold_start_insight` | 无数据时产出假设、验证方式和补数建议。 |
| research | `research_question_planning` | 把选题转为可检索问题。 |
| research | `source_evaluation` | 优先原始发布者，评估时效、适用性及利益关系。 |
| research | `claim_evidence_mapping` | 为主张建立证据映射与引用定位。 |
| research | `conflict_and_gap_analysis` | 对冲突、未知和材料缺口作显式标注。 |
| content | `content_strategy` | 将受众机会转为角度与可兑现承诺。 |
| content | `xiaohongshu_copywriting` | 采用适合阅读的标题、开头、段落和互动方式，不伪装真实经历。 |
| content | `evidence_grounded_writing` | 仅在证据适用范围内陈述事实。 |
| content | `review_driven_revision` | 逐项处理审核问题，保留差异与未解决项。 |
| reviewer | `editorial_review` | 检查内容价值、需求满足和阅读体验。 |
| reviewer | `evidence_review` | 核对来源是否真正支持主张、范围与时效。 |
| reviewer | `risk_and_authenticity_review` | 识别夸大、虚构经历、隐私和素材使用问题。 |
| reviewer | `actionable_feedback` | 将问题转为有位置、有修改建议、有复核条件的反馈。 |
