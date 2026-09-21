# 网站后端运行与迁移

适用于 v0.6。当前在本机 PostgreSQL 验证；尚未购买云服务、绑定域名或公网部署。前端布局沿用原 Demo。

## 环境与启动

使用 Python 3.12+ 和 PostgreSQL。项目根目录安装锁定依赖：

```bash
python3 -m venv runtime/venv
runtime/venv/bin/pip install -r requirements.txt
```

在已有 `.env` 保留 DeepSeek Key，增加以下配置（不要提交真实密码）：

```dotenv
DATABASE_URL=postgresql:///youji_operations
PUBLIC_ORIGIN=http://127.0.0.1:8765
```

创建本项目专用数据库后运行：

```bash
runtime/venv/bin/python -m backend.api
```

服务器网址必须与 PUBLIC_ORIGIN 完全一致。默认只监听本机。公网前需设置 HTTPS 域名、至少16位 REGISTRATION_INVITE、数据库最小权限用户、TLS 反向代理及服务托管，并完成单独部署验收。数据库连接信息与密钥仅在服务器。当前首次注册可绑定本浏览器旧 Demo Cookie 对应空间；不自动合并两个用户空间。

## 保留旧数据并迁移

先停止旧 Demo 写入，用 SQLite backup API 保存一致性快照。原文件不得删除。目标应为空的专用数据库：

```bash
runtime/venv/bin/python -m backend.migrate --source runtime/before-web-foundation-hotspot-review-demo.sqlite
```

迁移逐行核对原始表，保留确认状态、来源模式和 owner；失败回滚业务导入。重复运行对同一未变化目标逐行检查，目标产生新业务后拒绝再次覆盖。依赖表的建表操作可以保留，不影响原 SQLite。回退时停止新服务，使用原 SQLite 启动 backend.web；新站期间新增的数据不会自动回流到旧库。

网站密码恢复使用注册时显示的一次性网站恢复码，重设后所有旧会话失效。网站没有短信/邮件发送服务，旧 Demo 的恢复码与网站恢复码不同。切勿把旧 backend.web 暴露公网。

## 数据库与测试

SQL 层保留有版本的业务聚合，并有 social_accounts/account_records 关系目录。PostgreSQL 短写事务使用事务咨询锁，网络和模型调用在事务外。此为小范围内测设计，不宣称已完成高并发优化。

```bash
TEST_DATABASE_URL=postgresql:///youji_operations PYTHONDONTWRITEBYTECODE=1 runtime/venv/bin/python -m unittest discover -s tests -v
node --check frontend/app.js
node --check frontend/operations.js
node --check frontend/account.js
node --check frontend/auth.js
git diff --check
```

数据库测试自动建立唯一的 youji_test_ 临时 schema，结束后清理；没有 TEST_DATABASE_URL 会跳过 PostgreSQL 集成测试，不能据此宣称数据库已验收。HTTP 测试需要允许监听本机端口。测试使用模型替身，不产生模型费用。

备份应覆盖数据库及 `.env` 的安全保管。可用 PostgreSQL 自带 pg_dump 导出到 runtime，恢复到单独测试库并核对后再用于线上回退。不要把凭证、数据库和运行日志加入 Git。
