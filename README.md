# 有迹 · 热点驱动的博主运营助手

产品新方向：面向小红书、抖音，将选题发现、四 Agent 创作、版本评审、人工审核与发布、指标回流、历史学习连成运营闭环。

**当前可用的是四 Agent 本机文字创作 Demo；运营闭环 v0.4 为设计提案，尚未实现。** 模拟模式免费；DeepSeek 真实文字链路已有一次生成与审核记录，未证明模型质量稳定。详见 [实际开发进度](docs/IMPLEMENTATION_STATUS.md)。

2026-09-20 本轮只整理已有文档、运行现有 Demo、完成技术方案；不开发新功能、不新建文件夹。协作规则沿用根目录 AGENTS.md，不另建同义的 AGENT.md 或第二套 MVP README。

## 新版产品范围

| 目标能力 | 当前情况 | v0.4 设计方向 |
| --- | --- | --- |
| 实时选题与趋势发现 | 尚无联网热点源 | 授权来源采集、时间戳、去重、账号匹配与人工选题；无接口时手工导入并标注非实时 |
| 多 Agent 分工创作 | 四角色、五创作阶段可运行 | 保留 audience/research/content/reviewer，增加趋势与历史上下文 |
| 多版本评审优化 | 返修版本、比较、复审可用 | 增加同 Brief 的策略候选，分别审核、由人选用 |
| 人工审核与真实发布 | 已有定稿确认及 Markdown 导出 | 国内平台适配；发布前确认账号、平台、内容版本和时间，跟踪平台回执 |
| 数据指标回流 | 未实现 | 手工数据导入起步；获权后接官方指标接口，保留统计口径 |
| 根据历史自动学习 | 未实现 | 自动汇总效果与候选经验，经用户接受后进入有版本、可回滚的记忆 |

用户已明确首期聚焦国内平台，**暂不接入 Postiz**。参考仓库为 [Klaudiusz321/social-media-agents](https://github.com/Klaudiusz321/social-media-agents)，不能与 langchain-ai/social-media-agent 混同。建议后续编排采用 LangGraph，首期不同时引入 CrewAI、ElizaOS 或 OASIS。详细取舍见 [技术方案](docs/design/ARCHITECTURE.md#运营闭环-v04-技术提案) 与 [分阶段迁移](docs/design/MIGRATION.md#运营闭环-v04-推进计划)。

小红书优先规划图文笔记；抖音先规划标题、口播脚本、分镜和用户提供的成片发布，不把文本脚本当成视频，也不将视频生成纳入首期。具体账号资质、可用数据源和抖音内容形态在实施前确认。

## 打开方式

在项目目录运行：

```bash
python3 -m backend.web --port 8765
```

然后打开 http://127.0.0.1:8765/ 。保持终端运行；关闭后可用相同命令再次启动。首次不需安装依赖。端口被占用时改为 `--port 8766`，并打开对应地址。

## 填写 DeepSeek Key

项目根目录已准备 `.env`，只需填写 `DEEPSEEK_API_KEY=你的密钥`，保存并重启服务。新建创作时选择“真实 AI · DeepSeek”，再执行流程。旧任务保持原运行方式。密钥不提交 Git，不发送到浏览器。

完整步骤、限制与图片/PDF 扩展方式见 [DeepSeek 使用说明](docs/DEEPSEEK_SETUP.md)。

## 可以测试什么

1. 填写主题、读者、风格和素材，选择演示场景，点击“创建工作流”。
2. 用“执行下一步”逐阶段查看，也可“自动运行到人工处理”。点击角色或创作阶段，查看中文产物、输入和历史记录。
3. 选择“审核发现问题”场景：流程会停下，你可以自动改稿或手动编辑。保存的新版本需要复审，旧版本仍可比较。
4. 选择“资料不足”场景且不填素材：流程会要求你补充，再重新分析。
5. 最后由你确认准确版本，下载 Markdown 文稿。没有自动发布。

任务存储在被 Git 忽略的 runtime/demo.sqlite。使用同一浏览器和同一地址可恢复历史；localhost 和 127.0.0.1 的会话不同，清除 Cookie 后原会话不会自动找回。不要删除数据库来重启服务。

## 目前的边界

模拟模式使用固定模板；真实模式由 DeepSeek 执行四角色，正常首次 8 次请求，改稿后复审。暂未接联网搜索、历史指标导入、图片或 PDF 上传、图片生成和图文包导出。审核不代表事实、原创或平台合规已独立验证。

此服务只绑定本机回环地址，是 UI 与流程验收版本，不可直接部署公网。后续生产 API、账号体系和任务队列按设计继续开发。HTTP 使用标准库以便零安装测试，前端使用原生 HTML/CSS/JS；不宣称已实现规划中的 FastAPI/Next.js/PostgreSQL 部署。

- [实际开发进度](docs/IMPLEMENTATION_STATUS.md)
- [本轮验证记录](docs/WEB_DEMO_VALIDATION.md)
- [设计入口](docs/design/README.md)
- [Agent 规范](docs/agents/00_overview_and_all_agents.md)

## 开发验证

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
node --check frontend/app.js
git diff --check
```

集成测试在临时本机端口启动 HTTP 服务，需要允许监听回环端口，不请求外网。当前测试不调用收费模型。

## 本轮 Demo 与存档

代码基线：main / a561323。backend/ 和 frontend/ 已纳入 Git。修改前源码归档及 SQLite 一致性备份放在已有 runtime/ 中，未新建目录；不包含 .env。存档清单见 [验证记录](docs/WEB_DEMO_VALIDATION.md)。

本轮演示使用独立数据库，避免修改原有创作历史：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m backend.web --port 8765 --db runtime/hotspot-review-demo.sqlite
```

打开页面后明确选择“模拟流程（免费，不调用模型）”。已配置 Key 时页面可能默认选择真实 AI。本轮只运行原有流程；热点、发布、指标和学习的界面与演示仍待后续实现。
