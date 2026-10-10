# 个人模型连接

选择服务商、选择或填写模型 ID 和 API Key 即可保存；官方服务商预填 Base URL，自定义网关填写其实际地址。可编辑候选来自官方文档，模型 ID 由服务商账号决定，不将模型名称列表当作可用性保证。保存只写入加密配置，不调用模型。连接测试需要用户主动点击，可能产生费用。

高级设置默认折叠，包含显示名称、接口协议、预算和 JSON 模式。预算默认按输入输出合计每百万 token 20 美元估算，单次任务 1 美元、每日 5 美元；这是本应用的预算估算，不是服务商报价或服务商侧扣费上限。请按实际模型价格调整。已有连接更新时保留原预算。

支持 OpenAI Chat Completions、OpenAI Responses、Anthropic Messages 三种文本协议；自定义网关也可选择协议。完整的 `/chat/completions`、`/responses`、`/messages` 地址会识别协议并移除重复后缀。未知网关路径不自动补 `/v1`。地址限公网 HTTPS 443，保留 DNS 校验与固定解析地址连接。

默认通过提示词要求 JSON，不强制发送模型可能不支持的 JSON 参数。可手动启用 JSON 模式；Anthropic 不使用此开关。支持纯 JSON 或完整 JSON 代码围栏，仍验证业务结构、结束状态及实际报告用量；截断、拒答、格式错误或未知用量都会失败，不自动重试收费请求。只在百炼官方域名的原版 Qwen3 混合思考模型上关闭思考，以适配同步调用；不向任意网关注入该参数。

HTTP 错误保留服务商状态码、错误码和可读说明，同时去除 Key、Bearer 凭据及 URL。卡片只显示保存及最近测试状态；保存成功不等于联网验证。不同服务商模型的结构输出质量仍需按任务验收，本轮兼容测试使用协议替身，未逐一付费测试全部服务商。

## 参考与采用范围

- [CC Switch](https://github.com/farion1231/cc-switch)：采用服务商预设与少量连接字段的交互思路。
- [LiteLLM 模型参数适配](https://github.com/BerriAI/litellm/blob/main/litellm/llms/openai/chat/gpt_transformation.py)：按协议及模型处理兼容参数，不假定所有模型接受相同可选字段。
- [One API OpenAI 适配](https://github.com/songquanpeng/one-api/blob/main/relay/adaptor/openai/adaptor.go)：区分 Base URL、接口路径及认证。
- [LobeHub OpenAI Compatible Factory](https://github.com/lobehub/lobehub/blob/main/packages/model-runtime/src/core/openaiCompatibleFactory/index.ts)：参考配置规范化和服务商错误处理。
- [OpenAI 结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)及[百炼深度思考](https://help.aliyun.com/zh/model-studio/deep-thinking)：协议参数与 Qwen 同步限制依据。

以上为 2026-10-10 的官方仓库及文档检查。未引入这些项目的运行依赖或复制完整实现；原有账号隔离、密钥加密、版本快照、调用台账与预算预留继续使用。

候选模型依据：[DeepSeek Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)、[Qwen Plus](https://help.aliyun.com/zh/model-studio/qwen-plus)及[模型限流清单](https://help.aliyun.com/zh/model-studio/rate-limit)、[Kimi 模型选择](https://www.kimi.ai/help/kimi-api/api-model-selection)、[OpenAI GPT-4.1 Mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini)、[MiniMax OpenAI SDK](https://platform.minimax.cn/docs/api-reference/text-openai-api)、[Claude 模型表](https://platform.claude.com/docs/en/models/overview)、[Gemini OpenAI 兼容](https://ai.google.dev/gemini-api/docs/openai)。未读取用户账号的远程模型列表；未确认的服务商候选不猜填。
