# 有迹：云部署前置工作与内测交接

2026-10-08。本次只准备部署文件和本地回归，不代表已经部署公网。适用当前 FastAPI + 独立 Worker + PostgreSQL 实现；项目可以继续开发，先建立邀请制内测环境。

## 需要你准备的条件

| 条件 | 用途 / 交接内容 |
| --- | --- |
| 一台可通过 SSH 管理的 Linux 云服务器 | 告知厂商、地域、系统、IP、登录用户名及可用的 SSH 密钥路径；密码和私钥不要发进聊天。需要 sudo 管理服务。 |
| 域名和 DNS 管理权限 | 首版使用单独内测子域名，解析至服务器公网 IP；PUBLIC_ORIGIN 与外部地址必须完全一致。 |
| 数据与费用范围 | 默认新建空的内测库，不复制本机用户资料；迁移真实数据须另行确认范围。服务器和域名购买费用按云厂商结算页确认。 |
| 邀请码及可选模型 Key | 邀请码随机生成且至少16位；只在服务器安全配置。首次模型 Key 留空，用模拟流程验收；付费模型验收单独授权。 |
| 公网接入条件 | DNS、80/443端口、服务器出站访问包源及需要使用的模型服务；SSH仅允许管理员来源，5432/8765不开放公网。 |

Python 3.12+、PostgreSQL、Caddy 与 systemd 是本方案软件前提；具体系统发行版、软件安装方式和资源规格在服务器确定后匹配，不把尚未实测的配置当成容量承诺。数据库可以先同机部署，必须独立用户与专用库。域名指向中国内地服务器并对外提供网站服务时，需完成对应备案；以接入商当前审核要求为准。[阿里云官方说明](https://help.aliyun.com/zh/icp-filing/basic-icp-service/support/for-the-record-process-faq)

## 已准备的文件与边界

- `deploy/production.env.example`：服务器配置示例，不含真实密钥。
- `deploy/youji-api.service`、`deploy/youji-worker.service`：非 root 服务用户、自动重启、只读项目目录与可写 runtime。
- `deploy/Caddyfile`：HTTPS 反代入口。需替换域名并在 Linux 上验证配置。
- `scripts/deploy_check.py`：无模型调用的配置检查，可选只读数据库权限与 Worker 心跳检查；异常输出不会展示原始连接串。

源码固定在 `/opt/youji`，Linux 上重新创建 `runtime/venv`，不要复制 Mac 虚拟环境。本方案使用应用已有的根目录 `.env` 读取方式，两进程读取同一文件；不通过 shell `source` 执行。文件权限600，属主youji，项目代码由root管理。应用设置优先读取进程环境变量，所以不要在服务环境另设冲突的 DATABASE_URL/PUBLIC_ORIGIN。不要将本机 `.env`、runtime、日志或用户资料上传到源码包。

模板尚未在真实 Linux 服务器执行。systemd 托管与文件保护参数参照[官方说明](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml)；Caddy 自动证书需要域名解析正确以及对外可达的80/443端口，参照[官方 HTTPS 指南](https://caddyserver.com/docs/quick-starts/https)。

## 服务器确定后的落地顺序

先安装 Python、PostgreSQL、Caddy，并确认没有同名现有服务/数据库。以下针对专用新服务器，修改已有服务器前先检查现状；购买、DNS修改、对外开放和真实资料迁移分别在实际执行前交出具体配置供审阅。

1. 固定本次审阅的 Git commit，上传该版本的干净源码到 `/opt/youji`。不要直接同步带未提交材料的本机目录。保留上个发布版本用于回退。
2. 创建无登录shell的 youji 系统用户与同名组，项目目录归root，只给 runtime 和配置文件必要权限；在服务器安装依赖：

```bash
cd /opt/youji
sudo python3.12 -m venv runtime/venv
sudo runtime/venv/bin/pip install -r requirements.txt
sudo chown -R youji:youji runtime
sudo install -o youji -g youji -m 600 deploy/production.env.example .env
```

这条 install 仅在 `.env` 不存在时执行；升级时保留原文件。用服务器编辑器填写 `.env`，不要把真实配置写到命令行历史。

3. 用PostgreSQL管理员创建 `youji` 非 superuser 角色，禁止 CREATEDB/CREATEROLE；建立属主为youji的专用数据库。在交互式 psql 用 `\password youji` 设置密码。DATABASE_URL 中密码特殊字符需 URL 编码。应用当前启动会建表和升级，用户必须拥有专用schema内DDL权限；不能仅授予DML权限，也不授予其他数据库的管理权限。
4. 校验配置及数据库：

```bash
sudo -u youji /opt/youji/runtime/venv/bin/python -m scripts.deploy_check --database
```

所有 `python -m` 命令必须从 `/opt/youji` 执行。默认模式只检查配置；`--database` 只读连接及权限；`--worker` 还需要最近45秒心跳。检查通过不意味着数据库结构、网页或后台任务已经验收。

5. 备份已有目标数据库后，停止API/Worker，再执行初始化/升级。空库无需旧数据导入；`backend.migrate` 是SQLite旧数据导入入口，不是版本升级CLI。下面初始化业务表和LangGraph检查点，不领取任务、不调用模型：

```bash
sudo -u youji runtime/venv/bin/python -c '
from backend.api import create_app
from backend.runtime import checkpointer
app = create_app()
with checkpointer(app.state.store):
    pass
print("Database initialization complete; no model calls")
'
```

6. 替换 Caddyfile 域名，与 `.env` 的 PUBLIC_ORIGIN 一致；服务文件按实际安装路径核对后安装。Caddy反代保留浏览器Host，不改成127.0.0.1；应用不支持挂在子路径。

```bash
sudo install -m 644 deploy/youji-api.service /etc/systemd/system/youji-api.service
sudo install -m 644 deploy/youji-worker.service /etc/systemd/system/youji-worker.service
sudo systemd-analyze verify /etc/systemd/system/youji-api.service /etc/systemd/system/youji-worker.service
sudo install -m 644 deploy/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl daemon-reload
sudo systemctl enable --now youji-api youji-worker
sudo systemctl reload caddy
sudo -u youji runtime/venv/bin/python -m scripts.deploy_check --worker
```

替换已有Caddy配置前备份并检查是否还承载其他网站。以上不设置安全组、不改DNS，也不采购资源；域名、备案与外部开放条件满足后再启用公网访问。

## 首次验收与继续更新

由部署人员填写以下记录，未验证项保持待验证。首轮 DEEPSEEK_API_KEY 留空且 WINDTUNNEL_ALLOW_LIVE=false；不得把模型替身/模拟通过写成模型质量已通过。

| 验收项 | 记录 / 证据 |
| --- | --- |
| 发布版本 | Git commit、服务器系统、依赖安装结果、测试日志 |
| 数据库 | 专用角色、业务迁移、检查点表、备份和独立恢复演练 |
| 服务 | API与Worker均正常，--worker检查通过；systemctl active不能单独证明Worker健康 |
| HTTPS | 外部设备访问域名，证书有效，HTTP跳转HTTPS；/health返回ok且database为postgresql |
| 身份与隔离 | 邀请码注册、登录、退出、CSRF拒绝、两个用户无法互相访问资料与任务 |
| 完整模拟流程 | 上传资料→后台创作→人工修改/确认→下载；亲自检查下载的内容 |
| 重启恢复 | 测试专用模拟任务时分别重启两个服务，刷新后可恢复，不重复提交产物 |
| 全量回归 | 真实PostgreSQL临时schema测试及检查点/进程重启用例，不把skip计为通过；五份脚本语法、卡片同步、空白检查 |
| 待独立验收 | 模型真实质量/费用、公开搜索可用性、真实社媒发布权限、公开用户规模及数据删除政策 |

本机 API 健康探测必须携带域名Host（将示例替换为实际域名）：

```bash
curl --fail --silent --show-error -H 'Host:youji.example.org' http://127.0.0.1:8765/health
curl --fail --silent --show-error https://youji.example.org/health
```

Worker检查只证明至少一个近期Worker在线，仍需端到端模拟任务验证。更新前停止写入和Worker，备份数据库及服务器配置并保存旧代码版本；使用pg_dump/pg_restore在独立库完成恢复演练，参照[PostgreSQL备份文档](https://www.postgresql.org/docs/current/app-pgdump.html)。检查备份不含遗漏的检查点/schema，并核对账号、任务与资料数量。迁移不可通过删除版本记录降级；代码回退必须先检查旧代码与新schema兼容，不兼容时将备份恢复到独立库并切换，避免覆盖唯一现存数据库。恢复点之后的新数据不会自动保留。

项目继续开发时，本机开发与云端内测库分开；发布固定commit，更新后重复必要验收。没有服务器信息、SSH/DNS权限与外部实测前，不标记公网部署完成。

## 本次本地验证记录（2026-10-08）

使用 `runtime/venv/bin/python`，在进程内从已有设置读取本机 DATABASE_URL 到 TEST_DATABASE_URL（不打印连接串），执行全量 `unittest discover -s tests`：460个测试通过、0失败、0错误、0跳过，耗时149.958秒。包含本次新增5个部署检查测试以及真实PostgreSQL临时schema、持久检查点与进程重启用例。首次受沙箱数据库/端口限制的运行没有计作验收，通过授权环境重跑后得到以上结果。

五份前端脚本 `node --check`、角色卡生成内容与已保存文件一致性、`git diff --check` 均通过。部署检查使用的只读事务与pg_roles查询另在真实PostgreSQL执行验证；未做收费模型调用。Linux服务启动、Caddy配置验证、域名证书、外部设备和云端下载验收仍待服务器具备后执行。
