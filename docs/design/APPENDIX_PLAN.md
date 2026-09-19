# 附录交付追踪与验证计划

v0.2。依据：[AIC AI+软件创新参考大纲第六项](https://www.aicomp.cn/tracks/tracks-2/3792.html)。本次新增截图与该页附录内容相符，区别于前次涉及 HAP/小艺的未确认截图。

## 1. 五类附录的当前交付边界

| 附录项 | 当前交付 | 状态与后续动作 |
| --- | --- | --- |
| 软件设计资料 | [总入口](README.md)、架构、模块、流程、参数及五张 SVG | 设计资料已编写；开发后按实际实现修订 |
| 核心代码 | 此前核验的六角色 starter 原型（工作区现已移除）；本次只修订设计和文档验证 | 新版四角色核心代码待迁移实现，不用伪代码冒充成品代码 |
| 测试数据 | 文档链接/结构/图件等检查 | 产品原始测试、用例和性能结果待采集，不能填造数据 |
| 参考文献 | 本文、技术文档及 [GitHub 调研](../research/GITHUB_PROJECTS.md) | 记录来源和访问日期；实际复用时记录固定 commit 和许可证 |
| 其他佐证 | 当前无专利、检测或用户使用证明 | 仅有真实材料时添加，不要求为参赛虚构证明 |

## 2. 核心代码未来应选哪些片段

开发后从真实仓库抽取：并行汇合、四 Agent 图与路由、五阶段 content、Tool/Skill Registry、Memory 来源追踪及 Runtime Console、输入输出 Schema、版本安全提交、人工恢复接口、任务去重与 fencing、用量预留和终止、模板渲染。每段附代码路径、行号、commit、实现动机、输入输出、关联测试。第三方调用必须说明哪些是框架能力，哪些是团队实现。

## 3. 原始测试与报告结构

建议在实际测试时创建 tests/unit、tests/integration、tests/e2e、evals/cases 与 docs/evidence。原始个人素材需授权、匿名化；未授权正文不能进入公开仓库。

建议测试记录 CSV 字段：case_id、scenario、input_fixture_hash、expected、actual、passed、started_at、duration_ms、model_id、prompt_version、input_tokens、output_tokens、cost_status、estimated_cost、currency、commit_sha、environment、failure_reason、trace_id。金额未核对时留空并标 unknown，不填 0。

样本分层：正常输入、资料不足、相互矛盾资料、夸大经历、较长输入、风格不匹配、排版溢出、敏感资料和故障注入。合成测试用例标 synthetic，真人素材标 consented_real；不把前者称为真实用户试用。

## 4. 计划测试矩阵（尚未执行）

| 编号 | 验证目标 | 预期判定 |
| --- | --- | --- |
| T01 | 创建到导出完整流程 | 版本、标题、正文、图片和 manifest 一致 |
| T02 | 用户 A 访问 B 的 run/source/export | 404，无正文、签名 URL 或事件泄露 |
| T03 | 重复提交和重复队列投递 | 一个业务 run/步骤结果，计数不丢失 |
| T04 | 用户编辑期间旧 Agent 返回 | 新稿不被覆盖，旧建议明确标识 |
| T05 | 缺资料及矛盾素材 | 返回补料或问题，不虚构亲测事实 |
| T06 | 返修/重试/格式修复 | 达到统一次数、Token、金额、时限后停止 |
| T07 | Worker/Redis 故障与恢复 | 已提交成果可恢复，过期 Worker 不能写入 |
| T08 | 用户确认重放与过期确认 | 幂等响应或 409，不启动错误节点 |
| T09 | 渲染安全与溢出 | 不执行注入脚本、不访问任意 URL、无缺页成功 |
| T10 | 浏览器兼容与断线 | 桌面 Chrome/Safari 及手机浏览器真实验收 |
| T11 | 负载与用量 | 10 个浏览会话、2 个执行任务，采集至少 30 次样本的 P50/P95 |
| T12 | 普通生成 vs 多 Agent | 相同素材，记录时间、修改量、采用率和失败样本 |

每轮报告写明样本数、环境、日期、模型和代码版本，列出全部失败与限制。不承诺测试能证明“无任何 bug”或获奖。

## 5. 参考资料

访问日期均为 2026-09-20。

- [比赛总通知](https://www.aicomp.cn/notice/notice-1/3674.html)：赛事资格与时间。
- [AI+软件创新](https://www.aicomp.cn/tracks/tracks-2/3792.html)：设计附录和交付要求。
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：持久化和检查点。
- [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)：人工暂停与恢复。
- [Celery Tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html)：幂等、确认、超时和重试。
- [GitHub 项目与许可证核对](../research/GITHUB_PROJECTS.md)：静态调研，未安装和运行第三方项目。

## 6. 开发阶段

A：身份、项目、素材、契约和数据库；B：四 Agent 与用户确认；C：版本编辑、审稿和图文导出；D：故障恢复、额度、部署和真实评测。每阶段完成相关测试和 Git commit 后交付，最后再根据真实结果整理比赛文档、视频及佐证。

新增 v0.2 验收：同快照双分支汇合；历史为零与 Tool 失败的区分；content 局部阶段失效与复审；Skill 固定版本；Memory 越权与撤销；Console 事件重放/费用去重；老 completed 不等于 accepted。详见 [模块](MODULES.md)、[工具/方法/记忆](TOOLS_SKILLS_MEMORY.md)、[控制台](RUNTIME_CONSOLE.md)。
