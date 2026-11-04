# 原创文案能力：六场景真实流程验收

自编受控虚构产品与样例；真实模型、真实本地向量、生产HTTP和Worker流程，不代表真实产品效果或全网原创查重。本报告保留最终完整稿件与实际证据，不将模型审核通过等同于完全符合质量要求。

授权上限 US$0.50；保守计费账本 US$0.481782；去重调用 83 次，其中用量未知 2 次。未知调用按预留 token × 账本费率计入，不作零费用处理；这不是服务商最终账单。

六个最终场景均须逐项查看下方状态；WAITING_USER / final_confirmation 表示等待用户确认，未发布。各轮修复保留历史失败与旧稿，不能将早期尝试合并为一次无失败运行。

验收期间运行提示词由 retrieval1 迭代到 retrieval2、retrieval3；后续又压缩重复阶段输入以满足剩余预算。每个案例列出实际调用的 prompt_version，早期成稿没有假装在最终提示词版本下重新生成。

## 人工核对仍发现的质量问题

美妆图文 CTA 使用“便携包装”，现有规格只有透明方管、斜面刷头和净含量，不能据此证明便携性；应改为“包装细节”。口播稿存在正文与 CTA 重复提问以及“本次提供的规格”等范围说明，可进一步清理。以下保留原始成稿，不静默改写验收产物。

样例对照与逐字引文匹配只能证明有限资料范围内的引用关系，不能证明资料真实、全网原创或发布效果。模型审核中的 originality_risk=unknown 按未知保留，不升级为原创性通过。

## 1. 美妆图文

验收记录状态：WAITING_USER / final_confirmation。后续关闭标记：受控验收已保留成稿和审核；取消执行以释放单任务槽，未替用户确认或发布

### 分类与真实检索条件

```json
{
  "classification": {
    "domains": [
      "beauty"
    ],
    "channel": "xiaohongshu",
    "format": "note",
    "goal": "清楚介绍已有规格，帮助读者核对选择条件",
    "word_count": 180,
    "origin": "user",
    "ambiguities": []
  },
  "engine": "filtered-local-vector-rerank-v1",
  "reranker": "cosine-topic-coverage-v1",
  "filters": {
    "methods": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "method",
      "domains": [
        "beauty"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "allow_general": true,
      "document_ids": null,
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "图文笔记 原创写作 开篇 节奏 结构 表达 行动引导",
      "vector_candidate_count": 1
    },
    "examples": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "example",
      "domains": [
        "beauty"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "allow_general": false,
      "document_ids": null,
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "美妆 图文笔记 开篇 结构 表达",
      "vector_candidate_count": 1
    },
    "facts": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "fact",
      "domains": [
        "beauty"
      ],
      "channel": null,
      "format": null,
      "allow_general": false,
      "document_ids": [
        "8931404b-d7d9-4a93-a89f-e8c4732fd35b"
      ],
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "雾桃B01唇釉的色号与包装介绍",
      "vector_candidate_count": 1
    }
  },
  "gaps": [],
  "example_gap": false,
  "prompt_versions": [
    "four-role-v1.0-original-grouped-retrieval1"
  ],
  "draft_ref": "a73dd22f-5d9c-4173-a879-90d46abba42e@1",
  "snapshot_id": "cb703a73-f63d-4b23-b96d-5e2db145b8dc"
}
```

### 通用创作方法（1 条）

```json
{
  "title": "验收自编通用原创方法",
  "source_id": "kb:1574231d-de88-459d-af1e-63429fc85668",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "general"
    ],
    "channel": "any",
    "format": "any",
    "material_type": "method",
    "origin": "user"
  },
  "score": 0.559903,
  "semantic_score": 0.622956,
  "topic_coverage": 0.090909
}
```

> 通用原创产品介绍方法：围绕读者实际选择问题开篇，把已知规格分成易读段落；根据图文、口播或详情形式调整段长与节奏，结尾按任务目标选择提问或核对提示。只用本次产品资料，不把参考作者的经历和测试数字写成自己的事实，不承诺必爆。

### 领域参考样例（1 条）

```json
{
  "title": "自编结构样例 · 美妆图文",
  "source_id": "kb:f493c5c4-4878-4637-9fe9-17d8e0ed012d",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "beauty"
    ],
    "channel": "xiaohongshu",
    "format": "note",
    "material_type": "example",
    "origin": "user"
  },
  "score": 0.46909,
  "semantic_score": 0.479219,
  "topic_coverage": 0.181818
}
```

> 今天把颜色当成衣橱的一部分：先给一个选色场景，再用短段介绍色调和搭配思路，结尾问读者偏爱的色系。样例作者声称自己连续试用21天、不沾杯；这些是样例私有经历，不适用于其他产品。

### 独立事实依据（1 条）

```json
{
  "title": "虚构规格 · 雾桃B01唇釉",
  "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "beauty"
    ],
    "channel": "any",
    "format": "any",
    "material_type": "fact",
    "origin": "user"
  },
  "score": 0.775071,
  "semantic_score": 0.855203,
  "topic_coverage": 0.454545
}
```

> 雾桃B01唇釉是虚构验收产品。色号为陶土玫瑰，净含量3克，包装为透明方管，配斜面刷头。没有持妆时长、保湿效果或个人试用数据。

### 最后版本完整成稿（未发布）

#### 雾桃B01唇釉先别猜色调：色号、净含量、包装逐项看

> 想核对雾桃B01唇釉，先别急着凭名字猜色调。把已知规格按顺序排开，一共四项，逐条对照更省事。
>
> 色号是陶土玫瑰。目前可核对的是色号名称，具体显色和上脸效果建议以实物或线下试色为准。
>
> 净含量3克。包装为透明方管，配斜面刷头。本次可核对规格为净含量、包装形态与刷头，质地、持妆等信息请以实际产品说明为准。
>
> 按色号、净含量、包装和刷头这四项对照，基本能完成初步筛选。

行动引导：你更在意颜色观感还是便携包装？可以留言说说你的核对顺序。

标签：雾桃B01唇釉 / 唇釉色号 / 陶土玫瑰 / 净含量3克 / 透明方管 / 斜面刷头 / 唇釉包装细节 / 唇釉怎么选色号

### 独立人工抽查意见

规格引用相符，未继承21天试用或不沾杯承诺；CTA中的“便携包装”缺少依据，应改为“包装细节”。

本次对照未发现继承样例中的21天、不沾杯、八级风、180天、五年等私有经历或测试结论；此结论仅覆盖本报告列出的受控样例。

### 仅匹配当前稿件与快照的审核

```json
{
  "decision": "approved",
  "next_action": "await_user_confirmation",
  "draft_ref": "a73dd22f-5d9c-4173-a879-90d46abba42e@1",
  "snapshot_id": "cb703a73-f63d-4b23-b96d-5e2db145b8dc",
  "checks": [
    {
      "name": "brief_fit",
      "result": "pass",
      "basis": "主题为雾桃B01色号与包装，受众为核对规格的普通读者，渠道形式与180字卡点相符，未越出规格介绍目标。"
    },
    {
      "name": "audience_fit",
      "result": "pass",
      "basis": "开篇即给“先别急着凭名字猜色调”的核对顺序，随后逐项列出色号、净含量、包装、刷头，读者可据此初步筛选。"
    },
    {
      "name": "usefulness_and_readability",
      "result": "pass",
      "basis": "此前“资料只给出”“材料未提供”等内部元话语已删除，正文仅保留已知规格、适用条件与可操作的核对顺序，无空泛说明。"
    },
    {
      "name": "title_body_alignment",
      "result": "pass",
      "basis": "标题承诺“色号、净含量、包装逐项看”，正文按色号、净含量、包装、刷头逐项承接，首句对应标题的核对意图，兑现无偏差。"
    },
    {
      "name": "evidence_integrity",
      "result": "pass",
      "basis": "陶土玫瑰、3克、透明方管、斜面刷头均可在kb:311d2826原文逐字对应；未添加持妆、保湿、试用数据或统计来源。"
    },
    {
      "name": "experience_authenticity",
      "result": "pass",
      "basis": "正文未声称亲测、试用或继承样例结论，也未移植kb:f493c5c4的连续试用21天、不沾杯等私有经历。"
    },
    {
      "name": "originality_risk",
      "result": "unknown",
      "basis": "已对照kb:f493c5c4与kb:1574231d，未见独特句子照搬或私有经历移植；未与站内其他文案穷尽比对，不能判定完全原创。"
    },
    {
      "name": "privacy_and_policy",
      "result": "pass",
      "basis": "无个人信息、功效承诺、保证爆款或虚构数据；tags均为产品与选择场景词，账号未设禁用表达。"
    }
  ],
  "issues": [],
  "claim_map": [
    {
      "excerpt": "色号是陶土玫瑰。",
      "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
      "quote": "色号为陶土玫瑰"
    },
    {
      "excerpt": "净含量3克。",
      "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
      "quote": "净含量3克"
    },
    {
      "excerpt": "包装为透明方管，配斜面刷头。",
      "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
      "quote": "包装为透明方管，配斜面刷头"
    }
  ],
  "reference_records": {
    "classification": {
      "domains": [
        "beauty"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "goal": "清楚介绍已有规格，帮助读者核对选择条件",
      "word_count": 180,
      "origin": "user",
      "ambiguities": []
    },
    "groups": {
      "methods": [
        "kb:1574231d-de88-459d-af1e-63429fc85668"
      ],
      "examples": [
        "kb:f493c5c4-4878-4637-9fe9-17d8e0ed012d"
      ],
      "facts": [
        "user-material",
        "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9"
      ]
    },
    "example_gap": false,
    "adoption_notes": [
      "采用 kb:1574231d-de88-459d-af1e-63429fc85668 的围绕选择问题开篇与分段核对方法，本题改为按色号—净含量—包装—刷头的核对顺序组织；借鉴 kb:f493c5c4-4878-4637-9fe9-17d8e0ed012d 的场景开篇、短段节奏与结尾提问结构，但删除其作者连续试用和不沾杯等私有经历，换成用 kb:311d2826 的色号、净含量、包装、刷头四项事实重新组织，不使用任何效果或体验表述；材料仅两份参考，暂无第二份可对比样例，缺口已记录。"
    ],
    "claim_map": [
      {
        "excerpt": "色号是陶土玫瑰。",
        "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
        "quote": "色号为陶土玫瑰"
      },
      {
        "excerpt": "净含量3克。",
        "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
        "quote": "净含量3克"
      },
      {
        "excerpt": "包装为透明方管，配斜面刷头。",
        "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
        "quote": "包装为透明方管，配斜面刷头"
      }
    ],
    "scope": "仅验证逐字引文和本任务事实组；不等同独立真实性核验或全网原创证明"
  },
  "limitations": [
    "kb:f493c5c4-4878-4637-9fe9-17d8e0ed012d：仅借鉴场景开篇、短段节奏与结尾提问结构，本题以规格核对顺序重新组织，未移植作者试用经历与效果承诺。",
    "kb:1574231d-de88-459d-af1e-63429fc85668：仅用于围绕选择问题开篇与分段核对方法，未当作产品事实。",
    "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9：产品事实仅涉色号、净含量、包装、刷头，无质地、持妆、保湿依据。",
    "原创性未与站内其他文案穷尽比对，originality_risk为unknown，不能凭已对照样例放行。",
    "来源匹配只验证逐字引文存在，不能证明素材真实，最终由用户确认。",
    "来源匹配只验证引用存在，不能证明素材真实或检查完全；最终由用户确认。"
  ]
}
```

## 2. 摄影图文

验收记录状态：WAITING_USER / final_confirmation。后续关闭标记：受控验收已保留成稿和审核；取消执行以释放单任务槽，未替用户确认或发布

### 分类与真实检索条件

```json
{
  "classification": {
    "domains": [
      "photography"
    ],
    "channel": "xiaohongshu",
    "format": "note",
    "goal": "清楚介绍已有规格，帮助读者核对选择条件",
    "word_count": 180,
    "origin": "user",
    "ambiguities": []
  },
  "engine": "filtered-local-vector-rerank-v1",
  "reranker": "cosine-topic-coverage-v1",
  "filters": {
    "methods": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "method",
      "domains": [
        "photography"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "allow_general": true,
      "document_ids": null,
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "图文笔记 原创写作 开篇 节奏 结构 表达 行动引导",
      "vector_candidate_count": 1
    },
    "examples": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "example",
      "domains": [
        "photography"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "allow_general": false,
      "document_ids": null,
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "摄影 图文笔记 开篇 结构 表达",
      "vector_candidate_count": 1
    },
    "facts": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "fact",
      "domains": [
        "photography"
      ],
      "channel": null,
      "format": null,
      "allow_general": false,
      "document_ids": [
        "41c69f4a-448a-42a7-ab25-46e5d70ede0f"
      ],
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "轻行P02三脚架的收纳尺寸与重量介绍",
      "vector_candidate_count": 1
    }
  },
  "gaps": [],
  "example_gap": false,
  "prompt_versions": [
    "four-role-v1.0-original-grouped-retrieval2"
  ],
  "draft_ref": "21788798-e4d3-47ee-abef-563f92393416@1",
  "snapshot_id": "47df61e1-0fbd-4edc-bd69-1ff2a2abf481"
}
```

### 通用创作方法（1 条）

```json
{
  "title": "验收自编通用原创方法",
  "source_id": "kb:1574231d-de88-459d-af1e-63429fc85668",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "general"
    ],
    "channel": "any",
    "format": "any",
    "material_type": "method",
    "origin": "user"
  },
  "score": 0.559903,
  "semantic_score": 0.622956,
  "topic_coverage": 0.071429
}
```

> 通用原创产品介绍方法：围绕读者实际选择问题开篇，把已知规格分成易读段落；根据图文、口播或详情形式调整段长与节奏，结尾按任务目标选择提问或核对提示。只用本次产品资料，不把参考作者的经历和测试数字写成自己的事实，不承诺必爆。

### 领域参考样例（1 条）

```json
{
  "title": "自编结构样例 · 摄影图文",
  "source_id": "kb:5110ca5a-f745-4c94-9e39-a48f22a0af00",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "photography"
    ],
    "channel": "xiaohongshu",
    "format": "note",
    "material_type": "example",
    "origin": "user"
  },
  "score": 0.489671,
  "semantic_score": 0.504946,
  "topic_coverage": 0.071429
}
```

> 出门前先看器材能否装进包，再按重量、折叠方式和附件分段，最后留下一个检查清单。样例作者说自己在八级风中拍摄稳定，这是独有经历，不能继承。

### 独立事实依据（1 条）

```json
{
  "title": "虚构规格 · 轻行P02三脚架",
  "source_id": "kb:bd31f4d0-96b0-4d5a-9b32-bde192b52802",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "photography"
    ],
    "channel": "any",
    "format": "any",
    "material_type": "fact",
    "origin": "user"
  },
  "score": 0.761181,
  "semantic_score": 0.844334,
  "topic_coverage": 0.428571
}
```

> 轻行P02三脚架是虚构验收产品。重量1.2千克，收纳长度40厘米，最大展开高度150厘米，含一个便携袋。没有负重稳定性、抗风或实拍测试数据。

### 最后版本完整成稿（未发布）

#### 出门前先量两下：轻行P02收纳40厘米、重1.2千克

> 出门前把包放在门口，常卡住的两个问题就是：装不装得下、背不背得动。轻行P02这几项已给规格可以逐项看。
>
> 收纳长度标称40厘米。这是单一数据，不等于能放进任意背包，也不代表可以登机，最好拿你常背的包量一下内长再对照。
>
> 重量标称1.2千克。是否愿意随身带，可以按自己平时拎器材的习惯掂一掂、称一称再判断，这组数字本身不说明背起来累不累。
>
> 最大展开高度标称150厘米，和收纳尺寸是两组不同参数，看的时候别混在一起。随附一个便携袋。
>
> 规格是核对条件，不是适配结论。你更在意收纳长度，还是重量？

行动引导：你平时出门更在意收纳长度还是重量？可以拿手边的包和称重量一下再对照。

标签：三脚架 / 摄影器材 / 轻行P02 / 产品规格 / 器材收纳

### 独立人工抽查意见

重量、收纳长度、展开高度与便携袋事实相符，未继承八级风稳定性或保证装包结论；正文与CTA重复，原文“包和称重量一下”表达生硬，需编辑。

本次对照未发现继承样例中的21天、不沾杯、八级风、180天、五年等私有经历或测试结论；此结论仅覆盖本报告列出的受控样例。

### 仅匹配当前稿件与快照的审核

```json
{
  "decision": "approved",
  "next_action": "await_user_confirmation",
  "draft_ref": "21788798-e4d3-47ee-abef-563f92393416@1",
  "snapshot_id": "47df61e1-0fbd-4edc-bd69-1ff2a2abf481",
  "checks": [
    {
      "name": "brief_fit",
      "result": "pass",
      "basis": "围绕收纳长度、重量、展开高度与便携袋逐项介绍，符合清楚克制介绍规格的要求。"
    },
    {
      "name": "audience_fit",
      "result": "pass",
      "basis": "以出门前装不装得下、背不背得动切入，再给规格供读者自行对照。"
    },
    {
      "name": "usefulness_and_readability",
      "result": "pass",
      "basis": "四段短句分段列规格，给出量包内长、称重对照的可操作核对方式。"
    },
    {
      "name": "title_body_alignment",
      "result": "pass",
      "basis": "标题给出40厘米、1.2千克两项数字，正文首段承接装不装得下并逐项兑现。"
    },
    {
      "name": "evidence_integrity",
      "result": "pass",
      "basis": "仅陈述40厘米、1.2千克、150厘米与含便携袋，均与规格材料一致，无效果推导。"
    },
    {
      "name": "experience_authenticity",
      "result": "pass",
      "basis": "未写亲测、开箱、实拍、承重或抗风体验，也未移植样例作者的八级风经历。"
    },
    {
      "name": "originality_risk",
      "result": "unknown",
      "basis": "仅与单份结构样例比对，未做全网穷尽比对，见limitations。"
    },
    {
      "name": "privacy_and_policy",
      "result": "pass",
      "basis": "无隐私信息、无夸大功效承诺、无内部沟通语句进入读者文案。"
    }
  ],
  "issues": [],
  "claim_map": [
    {
      "excerpt": "收纳长度标称40厘米。",
      "source_id": "kb:bd31f4d0-96b0-4d5a-9b32-bde192b52802",
      "quote": "收纳长度40厘米"
    },
    {
      "excerpt": "重量标称1.2千克。",
      "source_id": "kb:bd31f4d0-96b0-4d5a-9b32-bde192b52802",
      "quote": "重量1.2千克"
    },
    {
      "excerpt": "最大展开高度标称150厘米",
      "source_id": "kb:bd31f4d0-96b0-4d5a-9b32-bde192b52802",
      "quote": "最大展开高度150厘米"
    },
    {
      "excerpt": "随附一个便携袋。",
      "source_id": "kb:bd31f4d0-96b0-4d5a-9b32-bde192b52802",
      "quote": "含一个便携袋"
    }
  ],
  "reference_records": {
    "classification": {
      "domains": [
        "photography"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "goal": "清楚介绍已有规格，帮助读者核对选择条件",
      "word_count": 180,
      "origin": "user",
      "ambiguities": []
    },
    "groups": {
      "methods": [
        "kb:1574231d-de88-459d-af1e-63429fc85668"
      ],
      "examples": [
        "kb:5110ca5a-f745-4c94-9e39-a48f22a0af00"
      ],
      "facts": [
        "user-material",
        "kb:bd31f4d0-96b0-4d5a-9b32-bde192b52802"
      ]
    },
    "example_gap": false,
    "adoption_notes": [
      "kb:1574231d-de88-459d-af1e-63429fc85668：采用“围绕读者选择问题开篇、分段列已知规格”的方法，本题改为按收纳、重量、高度、附件四段陈述。kb:5110ca5a-f745-4c94-9e39-a48f22a0af00：借鉴“出门前看能否装进包—按重量/折叠/附件分段—留检查清单”的结构节奏与CTA方式，改写为规格核对场景，不移植样例作者八级风经历与效果结论。kb:bd31f4d0-96b0-4d5a-9b32-bde192b52802：事实仅取重量1.2千克、收纳长度40厘米、最大展开高度150厘米、含便携袋，不延伸结构、承重与适配判断。"
    ],
    "claim_map": [
      {
        "excerpt": "收纳长度标称40厘米。",
        "source_id": "kb:bd31f4d0-96b0-4d5a-9b32-bde192b52802",
        "quote": "收纳长度40厘米"
      },
      {
        "excerpt": "重量标称1.2千克。",
        "source_id": "kb:bd31f4d0-96b0-4d5a-9b32-bde192b52802",
        "quote": "重量1.2千克"
      },
      {
        "excerpt": "最大展开高度标称150厘米",
        "source_id": "kb:bd31f4d0-96b0-4d5a-9b32-bde192b52802",
        "quote": "最大展开高度150厘米"
      },
      {
        "excerpt": "随附一个便携袋。",
        "source_id": "kb:bd31f4d0-96b0-4d5a-9b32-bde192b52802",
        "quote": "含一个便携袋"
      }
    ],
    "scope": "仅验证逐字引文和本任务事实组；不等同独立真实性核验或全网原创证明"
  },
  "limitations": [
    "kb:5110ca5a-f745-4c94-9e39-a48f22a0af00：仅借鉴“出门前先看能否装进包—按重量/附件分段”的结构节奏，本题改为只陈述已有规格，未移植样例作者八级风经历与效果结论。",
    "kb:1574231d-de88-459d-af1e-63429fc85668：采用围绕选择问题开篇、分段列已知规格的通用方法，未承诺爆款或适配效果。",
    "原创性比对仅覆盖上述两份来源，未做穷尽检索，故originality_risk为unknown。",
    "素材未提供结构、脚管节数、材质、承重、实拍数据；收纳40厘米与1.2千克均为单一规格，不能据此判断可放入某类背包或轻便程度。",
    "来源匹配只验证引用存在，不能证明素材真实或检查完全；最终由用户确认。"
  ]
}
```

## 3. 美妆换口播

验收记录状态：WAITING_USER / final_confirmation。后续关闭标记：受控验收已保留成稿和审核；取消执行以释放单任务槽，未替用户确认或发布

### 分类与真实检索条件

```json
{
  "classification": {
    "domains": [
      "beauty"
    ],
    "channel": "xiaohongshu",
    "format": "video_script",
    "goal": "清楚介绍已有规格，帮助读者核对选择条件",
    "word_count": 180,
    "origin": "user",
    "ambiguities": []
  },
  "engine": "filtered-local-vector-rerank-v1",
  "reranker": "cosine-topic-coverage-v1",
  "filters": {
    "methods": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "method",
      "domains": [
        "beauty"
      ],
      "channel": "xiaohongshu",
      "format": "video_script",
      "allow_general": true,
      "document_ids": null,
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "短视频口播 原创写作 开篇 节奏 结构 表达 行动引导",
      "vector_candidate_count": 1
    },
    "examples": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "example",
      "domains": [
        "beauty"
      ],
      "channel": "xiaohongshu",
      "format": "video_script",
      "allow_general": false,
      "document_ids": null,
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "美妆 短视频口播 开篇 结构 表达",
      "vector_candidate_count": 1
    },
    "facts": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "fact",
      "domains": [
        "beauty"
      ],
      "channel": null,
      "format": null,
      "allow_general": false,
      "document_ids": [
        "8931404b-d7d9-4a93-a89f-e8c4732fd35b"
      ],
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "雾桃B01唇釉的色号与包装口播介绍",
      "vector_candidate_count": 1
    }
  },
  "gaps": [],
  "example_gap": false,
  "prompt_versions": [
    "four-role-v1.0-original-grouped-retrieval3"
  ],
  "draft_ref": "27a4712a-76c7-4d9b-84da-e8c51a110df2@1",
  "snapshot_id": "48a89ba6-62d8-47e5-9a75-da0cbd8ca47a"
}
```

### 通用创作方法（1 条）

```json
{
  "title": "验收自编通用原创方法",
  "source_id": "kb:1574231d-de88-459d-af1e-63429fc85668",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "general"
    ],
    "channel": "any",
    "format": "any",
    "material_type": "method",
    "origin": "user"
  },
  "score": 0.554197,
  "semantic_score": 0.621317,
  "topic_coverage": 0.153846
}
```

> 通用原创产品介绍方法：围绕读者实际选择问题开篇，把已知规格分成易读段落；根据图文、口播或详情形式调整段长与节奏，结尾按任务目标选择提问或核对提示。只用本次产品资料，不把参考作者的经历和测试数字写成自己的事实，不承诺必爆。

### 领域参考样例（1 条）

```json
{
  "title": "自编结构样例 · 美妆换口播",
  "source_id": "kb:a950cf10-80f4-49ba-8a05-04077dddfb37",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "beauty"
    ],
    "channel": "xiaohongshu",
    "format": "video_script",
    "material_type": "example",
    "origin": "user"
  },
  "score": 0.503835,
  "semantic_score": 0.536044,
  "topic_coverage": 0.153846
}
```

> 先用一句选色问题开场，镜头展示管身，再以短句依次讲色号和刷头，最后自然询问观众偏好。样例作者的独特句子是“晚霞被我装进了口袋的第七层”，不能复制。

### 独立事实依据（1 条）

```json
{
  "title": "虚构规格 · 雾桃B01唇釉",
  "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "beauty"
    ],
    "channel": "any",
    "format": "any",
    "material_type": "fact",
    "origin": "user"
  },
  "score": 0.749895,
  "semantic_score": 0.841215,
  "topic_coverage": 0.384615
}
```

> 雾桃B01唇釉是虚构验收产品。色号为陶土玫瑰，净含量3克，包装为透明方管，配斜面刷头。没有持妆时长、保湿效果或个人试用数据。

### 最后版本完整成稿（未发布）

#### 雾桃B01唇釉：色号陶土玫瑰，3克的透明方管

> 正想核对雾桃B01唇釉，手头却只有一个色号名？那就把已知规格一次听清。它的色号是陶土玫瑰，净含量3克，包装做成透明方管，刷头是斜面设计。这条只讲这些能被核对的规格，不涉及上色呈现、质地、持妆或保湿。你挑唇釉时一般先看色号，还是先看包装？

行动引导：你选唇釉会先看色号还是包装，评论区说一声

标签：雾桃B01 / 唇釉色号 / 陶土玫瑰 / 透明方管 / 斜面刷头 / 美妆口播 / 产品规格 / 选色

### 独立人工抽查意见

事实相符，未照搬样例独特表述；“这条只讲这些能被核对的规格”仍偏内部范围说明，正文与CTA重复，应清理。

本次对照未发现继承样例中的21天、不沾杯、八级风、180天、五年等私有经历或测试结论；此结论仅覆盖本报告列出的受控样例。

### 仅匹配当前稿件与快照的审核

```json
{
  "decision": "approved",
  "next_action": "await_user_confirmation",
  "draft_ref": "27a4712a-76c7-4d9b-84da-e8c51a110df2@1",
  "snapshot_id": "48a89ba6-62d8-47e5-9a75-da0cbd8ca47a",
  "checks": [
    {
      "name": "brief_fit",
      "result": "pass",
      "basis": "标题与正文只讲色号陶土玫瑰、净含量3克、透明方管、斜面刷头，与选题及事实范围一致；未加体验结论。"
    },
    {
      "name": "audience_fit",
      "result": "pass",
      "basis": "面向核对规格的普通读者，先回应色号名以外的信息缺口，全篇用短句口播节奏，无专业黑话。"
    },
    {
      "name": "usefulness_and_readability",
      "result": "pass",
      "basis": "给出色号、容量、包装、刷头四项可核对信息；未把“素材没有”“发布时间为空”等内部说明写进正文。"
    },
    {
      "name": "title_body_alignment",
      "result": "pass",
      "basis": "标题承诺三项具体规格，正文首句承接并逐项兑现；CTA也落在同一选择场景。"
    },
    {
      "name": "evidence_integrity",
      "result": "pass",
      "basis": "claim_map四条均逐字取自kb:311d2826-d7a1-4710-a5f6-75bc36f913c9，未引入上色、质地、持妆、保湿或热度数据。"
    },
    {
      "name": "experience_authenticity",
      "result": "pass",
      "basis": "全文无亲测、无试用、无样例作者经历移植，未把虚构验收写成真实评测。"
    },
    {
      "name": "originality_risk",
      "result": "unknown",
      "basis": "已比对kb:a950cf10-80f4-49ba-8a05-04077dddfb37，未照搬其独特句，仅借鉴选色问题开场与短句节奏；未穷尽比对，记limitations。"
    },
    {
      "name": "privacy_and_policy",
      "result": "pass",
      "basis": "未出现个人信息、联系方式或医疗功效承诺；无平台违禁表达。"
    }
  ],
  "issues": [],
  "claim_map": [
    {
      "excerpt": "它的色号是陶土玫瑰",
      "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
      "quote": "色号为陶土玫瑰"
    },
    {
      "excerpt": "净含量3克",
      "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
      "quote": "净含量3克"
    },
    {
      "excerpt": "包装做成透明方管",
      "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
      "quote": "包装为透明方管"
    },
    {
      "excerpt": "刷头是斜面设计",
      "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
      "quote": "配斜面刷头"
    }
  ],
  "reference_records": {
    "classification": {
      "domains": [
        "beauty"
      ],
      "channel": "xiaohongshu",
      "format": "video_script",
      "goal": "清楚介绍已有规格，帮助读者核对选择条件",
      "word_count": 180,
      "origin": "user",
      "ambiguities": []
    },
    "groups": {
      "methods": [
        "kb:1574231d-de88-459d-af1e-63429fc85668"
      ],
      "examples": [
        "kb:a950cf10-80f4-49ba-8a05-04077dddfb37"
      ],
      "facts": [
        "user-material",
        "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9"
      ]
    },
    "example_gap": false,
    "adoption_notes": [
      "参考kb:1574231d-de88-459d-af1e-63429fc85668的通用方法：按读者核对问题开篇、分段讲已知规格、结尾用提问收住；参考kb:a950cf10-80f4-49ba-8a05-04077dddfb37的口播结构，借其选色提问开场、短句逐项讲规格、自然询问偏好的节奏，但本题只陈述陶土玫瑰、3克、透明方管与斜面刷头，不采用其镜头展示的上唇效果与独特句子，并保留克制语气"
    ],
    "claim_map": [
      {
        "excerpt": "它的色号是陶土玫瑰",
        "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
        "quote": "色号为陶土玫瑰"
      },
      {
        "excerpt": "净含量3克",
        "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
        "quote": "净含量3克"
      },
      {
        "excerpt": "包装做成透明方管",
        "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
        "quote": "包装为透明方管"
      },
      {
        "excerpt": "刷头是斜面设计",
        "source_id": "kb:311d2826-d7a1-4710-a5f6-75bc36f913c9",
        "quote": "配斜面刷头"
      }
    ],
    "scope": "仅验证逐字引文和本任务事实组；不等同独立真实性核验或全网原创证明"
  },
  "limitations": [
    "kb:a950cf10-80f4-49ba-8a05-04077dddfb37：借鉴以选色问题开场、短句讲色号与刷头、结尾询问偏好的结构；本题改为规格核对，未用镜头展示与作者上唇体验，未复制其独特句子。",
    "kb:1574231d-de88-459d-af1e-63429fc85668：仅用于开篇提问、分段节奏与CTA选择，未作为本品事实依据。",
    "事实边界来自kb:311d2826-d7a1-4710-a5f6-75bc36f913c9：只有色号、净含量、包装形状与刷头类型，上色呈现、质地、持妆、保湿、适配唇况均无依据，正文已回避。",
    "原创性未穷尽比对，仅覆盖retrieved_references内1条样例，故originality_risk记unknown。",
    "来源匹配只验证引用存在，不能证明素材真实或检查完全；最终由用户确认。"
  ]
}
```

## 4. 数码图文

验收记录状态：WAITING_USER / final_confirmation。后续关闭标记：受控验收已保留成稿和审核；取消执行以释放单任务槽，未替用户确认或发布

### 分类与真实检索条件

```json
{
  "classification": {
    "domains": [
      "digital"
    ],
    "channel": "xiaohongshu",
    "format": "note",
    "goal": "清楚介绍已有规格，帮助读者核对选择条件",
    "word_count": 180,
    "origin": "user",
    "ambiguities": []
  },
  "engine": "filtered-local-vector-rerank-v1",
  "reranker": "cosine-topic-coverage-v1",
  "filters": {
    "methods": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "method",
      "domains": [
        "digital"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "allow_general": true,
      "document_ids": null,
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "图文笔记 原创写作 开篇 节奏 结构 表达 行动引导",
      "vector_candidate_count": 1
    },
    "examples": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "example",
      "domains": [
        "digital"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "allow_general": false,
      "document_ids": null,
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "数码 图文笔记 开篇 结构 表达",
      "vector_candidate_count": 1
    },
    "facts": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "fact",
      "domains": [
        "digital"
      ],
      "channel": null,
      "format": null,
      "allow_general": false,
      "document_ids": [
        "3c18b9a1-dfa6-47f4-9330-dce9ef46dacf"
      ],
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "静点D03鼠标的连接方式与尺寸介绍",
      "vector_candidate_count": 1
    }
  },
  "gaps": [],
  "example_gap": false,
  "prompt_versions": [
    "four-role-v1.0-original-grouped-retrieval3"
  ],
  "draft_ref": "e60edc77-da7a-450b-9902-433276f038ed@1",
  "snapshot_id": "a48ef9fd-f76c-4dc8-a846-ad66eaceb7cc"
}
```

### 通用创作方法（1 条）

```json
{
  "title": "验收自编通用原创方法",
  "source_id": "kb:1574231d-de88-459d-af1e-63429fc85668",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "general"
    ],
    "channel": "any",
    "format": "any",
    "material_type": "method",
    "origin": "user"
  },
  "score": 0.559903,
  "semantic_score": 0.622956,
  "topic_coverage": 0.076923
}
```

> 通用原创产品介绍方法：围绕读者实际选择问题开篇，把已知规格分成易读段落；根据图文、口播或详情形式调整段长与节奏，结尾按任务目标选择提问或核对提示。只用本次产品资料，不把参考作者的经历和测试数字写成自己的事实，不承诺必爆。

### 领域参考样例（1 条）

```json
{
  "title": "自编结构样例 · 数码图文",
  "source_id": "kb:ea4d5526-bdcd-47f7-90d0-1873341c5c99",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "digital"
    ],
    "channel": "xiaohongshu",
    "format": "note",
    "material_type": "example",
    "origin": "user"
  },
  "score": 0.497613,
  "semantic_score": 0.514874,
  "topic_coverage": 0.307692
}
```

> 从桌面上一根多余的线说起，先列连接方式，再把尺寸和供电写成容易扫读的段落。样例作者自测续航180天，这是仅属于该样例的测试结论，不能用于新产品。

### 独立事实依据（1 条）

```json
{
  "title": "虚构规格 · 静点D03鼠标",
  "source_id": "kb:746e29b0-2114-4491-aa06-1bdb2828f108",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "digital"
    ],
    "channel": "any",
    "format": "any",
    "material_type": "fact",
    "origin": "user"
  },
  "score": 0.735235,
  "semantic_score": 0.82289,
  "topic_coverage": 0.384615
}
```

> 静点D03鼠标是虚构验收产品。支持蓝牙和2.4GHz接收器两种连接，外形尺寸108×60×35毫米，重量68克，使用一节AA电池，包装不含电池。没有续航、延迟或静音测试数据。

### 最后版本完整成稿（未发布）

#### 静点D03鼠标：连接方式与尺寸规格一览

> 静点D03鼠标提供两种连接方式：蓝牙和2.4GHz接收器，两种都写在规格里。
>
> 外形尺寸为108×60×35毫米，重量68克，可用这几个数字对照你的桌面空间。
>
> 供电方面，鼠标使用一节AA电池，包装不含电池。
>
> 以上是本次可核对的三项规格：连接方式、外形尺寸与重量、供电方式。

行动引导：你更需要蓝牙还是2.4GHz接收器？可先按这两项规格核对。

标签：静点D03 / 鼠标规格 / 蓝牙鼠标 / 2.4G鼠标 / 鼠标尺寸 / 数码配件

### 独立人工抽查意见

事实相符，先前关于USB的错误主张在最终稿中删除；结尾总结存在重复，仍有精简空间。

本次对照未发现继承样例中的21天、不沾杯、八级风、180天、五年等私有经历或测试结论；此结论仅覆盖本报告列出的受控样例。

### 仅匹配当前稿件与快照的审核

```json
{
  "decision": "approved",
  "next_action": "await_user_confirmation",
  "draft_ref": "e60edc77-da7a-450b-9902-433276f038ed@1",
  "snapshot_id": "a48ef9fd-f76c-4dc8-a846-ad66eaceb7cc",
  "checks": [
    {
      "name": "brief_fit",
      "result": "pass",
      "basis": "标题与正文只介绍连接方式、尺寸、重量与供电，覆盖brief的规格介绍目标；无续航、延迟、静音等越界内容。"
    },
    {
      "name": "audience_fit",
      "result": "pass",
      "basis": "面向需核对规格的普通读者，用词清楚、断句短；未使用内部术语或购买指令。"
    },
    {
      "name": "usefulness_and_readability",
      "result": "pass",
      "basis": "正文按连接方式、尺寸重量、供电分段，段落易扫读；未混入“素材里没有依据”等内部沟通语句。"
    },
    {
      "name": "title_body_alignment",
      "result": "pass",
      "basis": "标题“连接方式与尺寸规格一览”与正文两项规格及供电段落一致，首句承接连接方式，承诺已兑现。"
    },
    {
      "name": "evidence_integrity",
      "result": "pass",
      "basis": "三项规格均逐字对应kb:746e29b0正文；未出现续航、延迟、静音或适配判断等未给数据。"
    },
    {
      "name": "experience_authenticity",
      "result": "pass",
      "basis": "全文无“亲测、实测、用了多久”等个人体验表述，也未移植样例作者180天续航结论。"
    },
    {
      "name": "originality_risk",
      "result": "unknown",
      "basis": "仅与kb:ea4d5526结构样例比对开头思路与分段节奏，未与其他来源穷尽比对；具体差异见limitations。"
    },
    {
      "name": "privacy_and_policy",
      "result": "pass",
      "basis": "无个人隐私、联系方式或违规内容；标签为产品名与规格类通用词。"
    }
  ],
  "issues": [],
  "claim_map": [
    {
      "excerpt": "静点D03鼠标提供两种连接方式：蓝牙和2.4GHz接收器，两种都写在规格里。",
      "source_id": "kb:746e29b0-2114-4491-aa06-1bdb2828f108",
      "quote": "静点D03鼠标是虚构验收产品。支持蓝牙和2.4GHz接收器两种连接，外形尺寸108×60×35毫米，重量68克，使用一节AA电池，包装不含电池。"
    },
    {
      "excerpt": "外形尺寸为108×60×35毫米，重量68克，可用这几个数字对照你的桌面空间。",
      "source_id": "kb:746e29b0-2114-4491-aa06-1bdb2828f108",
      "quote": "静点D03鼠标是虚构验收产品。支持蓝牙和2.4GHz接收器两种连接，外形尺寸108×60×35毫米，重量68克，使用一节AA电池，包装不含电池。"
    },
    {
      "excerpt": "供电方面，鼠标使用一节AA电池，包装不含电池。",
      "source_id": "kb:746e29b0-2114-4491-aa06-1bdb2828f108",
      "quote": "静点D03鼠标是虚构验收产品。支持蓝牙和2.4GHz接收器两种连接，外形尺寸108×60×35毫米，重量68克，使用一节AA电池，包装不含电池。"
    }
  ],
  "reference_records": {
    "classification": {
      "domains": [
        "digital"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "goal": "清楚介绍已有规格，帮助读者核对选择条件",
      "word_count": 180,
      "origin": "user",
      "ambiguities": []
    },
    "groups": {
      "methods": [
        "kb:1574231d-de88-459d-af1e-63429fc85668"
      ],
      "examples": [
        "kb:ea4d5526-bdcd-47f7-90d0-1873341c5c99"
      ],
      "facts": [
        "user-material",
        "kb:746e29b0-2114-4491-aa06-1bdb2828f108"
      ]
    },
    "example_gap": false,
    "adoption_notes": [
      "采用kb:1574231d-de88-459d-af1e-63429fc85668的方法：围绕读者选择问题开篇、按图文形式分段、结尾用核对提示；采用kb:ea4d5526-bdcd-47f7-90d0-1873341c5c99的表达：从桌面线缆困扰切入、把连接方式与尺寸供电分段的扫读节奏。本题改写为只陈述素材中的连接方式、尺寸、重量与电池事实，不引用样例作者自测续航等经历或结论，也不声称亲测。仅一份可用参考，已如实说明，不足则主要依据通用方法。"
    ],
    "claim_map": [
      {
        "excerpt": "静点D03鼠标提供两种连接方式：蓝牙和2.4GHz接收器，两种都写在规格里。",
        "source_id": "kb:746e29b0-2114-4491-aa06-1bdb2828f108",
        "quote": "静点D03鼠标是虚构验收产品。支持蓝牙和2.4GHz接收器两种连接，外形尺寸108×60×35毫米，重量68克，使用一节AA电池，包装不含电池。"
      },
      {
        "excerpt": "外形尺寸为108×60×35毫米，重量68克，可用这几个数字对照你的桌面空间。",
        "source_id": "kb:746e29b0-2114-4491-aa06-1bdb2828f108",
        "quote": "静点D03鼠标是虚构验收产品。支持蓝牙和2.4GHz接收器两种连接，外形尺寸108×60×35毫米，重量68克，使用一节AA电池，包装不含电池。"
      },
      {
        "excerpt": "供电方面，鼠标使用一节AA电池，包装不含电池。",
        "source_id": "kb:746e29b0-2114-4491-aa06-1bdb2828f108",
        "quote": "静点D03鼠标是虚构验收产品。支持蓝牙和2.4GHz接收器两种连接，外形尺寸108×60×35毫米，重量68克，使用一节AA电池，包装不含电池。"
      }
    ],
    "scope": "仅验证逐字引文和本任务事实组；不等同独立真实性核验或全网原创证明"
  },
  "limitations": [
    "kb:746e29b0-2114-4491-aa06-1bdb2828f108：文案事实全部取自该切片正文，该来源标注为原文切片，事实真实性未独立核验。",
    "kb:ea4d5526-bdcd-47f7-90d0-1873341c5c99：仅参考其开头由桌面线缆切入、规格分段与结尾核对提示的结构思路；本次以静点D03规格重新组织，未移植样例作者180天续航测试结论与个人经历。",
    "kb:1574231d-de88-459d-af1e-63429fc85668：借鉴围绕读者选择问题开篇、按图文调整段长与结尾提问；该方法文本不作为本产品适配、续航或性能的事实依据。",
    "原创性仅完成与上述参考的比对，未与其他来源穷尽比对，故originality_risk为unknown。",
    "来源匹配只验证引用存在，不能证明素材真实或检查完全；最终由用户确认。"
  ]
}
```

## 5. 家具图文

验收记录状态：WAITING_USER / final_confirmation。后续关闭标记：受控验收已保留成稿和审核；取消执行以释放单任务槽，未替用户确认或发布

### 分类与真实检索条件

```json
{
  "classification": {
    "domains": [
      "furniture"
    ],
    "channel": "xiaohongshu",
    "format": "note",
    "goal": "清楚介绍已有规格，帮助读者核对选择条件",
    "word_count": 180,
    "origin": "user",
    "ambiguities": []
  },
  "engine": "filtered-local-vector-rerank-v1",
  "reranker": "cosine-topic-coverage-v1",
  "filters": {
    "methods": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "method",
      "domains": [
        "furniture"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "allow_general": true,
      "document_ids": null,
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "图文笔记 原创写作 开篇 节奏 结构 表达 行动引导",
      "vector_candidate_count": 1
    },
    "examples": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "example",
      "domains": [
        "furniture"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "allow_general": false,
      "document_ids": null,
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "家具 图文笔记 开篇 结构 表达",
      "vector_candidate_count": 1
    },
    "facts": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "fact",
      "domains": [
        "furniture"
      ],
      "channel": null,
      "format": null,
      "allow_general": false,
      "document_ids": [
        "d11ed198-a806-41b1-a085-14dd5ac06f33"
      ],
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "木序F04边桌的尺寸与结构介绍",
      "vector_candidate_count": 1
    }
  },
  "gaps": [],
  "example_gap": false,
  "prompt_versions": [
    "four-role-v1.0-original-grouped-retrieval3"
  ],
  "draft_ref": "cfc0c272-7bc4-4d72-a87f-3c1e5b318dcf@1",
  "snapshot_id": "a5021bd8-c74a-4c9c-9168-ffdbea36d883"
}
```

### 通用创作方法（1 条）

```json
{
  "title": "验收自编通用原创方法",
  "source_id": "kb:1574231d-de88-459d-af1e-63429fc85668",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "general"
    ],
    "channel": "any",
    "format": "any",
    "material_type": "method",
    "origin": "user"
  },
  "score": 0.559903,
  "semantic_score": 0.622956,
  "topic_coverage": 0.090909
}
```

> 通用原创产品介绍方法：围绕读者实际选择问题开篇，把已知规格分成易读段落；根据图文、口播或详情形式调整段长与节奏，结尾按任务目标选择提问或核对提示。只用本次产品资料，不把参考作者的经历和测试数字写成自己的事实，不承诺必爆。

### 领域参考样例（1 条）

```json
{
  "title": "自编结构样例 · 家具图文",
  "source_id": "kb:4dfacf86-b6f0-4007-8c4e-9f78049b3dd5",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "furniture"
    ],
    "channel": "xiaohongshu",
    "format": "note",
    "material_type": "example",
    "origin": "user"
  },
  "score": 0.514416,
  "semantic_score": 0.535878,
  "topic_coverage": 0.272727
}
```

> 先想边桌放在哪里，再把尺寸、材质、收纳分成三段，让读者拿尺子核对空间。样例作者使用五年仍无划痕，这是个人经历，不能当成新产品结论。

### 独立事实依据（1 条）

```json
{
  "title": "虚构规格 · 木序F04边桌",
  "source_id": "kb:2e3f65d4-15d9-4f24-bcf1-72a9bd5af2f5",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "furniture"
    ],
    "channel": "any",
    "format": "any",
    "material_type": "fact",
    "origin": "user"
  },
  "score": 0.725807,
  "semantic_score": 0.839077,
  "topic_coverage": 0.272727
}
```

> 木序F04边桌是虚构验收产品。桌面为圆形，直径45厘米，高度52厘米，材质为橡胶木，底部设一层置物板。没有承重、耐水或环保等级检测结论。

### 最后版本完整成稿（未发布）

#### 圆桌直径45厘米、高52厘米，木序F04尺寸先量再决定

> 想给沙发或床边添一张边桌，先把打算放的位置量出来。木序F04边桌的桌面是圆形，直径45厘米，整体高度52厘米。
>
> 规格可以分成四点核对：桌面为圆形，直径45厘米；整体高度52厘米；材质为橡胶木；底部设一层置物板。
>
> 结构上能确认的是圆形桌面配底部一层置物板。目前没有承重、耐水或环保等级的检测结论，是否合适还要看你的实际空间与使用需求。

行动引导：可以先量一下打算放的位置，再对照直径45厘米、高52厘米这两个数字；尺寸合适的话，再来了解它是不是你要的那张边桌。

标签：边桌 / 木序F04 / 家具尺寸 / 小家具 / 家居选购

### 独立人工抽查意见

材质与尺寸事实相符，未继承五年使用经历；尺寸说明与结构重复，应精简。

本次对照未发现继承样例中的21天、不沾杯、八级风、180天、五年等私有经历或测试结论；此结论仅覆盖本报告列出的受控样例。

### 仅匹配当前稿件与快照的审核

```json
{
  "decision": "approved",
  "next_action": "await_user_confirmation",
  "draft_ref": "cfc0c272-7bc4-4d72-a87f-3c1e5b318dcf@1",
  "snapshot_id": "a5021bd8-c74a-4c9c-9168-ffdbea36d883",
  "checks": [
    {
      "name": "brief_fit",
      "result": "pass",
      "basis": "主题为木序F04尺寸与结构，受众为需了解规格的普通读者，语气清楚克制，约180字，均与简报一致。"
    },
    {
      "name": "audience_fit",
      "result": "pass",
      "basis": "以“先量位置”切入，用四点列出直径、高度、材质、置物板，面向选桌读者可核对。"
    },
    {
      "name": "usefulness_and_readability",
      "result": "pass",
      "basis": "段落短、数字集中，正文未混入“素材没给”“来源为空”等内部沟通语。"
    },
    {
      "name": "title_body_alignment",
      "result": "pass",
      "basis": "标题给出直径45厘米、高52厘米，正文首句承接量尺，正文兑现“先量再决定”的核对承诺，未超出规格。"
    },
    {
      "name": "evidence_integrity",
      "result": "pass",
      "basis": "直径45厘米、高52厘米、橡胶木、底部一层置物板均来自kb:2e3f65d4事实切片；未出现承重、耐水、环保等级结论。"
    },
    {
      "name": "experience_authenticity",
      "result": "pass",
      "basis": "未声称亲测或长期使用，未移植样例“五年无划痕”经历；无未核验的个人体验。"
    },
    {
      "name": "originality_risk",
      "result": "unknown",
      "basis": "已比对kb:4dfacf86样例与kb:1574231d方法，未见大段照搬或特色句复制；但未穷尽外部比对，故为unknown。"
    },
    {
      "name": "privacy_and_policy",
      "result": "pass",
      "basis": "未涉及隐私信息、绝对化功效或违规承诺，无来源ID混入读者文案。"
    }
  ],
  "issues": [],
  "claim_map": [
    {
      "excerpt": "木序F04边桌的桌面是圆形，直径45厘米，整体高度52厘米。",
      "source_id": "kb:2e3f65d4-15d9-4f24-bcf1-72a9bd5af2f5",
      "quote": "桌面为圆形，直径45厘米，高度52厘米，材质为橡胶木，底部设一层置物板。"
    },
    {
      "excerpt": "规格可以分成四点核对：桌面为圆形，直径45厘米；整体高度52厘米；材质为橡胶木；底部设一层置物板。",
      "source_id": "kb:2e3f65d4-15d9-4f24-bcf1-72a9bd5af2f5",
      "quote": "桌面为圆形，直径45厘米，高度52厘米，材质为橡胶木，底部设一层置物板。"
    },
    {
      "excerpt": "结构上能确认的是圆形桌面配底部一层置物板。",
      "source_id": "kb:2e3f65d4-15d9-4f24-bcf1-72a9bd5af2f5",
      "quote": "底部设一层置物板。"
    },
    {
      "excerpt": "目前没有承重、耐水或环保等级的检测结论",
      "source_id": "kb:2e3f65d4-15d9-4f24-bcf1-72a9bd5af2f5",
      "quote": "没有承重、耐水或环保等级检测结论。"
    }
  ],
  "reference_records": {
    "classification": {
      "domains": [
        "furniture"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "goal": "清楚介绍已有规格，帮助读者核对选择条件",
      "word_count": 180,
      "origin": "user",
      "ambiguities": []
    },
    "groups": {
      "methods": [
        "kb:1574231d-de88-459d-af1e-63429fc85668"
      ],
      "examples": [
        "kb:4dfacf86-b6f0-4007-8c4e-9f78049b3dd5"
      ],
      "facts": [
        "user-material",
        "kb:2e3f65d4-15d9-4f24-bcf1-72a9bd5af2f5"
      ]
    },
    "example_gap": false,
    "adoption_notes": [
      "采用kb:1574231d-de88-459d-af1e-63429fc85668：按“读者实际选择问题开篇—已知规格分段—结尾核对提示”组织，本题把选择问题收窄为放置尺寸，段落只写kb:2e3f65d4-15d9-4f24-bcf1-72a9bd5af2f5的四个已知项。参考kb:4dfacf86-b6f0-4007-8c4e-9f78049b3dd5的开篇方式（先想放在哪）与三段式节奏、尺子核对收尾；不采用其“使用五年仍无划痕”的个人经历，也不把样例结论移植到木序F04。样例仅一份可用，标题与开头方式参考有限，其余按事实边界自行收窄承诺。"
    ],
    "claim_map": [
      {
        "excerpt": "木序F04边桌的桌面是圆形，直径45厘米，整体高度52厘米。",
        "source_id": "kb:2e3f65d4-15d9-4f24-bcf1-72a9bd5af2f5",
        "quote": "桌面为圆形，直径45厘米，高度52厘米，材质为橡胶木，底部设一层置物板。"
      },
      {
        "excerpt": "规格可以分成四点核对：桌面为圆形，直径45厘米；整体高度52厘米；材质为橡胶木；底部设一层置物板。",
        "source_id": "kb:2e3f65d4-15d9-4f24-bcf1-72a9bd5af2f5",
        "quote": "桌面为圆形，直径45厘米，高度52厘米，材质为橡胶木，底部设一层置物板。"
      },
      {
        "excerpt": "结构上能确认的是圆形桌面配底部一层置物板。",
        "source_id": "kb:2e3f65d4-15d9-4f24-bcf1-72a9bd5af2f5",
        "quote": "底部设一层置物板。"
      },
      {
        "excerpt": "目前没有承重、耐水或环保等级的检测结论",
        "source_id": "kb:2e3f65d4-15d9-4f24-bcf1-72a9bd5af2f5",
        "quote": "没有承重、耐水或环保等级检测结论。"
      }
    ],
    "scope": "仅验证逐字引文和本任务事实组；不等同独立真实性核验或全网原创证明"
  },
  "limitations": [
    "kb:4dfacf86-b6f0-4007-8c4e-9f78049b3dd5：借鉴其“先想放置位置—尺寸/材质/收纳分段—核对式CTA”的标题与节奏结构；本题以木序F04已知规格重新组织，未移植“使用五年仍无划痕”等个人经历或效果结论。",
    "kb:1574231d-de88-459d-af1e-63429fc85668：采纳围绕读者选择问题开篇、按已知规格分段、结尾核对提示的方法；差异在于本题仅尺寸与结构事实，未补测试数字或承诺。",
    "原有事实切片只提供单页规格，无实拍图、安装步骤、说明书，正文按已知规格收束，不补步骤。",
    "原创性仅与本次两项参考比对，未做全平台穷尽比对，故originality_risk为unknown。",
    "来源匹配只验证引用存在，不能证明素材真实或检查完全；最终由用户确认。"
  ]
}
```

## 6. 园艺缺样例

验收记录状态：WAITING_USER / final_confirmation。后续关闭标记：受控验收已保留成稿和审核；取消执行以释放单任务槽，未替用户确认或发布

### 分类与真实检索条件

```json
{
  "classification": {
    "domains": [
      "gardening"
    ],
    "channel": "xiaohongshu",
    "format": "note",
    "goal": "清楚介绍已有规格，帮助读者核对选择条件",
    "word_count": 180,
    "origin": "user",
    "ambiguities": []
  },
  "engine": "filtered-local-vector-rerank-v1",
  "reranker": "cosine-topic-coverage-v1",
  "filters": {
    "methods": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "method",
      "domains": [
        "gardening"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "allow_general": true,
      "document_ids": null,
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "图文笔记 原创写作 开篇 节奏 结构 表达 行动引导",
      "vector_candidate_count": 1
    },
    "examples": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "example",
      "domains": [
        "gardening"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "allow_general": false,
      "document_ids": null,
      "enabled": true,
      "candidate_count": 0,
      "vector_query": "园艺 图文笔记 开篇 结构 表达",
      "vector_candidate_count": 0
    },
    "facts": {
      "owner": "[已隐去，按所属账号隔离]",
      "account_id": "[已隐去，按所属账号隔离]",
      "material_type": "fact",
      "domains": [
        "gardening"
      ],
      "channel": null,
      "format": null,
      "allow_general": false,
      "document_ids": [
        "a03e2764-a48a-4fa2-b394-c75cf32f078f"
      ],
      "enabled": true,
      "candidate_count": 1,
      "vector_query": "青芽G05花盆的尺寸与配件介绍",
      "vector_candidate_count": 1
    }
  },
  "gaps": [
    {
      "code": "NO_MATCHING_EXAMPLES",
      "group": "examples",
      "detail": "限定范围内无匹配材料，不使用无关资料补齐"
    }
  ],
  "example_gap": true,
  "prompt_versions": [
    "four-role-v1.0-original-grouped-retrieval3"
  ],
  "draft_ref": "a10e5b4b-65f9-4879-b1fe-151fe38b91a8@1",
  "snapshot_id": "e008c2f4-1b34-4502-bc90-83487f567d1e"
}
```

### 通用创作方法（1 条）

```json
{
  "title": "验收自编通用原创方法",
  "source_id": "kb:1574231d-de88-459d-af1e-63429fc85668",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "general"
    ],
    "channel": "any",
    "format": "any",
    "material_type": "method",
    "origin": "user"
  },
  "score": 0.559903,
  "semantic_score": 0.622956,
  "topic_coverage": 0.090909
}
```

> 通用原创产品介绍方法：围绕读者实际选择问题开篇，把已知规格分成易读段落；根据图文、口播或详情形式调整段长与节奏，结尾按任务目标选择提问或核对提示。只用本次产品资料，不把参考作者的经历和测试数字写成自己的事实，不承诺必爆。

### 领域参考样例（0 条）

没有匹配材料；未用其他领域样例补位。

### 独立事实依据（1 条）

```json
{
  "title": "虚构规格 · 青芽G05花盆",
  "source_id": "kb:2cec67fe-7adc-4307-bc13-4db3f08cbe82",
  "version": 1,
  "page": 1,
  "offset": 0,
  "classification": {
    "domains": [
      "gardening"
    ],
    "channel": "any",
    "format": "any",
    "material_type": "fact",
    "origin": "user"
  },
  "score": 0.690992,
  "semantic_score": 0.795558,
  "topic_coverage": 0.272727
}
```

> 青芽G05花盆是虚构验收产品。口径18厘米，高16厘米，底部有排水孔，附一个托盘，材质为陶土。没有植物生长速度、保水率或使用效果数据。

### 最后版本完整成稿（未发布）

#### 青芽G05规格一览：口径18、高16，附托盘

> 青芽G05花盆的已知规格，一条条列清楚。口径18厘米，高16厘米，底部有排水孔，附一个托盘，材质为陶土。摆放前拿尺子量两处：准备放花盆的位置，和现有容器的口径，再和18厘米、16厘米比对。要不要用托盘、陶土这个材质合不合你的习惯，也按自家条件判断。已知配件为附一个托盘。

行动引导：先量一下准备摆放的位置和现有容器口径，再决定是否合适。

标签：花盆规格 / 青芽G05 / 陶土花盆 / 尺寸核对 / 花盆尺寸

### 独立人工抽查意见

缺少同领域样例时只使用通用方法和本次事实；托盘说明重复，外部尺寸不等于实际适配证明，应保留测量核对边界。

本次对照未发现继承样例中的21天、不沾杯、八级风、180天、五年等私有经历或测试结论；此结论仅覆盖本报告列出的受控样例。

### 仅匹配当前稿件与快照的审核

```json
{
  "decision": "approved",
  "next_action": "await_user_confirmation",
  "draft_ref": "a10e5b4b-65f9-4879-b1fe-151fe38b91a8@1",
  "snapshot_id": "e008c2f4-1b34-4502-bc90-83487f567d1e",
  "checks": [
    {
      "name": "brief_fit",
      "result": "pass",
      "basis": "标题与正文均围绕口径18厘米、高16厘米、排水孔、附一托盘、陶土材质展开，符合“尺寸与配件介绍”主题；语气清楚克制，字数范围接近180字要求。"
    },
    {
      "name": "audience_fit",
      "result": "pass",
      "basis": "面向需核对规格的普通读者，正文给出量位置、量现有容器口径的核对方式，未用专业术语或效果承诺，便于非专业读者判断。"
    },
    {
      "name": "usefulness_and_readability",
      "result": "pass",
      "basis": "首句直接说明规格清单，逐条列已知项；上轮内部沟通句已删除，无“素材里没有”“待补一版”等创作过程交代，读者可获得可操作的核对步骤。"
    },
    {
      "name": "title_body_alignment",
      "result": "pass",
      "basis": "标题承诺“规格一览：口径18、高16，附托盘”，正文首句承接并逐条兑现这些已知项，CTA也围绕尺寸核对，无超出事实的承诺。"
    },
    {
      "name": "evidence_integrity",
      "result": "pass",
      "basis": "口径18厘米、高16厘米、排水孔、附一托盘、陶土均可在kb:2cec67fe-7adc-4307-bc13-4db3f08cbe82中逐字对应；未出现保水率、生长速度或适配结论等无依据断言。"
    },
    {
      "name": "experience_authenticity",
      "result": "pass",
      "basis": "正文无亲测、实拍、上手感受或继承样例结论的表述，符合user-material的禁止要求。"
    },
    {
      "name": "originality_risk",
      "result": "unknown",
      "basis": "限定范围内无匹配样例（NO_MATCHING_EXAMPLES），无可比对的参考文本，无法穷尽判断与全网既有表达的近似程度，仅能确认未复制参考案例。"
    },
    {
      "name": "privacy_and_policy",
      "result": "pass",
      "basis": "未涉及个人隐私、第三方经历、医疗或功效内容；标签为中性规格词，无“好物”等推荐倾向，无平台违规风险表述。"
    }
  ],
  "issues": [],
  "claim_map": [
    {
      "excerpt": "口径18厘米，高16厘米，底部有排水孔，附一个托盘，材质为陶土。",
      "source_id": "kb:2cec67fe-7adc-4307-bc13-4db3f08cbe82",
      "quote": "口径18厘米，高16厘米，底部有排水孔，附一个托盘，材质为陶土。"
    }
  ],
  "reference_records": {
    "classification": {
      "domains": [
        "gardening"
      ],
      "channel": "xiaohongshu",
      "format": "note",
      "goal": "清楚介绍已有规格，帮助读者核对选择条件",
      "word_count": 180,
      "origin": "user",
      "ambiguities": []
    },
    "groups": {
      "methods": [
        "kb:1574231d-de88-459d-af1e-63429fc85668"
      ],
      "examples": [],
      "facts": [
        "user-material",
        "kb:2cec67fe-7adc-4307-bc13-4db3f08cbe82"
      ]
    },
    "example_gap": true,
    "adoption_notes": [
      "账号定位为原创分类验收下的规格介绍，本条只陈述已知属性、不附加效果；样例缺口NO_MATCHING_EXAMPLES，无source_id可借鉴，按方法kb:1574231d-de88-459d-af1e-63429fc85668围绕读者选择问题开篇、分项段落、结尾核对提示组织，未做跨样例迁移，也未继承任何案例结论"
    ],
    "claim_map": [
      {
        "excerpt": "口径18厘米，高16厘米，底部有排水孔，附一个托盘，材质为陶土。",
        "source_id": "kb:2cec67fe-7adc-4307-bc13-4db3f08cbe82",
        "quote": "口径18厘米，高16厘米，底部有排水孔，附一个托盘，材质为陶土。"
      }
    ],
    "scope": "仅验证逐字引文和本任务事实组；不等同独立真实性核验或全网原创证明"
  },
  "limitations": [
    "未联网核验，仅供验收；口径与配件以kb:2cec67fe-7adc-4307-bc13-4db3f08cbe82原文为准，未独立核实。",
    "限定园艺领域内无匹配样例（NO_MATCHING_EXAMPLES），未做跨样例表达迁移；无样例本身不构成阻断。",
    "账号侧无受众评论、互动指标或平台榜单数据，受众需求判断为通用推理，不代表需求热度。",
    "素材未提供托盘尺寸、材质一致性、是否可拆卸等配件细节，正文未展开，也无法判断这些缺口对读者选择是否必需。",
    "来源匹配只验证引用存在，不能证明素材真实或检查完全；最终由用户确认。"
  ]
}
```

## 历史失败、被替代尝试与费用未知记录

### 摄影图文

```json
{
  "status": "FAILED",
  "wait_reason": null,
  "background": {
    "status": "done",
    "error": null,
    "attempts": 1,
    "updated": 1791681613.9540448,
    "active_seconds": 20.060627250000834,
    "completed_nodes": 12,
    "worker_online": true
  },
  "closed_for_next_case": null,
  "closure_note": null
}
```

```json
[
  {
    "stage": "research",
    "status": "validated",
    "error": null,
    "tokens": 3661,
    "reserved_tokens": 15276,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval1"
  },
  {
    "stage": "audience",
    "status": "validated",
    "error": null,
    "tokens": 3263,
    "reserved_tokens": 14901,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval1"
  },
  {
    "stage": "strategy",
    "status": "validated",
    "error": null,
    "tokens": 3919,
    "reserved_tokens": 16976,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval1"
  },
  {
    "stage": "outline",
    "status": "validated",
    "error": null,
    "tokens": 3895,
    "reserved_tokens": 17784,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval1"
  },
  {
    "stage": "hook",
    "status": "validated",
    "error": null,
    "tokens": 4032,
    "reserved_tokens": 18567,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval1"
  },
  {
    "stage": "title",
    "status": "validated",
    "error": null,
    "tokens": 4308,
    "reserved_tokens": 19043,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval1"
  },
  {
    "stage": "body",
    "status": "validated",
    "error": null,
    "tokens": 4606,
    "reserved_tokens": 20541,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval1"
  },
  {
    "stage": "review",
    "status": "validated",
    "error": null,
    "tokens": 5593,
    "reserved_tokens": 20423,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval1"
  },
  {
    "stage": "revise",
    "status": "validated",
    "error": null,
    "tokens": 5947,
    "reserved_tokens": 24798,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval1"
  },
  {
    "stage": "review",
    "status": "validated",
    "error": null,
    "tokens": 7234,
    "reserved_tokens": 27527,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval1"
  },
  {
    "stage": "revise",
    "status": "validated",
    "error": null,
    "tokens": 5324,
    "reserved_tokens": 22612,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval1"
  },
  {
    "stage": "review",
    "status": "validated",
    "error": null,
    "tokens": 6567,
    "reserved_tokens": 25343,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval1"
  }
]
```

### 数码图文

```json
{
  "status": "WAITING_USER",
  "wait_reason": "missing_material",
  "background": {
    "status": "waiting",
    "error": null,
    "attempts": 1,
    "updated": 1791681937.871667,
    "active_seconds": 10.005032374989241,
    "completed_nodes": 8,
    "worker_online": true
  },
  "closed_for_next_case": true,
  "closure_note": "受控验收已保留成稿和审核；取消执行以释放单任务槽，未替用户确认或发布"
}
```

```json
[
  {
    "stage": "audience",
    "status": "validated",
    "error": null,
    "tokens": 3498,
    "reserved_tokens": 15768,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval2"
  },
  {
    "stage": "research",
    "status": "validated",
    "error": null,
    "tokens": 4039,
    "reserved_tokens": 16143,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval2"
  },
  {
    "stage": "strategy",
    "status": "validated",
    "error": null,
    "tokens": 4064,
    "reserved_tokens": 17719,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval2"
  },
  {
    "stage": "outline",
    "status": "validated",
    "error": null,
    "tokens": 3951,
    "reserved_tokens": 18576,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval2"
  },
  {
    "stage": "hook",
    "status": "validated",
    "error": null,
    "tokens": 4062,
    "reserved_tokens": 19001,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval2"
  },
  {
    "stage": "title",
    "status": "validated",
    "error": null,
    "tokens": 4433,
    "reserved_tokens": 19722,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval2"
  },
  {
    "stage": "body",
    "status": "validated",
    "error": null,
    "tokens": 4690,
    "reserved_tokens": 20848,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval2"
  },
  {
    "stage": "review",
    "status": "validated",
    "error": null,
    "tokens": 5751,
    "reserved_tokens": 21252,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval2"
  }
]
```

### 家具图文

```json
{
  "status": "RUNNING",
  "wait_reason": null,
  "background": {
    "status": "blocked",
    "error": "模型返回格式不正确，未自动重试",
    "attempts": 1,
    "updated": 1791681949.0685298,
    "active_seconds": 10.001929167017806,
    "completed_nodes": 2,
    "worker_online": true
  },
  "closed_for_next_case": true,
  "closure_note": null
}
```

```json
[
  {
    "stage": "research",
    "status": "validated",
    "error": null,
    "tokens": 4835,
    "reserved_tokens": 16105,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval2"
  },
  {
    "stage": "audience",
    "status": "validated",
    "error": null,
    "tokens": 3584,
    "reserved_tokens": 15730,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval2"
  },
  {
    "stage": "strategy",
    "status": "failed",
    "error": "模型返回格式不正确，未自动重试",
    "tokens": null,
    "reserved_tokens": 17554,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval2"
  }
]
```

### 园艺缺样例

```json
{
  "status": "RUNNING",
  "wait_reason": null,
  "background": {
    "status": "blocked",
    "error": "模型返回格式不正确，未自动重试",
    "attempts": 1,
    "updated": 1791682392.512287,
    "active_seconds": 10.00503162498353,
    "completed_nodes": 3,
    "worker_online": true
  },
  "closed_for_next_case": true,
  "closure_note": null
}
```

```json
[
  {
    "stage": "research",
    "status": "validated",
    "error": null,
    "tokens": 4152,
    "reserved_tokens": 15126,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval3"
  },
  {
    "stage": "audience",
    "status": "validated",
    "error": null,
    "tokens": 3088,
    "reserved_tokens": 14763,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval3"
  },
  {
    "stage": "strategy",
    "status": "validated",
    "error": null,
    "tokens": 4187,
    "reserved_tokens": 16641,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval3"
  },
  {
    "stage": "outline",
    "status": "failed",
    "error": "模型返回格式不正确，未自动重试",
    "tokens": null,
    "reserved_tokens": 17556,
    "rate": 1.2e-06,
    "prompt_version": "four-role-v1.0-original-grouped-retrieval3"
  }
]
```

上述历史状态为当时保存的记录，RUNNING 不表示报告生成时仍在执行；以最终六场景验收和后续关闭标记为准。失败调用没有自动按成功计入，未知费用保守预留。

## 网页证据与核验边界

网页任务沿用 /api/runs → PostgreSQL 后台队列 → Worker → 四角色 → 审核 → 人工确认；分组检索资料与事实对应记录通过同一网页稿件依据入口查看。附图 web-retrieval.jpg 为本轮网页截图。

自动化检查在阶段交付中独立记录：全量 813 项、前端 131 项及最后定向 66 项通过；它们与真实模型六场景、人工质量核对是三类证据。报告生成不执行模型、不进行外部联网、不自动给出“全部质量通过”。
