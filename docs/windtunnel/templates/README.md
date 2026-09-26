# 研究表格使用说明

所有 CSV 使用 UTF-8；英文列名用于稳定导入，中文说明见下表。空白表示尚未采集，不是 0、否或失败。样本号、读者号和盲号均为预分配标识，不代表真实参与已经发生。

| 文件 | 谁填写、如何使用 |
| --- | --- |
| `sample_registry.csv` | 研究者登记 10 篇稿件；`cohort` 已分探索/留出，其余来源信息空白 |
| `source_authorization.csv` | 每份稿件、材料、反馈各填一行，可为同一样本追加多行；记录授权范围与同意凭据位置，不填写私人联系方式 |
| `assignment_key_RESEARCHER_ONLY.csv` | 仅研究者保存，14 个盲号分别对应 7 篇稿件的两个版本；发给读者前补纯文本稿件哈希 |
| `reader_R01.csv`—`reader_R06.csv` | 每人只领取自己 7 个任务；研究者补 `task_prompt`，不改随机顺序、盲号或夹带答案 |
| `reader_evaluation_TEMPLATE.csv` | 42 条任务对应的空白反馈；发给单个读者时只取其自己的 7 行，不能发送其他读者任务 |
| `reader_consent_RESEARCHER_ONLY.csv` | 记录 6 位读者资格、同意凭据和退出请求；不放姓名、电话等身份信息 |
| `human_scoring_RESEARCHER_ONLY.csv` | 人工评分者按冻结判分标准判定 `task_correct`，不看版本映射；理由和评分者代号保留 |
| `run_costs_RESEARCHER_ONLY.csv` | 逐篇逐流程记录模型、提示词、调用数、Token、费用、系统耗时、作者耗时及原始记录位置 |
| `study_run_TEMPLATE.json` | 运行前填写样本/提示词/规则版本、模型配置和授权；完成后填写数据位置 |

`answer_found`：读者自述是否从稿件找到答案，填写 yes/no/unsure。`answer_text`：读者实际答案，留给盲评分者按预先标准判分。`difficulty_1_to_5`：1 很容易、5 很困难。`elapsed_seconds`：单次阅读和回答总秒数。`task_correct`：人工判分 correct/incorrect/unscorable；不能把未评分直接当 incorrect。费用未知时留空并填写 `missing_reason`。

分配固定种子 20260926：先从 1000—9999 抽取 14 个不重复盲号；依 S04—S10 顺序，对六位读者分别随机洗牌，前三读 baseline，后三读 windtunnel；再分别洗牌每人的七次阅读。盲号文件名只用 `P` 加四位数，与流程、样本和胜负无编码关系。完整源码包含研究者映射，不可直接发给受试者。

不用 Excel 自动把稿件文本识别为公式。未来导入真实文本时，以纯文本导入列为准；若记录以 `=`、`+`、`-`、`@` 开头的内容，应采取安全导入方式。当前模板只含标识、顺序和空字段。
