# GitHub 相近项目调研

检索日期：2026-09-20。通过用户指定的 GitHub 连接器搜索并读取仓库元数据、README、部分源码和许可证，网页搜索补充定位。检索词：xiaohongshu agent、小红书 图文 生成、social media agent langgraph。

本次为静态调研，未安装、运行、压测或安全审计第三方项目。README 功能是作者描述，不是本项目的验证结果。公开可读的仓库不一定具备允许商业复用的开源许可证。

## 1. 推荐顺序与对照

| 项目 | 与本项目的相似点 | 主要差异 / 建议用途 | 许可核对 |
| --- | --- | --- | --- |
| [EthanYoQ/agent-xiaohongshu-workbench](https://github.com/EthanYoQ/agent-xiaohongshu-workbench) | 账号定位、研究、选题、文稿、配图、人工预览 | 流程参考最接近；依赖本地 Codex、Chrome 和 Browser Bridge，不是用户直接用网页的托管产品 | 根 LICENSE 为 MIT；第三方 Skill 和 Logo 有独立边界 |
| [langchain-ai/social-media-agent](https://github.com/langchain-ai/social-media-agent) | 内容生成、人工修改/接受/拒绝、多步骤图编排 | 最值得读工作流代码；面向 Twitter/LinkedIn，不能直接当小红书成品 | 根 LICENSE 为 MIT |
| [HisMax/RedInk](https://github.com/HisMax/RedInk) | 大纲编辑、封面、多页图文、单页重生成 | 图文交互和输出组织参考；依赖生成式图片，MVP 采用固定模板以控制范围 | 根 LICENSE 为 CC BY-NC-SA 4.0，另有商业授权路径 |
| [Aaronwn/ai-xiaohs](https://github.com/Aaronwn/ai-xiaohs) | 标题正文、风格、编辑、卡片导出 | 轻量 UI 参考；README 未体现完整多 Agent 后台与任务恢复 | README 声明修改版 GPLv3 和商业限制；根 LICENSE URL 返回 404，不能按标准 GPL 推断 |
| [kvnZero/xhs-agent](https://github.com/kvnZero/xhs-agent) | 小红书与 AI Agent 场景 | 主要是 Selenium 浏览、点赞、收藏、评论自动化；不是创作产品底座 | API 未识别许可证，README 限学习用途、不允许商业使用 |

我的建议：参考前两个项目的流程与接口设计，借鉴 RedInk 的可编辑分页体验；自行实现云端身份、项目隔离、版本、任务恢复和模板导出。暂不整体 fork 任何项目，也不引入浏览器自动互动。

## 2. 值得阅读的具体位置

### 2.1 小红书工作台：用户流程与结构化提案

已读取 [README](https://github.com/EthanYoQ/agent-xiaohongshu-workbench/blob/main/README.md)、[修订 Schema](https://github.com/EthanYoQ/agent-xiaohongshu-workbench/blob/main/server/schemas/revise.schema.json)、[LICENSE](https://github.com/EthanYoQ/agent-xiaohongshu-workbench/blob/main/LICENSE) 和目录树。

可以研究“完整预览后确认”和结构化修改成果。其单一修订结构包含文案、卡片和视觉方向，本项目将文案与布局分开并绑定版本，以支持局部重做。其本地运行方式不能直接满足我们的零配置网页用户体验，需独立设计服务端模型调用、鉴权和持久化。

### 2.2 Social Media Agent：工作流与人工反馈

已读取 [生成工作流源码](https://github.com/langchain-ai/social-media-agent/blob/main/src/agents/generate-post/generate-post-graph.ts)、README、LICENSE 和目录树。源码具有内容验证、报告、写帖、图片、人工反馈及重写等节点，并使用条件边连接。

可借鉴状态图、人工反馈和失败分支的组织方式；其中平台授权、调度发布等集成不属于本 MVP。存在测试目录只说明有测试代码，本次未验证测试是否通过。

### 2.3 RedInk：分页、重生成与图文体验

已读取 [README](https://github.com/HisMax/RedInk/blob/main/README.md)、[依赖声明](https://github.com/HisMax/RedInk/blob/main/pyproject.toml)、[LICENSE](https://github.com/HisMax/RedInk/blob/main/LICENSE) 和目录树。其 Python/Flask、Vue 前后端适合研究图文生成交互，但本项目不因此更换所建议的技术栈。

作者许可明确包括非商业限制及相同方式共享条件，并单列商业授权。因此本轮仅作产品体验参考，不复制代码或素材作为商业产品底座。后续如要复用，先核对拟用文件、依赖与具体授权。

### 2.4 其余两个项目的边界

[ai-xiaohs README](https://github.com/Aaronwn/ai-xiaohs/blob/main/README.md) 有卡片样式和编辑流程，可做界面对照；许可描述非标准，应先澄清再复用。

[xhs-agent README](https://github.com/kvnZero/xhs-agent/blob/main/README.md) 的主要能力是平台交互自动化，且有用途限制。本 MVP 只做用户确认后的图文导出，不采用其自动点赞评论方向。

## 3. 活跃度快照

以下是 GitHub API 的 pushed_at（最近推送时间，不等于最后一个功能提交）和归档状态。动态信息仅代表本次查询，详见 [机器可读快照](repository_snapshot.json)。

| 项目 | 最近推送 UTC 日期 | 已归档 |
| --- | --- | --- |
| EthanYoQ/agent-xiaohongshu-workbench | 2026-09-07 | 否 |
| langchain-ai/social-media-agent | 2026-09-18 | 否 |
| HisMax/RedInk | 2026-06-30 | 否 |
| Aaronwn/ai-xiaohs | 2026-03-03 | 否 |
| kvnZero/xhs-agent | 2025-04-20 | 否 |

不以星数证明质量；未做全 GitHub 穷尽搜索，也不能证明不存在完全同类产品。表中的相似度和推荐顺序是本次设计判断。

## 4. 本项目可以验证的差异化

1. 用户无需本地 Agent/浏览器运行环境，直接通过网页完成创作。
2. 四角色共享有来源的素材，但仅获得所需上下文；审稿能精确返回问题段落。
3. 用户稿、候选稿、排版和审稿绑定版本，旧结果不能覆盖新编辑。
4. 任务可恢复、费用有硬上限、导出可重试，支撑持续使用。
5. 用同一批任务比较普通生成和协作流程，记录采用率、修改量、耗时与成本。

这些是拟实现和待验证的方向，不能宣称全行业首次。将竞赛创新点写成实际实现及对照证据，不将开源框架自身功能包装为团队原创算法。

## 5. 后续复用记录

若实际复用，新增第三方清单：仓库 URL、固定 commit、文件路径、许可证全文、改动说明、在本项目的用途、测试结果；同时核对依赖及图片/字体许可。当前没有复制这些项目的代码或下载运行它们，也没有产生模型调用费用。
