# 最新版本部署与验收路径

本轮交付是本地软件候选版，无公网演示承诺。Windows包提供原有Python运行时和最新源码，已核查文件一致性，尚未在Windows原生环境执行。模型密钥、已有账号、数据库及运行记录不在公开软件包中。

## Windows本机

完整解压有迹-省赛最终交付-Windows-x64-20261103.zip，保留python与app等相对目录；双击一键启动.cmd。首次在本机创建网站账号，妥善保存恢复码；免费模拟不调用模型。真实AI需在模型与搜索设置中由使用者配置自己的可用连接，网络、厂商额度和模型输出均会影响运行。不要向评委分发个人密钥或已有私有数据。

实际Windows验收需记录系统版本、解压路径、启动日志、首页、免费模拟、真实模型、补料回答或跳过、改稿重审、人工确认和Word导出。模型费须在新的有效预算内，不能借本次交付自动续费。未执行的步骤保持待验收，不能用Mac测试或包哈希证明Windows可以启动。

## macOS或Linux源码

进入源码内app，按docs/DEPLOYMENT.md建立Python 3.12以上虚拟环境并安装requirements.txt；使用项目专用PostgreSQL数据库。DATABASE_URL及PUBLIC_ORIGIN只配置在本机，不提交密码。现有用户升级前备份，不删除数据库或应用过的迁移。

从app运行runtime/venv/bin/python scripts/local_dev.py start，同时管理API与Worker；入口http://127.0.0.1:8765/。也可以分别运行python -m backend.api --port 8765与python -m backend.worker，两个进程必须使用同一数据库和配置。源码包不附已安装的Mac依赖，首次启动不是双击Windows入口。

## 用户主流程

新建创作，选择小红书图文笔记，输入明确主题、读者、字数和真实素材。导入的事实资料与写法参考分开分类。联网只在用户明确选择时发起；未取得正文不算来源核实。三算法高级开关用于选择覆盖、结构及可选补料，补料默认不强制。

生成后查看规划及依据，先核对主要问题、型号、数值、条件、亲历和标签。规划覆盖不是正文完整度。审核needs_human或unknown保留问题；不能因稿件读起来流畅就当已核实。修改稿件产生新版本，旧审核不能直接批准新稿。人工采用和下载Word只表示本地采用或导出，不代表小红书发布。

本轮研究因未知用量失败停止，不提供绕过入口。若需继续真实研究，先到供应商侧核对对应失败调用及实际用量，保留原账本和失败格，再安排新冻结版本；不要删除unknown、重置账本或自动重发原请求。

## 免费复现

从app执行python scripts/algorithm_bench.py --output runtime/reproduce-mechanism --tasks 24 --seed 20261102，以及python scripts/structure_ablation.py --output runtime/reproduce-structure。两者为离线构造机制，不调用模型。覆盖修正可用scripts/replay_coverage_gate.py对公开脱敏receipt离线回放，原稿不变。

后端完整回归需要TEST_DATABASE_URL指向可建立临时schema的专用PostgreSQL；命令python -m unittest discover -s tests -v。无数据库时跳过的集成用例不计通过。Node可执行node --test tests/frontend*.test.js。所有真实模型实验入口单独标明付费，不属于免费复现。
