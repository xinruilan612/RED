# 空库部署与可复现交付

本说明用于本机验证。需要 Python 3.12+、PostgreSQL 服务及其 `createdb`、`psql` 客户端；前端无需构建，脚本检查使用 Node.js。操作使用新空库，不导入已有账号、历史或密钥。

## 1. 校验并解压

开发者在仓库根目录构建：

```bash
python3 scripts/package_windtunnel.py --output output/youji-windtunnel-source.zip
```

产生 ZIP、同名 `.manifest.json` 文件和 `.sha256` 文件。打包对象是当前存在的 Git 已跟踪源码及明确指定的新文件；不会恢复工作区已删除的文件。未提交文件通过内置交付清单或 `--include 仓库相对路径` 指定，仍受敏感路径和内容拦截约束。

接收者使用系统 SHA-256 工具校验 ZIP 与 `.sha256`，解压后进入 `youji-windtunnel`。归档内 `DELIVERY_MANIFEST.json` 给出各源码文件的 SHA-256 和大小；`git_base_revision` 只表示来源基线，交付内容以逐文件哈希为准。重复打包相同源码得到相同 ZIP。

## 2. 创建本机空库与安装依赖

以下示例假定当前操作系统用户已有本机 PostgreSQL 建库权限及 socket 认证。数据库名若已存在，请换新名字；不要删除或覆盖原数据库。

```bash
createdb youji_windtunnel_demo
python3 -m venv runtime/venv
runtime/venv/bin/python -m pip install -r requirements.txt
```

`requirements.txt` 固定依赖版本；它不是包含全部平台 wheel 哈希的离线锁文件。数据库服务、系统依赖和下载网络需接收者自行准备。

在每个启动终端设置以下相同配置。环境变量覆盖项目 `.env`，空 Key 可阻止复用机器上的付费凭证：

```bash
export DATABASE_URL=postgresql:///youji_windtunnel_demo
export PUBLIC_ORIGIN=http://127.0.0.1:8765
export DEEPSEEK_API_KEY=
export WINDTUNNEL_ALLOW_LIVE=false
```

不需要创建 `.env`。本机另需密码连接时，由本机 PostgreSQL 配置管理凭证，不把连接密码写入源码、演示资料或交付包。

## 3. 初始化并启动 API 与 Worker

终端 A 在项目根目录执行：

```bash
runtime/venv/bin/python -m backend.api --port 8765
```

启动时 `Store` 创建基础表，`Service` 调用顺序迁移并校验已应用迁移的 checksum；这是新空库初始化。不要对空库运行面向旧 SQLite 数据导入的 `backend.migrate`。迁移出错时先停止并检查错误，不修改已应用迁移记录绕过校验。

终端 B 进入同一目录，重复上面的四个环境设置后执行：

```bash
runtime/venv/bin/python -m backend.worker
```

浏览器访问 `http://127.0.0.1:8765`，不能换成不同域名或端口。`/health` 应返回数据库类型 `postgresql`。创建全新的普通演示账号并保管其恢复码；恢复码不录进演示视频。

API 接收登录、保存和入队；Worker 从 PostgreSQL 队列领取后台任务。两个进程都必须运行，并指向同一数据库。仅开网页服务不等于后台任务执行。停止演示使用两个终端的 Ctrl+C，数据库保留；再次启动可读取已保存记录。

## 4. 免费模拟复现

打开内容风洞入口，用 [团队自建演示](DEMO_MATERIAL.md) 的材料创建任务。请求契约为 `POST /api/runs`，`workflow_type: "windtunnel"`、`mode: "simulation"`；经网页确认问题卡后由既有 `/api/runs/{id}/background` 后台入口继续。

不设置 `WINDTUNNEL_ALLOW_LIVE=true`，不提供真实模型 Key。本轮模拟和模型替身测试不产生模型费用；模拟标签应持续可见，不把替身的预设判断解释成真实模型效果。已有 Key 也不能代替开启真实风洞调用的显式授权。

按演示脚本执行：确认问题、读稿检查、资料核实、局部改稿、作者采用、同条件复查和导出。刷新页面、停止后重启两进程，核对保存的稿件和报告；是否已实际通过这些检查以 [工程记录](ENGINEERING_REPORT.md) 为准。

## 5. 验证与交付边界

完整回归使用可建立临时 schema 的专用测试库：

```bash
createdb youji_windtunnel_test
TEST_DATABASE_URL=postgresql:///youji_windtunnel_test PYTHONDONTWRITEBYTECODE=1 runtime/venv/bin/python -m unittest discover -s tests -v
node --check frontend/windtunnel.js
```

项目其余前端脚本检查、角色卡一致性与 Git 空白检查由主交付记录统一列出。没有 `TEST_DATABASE_URL` 时跳过的 PostgreSQL 用例不算通过。完整测试使用替身，不能证明真实模型发现问题的精度。

本包是源码部署包，不是已验收的公网服务。公网开放另需 HTTPS、邀请码、服务守护、权限复验、备份恢复和模型费用授权；本轮不会代用户部署或充值。正式赛题与材料要求以项目 [参赛要求](../CONTEST_REQUIREMENTS.md) 为入口。
