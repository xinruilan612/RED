# 第二阶段共享文件增量

这两份补丁以本轮开始时的未提交工作树为基线，不是以 HEAD 为基线；当前工作树已包含它们，不要重复应用。service.patch 对应 backend/service.py，knowledge.patch 对应 frontend/knowledge.js。

原文件包含此前搜索确认流程等修改，增量无法安全独立暂存，因此保留原工作树并随本轮提交保存可审阅补丁。完整测试依赖此前未提交的 api.py、knowledge.py、research_jobs.py 等以及 tests/test_research_confirmation.py。该提交是本轮变更记录，不是独立部署包；恢复需保留此前基线。
