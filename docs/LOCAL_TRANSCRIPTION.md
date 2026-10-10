# 本地音视频转写

这是用户有权上传媒体的本地音轨转写，不读取任意路径，不下载他人媒体，不调用收费 API，也不分析视频画面。

## 环境与安装

使用项目 `runtime/venv/bin/python`。可选依赖清单是 `requirements-asr.txt`，已有 RAG 环境通常只需确认 `imageio-ffmpeg`，不要重复安装整套模型环境。`imageio-ffmpeg` 自带 FFmpeg，不要求系统 PATH 有 ffmpeg，也不需要 soundfile、torchaudio。

显式运行 `runtime/venv/bin/python scripts/setup_local_transcription.py` 下载公开模型。固定模型为 `openai/whisper-tiny` 多语言版，revision `169d4a4341b33bc18d8881c4b69c2e104e1cc0af`。模型目录为 `runtime/models/whisper-tiny`；清单保存官方来源、仓库许可证标注与各文件 SHA256。下载不等于推理收费；运行时只用本地文件和 CPU。模型原始来源：https://huggingface.co/openai/whisper-tiny/tree/169d4a4341b33bc18d8881c4b69c2e104e1cc0af 。

## 接口与边界

`backend.local_transcription.transcribe_upload(data: bytes, *, filename, account_id, title, permission_confirmed, platform='other')` 返回 `payload`、`segments` 和 `provenance`，不自行写入数据库。调用边界必须先校验登录和账号归属，并在并发入口设置限制；此函数本身没有账号数据库权限判定。

`payload` 可供 `ResearchCases.save` 保存；用户应先预览校对。`provenance` 含原媒体 hash、字节数、音轨秒数和固定模型版本，调用方应随转写记录保留。标题只是文档标题，不进入转写正文。默认用途为表达参考，内容类别为 transcript，不能自动成为商品功效事实。

单文件最多 10 MiB，容器时长及实际音轨均不能超过 120 秒；只接受 mp4/mov/m4a/mp3/wav/aiff/aif/flac/ogg/webm。解码只允许 file/pipe 协议和指定媒体解析器。临时目录私有，媒体及音频文件权限 0600，退出后清理。探测 10 秒、解码 30 秒、CPU 推理 240 秒超时；不进行自动重试。无音轨、无可验证时长、坏文件、静音、输出不完整均失败，不截断后称完整结果。

每 30 秒一段，时间是输入音轨范围，不是逐字对齐。当前不提供说话人区分、画面 OCR、音乐识别或保证准确率。模型可能错写专有名词、输出繁体、在噪音中产生幻觉，必须由用户校对。

## 验收记录（2026-10-10）

真实离线 CPU 验收使用 macOS Tingting 合成的自有中文测试音频，时长 13.083 秒；成功产生时间分段转写。预期包含“杏茶、莓果和豆沙”，实际有“姓茶、美國和豆沙”等同音误识别。这证明解码、模型推理与返回链路可运行，不证明识别质量已满足生产使用。未进行付费调用。

核心失败边界运行：`runtime/venv/bin/python -m unittest discover -s tests -p test_local_transcription.py -v`。
