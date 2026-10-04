# 真实调用费用确认修复验收

2026-10-02，基于本地修复提交2f5c24e。本次只修复真实AI执行前的费用确认入口。自动化门禁通过，修复后真实浏览器点击尚未复验，因此不能宣称完整真实端到端验收通过。

## 实际修改

原生window.confirm替换为页面内费用面板，保留费用上限、Token上限和资料发送提示。拒绝不派发执行；批准清空待处理命令后仅恢复一次原操作。待批准任务及资料快照变化时拒绝授权。全部执行入口继续沿用原有服务端认证、CSRF、预算、版本和幂等控制，无新增依赖、锁文件或数据库迁移。

新增前端行为用例验证：禁止原生弹窗、确认前零请求、拒绝零请求、重复批准仅一次派发、任务或素材变化拒绝执行。这里的请求计数来自测试替身，不代表模型实测。

## 本补丁独立测试

| 检查 | 实际结果 |
| --- | --- |
| Windows venv SQLite全量 | 367项，276通过、91条件跳过、0失败；78.173秒 |
| WSL专用PostgreSQL最终全量 | 367通过、0失败、0跳过；225.709秒 |
| Node全部前端行为测试 | 39通过、0失败、0跳过 |
| 前端8份JS语法 | 全部通过 |
| pip check | No broken requirements found |
| git diff --check | 通过 |

命令为`python -m unittest discover -s tests -v`，PG设置`TEST_DATABASE_URL=postgresql:///red_test_20260921`；仅使用专用测试库和临时schema。前端为`node --test tests/frontend*.test.js`及逐个`node --check frontend/*.js`，单独execution文件只有34项，不将其写成39项。

证据位于外层工作区outputs/live-acceptance-20261001：budget-fix-sqlite.log、budget-fix-node.log、budget-fix-postgres-final.log。首次PG全量budget-fix-postgres.log有2项SIGKILL子进程marker等待超时，空子进程日志；后续runtime组19项通过后再次完整运行367项通过。没有修改20秒门限，首次失败未删除；仍保留进程启动时序波动风险。

## 网页与真实模型边界

8799独立服务的首页和app.js直接HTTP诊断均返回200，响应包含新费用面板和回调。该诊断只证明服务返回补丁，不证明页面渲染、拒绝或同意后的真实点击通过。

用户已手动打开正常HTTP页面，但本轮工具没有原内置浏览器控制接口。computer-use只识别到ChatGPT窗口，其规则禁止自动操作该界面；没有换用原始CDP或其他界面绕过。真实网页启动、费用台账和导出需在受支持接口恢复后继续验收。

此前2f5c24e的8次DeepSeek请求、人工采用及960字节导出属于先前真实后端与部分网页验收，不能归到本补丁。原ACCEPTANCE.md及台账证据保留；本补丁没有追加收费请求，不声称实际模型质量或生产发布已经验证。

本轮仅本地分支fix/new-user-workflow-20261001封存，不推送协作者分支、不改main、不创建PR、不部署、不操作真实社媒或业务库。.env、API凭据、数据库和运行状态不纳入提交。
