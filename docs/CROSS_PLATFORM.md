# Windows、macOS 与 Linux 本地使用

同一份 Python 后端和原生网页代码，不依赖某个平台专用的业务实现。目标支持 Windows 10/11 x64、Intel / Apple Silicon macOS，以及常见 x64 Linux；推荐 Python 3.12、本机 PostgreSQL 和现代浏览器（Safari 15.4+，或受支持的新版 Chrome/Edge/Firefox）。已验证与待验证范围见下方；不能把虚拟环境、`.env` 或数据库从另一台电脑直接复制来运行。

## 苹果电脑

先安装适用于自己 CPU 的 Python 3.12+ 与 PostgreSQL，保持数据库服务开启。在项目目录的终端执行：

```sh
bash start-unix.sh setup
```

安装使用 requirements.txt 的锁定版本；失败则停止，不跳过依赖。已有 `.env` 会保留。用 PostgreSQL 的 psql 在自己电脑创建独立应用数据库：

```sql
CREATE DATABASE youji_operations;
```

用文本编辑器打开项目根目录 `.env`，设置本机连接；有密码时使用 URL 编码，不要上传密码：

```dotenv
DATABASE_URL=postgresql://YOUR_LOCAL_USER:CHANGE_ME@127.0.0.1:5432/youji_operations
PUBLIC_ORIGIN=http://127.0.0.1:8765
DEEPSEEK_API_KEY=
```

Key 可以留空，默认模拟不收费。检查并启动：

```sh
bash start-unix.sh doctor
bash start-macos.command
```

从 GitHub ZIP 下载时若 Finder 提示脚本不可执行，在终端执行一次 `chmod +x start-macos.command start-unix.sh`，之后可双击 `start-macos.command`。不要绕过 macOS 或浏览器的安全提示；可直接在终端使用上面的 `bash` 命令。

启动器从脚本所在目录寻找源码，兼容路径中的空格和中文。它优先使用本机 `runtime/venv`（也兼容已有 `.venv`），而不是直接调用其他电脑的解释器。API 与 Worker 同时运行，一个异常退出时另一个会停；Ctrl+C 停止两者。

## Windows

完整步骤见 [Windows 安装与启动](WINDOWS.md)：

```powershell
./start-windows.cmd setup
./start-windows.cmd doctor
./start-windows.cmd
```

先安装本机 Python 3.12+ 与 PostgreSQL，自己创建应用数据库并填写 `.env`。脚本不自动迁移现有业务数据。Windows 使用 Scripts/python.exe，苹果/Linux 使用 bin/python；不要把两者混用。

## 两个平台共有的使用方式

启动后打开与 `.env` 中 PUBLIC_ORIGIN 一致的地址（默认 http://127.0.0.1:8765/），注册自己的网站账号。填写档案 → 创作主题与素材 → 运行 → 检查并确认 → 下载。资料、周计划与进阶检查可按需使用。其他电脑的数据不随源码同步；不要为方便演示直接拷贝运行中的数据库。

模拟与真实 AI 始终分开。选择真实模式、确认费用后才调用模型；平台发布仍需本人完成，不会自动发送内容。

## 验证边界

最新 v5 修正了原生 Windows 完整 CI 暴露的迁移 SQLite reader 未显式关闭，以及测试夹具人为 1 秒租约的问题；产品仍使用原 30 秒租约，安全守卫不变，恢复测试仍真实终止进程并验证不重复调用。测试控制精确已终止任务的过期时间，不冒称自然等待。重新独立门禁：Windows SQLite 487 项中 377 通过/110 PG 条件跳过、106.719 秒；专用 PG 487/487 零跳过、91.799 秒；Node 94/94、9 JS、cp936 文本 3/3、依赖/空白/原生启动 help 与 Unix shell 全过。下段 478 为 v4 历史，不归给新补丁；新版本的原生四平台结果以实际精确提交 Actions 为准，不能由本地 WSL 推断。

2026-10-02 真实网站账号验收又发现并修复默认停留旧稿、复审已耗尽仍提示收费操作、人工采用后仍显示阻断面板；干净包复验还修复了旧版本机 Demo 拒绝 POST 时的 Windows 连接中止。首次上传后的实际 CI 又纠正了私有临时目录的 Windows 当前用户权限和 macOS 测试路径别名。最新补丁重新独立执行：Windows Python 3.12.6 全量 478 项（368 通过、110 项专用 PostgreSQL 条件跳过，零失败，85.468 秒）；WSL Linux Python 3.14.4 / 专用 PostgreSQL 18.6 全量 478/478，零跳过（93.307 秒）；前端行为 94/94、9 个 JS 语法、依赖一致性和 cp936 下 UTF-8 契约均通过。legacy 拒绝修复时另有 20 个独立场景共 60 次实际 403，没有重试请求或放宽安全规则。详细范围与真实付费模型、人工采用事实见 [本轮实际验收](validation/REAL_ACCOUNT_ACCEPTANCE_20261002.md)。此前 391、433/80、459/93、459/94、468/94 门禁只属于各自源码快照。

Windows 本机网页模拟闭环、中文 / 空格路径的原生启动入口已经实测；本轮另外完成已登录网站账号的真实 DeepSeek 创作、人工采用、下载和刷新保持。它不是社媒账号授权或真人盲测。

macOS Intel 与 Apple Silicon、Windows 和 Linux 的 GitHub 测试矩阵采用独立临时 PostgreSQL、Python 3.12 和 Node 22。对应平台是否通过，以 [本分支实际 Actions](https://github.com/xinruilan612/RED/actions?query=branch%3A%E7%8E%8B%E9%A1%BA%E7%84%B6-20261002) 的具体提交和结果为准；配置文件本身不算执行证据。首次上传的 CI 失败及最小修正完整保留，当前 v4 包制作时该修正尚未推送，后续真实结果保存在验收证据中。Windows CI 权限处理仅用于已验证的 GitHub 临时目录，不修改使用者机器权限、业务库或系统服务。Mac Finder / Safari 用户闭环尚未验收，不能以 CI 的命令行成功称为苹果桌面完整实测。

独立报告 PDF 生成工具（非网站运行所必需）使用文档专用 Python / ReportLab，可自动选择本机中文 TrueType 字体，也可用 `SUBMISSION_CJK_FONT` 指定已有字体。无可用字体或缺字时明确失败，不下载字体或默默生成乱码。Windows 临时中文样本已验证字体嵌入和显示；这不是原六份报告或 Mac 排版完整验收。

Unix PDF 子进程可使用 resource 限额；Windows 缺少该模块，仍受文件大小、页数、文本长度和父进程超时控制。不承诺所有旧系统、任意浏览器、Windows ARM、OCR/扫描 PDF 或平台自动发布已兼容。浏览器需支持安全上下文的 Web Crypto；localhost 不需为此暴露公网。
