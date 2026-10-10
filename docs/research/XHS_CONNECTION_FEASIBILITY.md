# 小红书个人账号连接可行性核实

核对日期：2026-10-10。用户目标是项目内连接个人小红书账号后自动同步数据，理想状态为实时。本文保留目标，但不把尚未取得的授权或未实测通道写成已完成。

## 结论与更正

目前没有找到可证明适用于本项目的“无接口权限个人账号自然笔记曝光、评论持续同步”通道。前期把本地浏览器自动化列为可直接实施的合法路线，依据不足，现更正为仅有技术候选，不能据此启用。平台条款限制与法律定性并非同一概念；本项目不在未有适用授权的情况下将受限制路线称为合规方案。

《小红书创作服务平台用户协议》于 2026-04-24 更新/生效，2026-10-10 通过官方登录页指向的协议页面读取全文。网页检索工具超时后，使用正常浏览器读取；未登录账号、未下载后台数据、未安装开源连接器。

| 官方条款 | 核实结果及影响 |
| --- | --- |
| 4.1 | 平台提供账号概览、曝光、观看、互动、涨粉、粉丝画像（有门槛）与数据文件导出，实际范围以平台为准；不能据此声称具体账号字段已实测 |
| 4.2 | 限制数据向第三方披露、商业推广/数据分析用途和技术批量抓取汇总 |
| 4.4 | 导出用于本人或机构内部优化创作，限制向第三方提供与商业化用途；不能默认把导出数据送入云端或外部模型 |
| 5.2、7.2 | 限制未授权第三方工具登录使用和自动程序访问；低频、自己的账号、开源项目或本机执行均不自动构成平台授权 |

来源：[创作服务平台用户协议](https://agree.xiaohongshu.com/h5/terms/ZXXY20260422001/-1)。以上为条款摘要，适用性发生变化时重新核实。

## 渠道矩阵

| 路线 | 已确认范围 | 对个人自然笔记同步的判断 |
| --- | --- | --- |
| [账号开放平台 Scope](https://openaccount.xiaohongshu.com/docs/scope) | 仅 basic_info 开放，昵称/头像/性别/地区；user_profile、read_notes 等规划中 | 登录身份不能标记为笔记数据授权 |
| [账号 API](https://openaccount.xiaohongshu.com/docs/api-reference)与[Webhook](https://openaccount.xiaohongshu.com/docs/webhook) | 身份与授权流程，Webhook 为撤销和扫码确认 | 无评论或自然流量事件证据 |
| [蒲公英官方帮助](https://pgy.xiaohongshu.com/help/detail?id=97e5a307cc23aeefc7295c76926088c6&userType=4) | 品牌营销、订单、累计投后数据，消耗/白名单准入条件 | 不等于个人账号全量自然笔记；广告投后不能替代自然流量 |
| [电商开放平台](https://open.xiaohongshu.com/document/developer/file/17) | 商品、订单、售后与店铺授权 | 不作为个人内容账号同步接口 |
| 官方文件导出 | 条款明确存在，具体文件格式未取得 | 可在许可用途内本人本机分析；不是自动同步，也无已验证官方格式解析器 |
| [新榜定制服务](https://newrank.cn/account/api)与[账号绑定](https://www.newrank.cn/account/user/authored.html) | 有定制 API 宣传，小红书简介唯一码认领 | 没有足够公开证据证明提供本项目所需的全部授权和字段；认领不等于平台数据 API 授权 |
| [千瓜协议](https://qian-gua.com/appfile/UserAgreement) | 数据产品另有抓取、第三方使用和云端/API 封装限制 | 购买会员不等于取得向本项目转接和再利用许可 |
| [xiaohongshu-mcp](https://github.com/xpzouying/xiaohongshu-mcp) | 开源浏览器实现 | 技术可参考，不是官方授权通道，未安装运行 |

开源核实：[LICENSE](https://github.com/xpzouying/xiaohongshu-mcp/blob/main/LICENSE) 是 Apache-2.0；[go.mod](https://github.com/xpzouying/xiaohongshu-mcp/blob/main/go.mod) 使用 Rod/headless_browser，包含 stealth 间接依赖；[feed_detail.go](https://github.com/xpzouying/xiaohongshu-mcp/blob/main/xiaohongshu/feed_detail.go)读取浏览器页面状态并滚动展开评论。代码许可仅说明代码使用条件，未授予小红书平台数据访问权。本次未采用其代码、规避检测功能或会话持久化方式。

## 当前实用交付与接口边界

`backend/social_connections.py` 提供 `SocialConnections.read(owner, account_id)` 和 `catalog(platform)`，从当前 owner 的 Operations 状态构建数据中心。它展示当前连接能力、来源证据、接入阻碍，以及本账号已人工归档的作品数量和指标快照数量。最近一份指标保留原来的来源、时间和窗口，缺失值为 null；不合计跨窗口快照、不把评论总数当评论正文、不把本地账号档案当平台连接。

当前无平台连接器，`connection_status=not_connected`、`automatic_sync_available=false`、`last_sync_at=null`。小红书能力是 permission_required；抖音是 not_implemented。不提供接收 Cookie、任意连接 URL 或浏览器伪授权状态的接口。身份连接、指标、评论、搜索均不能由客户端宣称为成功。

已有 `Operations.import_post` 和指标录入仍属用户人工记录。尚未取得官方导出样本，不编造官方 CSV/XLSX 列定义，不把现有导入说成官方文件格式兼容。

## 供应商或官方询证清单

在接入前需要可审阅的证据，尚未联系任何供应商或提交申请：

1. 平台授权或合法提供数据的依据，明确允许向本项目提供数据，而非只在供应商自己的产品内查看。
2. 普通个人账号是否支持；是否要求专业号、商单、投放、粉丝量或额外认证；自然笔记与广告数据分别列明。
3. 逐字段示例与定义：曝光、阅读、播放、点赞、收藏、分享、评论计数、评论正文及回复；无法提供项保留缺失。
4. 数据更新延迟、查询限制、授权有效期、历史覆盖范围、删除与撤销规则，不能只承诺“实时”。
5. 数据存储、本人本机使用、云端多租户使用、发送外部模型、RAG 与案例文档导出的允许范围。
6. 费用、试用样本与实测安排；不未经用户批准采购，不发送密码或 Cookie 换取接口。

接入路径的工程验收是：管理员核实授权材料 → 实现审查过的适配器 → 账号隔离与撤销测试 → 两次真实增量同步 → 核对源页面和采集时间 → 才启用对应能力。单独保存一份授权说明不会自动解锁代码。若仅身份授权成功，数据同步仍未完成。

## 验证范围

相关单元测试：`runtime/venv/bin/python -m unittest discover -s tests -p 'test_social_connections.py' -v`。覆盖账号隔离、模拟数据排除、人工记录不能冒充自动同步、缺失值、时区排序、不合计快照和敏感字段不返回。测试只证明本地状态投影与边界，不能证明真实平台连接成功。全量产品验证与最终提交记录由主任务统一执行和汇总。
