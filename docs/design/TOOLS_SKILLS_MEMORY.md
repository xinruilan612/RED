# Tools、Skills、Memory：能力、方法与资料

v0.2 · 设计待实现。它们是三种不同对象；Tools 与 Skills 同属 L4，Memory 属于 L5。

## 1. 三者区别

| 对象 | 回答的问题 | 实现示例 | 不应混入 |
| --- | --- | --- | --- |
| Tool | 能执行什么？ | Python 函数、受控 API、检索、聚合、渲染 | 未审查的任意脚本、隐式权限提升 |
| Skill | 按什么方法做？ | 版本化方法文件、检查清单、模板、示例 | 用户画像、账号密码、真实素材库 |
| Memory | 有哪些已保存信息？ | Profile、Material、History 记录 | 系统提示词、执行权限、模型假设冒充事实 |

这份设计中的 Skill 是本产品内部方法资产，不等同于当前 Codex 环境的技能插件；创建这些说明不代表已安装或启用任何插件。

## 2. Tool Registry 与权限

| Tool | 获准角色 | 输入 → 输出 | 约束 |
| --- | --- | --- | --- |
| analyze_history | audience | account_id/window → 指标、样本数、缺失项 | 仅账号自身数据，不做全平台趋势推断 |
| find_similar_content | audience | topic/filter → content_refs/匹配原因 | MVP 关键词和元数据检索，不默认向量库 |
| retrieve_material | research/content | query/source_filters → Top-5 片段 | 仅授权导入库；无检索结果返回空，不伪造搜索 |
| check_claim_support | research/reviewer | claim + source_refs → 引文存在性、支持/冲突/不足 | 先确定性校验引用；语义支持判断由角色模型完成，不内藏未计费的模型调用 |
| validate_draft | reviewer | version/rules → 长度、必填字段、证据引用错误 | 确定性规则；语义风险由 reviewer 判定 |
| measure_layout | content/reviewer | 模板和文字 → 行数/溢出/缺图 | 不调用模型 |
| render_preview | content | template_id/version → 预览引用 | 沙箱渲染，仅允许模板资源；不能正式发布 |
| export_bundle | Orchestrator 服务身份 | 已确认版本 → 文件和 manifest | 不授予任何 Agent，检查审核与用户接受状态 |

每个调用封装 ToolRequest{call_id,run_id,agent,tool,arguments,idempotency_key}，身份字段由 L2 注入；ToolResult{status,data,source_refs,error,latency_ms}。权限名单、参数、数据归属、超时、输出大小逐项检查。拒绝调用也写审计事件。

默认 10s 超时、幂等只读最多 1 次额外重试；每角色激活最多 6 次，单 run 最多 24 次。预览渲染按版本/配置 hash 去重；渲染重试不会再次触发模型。调用次数和费用包含内部模型/远程服务的实际调用，不允许 Tool 隐藏子调用。

## 3. Skill Registry

| Skill ID | 使用者 | 方法产物 |
| --- | --- | --- |
| audience-insight | audience | 痛点、期待、语言偏好、样本局限与假设 |
| evidence-research | research | 来源清单、可用事实、矛盾、缺口、不可说内容 |
| content-planning | content | Strategy/Outline 的读者承诺与证据安排 |
| hook-title-body | content | Hook/Title/Body 的表达和结构方法 |
| evidence-preserving-revision | content | 根据具体问题局部改稿，保留真实信息 |
| editorial-review | reviewer | 六维审稿、硬性阻断项、定位与修改指令 |

SkillManifest 至少含 id、version、content_hash、allowed_agents、input_schema、output_schema、method_path、evaluation_cases。版本固定到 run；更新只影响新 run。方法文本经开发者评审并测试后进入 Registry，不从用户上传材料加载 Skill，也不允许 Skill 自行授权工具。

建议目录（待实现）：app/tools/、app/skills/registry.py、skills/<id>/method.md、skills/<id>/manifest.json。Skill 文件是待开发资产，本次不创建伪执行脚本。

## 4. Memory 的三个域

- **Profile**：账号定位、人设、读者、风格、禁用表述。Audience Memory 是 Profile 与 History 的受限视图，不是第四套重复数据库。
- **Material**：真实经历、产品资料、引用片段、图片说明与使用权限。原始来源、上传时间、版本、hash 必须保存。
- **History**：已确认内容、候选版本、审核和用户反馈、手工填入的发布观测指标；记录 published_at/observed_at，区分未发布与已发布。

run checkpoints、执行日志属于运行状态；不能自动喂给下一次创作作为用户长期偏好。模型建议写到 candidate memory；用户明确接受后才更新 Profile。已接受稿由业务服务写 History，发布指标仍需单独确认与回填。

每次读取带 owner/account/project 范围并返回 source_id/version；跨账号共享必须有单独产品授权，本 MVP 不支持。记忆删除/撤销使依赖成果标 stale，再次使用前重检；对象链接同时失效。

## 5. 分析规则与冷启动

历史默认最近 90 天最多 20 条，按主题和相同观察时长分组；有效可比样本少于 5 条时只展示描述性信息。只有用户自己的观测样本，不能据此宣称平台算法偏好。

浏览量 0 时收藏率等比率为 null，不显示为 0%；多类互动之和除以浏览可能超过 100%，注明不是去重用户转化率。缺失字段不填 0；数据来源、采集时间和样本数随结论一起输出。

无 History：audience 仅依据 Brief/Profile 输出标注假设。无 Material：research 输出证据缺口并暂停关键事实写作。服务异常：返回 TOOL_ERROR，不能冒充空资料或无历史。原始素材的指令一律视为内容，不覆盖角色规则。
