# 三算法理论参考核验与实现边界

核验日期：2026-11-02。以下依据论文原文、出版机构或理论维护者网站核对；不是将参考文献的效果或理论保证移植到有迹。用户提供文本中的建议作为研究线索，不作为已实现证据。

## 1. 覆盖贪心：Nemhauser、Wolsey、Fisher（1978）

**准确书目：** G. L. Nemhauser, L. A. Wolsey, M. L. Fisher. *An analysis of approximations for maximizing submodular set functions—I*. Mathematical Programming 14, 265–294 (1978). DOI: 10.1007/BF01588971。

已读[原论文PDF](https://thibaut.horel.org/submodularity/papers/nemhauser1978.pdf)，首页和正文说明：在单调、归一化的次模目标及基数约束下，经典贪心存在相应最坏情况近似界，极限为 `1−1/e`。

**书目纠正：** 用户文本提供的 [10.1287/moor.3.3.177](https://pubsonline.informs.org/doi/abs/10.1287/moor.3.3.177) 对应另一篇 *Best Algorithms for Approximating the Maximum of a Submodular Set Function*，作者为 Nemhauser 与 Wolsey，Mathematics of Operations Research 3(3), 177–188 (1978)，不能写成上述三位作者论文。

**与当前实现的区别：** `backend/planning.py::plan` 使用不等长预算和重复覆盖惩罚。2026-11-02冲刺修订：合法候选不超过12时枚举全部子集，保证在当前候选池、当前权重和预计篇幅目标内最优；超过12时仍按边际收益密度贪心，不保证最优。候选池可能遗漏读者需求，预计字数不等于实际字数。重复惩罚可能破坏目标单调性，因此无论哪条路径都不声称经典 `1−1/e` 保证、全局检索最优或文章质量保证。受控基准保留贪心劣于精确搜索的反例。

## 2. 背包次模优化：Sviridenko（2004）

**准确书目：** Maxim Sviridenko. *A note on maximizing a submodular set function subject to a knapsack constraint*. Operations Research Letters 32(1), 41–43 (2004). DOI: 10.1016/S0167-6377(03)00062-2。

已核对[IBM研究出版记录](https://research.ibm.com/publications/a-note-on-maximizing-a-submodular-set-function-subject-to-a-knapsack-constraint)及[原论文PDF](https://thibaut.horel.org/submodularity/papers/sviridenko2004.pdf)。论文的 `1−1/e` 结论针对非负、单调次模目标与单背包约束，并采用小集合枚举结合贪心扩展，不等同于仅按收益密度从空集开始选取。

**与当前实现的区别：** 本轮小规模子集穷举是当前候选池内直接精确搜索，不是该论文用于获得近似保证的“枚举种子加贪心扩展”算法。超过12候选回退贪心，不能借用论文保证。`1−1/e≈63.2%` 不是有迹的覆盖率、准确率或提升幅度。

## 3. 提问价值：Dong 等（ACL 2026）

**准确书目：** Yijiang River Dong, Tiancheng Hu, Zheng Hui, Caiqi Zhang, Ivan Vulić, Andreea Bobu, Nigel Collier. *Value of Information: A Framework for Human–Agent Communication*. ACL 2026, 42879–42896. DOI: 10.18653/v1/2026.acl-long.1987。

[ACL官方条目](https://aclanthology.org/2026.acl-long.1987/)与[论文PDF](https://aclanthology.org/2026.acl-long.1987.pdf)均可访问，核实该文确实存在。研究以任务收益与交流成本权衡是否澄清，不应将其表现数字写成有迹结果。

**与当前实现的区别：** `backend/gap_ranker.py` 是可检查的规则价值排序：

`importance × (1 + 尚未覆盖的依赖块数) × resolvable / (1 + cost)`。

没有学习或校准答案分布，没有计算 Shannon 熵、期望后验效用或论文的 VoI 决策过程。`resolvable` 是规则可解决程度，不能解释为已校准成功概率；存在显式阈值，因此不能声称复现该文“无需超参数调优”的方法。适当名称为“关键缺口提问价值排序”，可称受信息价值思想启发，不能称精确的信息增益估计。固定标准答案实验仅是模拟补料机制。

## 4. 中文篇章研究：Peng、Liu、Zeldes（AACL-IJCNLP 2022）

**准确书目：** Siyao Peng, Yang Janet Liu, Amir Zeldes. *GCDT: A Chinese RST Treebank for Multigenre and Multilingual Discourse Parsing*. AACL-IJCNLP 2022, Volume 2: Short Papers, 382–391. DOI: 10.18653/v1/2022.aacl-short.47。

已核对[ACL官方论文条目](https://aclanthology.org/2022.aacl-short.47/)。论文提供中文RST篇章树库，涉及五种体裁、超过六万词元，并报告篇章解析实验；这是中文篇章结构建模的研究基础。

**与当前实现的区别：** 当前没有导入GCDT、训练篇章解析器或在该数据集评测。七个功能标签与规则匹配不是完整RST树解析；不能借用其SOTA、标签精度或跨语言结果。规则抽取准确率仍需独立人工标注测试集。

## 5. RST理论维护站：Simon Fraser University

已核对[修辞结构理论网站](https://www.sfu.ca/rst/)及其[理论介绍](https://www.sfu.ca/rst/01intro/index.html)。该站由 Bill Mann 创建、Maite Taboada 维护，关注文本连贯与片段之间的关系，并介绍文本生成、摘要及写作教学等应用。首页说明自2024年起主要作为档案维护，不应把它作为近期性能或最新系统进展来源。

**与当前实现的区别：** `backend/structure_profiles.py` 用确定性规则识别段落功能、保留位置与哈希、按任务分类和缺失证据字段选择结构，并替换缺依据槽位。没有构建核/卫星关系树，没有学习转移概率或用户写作偏好。准确名称是“规则篇章功能提取与证据约束结构适配”。结构元数据不含原文参数和独特句子不代表生成稿必然原创或事实正确。

## 答辩可用表述

“我们借鉴预算覆盖优化、提问信息价值和篇章组织研究，针对有迹创作场景实现三项可解释决策模块：在证据与字数约束下规划内容、按缺口价值排序可选问题、按当前资料调整参考结构。当前采用小规模精确搜索、超限贪心与规则结构适配，已做受控机制验证；真实文本质量与用户效果需要另行实验。”

不能说：自创最大覆盖数学理论、已获得 `1−1/e` 保证、精确计算信息熵、训练了结构学习模型、复现完整RST解析、证明生成稿真实或无抄袭。
