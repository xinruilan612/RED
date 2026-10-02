# Windows 本地运行

适用于 Windows 10/11 64 位，推荐 Python 3.12 64 位及 PostgreSQL 16/17。同一份业务代码支持 macOS/Linux；Windows 使用本页入口，不执行 `runtime/venv/bin/python` 或 Bash 环境变量命令。

## 首次安装

1. 安装 [Python 3.12](https://www.python.org/downloads/windows/)（保留 Python Launcher）和 [PostgreSQL](https://www.postgresql.org/download/windows/)，记住本机数据库密码。确保 PostgreSQL 服务正在运行。
2. 克隆或下载项目后，在项目根目录打开 PowerShell。不要复制队友 Mac 的 `runtime/venv`、`.env` 或数据库文件；Python 虚拟环境需要在自己的电脑重新创建。
3. 运行 `./start-windows.cmd setup`，安装锁定依赖并生成 `.env`。已有 `.env` 会保留，不覆盖。首次下载依赖需要网络。
4. 打开 PostgreSQL 自带的 SQL Shell (psql)，使用安装时设置的 postgres 用户和密码连接本机，执行一次：

```sql
CREATE DATABASE youji_operations;
```

5. 用编辑器打开项目根目录 `.env`，以 UTF-8 保存，修改下面的连接密码。密码中的 `@`、`#`、`%` 等字符须使用 URL 百分号编码，例如 `@` 写为 `%40`。不要把真实密码提交到 GitHub。

```dotenv
DATABASE_URL=postgresql://postgres:CHANGE_ME@127.0.0.1:5432/youji_operations
PUBLIC_ORIGIN=http://127.0.0.1:8765
DEEPSEEK_API_KEY=
```

默认模拟模式不收费，API Key 可以先留空；要使用真实 AI，再在自己电脑填写有效 Key，并在网页中主动选择真实模式。首次启动会创建应用表，无需手动执行迁移 SQL。

## 每次启动

```powershell
./start-windows.cmd doctor
./start-windows.cmd
```

检查通过、出现 API 启动成功信息后，在浏览器打开 **http://127.0.0.1:8765/**，首次自行注册网站账号。启动窗口会同时运行网站和后台 Worker；保持窗口打开，按 Ctrl+C 停止两者。一个子进程异常退出时，启动器也会停止另一个，避免只开网页却没有 Worker。

双方分别运行时，账号和作品存在各自的 PostgreSQL 中，不会随 GitHub 同步；需要共同数据时应另行部署共享服务。不要直接复制运行中的数据库文件。

## 常见情况

- 提示找不到 `py`：修复 Python 3.12 安装并启用 Python Launcher，重新打开终端。
- `PostgreSQL connection failed`：检查服务是否启动、5432 端口、数据库名和 `.env` 密码；检查器不会打印连接串或密码。
- 端口被占用：关闭旧服务，或将 `.env` 中 `PUBLIC_ORIGIN` 改为另一本机端口，例如 `http://127.0.0.1:8766`，并使用相同地址访问。
- 安装依赖失败：保留报错检查网络；不要跳过失败的包继续运行。重新运行 setup 可重试，不覆盖 `.env`。
- 不要混用 `localhost` 和 `127.0.0.1`：浏览器地址须与 `PUBLIC_ORIGIN` 一致。

## 开发验证与适配边界

开发测试另需安装 Node.js；只启动网站无需 Node.js。测试可能清理表，必须另建专用、可丢弃的测试数据库，例如 `youji_test`，不能使用上面的应用库 `youji_operations` 或任何真实业务数据库。PowerShell 验证示例（用自己的专用测试数据库连接）：

```powershell
$env:TEST_DATABASE_URL = 'postgresql://postgres:CHANGE_ME@127.0.0.1:5432/youji_test'
$env:PYTHONUTF8 = '1'
./runtime/venv/Scripts/python.exe -m unittest discover -s tests -v
node --test tests/frontend_account_profile.test.js tests/frontend_execution.test.js
```

PDF/Word 解析子进程用 ASCII 安全的 JSON 传输中文，配置读取支持 UTF-8 BOM。Windows 缺少 Unix `resource` 模块，因此 PDF 不启用 Unix CPU/内存硬限制，仍保留父进程超时、文件大小、页数及文本长度限制。参考 [Python 虚拟环境文档](https://docs.python.org/3/library/venv.html) 和 [resource 平台范围](https://docs.python.org/3/library/resource.html)。

2026-10-02 本轮已在 Windows 本机重新验收网页免费模拟闭环及完整 SQLite 回归；专用 PostgreSQL 全量在 WSL Linux 原生依赖环境通过。Windows 原生 PostgreSQL安装与全量数据库验证、macOS Intel / Apple Silicon 验证另由跨平台 CI 分开记录，尚不能用 WSL 或路径替身结果代替。共同入口与边界见 [跨平台使用](CROSS_PLATFORM.md)。
