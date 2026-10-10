"""Bounded opt-in local ASR for user-owned uploads; no remote media or paid API."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from backend.contracts import DomainError, require

MODEL_ID = 'openai/whisper-tiny'
REVISION = '169d4a4341b33bc18d8881c4b69c2e104e1cc0af'
ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT/'runtime/models/whisper-tiny'
MAX_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 120
SAMPLE_RATE = 16000
FORMATS = {'.mp4':'mov','.mov':'mov','.m4a':'mov','.mp3':'mp3','.wav':'wav',
           '.aiff':'aiff','.aif':'aiff','.flac':'flac','.ogg':'ogg','.webm':'matroska'}


def _run(args, timeout):
    try:
        return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise DomainError('TRANSCRIPTION_TIMEOUT','本地媒体处理超时，未保存案例') from None
    except OSError:
        raise DomainError('TRANSCRIPTION_UNAVAILABLE','本地媒体处理依赖不可用') from None


def _decode(source, target, extension):
    try:
        import imageio_ffmpeg
        executable=imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError,RuntimeError):
        raise DomainError('TRANSCRIPTION_UNAVAILABLE','请安装可选本地转写依赖') from None
    common=[executable,'-nostdin','-hide_banner','-protocol_whitelist','file,pipe',
            '-f',FORMATS[extension],'-i',str(source)]
    probe=_run(common,10)
    info=probe.stderr.decode('utf-8',errors='replace')
    duration=re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)',info)
    require(duration is not None,'MEDIA_INVALID','无法确认媒体时长，请转成标准音频或视频后上传')
    seconds=sum(float(n)*scale for n,scale in zip(duration.groups(),(3600,60,1)))
    require(0 < seconds <= MAX_SECONDS,'MEDIA_TOO_LONG','媒体须为120秒以内，未截断保存')
    require('Audio:' in info,'MEDIA_INVALID','媒体没有可识别的音轨')
    # Local demuxer + protocol allowlist disallow playlist/network fetches. Decode
    # one extra second and bound output so understated container duration fails.
    result=_run(common+['-v','error','-map','0:a:0','-vn','-sn','-dn','-t',str(MAX_SECONDS+1),
         '-ac','1','-ar',str(SAMPLE_RATE),'-f','f32le','-fs',str((MAX_SECONDS+1)*SAMPLE_RATE*4),'-y',str(target)],30)
    require(result.returncode==0 and target.is_file(),'MEDIA_INVALID','媒体音轨无法解码')
    size=target.stat().st_size
    require(size>0 and size%4==0,'MEDIA_INVALID','音轨为空或已损坏')
    require(size<=MAX_SECONDS*SAMPLE_RATE*4,'MEDIA_TOO_LONG','实际音轨超过120秒，未截断保存')
    return size/4/SAMPLE_RATE


def _infer(audio, directory):
    manifest=MODEL_PATH/'youji-model-manifest.json'
    require(manifest.is_file(),'TRANSCRIPTION_UNAVAILABLE','请先运行本地转写模型安装脚本')
    try:
        provenance=json.loads(manifest.read_text())
        require(provenance['model_id']==MODEL_ID and provenance['revision']==REVISION,
                'TRANSCRIPTION_UNAVAILABLE','本地转写模型版本不匹配')
    except (ValueError,KeyError):
        raise DomainError('TRANSCRIPTION_UNAVAILABLE','本地转写模型清单无效') from None
    result=_run([sys.executable,'-m','backend.local_transcription','--worker',str(audio)],240)
    require(result.returncode==0,'TRANSCRIPTION_FAILED','本地转写失败，未保存案例')
    try:
        segments=json.loads(result.stdout)
    except (ValueError,UnicodeError):
        raise DomainError('TRANSCRIPTION_FAILED','转写返回格式无效') from None
    return segments


def transcribe_upload(data, *, filename, account_id, title, permission_confirmed, platform='other'):
    """Return {payload, provenance, segments}; caller previews/saves ResearchCases payload.

    Only bytes accepted. Filenames select a fixed demuxer; never become paths.
    No network is used by decoding or inference, and no case is saved here.
    """
    require(permission_confirmed is True,'INVALID_INPUT','请确认有权保存并使用这份媒体')
    require(isinstance(data,bytes) and 0<len(data)<=MAX_BYTES,'INVALID_INPUT','媒体文件须为10MB以内的非空文件')
    require(isinstance(filename,str) and 0<len(filename)<=255,'INVALID_INPUT','文件名无效')
    extension=Path(filename).suffix.lower()
    require(extension in FORMATS,'INVALID_INPUT','不支持该媒体格式')
    require(isinstance(account_id,str) and bool(account_id),'INVALID_INPUT','请选择资料所属账号')
    require(isinstance(title,str) and 0<len(title.strip())<=200,'INVALID_INPUT','标题须为1至200字')
    with tempfile.TemporaryDirectory(prefix='youji-asr-') as folder:
        source=Path(folder)/('upload'+extension);audio=Path(folder)/'audio.f32'
        fd=os.open(source,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as handle:handle.write(data)
        fd=os.open(audio,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        seconds=_decode(source,audio,extension)
        segments=_infer(audio,folder)
    require(isinstance(segments,list) and 0<len(segments)<=4,'TRANSCRIPTION_FAILED','未识别到有效语音')
    previous=0
    for segment in segments:
        require(isinstance(segment,dict) and set(segment)=={'start','end','text'},'TRANSCRIPTION_FAILED','转写分段无效')
        require(type(segment['start']) in (int,float) and type(segment['end']) in (int,float)
                and previous<=segment['start']<segment['end']<=seconds+.01,
                'TRANSCRIPTION_FAILED','转写时间段无效')
        require(isinstance(segment['text'],str) and 0<len(segment['text'].strip())<=4000,'TRANSCRIPTION_FAILED','转写文字无效')
        previous=segment['end']
    text='本地机器转写，尚未人工核对；时间为音轨分段范围，不代表精确逐字对齐。\n'+ '\n'.join(
        f"[{s['start']:.2f}s–{s['end']:.2f}s] {s['text']}" for s in segments)
    return {'payload':{'account_id':account_id,'title':title.strip(),'text':text,
            'platform':platform,'content_kind':'transcript','evidence_role':'expression_reference',
            'permission_confirmed':True},
            'segments':segments,'provenance':{'source_sha256':hashlib.sha256(data).hexdigest(),
            'bytes':len(data),'duration_seconds':seconds,'model_id':MODEL_ID,'revision':REVISION,
            'method':'local_whisper_audio_only','verification':'machine_transcript_unverified'}}


def _worker(path):
    import numpy as np
    import torch
    from transformers import WhisperProcessor, WhisperForConditionalGeneration
    torch.set_num_threads(2)
    processor=WhisperProcessor.from_pretrained(str(MODEL_PATH),local_files_only=True)
    model=WhisperForConditionalGeneration.from_pretrained(str(MODEL_PATH),local_files_only=True,
                     use_safetensors=True,trust_remote_code=False).to('cpu').eval()
    audio=np.fromfile(path,dtype='<f4');segments=[]
    with torch.inference_mode():
        for start in range(0,len(audio),30*SAMPLE_RATE):
            chunk=audio[start:start+30*SAMPLE_RATE]
            if float(np.sqrt(np.mean(chunk**2)))<.0001:continue
            features=processor(chunk,sampling_rate=SAMPLE_RATE,return_tensors='pt')
            ids=model.generate(features.input_features,language='zh',task='transcribe',max_new_tokens=440,
                               do_sample=False,return_timestamps=False)
            if int(ids[0,-1]) != model.generation_config.eos_token_id:
                raise RuntimeError('Transcription output truncated')
            text=processor.batch_decode(ids,skip_special_tokens=True)[0].strip()
            if text:segments.append({'start':start/SAMPLE_RATE,'end':(start+len(chunk))/SAMPLE_RATE,'text':text})
    print(json.dumps(segments,ensure_ascii=False))


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--worker':_worker(sys.argv[2])
    else:raise SystemExit('Internal worker only')
