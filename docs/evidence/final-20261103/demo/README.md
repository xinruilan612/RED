# 功能视频：截图讲解版

视频是7张真实产品界面的等比完整截图与两张说明页拼接，共9场景。不是连续录屏、不是完整实时实操验收。输入页仅填写，未保存或发模型请求；正在生成页为历史捕获。界面中的sprint_study是隔离测试账号。

版本口径：11月3日v2真实模型历史；v3只有离线修正，未重新生成真实模型稿。90.9%是v2旧规划误计，v3固定候选回放纠正为0%；这不是正文质量下降，也不能作为质量提升。模型审核引用未通过时展示保守人工交接，未假称通过。未涵盖Windows原生运行、人工采用或发布；独立盲评仍待完成。

最终文件在output/有迹-省赛最终交付-20261103/01提交文档/有迹-功能与证据讲解-20261103.mp4。MP4/H.264，1920×1080，102秒；中文旁白由本机系统Tingting离线合成。没有调用付费模型或联网TTS。

在app目录复现：

```sh
swiftc -module-cache-path /tmp/youji-swift-cache -parse-as-library scripts/build_demo_video.swift -o /tmp/youji-demo
/tmp/youji-demo --screens docs/evidence/final-20261103/demo/screens --output ../output/有迹-省赛最终交付-20261103/01提交文档/有迹-功能与证据讲解-20261103.mp4
```

需要macOS的AppKit/AVFoundation/VideoToolbox与系统Tingting语音。受限沙箱若无法访问系统编码服务，应在允许本机媒体编码的环境运行；不需网络。脚本复现会覆盖指定同名视频，原截图保持不变，临时场景/音频/解码抽帧写入screens/rendered。

QA.json由AVAsset检查实际轨道和时长，全部音轨解码为PCM，9个场景中点均由实际MP4解码抽帧并逐一查看。decoded-frames保存本轮抽帧，screens保留原PNG与源hash。此QA不等于真人播放听审或Windows播放器验收。
