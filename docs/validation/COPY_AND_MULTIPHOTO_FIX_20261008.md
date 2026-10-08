# 写稿声明与多视角配图修正（2026-10-08）

## 用户验收问题

上次只约束后续生成，交付包仍用了旧确认稿中的“本文据罗技官方公开资料整理，非亲测、非品牌合作。”；同一照片反复出现在全部图卡。用户要求修正写稿角色、现有成品和多视角分配，并自行验证后交付。

## 修正

1. body/revise 模型输出接纳前，窄匹配移除自动独立来源/非亲测/非品牌合作模板声明。发生在 draft/hash 创建前，后续审核绑定清理后的真实稿件；记录 copy_adjustments，保留原模型响应。用户明确要求的披露、真实合作与产品事实限制不被批量删除。既有审核规则不要求补默认免责声明。
2. 罗技 M185 目录采用 HS05 侧前方、HS01 俯视、HS06 底部三张不同实拍，依次分配前3页，用完后的页面无产品图。用户单图只用于封面。每页 metadata 有 photo_id/hash/来源，无图为 null；模板版本3，设计标识包含所有照片hash。来源许可见 frontend/assets/products/ATTRIBUTION.md。
3. 用户明确同意“保留第四版历史，保存修正版并设为当前确认稿”。只删除指定独立段落，其他文字不改；新稿不得冒充 AI 复审通过，旧版本保留审计。已实际写回第五版，第四版及旧审核未修改；当前 acceptance 为 manual_override，不伪造 AI 审核通过。

## 验证边界

生成规则通过确定性与模型替身测试，不使用真实收费模型测试。三张实拍已逐张查看。修正副本为4页，前三页图片hash互不相同，第四页photo_id=null；正文、绘制文本、字幕不含指定声明。整个ZIP CRC与图片字节一致性检查通过。此前预审副本没有改动数据库，也没有伪造新确认记录。


## 正式交付核验

经用户单独明确同意后，纠正事务已执行。新确认稿 ref=327e2866-414b-43ed-8072-2101f1c87c55@1；保存5个版本，旧4版逐字节不变，新正文仅删除指定独立段落。模型调用仍14次，Token和费用不变。纠正操作使用版本/哈希/权限/运行状态守卫与幂等键，新增确认事件保存旧acceptance审计。

正式包 output/corrected-product-cards-20261008/youji-complete-0efe5ebe-corrected.zip：4页，照片id依次为HS05/HS01/HS06/null；3张照片hash各不相同。caption、正文图片绘制文本、分镜、字幕均不含默认声明；旧审核只保留在历史审计。预览PNG与ZIP图片逐字节一致，ZIP CRC通过。SHA-256：07caea96a501ea2be5db592d7a31d95fe021b9d099dc39a85e7511e85289b440。

纠正事务14项测试（SQLite7+真实PostgreSQL7）通过；前端269项通过。首次全量911项中，后台恢复用例 test_parse_failure_keeps_usage_and_explicit_resume_reuses_successful_branch 出现一次 RUNNING/WAITING_USER 状态差异，单独重跑通过（未改断言）；最终重新完整运行925项全部通过，无跳过（含纠正事务与真实PostgreSQL），日志 /tmp/red-multiphoto-final-full.log。前端269项、12份JS语法、角色卡一致性与git diff --check通过。网站HTTP 200，API/worker已加载修复。
