# SKAPP 作者参考实现接入

本项目固定引用 [YifanZhang-git/SKAPP](https://github.com/YifanZhang-git/SKAPP) 的 `3353b5a79bbeacf8110971b2ef035a4046c1a25c`，MIT 许可证位于 `third_party/skapp/LICENSE`。`PROVENANCE.json` 保存全部引入文件的 SHA-256；包装命令执行前校验。源码未改动，不将该算法称为本团队原创。

## 复现边界

用户最终需要的是基于本人历史图文记录辅助评估下一篇选题热度。此公共基准复现只作为基础验证，不等于该个人历史预测产品已完成。

这是作者当前参考实现的复现。当前代码核心是 RRCP 门控注意力，不能据此声称逐公式复现论文所述双图网络和硬筛选。预处理数据已有图文特征、500 个检索邻居和 RRCP；本轮训练不重训提供这些 RRCP 的教师模型。教师训练与重建方式见作者 README。

公开数据集分数不等于小红书爆款概率。仓库没有从新稿文字/封面到兼容特征及检索邻居的完整生产流程，因此此入口展示公共样本预测，不接受新稿并伪造分数。ICIP 使用 `mean_views`；其采集时点未核实，不能证明严格发布前预测，更不能视为因果增长证明。单种子或缩短训练的实验必须按实际轮数展示，不能引用论文效果为本次效果。

## 独立运行

先建立单独 Python 3.12 环境（例如 `runtime/skapp-venv`），按作者要求安装适用设备的 PyTorch 和 `third_party/skapp/requirements.txt`。不要安装到网站 `runtime/venv`。所有数据、模型、环境和运行结果放在已忽略的 `runtime/`，不提交密钥、训练数据或模型权重。

以下命令在仓库根目录运行，默认 CPU；按本机实际 Python 路径调整。数据下载会访问作者目录给出的 Google Drive，ICIP 压缩包约 247 MB，解压后约 353 MB，下载器检查空间与哈希。

```sh
runtime/skapp-venv/bin/python scripts/skapp_experiment.py download --python runtime/skapp-venv/bin/python --dataset icip
runtime/skapp-venv/bin/python scripts/skapp_experiment.py train --python runtime/skapp-venv/bin/python --dataset-path runtime/skapp/data/icip --output-dir runtime/skapp/runs/icip-seed12 --epochs 60 --seeds 12
runtime/skapp-venv/bin/python scripts/skapp_experiment.py evaluate --python runtime/skapp-venv/bin/python --dataset-path runtime/skapp/data/icip --training-dir runtime/skapp/runs/icip-seed12 --output-dir runtime/skapp/evaluations/icip-seed12
runtime/skapp-venv/bin/python scripts/skapp_experiment.py publish --evaluation-dir runtime/skapp/evaluations/icip-seed12
```

若下载受限，可以先取得作者原始 ZIP，再向 download 添加 `--archive /绝对路径/skapp-icip.zip`；仍校验作者哈希。训练与评估目录不能覆盖，修改参数须使用新目录。`--device` 可显式指定已验证的硬件。缩短 `--epochs` 只证明流程可运行，不能宣称达到论文精度。

评估先检查验证集预测逐位一致，再运行测试集。publish 要求完整评估、固定数据发布版、检查点哈希、测试样本 ID/标签一致，并从真实预测重新计算 MSE、MAE、Spearman SRC。与“训练集平均标签预测所有测试样本”的基线比较；常量预测没有排序方差，基线 SRC 未定义，输出 null 而不是 0。测试标签不用于训练或模型选择。网站发布要求单个预先指定种子，避免挑选测试表现最好的种子；多种子统计保留在上游原始评估报告中。

结果默认写入 `runtime/skapp/result.json`，使用排他创建，存在时不覆盖。另一个实验可 `--output` 到新文件，由维护者审阅后选择网站展示哪份。CPU 和计时字段属于运行记录，可通过 `--device`、`--duration-seconds` 明确填写，未测量时计时为 null。网站仅展示真实存在且验证通过的结果；未完成训练不能生成占位指标。

## 验证

```sh
runtime/venv/bin/python -m unittest tests.test_skapp_experiment -v
```

包装层测试只验证来源完整性、参数、安全失败及禁止覆盖，不联网、不训练。实际训练与模型质量必须另行提供真实日志、检查点、预测文件和评估结果，不能用包装层测试通过替代。


## 2026-10-07 个人图文预测接入（原结构重新训练）

网页 `Topics.evaluate` 现在通过 `backend/skapp_personal.py` 调用隔离的
`scripts/skapp_personal.py`。只有账号专属模型验证通过才返回预测；原 kernel
回归估值不再从网页输出。公开参考继续用于匹配，不能充当固定窗口训练标签。

计算直接实例化未修改的上游 `SKAPP`、`Teacher`、`predict_single_item_delta`。
这实现的是作者当前参考代码的计算结构在中文目标域上重训，不是原 ICIP 权重迁移，
也不是论文全部公式的逐项复刻。中文编码器使用 ChineseCLIP 512 维，邻居数默认5；
原公开基准是768维、500邻居，两套权重不混用。自有账号的同作者关系为1。
元数据缺失时不伪造 mean_views；目标定义为指定窗口计数的 log1p，最终逆变换。

训练顺序：按发布时间划分70%训练、15%验证、15%测试；参考库仅取训练部分，
且邻居观测时间必须早于当前作品发布时间；先训练全邻居与单邻居教师，再计算
真实RRCP，最后训练SKAPP。教师及student仅按验证集选择权重，测试集只作报告。
默认至少100条为工程门槛，不代表统计充分。这不是要求用户必须自己发100篇：
训练文件也可由合法、同平台同指标同窗口的多作者图文数据构建，并填写真实author_id；
当前网页导出器只导出自有历史，尚未实现外部固定窗口数据的自动采集与训练集构建。验证集误差须优于训练集常量基线，
才能标记可预测；小样本测试集仍不能证明未来效果，不能宣称必爆或涨粉。

训练输入通过认证且同账号的 `POST /api/topics/training-data` 导出，字段为
`account_id`、当前`version`。只接纳手动报告的真实图文作品、自然流量、真实封面
特征、来源链接和目标窗口±5%以内的观测；缺值不填零，来源不冒充平台核验。
模拟发布、公开累计互动数、其他账号数据都不导入。

本地维护命令（账号标识从自己的账号记录取得，输出放 runtime，禁止提交数据）：

```sh
runtime/venv/bin/python scripts/export_skapp_training.py --owner OWNER --account ACCOUNT_ID --output runtime/skapp/training-input.json
runtime/skapp/venv/bin/python scripts/skapp_personal.py train --input runtime/skapp/training-input.json --bundle runtime/skapp/personal/SCOPE_DIGEST --epochs 10
runtime/skapp/venv/bin/python scripts/skapp_personal.py check --bundle runtime/skapp/personal/SCOPE_DIGEST
```

`SCOPE_DIGEST`取导出文件的同名字段；包不能覆盖，重新训练应先保存旧版本。
网页根据 owner/account_id 固定选择模型目录，不接受客户端指定文件路径。
模型包记录源代码指纹、编码器、数据口径、训练设置、留出误差及权重/参考库哈希。
另绑定真实历史快照：历史指标、封面、作品分类或定位变化会使旧模型失效；保存预测本身不会使模型失效。
训练库支持真实author_id，同作者关系按实际标识计算；新稿作者由模型配置固定，客户端不能伪造。
进程超时、模型不兼容、未训练、缺封面均返回温和状态，不回退为另一种预测算法。

当前真实账号数据检查：没有符合全部训练要求的记录，不能完成该账号的生产训练。
合成数据仅用于测试原结构训练、RRCP、保存重载和推理的程序链路；带synthetic标记的
模型包被网页拒绝，测试误差不能写成用户真实预测效果。
