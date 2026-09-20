# 多 Agent 图文创作工作台

已确认的目标：在线网页产品，受众洞察与素材研究并行，内容策划创作、主编审核、返修复审与人工确认后导出。

当前交付是后端领域核心，尚无可使用的新网页或模型服务。参见 [实际开发进度](docs/IMPLEMENTATION_STATUS.md)，不要将设计图或底层测试当作完整产品。

- [设计入口](docs/design/README.md)
- [Agent 规范](docs/agents/00_overview_and_all_agents.md)
- [运行协议](docs/design/AGENT_PROTOCOL.md)

在项目根目录执行全部测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

当前测试不调用收费模型，也不需要 API Key。backend 是新的开发目录；旧 starter 的删除不由本轮提交处理。
