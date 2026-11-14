# 三算法离线受控机制基准

全部为固定种子生成的构造任务，仅评估算法机制；不是实际生成质量、独立事实核验、真人阅读评分、用户效果、产品优越性或获奖证据。无模型调用、无网络和费用。

固定种子：20261102；构造任务：24；模型调用：0；网络请求：0。

## 需求覆盖：相同字数预算与证据准入

输入顺序 first-fit 和贪心均先排除无依据模块。枚举仅用于小案例参考最优；目标为加权覆盖减去 0.15 倍重复权重。

| 方法 | 覆盖权重分子/分母 | 使用字数预算/可用预算 | 目标值总和 |
| --- | --- | --- | --- |
| first_fit | 242/359 | 1218/1340 | 230.900 |
| greedy | 326/359 | 1023/1340 | 316.850 |
| enumerated_optimal | 333/359 | 1025/1340 | 328.650 |

## 关键缺口提问：固定标准答案模拟

标准答案提前绑定能解决的 block；这不是实际用户回答，block 数量不等于真人价值。两组每任务最多提问两次。

| 方法 | 解决block分子/可解决block分母 | 提问数/提问预算 |
| --- | --- | --- |
| in_order | 84/168 | 48/48 |
| ranked | 120/168 | 48/48 |

## 结构迁移：槽位适配与元数据隔离

未适配槽位：81/168；适配后仍缺证据槽位：0/168。

结构元数据出现原文独特标记：0/24；出现原文参数字符串：0/24。

字段存在只表示已提供资料。这里没有生成正文，不能据此推断内容真实、结构自然或不抄袭。

## 失败案例

- `synthetic-00`：greedy_below_enumerated_optimum。
- `synthetic-01`：greedy_below_enumerated_optimum。
- `synthetic-04`：greedy_below_enumerated_optimum。
- `synthetic-06`：greedy_below_enumerated_optimum。
- `synthetic-08`：greedy_below_enumerated_optimum。
- `synthetic-16`：greedy_below_enumerated_optimum。
- `synthetic-18`：greedy_below_enumerated_optimum。
- `synthetic-20`：greedy_below_enumerated_optimum。
- `synthetic-21`：greedy_below_enumerated_optimum。
- `synthetic-23`：greedy_below_enumerated_optimum。

全部输入、逐任务分子分母、标准答案映射和决策日志保存在 benchmark.json，可复算。
