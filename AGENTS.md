# 注意事项

1. 每次改动完成后，都必须创建一个对应的Git commit，以便后续追踪和回滚。
2. 每次改动后，都必须编写或更新相关测试，并在交付给用户前，确保所有测试和验证全部通过。

## 参赛要求入口

开展产品设计、实现、验收或参赛材料编写前，阅读 [参赛要求与交付对照](docs/CONTEST_REQUIREMENTS.md)。详细规则在该文档维护，不在此重复。

区分官网要求、待核实的截图材料与项目建议；未确认适用性的其他赛题规则不得作为本项目硬性要求。提交前复核最新官方通知，产品完成状态和测试结论必须有实际证据。

文档检查命令：`python3 -m unittest discover -s tests -v`；空白检查命令：`git diff --check`。有产品代码后，还需执行对应的产品测试。

软件设计入口：[架构、模块与流程](docs/design/README.md)；开源参考：[GitHub 项目调研](docs/research/GITHUB_PROJECTS.md)。这些是开发前方案，尚不能作为实现或性能证据。修改图件后运行 `python3 scripts/build_design_atlas.py` 并验证生成物一致。

当前设计基线为 v0.2 五层（UI/Runtime Console、Orchestrator、Agents、Tools/Skills、Memory）与 audience/research/content/reviewer 四角色。实现前阅读 [迁移计划](docs/design/MIGRATION.md)，不要混用旧版角色契约。
