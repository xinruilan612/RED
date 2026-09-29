# 启动独立演示

这是无模型密钥、无真实平台发布的功能演示入口，不会读取作者的 `.env` 或原业务数据库。

使用 Python 3.12，在解压后的项目根目录执行：

```text
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/start_demo.py
```

Linux / macOS：

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/start_demo.py
```

浏览器打开 <http://127.0.0.1:8786/>，自己注册本地测试用户，保管自己的恢复码。在“账号与历史”载入标注为演示的账号；资料库可预览并主动导入原创指南，也可上传自己的 UTF-8 文本或文本型 PDF。选择“模拟演示”进行创作与发布验证，不需要付费 API。

启动命令同时运行 API 和工作进程。`Ctrl+C` 停止本次启动的进程，数据保留在 `runtime/review-demo/demo.sqlite`，再次启动可继续；不要把该目录交给其他人。端口占用时可追加 `--port 8787`，启动器不会结束已有服务。可追加 `--check` 只检查依赖，或 `--smoke` 自动验证 HTTP 与工作进程并退出。

注意：首次安装依赖需要网络。该入口只监听本机，不是生产部署；HTTP Cookie 按主机共享，勿在同一浏览器中同时启动多个同类 review-demo 端口。模拟结果不代表真实模型质量、平台发布成功或运营增长。三份入门指南为项目自编，不是平台官方知识。
