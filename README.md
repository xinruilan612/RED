# 有迹 · 四 Agent 创作工作台

当前可用：本机网页模拟版，无需 API Key，不产生模型费用。

## 打开方式

在项目目录运行：

```bash
python3 -m backend.web --port 8765
```

然后打开 http://127.0.0.1:8765/ 。保持终端运行；关闭后可用相同命令再次启动。首次不需安装依赖。端口被占用时改为 `--port 8766`，并打开对应地址。

## 可以测试什么

1. 填写主题、读者、风格和素材，选择演示场景，点击“创建工作流”。
2. 用“执行下一步”逐阶段查看，也可“自动运行到人工处理”。点击角色或创作阶段，查看中文产物、输入和历史记录。
3. 选择“审核发现问题”场景：流程会停下，你可以自动改稿或手动编辑。保存的新版本需要复审，旧版本仍可比较。
4. 选择“资料不足”场景且不填素材：流程会要求你补充，再重新分析。
5. 最后由你确认准确版本，下载 Markdown 文稿。没有自动发布。

任务存储在被 Git 忽略的 runtime/demo.sqlite。使用同一浏览器和同一地址可恢复历史；localhost 和 127.0.0.1 的会话不同，清除 Cookie 后原会话不会自动找回。不要删除数据库来重启服务。

## 目前的边界

四个角色使用固定模板和少量本地检查规则，未接真实模型、联网搜索或历史数据分析。通过模拟审核不代表事实、原创或平台合规已验证。暂时提供文稿导出，尚无图片生成/图文包导出。

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
