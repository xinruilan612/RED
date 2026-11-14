// Reproducible screenshot explainer; requires macOS AppKit, AVFoundation and say.
// Usage: swiftc -module-cache-path /tmp/youji-swift-cache -parse-as-library scripts/build_demo_video.swift -o /tmp/youji-demo
// /tmp/youji-demo --screens ../tmp/final-demo --output ../output/.../demo.mp4
import Foundation
import AppKit
import AVFoundation
import CoreVideo
import VideoToolbox
import AudioToolbox
import CryptoKit

struct Scene {
    let title:String; let kicker:String; let lines:[String]; let image:String?; let duration:Double; let narration:String
}
let scenes:[Scene] = [
 Scene(title:"有迹\n有依据的创作",kicker:"功能与证据讲解 · 2026.11.03",lines:["面向资料驱动的内容创作","四 Agent 协作，三个算法改进","以下为真实界面截图拼接讲解"],image:nil,duration:10,narration:"有迹面向资料驱动的内容创作。四个智能体协作，三个算法改进。本片使用真实界面截图讲解，并非连续录屏。"),
 Scene(title:"从需求与事实开始",kicker:"01 / 输入",lines:["输入主题、读者和产品资料","当前截图仅填写，未启动新调用","不把缺失信息写成已知事实"],image:"07-input.png",duration:10,narration:"先输入主题、读者和事实资料。这张输入界面只展示填写过程，没有启动新的模型调用。缺失信息不能编成事实。"),
 Scene(title:"RAG 分清资料用途",kicker:"02 / 资料库",lines:["方法、表达样例与事实分别使用","参考写法不等于可移植参数","本片展示资料库加载完成界面"],image:"06-library.png",duration:10,narration:"资料库区分方法、表达样例与事实。参考文章可以提供组织思路，作者的经历和产品参数不能直接移植。"),
 Scene(title:"后台协作与留痕",kicker:"03 / 真实模型历史",lines:["独立 Worker 执行与持久化","四角色保留输入、来源和用量","这是 11 月 3 日 v2 历史界面"],image:"01-running.png",duration:10,narration:"任务在后台由工作进程执行，保留输入、来源和用量。这里展示十一月三日第二版的真实运行历史。"),
 Scene(title:"规划指标必须纠错",kicker:"04 / 需求覆盖优化",lines:["截图 90.9% 是 v2 旧误计","v3 固定候选离线回放纠正为 0%","不是正文质量下降或质量提升","v3 尚未重新生成真实模型稿"],image:"02-plan.png",duration:16,narration:"注意，截图中的百分之九十点九，是第二版已发现的规划误计。第三版在固定候选离线回放中纠正为零。这是纠正虚高，不是正文质量变化。第三版未重新生成真实模型稿。"),
 Scene(title:"四 Agent 分工协作",kicker:"05 / 创作决策",lines:["受众分析 → 证据研究","内容策划、结构与正文","主编审核 → 人工最后确认","缺口提问按价值排序，可跳过"],image:"04-agents.png",duration:10,narration:"受众与研究先分析，内容角色负责策划和写作，主编负责审核。关键缺口可以提问或跳过，最终决定留给用户。"),
 Scene(title:"依据与版本可追溯",kicker:"06 / RAG 与结构迁移",lines:["稿件绑定输入快照与来源片段","结构迁移只借鉴段落功能","证据不足时调整槽位、收窄表达","引用存在不等于事实已被证明"],image:"03-evidence.png",duration:12,narration:"稿件可以追溯到输入快照和来源片段。结构迁移借鉴段落功能，缺少证据时调整写法。引用存在，也不等于事实已经被独立证明。"),
 Scene(title:"保守交接，保留问题",kicker:"07 / 审核边界",lines:["审核引用未通过校验","原始响应与问题继续保留","这次是待人工处理，不是审核通过","没有演示人工采用或发布"],image:"05-review.png",duration:12,narration:"这次审核引用没有通过校验，系统保留原始响应并交给人工处理。这不代表审核通过，本片也没有演示人工采用或发布。"),
 Scene(title:"验证证据与下一步",kicker:"08 / 当前边界",lines:["v2：三对六稿；一次未知用量失败","预注册十二格，后续五格未运行","v3：仅离线修正，回归日志可复查","待独立盲评与 Windows 原生验收"],image:nil,duration:12,narration:"第二版留下三对六稿，一次未知用量失败，后续五格未运行。第三版完成离线修正，回归日志可复查。独立盲评和 Windows 原生验收仍待完成。")
]
func fail(_ message:String)->Never { fputs(message+"\n",stderr);exit(1) }
func hash(_ url:URL)throws->String { SHA256.hash(data:try Data(contentsOf:url)).map{String(format:"%02x",$0)}.joined() }
func text(_ value:String,_ rect:NSRect,_ size:CGFloat,_ color:NSColor = .white,_ weight:NSFont.Weight = .regular) {
 let paragraph=NSMutableParagraphStyle();paragraph.lineSpacing=9;paragraph.lineBreakMode = .byWordWrapping
 (value as NSString).draw(in:rect,withAttributes:[.font:NSFont.systemFont(ofSize:size,weight:weight),.foregroundColor:color,.paragraphStyle:paragraph])
}
func drawScene(_ scene:Scene,_ index:Int,_ screens:URL)throws->CGImage {
 let canvas=NSImage(size:NSSize(width:1920,height:1080));canvas.lockFocus()
 NSColor(calibratedRed:0.035,green:0.065,blue:0.105,alpha:1).setFill();NSRect(x:0,y:0,width:1920,height:1080).fill()
 text("有迹  /  省赛功能与证据讲解",NSRect(x:60,y:1008,width:1220,height:38),26,.white,.semibold)
 text(String(format:"%02d / %02d",index+1,scenes.count),NSRect(x:1720,y:1008,width:160,height:38),24,NSColor.gray)
 let x:CGFloat=scene.image == nil ? 140:1040
 if let imageName=scene.image {
  let url=screens.appendingPathComponent(imageName)
  guard let image=NSImage(contentsOf:url) else {fail("Missing source screenshot: "+url.path)}
  let maxRect=NSRect(x:60,y:102,width:920,height:884),scale=min(maxRect.width/image.size.width,maxRect.height/image.size.height)
  let rect=NSRect(x:maxRect.midX-image.size.width*scale/2,y:maxRect.midY-image.size.height*scale/2,width:image.size.width*scale,height:image.size.height*scale)
  image.draw(in:rect,from:.zero,operation:.sourceOver,fraction:1)
 }
 text(scene.kicker,NSRect(x:x,y:882,width:780,height:40),25,NSColor(calibratedRed:0.58,green:0.85,blue:0.70,alpha:1),.semibold)
 text(scene.title,NSRect(x:x,y:710,width:780,height:160),scene.image == nil ? 66:48,.white,.bold)
 for (lineIndex,line) in scene.lines.enumerated() {
  text("• "+line,NSRect(x:x,y:620-CGFloat(lineIndex)*100,width:790,height:90),29,NSColor(calibratedWhite:0.90,alpha:1))
 }
 NSColor(calibratedWhite:0.16,alpha:1).setFill();NSRect(x:60,y:78,width:1800,height:2).fill()
 text("真实界面截图讲解 · 非连续录屏  |  11/3 v2 实跑历史；v3 仅离线修正，未重新生成",NSRect(x:60,y:40,width:1800,height:28),21,NSColor(calibratedWhite:0.78,alpha:1))
 text("未涵盖 Windows 原生运行 / 人工采用 / 发布  ·  模型审核不等于独立事实核验",NSRect(x:60,y:12,width:1800,height:26),19,NSColor(calibratedWhite:0.65,alpha:1))
 canvas.unlockFocus();guard let data=canvas.tiffRepresentation,let rep=NSBitmapImageRep(data:data),let image=rep.cgImage else {fail("Scene drawing failed")};return image
}
func writePNG(_ image:CGImage,_ url:URL)throws {let rep=NSBitmapImageRep(cgImage:image);try rep.representation(using:.png,properties:[:])!.write(to:url)}
func buffer(_ image:CGImage)throws->CVPixelBuffer {
 var pixel:CVPixelBuffer?;let attrs:[CFString:Any]=[kCVPixelBufferCGImageCompatibilityKey:true,kCVPixelBufferCGBitmapContextCompatibilityKey:true]
 guard CVPixelBufferCreate(kCFAllocatorDefault,1920,1080,kCVPixelFormatType_32ARGB,attrs as CFDictionary,&pixel)==kCVReturnSuccess,let pixel else {fail("Pixel buffer failed")}
 CVPixelBufferLockBaseAddress(pixel,[]);defer{CVPixelBufferUnlockBaseAddress(pixel,[])}
 guard let context=CGContext(data:CVPixelBufferGetBaseAddress(pixel),width:1920,height:1080,bitsPerComponent:8,bytesPerRow:CVPixelBufferGetBytesPerRow(pixel),space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGImageAlphaInfo.noneSkipFirst.rawValue) else{fail("Context failed")}
 context.draw(image,in:CGRect(x:0,y:0,width:1920,height:1080));return pixel
}
@main struct Demo {
 static func main()throws {
  let args=CommandLine.arguments;func option(_ name:String)->String{guard let index=args.firstIndex(of:name),index+1<args.count else{fail("Missing "+name)};return args[index+1]}
  let screens=URL(fileURLWithPath:option("--screens")),output=URL(fileURLWithPath:option("--output")),work=screens.appendingPathComponent("rendered")
  try FileManager.default.createDirectory(at:work,withIntermediateDirectories:true);try FileManager.default.createDirectory(at:output.deletingLastPathComponent(),withIntermediateDirectories:true)
  let silent=work.appendingPathComponent("silent.mp4");try? FileManager.default.removeItem(at:silent);try? FileManager.default.removeItem(at:output)
  let writer=try AVAssetWriter(outputURL:silent,fileType:.mp4)
  let input=AVAssetWriterInput(mediaType:.video,outputSettings:[AVVideoCodecKey:AVVideoCodecType.h264,AVVideoWidthKey:1920,AVVideoHeightKey:1080,AVVideoEncoderSpecificationKey:[kVTVideoEncoderSpecification_EnableHardwareAcceleratedVideoEncoder as String:false],AVVideoCompressionPropertiesKey:[AVVideoAverageBitRateKey:6000000]])
  let adaptor=AVAssetWriterInputPixelBufferAdaptor(assetWriterInput:input,sourcePixelBufferAttributes:[kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_32ARGB,kCVPixelBufferWidthKey as String:1920,kCVPixelBufferHeightKey as String:1080]);writer.add(input)
  guard writer.startWriting() else{fail("Video writer: "+String(describing:writer.error))};writer.startSession(atSourceTime:.zero)
  var frame=0;var audioURLs:[URL]=[];var audioDurations:[Double]=[];var sourceHashes:[String:String]=[:]
  for (index,scene) in scenes.enumerated(){
   let image=try drawScene(scene,index,screens);try writePNG(image,work.appendingPathComponent(String(format:"slide-%02d.png",index+1)))
   if let name=scene.image{sourceHashes[name]=try hash(screens.appendingPathComponent(name))}
   let pixel=try buffer(image)
   for _ in 0..<Int(scene.duration*10){while !input.isReadyForMoreMediaData{if writer.status == .failed{fail(String(describing:writer.error))};Thread.sleep(forTimeInterval:0.01)};guard adaptor.append(pixel,withPresentationTime:CMTime(value:Int64(frame),timescale:10)) else{fail("Video append failed")};frame+=1}
   let audio=work.appendingPathComponent(String(format:"speech-%02d.aiff",index+1));var rate=215;var duration=0.0
   repeat {
    try? FileManager.default.removeItem(at:audio)
    let say=Process();say.executableURL=URL(fileURLWithPath:"/usr/bin/say");say.arguments=["-v","Tingting (中文（中国大陆）)","-r",String(rate),"-o",audio.path,scene.narration];try say.run();say.waitUntilExit();if say.terminationStatus != 0{fail("Offline narration failed")}
    duration=CMTimeGetSeconds(AVURLAsset(url:audio).duration);rate+=25
   }while duration>scene.duration-0.5 && rate<440
   if duration>scene.duration{fail("Narration too long for scene")};audioURLs.append(audio);audioDurations.append(duration)
   print("scene \(index+1), audio \(duration)s")
  }
  input.markAsFinished();let finished=DispatchSemaphore(value:0);writer.finishWriting{finished.signal()};finished.wait();guard writer.status == .completed else{fail("Writer did not finish")}
  let composition=AVMutableComposition();let videoTrack=composition.addMutableTrack(withMediaType:.video,preferredTrackID:kCMPersistentTrackID_Invalid)!,audioTrack=composition.addMutableTrack(withMediaType:.audio,preferredTrackID:kCMPersistentTrackID_Invalid)!
  let videoAsset=AVURLAsset(url:silent);try videoTrack.insertTimeRange(CMTimeRange(start:.zero,duration:videoAsset.duration),of:videoAsset.tracks(withMediaType:.video)[0],at:.zero)
  var offset=0.0
  for (index,url) in audioURLs.enumerated(){let asset=AVURLAsset(url:url);try audioTrack.insertTimeRange(CMTimeRange(start:.zero,duration:asset.duration),of:asset.tracks(withMediaType:.audio)[0],at:CMTime(seconds:offset,preferredTimescale:600));offset+=scenes[index].duration}
  guard let exporter=AVAssetExportSession(asset:composition,presetName:AVAssetExportPresetHighestQuality) else{fail("No exporter")};exporter.outputURL=output;exporter.outputFileType = .mp4;exporter.shouldOptimizeForNetworkUse=true
  let done=DispatchSemaphore(value:0);exporter.exportAsynchronously{done.signal()};done.wait();guard exporter.status == .completed else{fail("Export failed "+String(describing:exporter.error))}
  let asset=AVURLAsset(url:output);let video=asset.tracks(withMediaType:.video);let audio=asset.tracks(withMediaType:.audio)
  let generator=AVAssetImageGenerator(asset:asset);generator.appliesPreferredTrackTransform=true
  var chapterQA:[[String:Any]]=[];offset=0
  for (index,scene) in scenes.enumerated(){let sample=work.appendingPathComponent(String(format:"decoded-%02d.png",index+1));let image=try generator.copyCGImage(at:CMTime(seconds:offset+scene.duration/2,preferredTimescale:600),actualTime:nil);try writePNG(image,sample);chapterQA.append(["title":scene.title,"start_seconds":offset,"duration_seconds":scene.duration,"decoded_frame":sample.lastPathComponent,"narration_seconds":audioDurations[index]]);offset+=scene.duration}
  var audioSamples=0
  let audioReader=try AVAssetReader(asset:asset)
  guard let firstAudio=audio.first else{fail("No final audio track")}
  let audioOutput=AVAssetReaderTrackOutput(track:firstAudio,outputSettings:[AVFormatIDKey:kAudioFormatLinearPCM,AVLinearPCMIsFloatKey:false,AVLinearPCMBitDepthKey:16])
  audioReader.add(audioOutput);guard audioReader.startReading() else{fail("Audio decode failed")}
  while let sample=audioOutput.copyNextSampleBuffer(){audioSamples+=CMSampleBufferGetNumSamples(sample)}
  guard audioReader.status == .completed && audioSamples>0 else{fail("Audio track did not decode completely")}
  let qa:[String:Any]=["format":"MP4/H.264 with offline synthesized narration","presentation":"截图拼接讲解，非连续录屏；截图原文件未修改","video_seconds":CMTimeGetSeconds(asset.duration),"audio_track_seconds":audio.first.map{CMTimeGetSeconds($0.timeRange.duration)} ?? 0,"video_tracks":video.count,"audio_tracks":audio.count,"decoded_audio_samples":audioSamples,"width":video.first?.naturalSize.width ?? 0,"height":video.first?.naturalSize.height ?? 0,"source_screenshot_sha256":sourceHashes,"scenes":chapterQA,"output_sha256":try hash(output),"limitations":["11/3 v2实跑历史，v3仅离线修正未重新生成","未涵盖Windows原生运行、人工采用或发布","无独立人评质量结论"]]
  try JSONSerialization.data(withJSONObject:qa,options:[.prettyPrinted,.sortedKeys]).write(to:output.deletingPathExtension().appendingPathExtension("QA.json"))
  print("Created "+output.path)
 }
}
