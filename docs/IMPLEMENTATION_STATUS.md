# 开发进度与已验证边界

2026-09-20：用户已确认开始开发。首次实现交付为后端领域核心，属于阶段 A 的基础与部分阶段 B 守卫；完整 MVP 尚未完成。

## 已实现

- backend/contracts.py：加载 v0.3 参数与名单；按角色、运行时授权和资源归属限制工具；旧记录只读映射为 needs_review，不把 completed 当成用户确认。
- backend/workflow.py：任务状态、同快照双分支汇合、假设授权/核心资料不足暂停、失败分支有限重试、补料使两支失效、返修两轮上限、稿件不可变版本、八项审核结果检查、编辑后复审、准确版本人工确认。
- backend/store.py：SQLite 开发仓储，事务更新、乐观版本校验、命令幂等、按用户隔离、事件持久化、调用/Token 原子预留与结算。未知用量保留预留额度。
- tests/test_backend_workflow.py：18 个运行测试，包含并发预算争用、服务仓储重新打开、失败回滚、过期确认、跨用户操作、重复命令、返修/重试上限。

运行测试使用真实 Python 领域代码与临时 SQLite；没有调用模型、没有编造模型评测或真实流量效果。与已有 24 项文档测试合计 42 项。

## 尚未实现，不能对外当作完整产品

四角色完整产物 Schema、真实 Agent/模拟 Agent 执行器、语义事实校验、Brief/素材/画像管理、Skill 资产加载、Tool 参数 Schema 与实际工具、完整 Memory 读写接口、费用账本、队列/租约/后台恢复、HTTP 登录鉴权和 CSRF、网页工作台、图文渲染导出、模型供应商适配及云端部署。

现有 Run 是服务内部领域状态，不是所有 API 字段的最终实现。reviewed 的 gates 由未来可信服务计算，不能从浏览器或模型原样传入；当前只校验这些守卫是否全部成立，不声称已核实来源内容。核心缺口 core_gap 同样是上层已判断结果，本阶段不做语义判断。Store.command 是内部接口，未来 HTTP 必须使用用户动作白名单，不能直接暴露 start/branch/reviewed 等命令。

SQLite 是可替换的开发仓储，不改变规划中的 FastAPI/PostgreSQL/任务队列部署方向。状态与幂等已持久化不代表 Worker 崩溃恢复已实现。预算超限目前抛 BUDGET_EXCEEDED，后续执行器必须捕获、持久化 budget_exhausted 并停止调度。当前无收费调用路径。

## 验证与下一步

项目根目录运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

本阶段无第三方依赖，兼容当前 Python 3.9；生产部署仍按后续环境锁定版本。接下来先补严格角色 Schema 和四 Agent 模拟执行器，落实守卫的可信计算与真实事件，然后接后台 API 和网页。在模型质量、权限和部署均验证前，不宣称可以公开上线。
