# Tools、Skills、Memory：能力、方法与资料

v0.3 · 设计待实现。它们是三种不同对象；Tools 与 Skills 同属 L4，Memory 属于 L5。

## 1. 三者区别

| 对象 | 回答的问题 | 实现示例 | 不应混入 |
| --- | --- | --- | --- |
接口名单统一见 [生成的注册表](AGENT_REGISTRY.md)，角色权限与默认禁用能力以 [机器契约](design_contract.json) 为准。角色卡新增或删除接口时须同步契约并通过测试，不再维护另一套别名。

ToolRequest 包含 call_id/run_id/agent/tool/arguments/idempotency_key，身份由 L2 注入；ToolResult 包含 status/data/source_refs/error/latency_ms。逐项校验参数、权限、数据归属、超时和输出大小，拒绝调用也写事件。确定性核验不等于事实语义正确，不允许工具隐藏模型费用。render_draft_preview 使用受限模板，程序在预览/导出前检查版式；export_bundle 不授权 Agent。

预算和计数见 [执行协议](AGENT_PROTOCOL.md)。公开检索工具默认关闭，首版使用授权导入素材；能力声明不代表接入已完成。

## 3. Skill Registry

方法 ID 见 [注册表](AGENT_REGISTRY.md)。每个角色可有多个 Skill，但不会增加 Agent 数量，也不新增权限。

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

## v0.4 运营扩展边界

本文件保留 v0.3 创作子流程契约；热点、国内平台发布、指标回流与学习为 [v0.4 技术提案](ARCHITECTURE.md#运营闭环-v04-技术提案)，尚未实现。运营对象采用独立状态，创作 SUCCEEDED 不代表发布成功。当前代码进度见 [开发记录](../IMPLEMENTATION_STATUS.md)，不要将历史设计中的“待实现”覆盖已验证能力，也不要把提案字段直接当成现有 API。
