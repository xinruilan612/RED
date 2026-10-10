# 本地语义 RAG 与案例库部署

当前需求入口：[小红书连接、研究资料库与多模型](design/CONNECTED_CREATOR_REQUIREMENTS.md)。本功能不提供未获许可的小红书自动采集通道。

实际完整验收及环境冲突见 [2026-10-10 状态说明](CONNECTED_CREATOR_STATUS.md)：本轮使用8775独立schema，原默认库触发SCHEMA_TOO_NEW，不把隔离测试成功当成默认启动成功。

## 安装和运行

使用已有项目虚拟环境，显式下载一次；应用运行时不自动下载、不调用收费向量 API：

```bash
runtime/venv/bin/python scripts/setup_local_embeddings.py --install-dependencies
```

脚本安装 requirements-rag.txt 的固定版本依赖，将模型保存在忽略提交的 runtime/models/bge-small-zh-v1.5。HuggingFace 缓存默认位于忽略提交的 runtime/huggingface。仅下载配置、词表、文本和 safetensors，不下载 pickle 权重或执行远程代码。完成后重启 API 与 Worker，应用检测 manifest 自动使用本地 CPU 语义检索。模型未安装时正常使用 BM25，并在返回结果 embedding_note 说明原因。

模型：[BAAI/bge-small-zh-v1.5](https://huggingface.co/BAAI/bge-small-zh-v1.5)，MIT 许可证，固定 revision `7999e1d3359715c523056ef9478215996d62a620`；权重 SHA256 `354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026`。完整各文件 hash、来源与许可记录位于本地 youji-model-manifest.json；模型 README 同目录保留。不将此模型输出当作事实独立核验。

可配置 YOUJI_EMBEDDING_MODEL_PATH 为另一个已审核的本地 sentence-transformers 模型目录；设为 off 可关闭语义检索。未安装依赖、目录无效、向量计算失败均显式回退 BM25。官方模型使用 trust_remote_code=False、local_files_only=True、use_safetensors=True，不发生隐式联网。

## 检索边界

账号 owner/account_id、有效资料与当前版本在语义运算前过滤。BM25 与真实本地语义检索分别召回，RRF 融合排序；因此可召回没有共享字词的语义材料。语义相似度最低门槛 0.40 是初始工程阈值，不是事实置信度或质量承诺；后续需按业务检索样本评估。中文 BGE 输出 512 维。

每次最多 256 个当前资料块进入本地语义检索，超限明确回退 BM25并提示缩小资料选择范围，不偷偷截断候选后宣称完整语义检索。进程内最多缓存 1024 个向量，以模型路径、manifest版本和全文 SHA256 为键；缓存不替代每次账号/版本过滤。缓存仅内存，重启后重算。

应用返回 engine 为 bm25-zh-bigram-v1 或 hybrid-bm25-local-rrf-v1，并保留实际来源片段/版本/位置；案例证据还含 evidence_role、content_kind、source_scope、case_ref。相关度用于排序，不是事实置信度。

## 案例库

案例沿用 knowledge_documents/knowledge_versions 原子事务，无新增数据库表。metadata.research_case 保存来源平台、作者、发布时间、指标观察时间、采集时间、指标、内容类别和筛选规则。text/transcript 可检索；lead 仅为未读线索，不进入 RAG。expression_reference 与 product_fact 分开，前者只能参考表达结构，后者仍需核对事实。

保存有权使用的资料需 permission_confirmed=true。from_article 仅消费已读网页正文包，使用统一来源许可检查；不会自动访问小红书。缺失指标保留 null，未给观察时间不能提交指标；高互动候选按公开的绝对阈值/时间窗筛选，不是平台爆款核实或因果结论。

Markdown 导出包括当前选定案例的版本、来源、时间、未知指标、筛选规则与正文/字幕/线索，内容转义以避免生成外部图片或可执行 HTML。删除资料停止新检索，旧版本与任务证据审计保留。后台采集通过事务内guard/saved钩子与租约提交保持原子性。

## 验证

```bash
YOUJI_EMBEDDING_MODEL_PATH=off runtime/venv/bin/python -m unittest discover -s tests -p 'test_hybrid_retrieval.py' -v
runtime/venv/bin/python -m unittest discover -s tests -p 'test_local_semantic_model.py' -v
runtime/venv/bin/python -m unittest discover -s tests -p 'test_research_cases.py' -v
```

案例测试设置 TEST_DATABASE_URL 后还运行真实 PostgreSQL 临时 schema。未设置数据库或未安装本地模型时相应用例会跳过，跳过不得计为该能力验收。词法回归测试显式使用 YOUJI_EMBEDDING_MODEL_PATH=off；真实语义用例单独验证无共享中文bigram的查询仍能召回相关资料、排除无关样本。该小样本只证明真实模型和检索接线，不证明通用检索质量改善。
