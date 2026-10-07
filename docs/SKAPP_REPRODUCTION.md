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
