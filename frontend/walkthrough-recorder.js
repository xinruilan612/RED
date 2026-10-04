'use strict';
(function () {
  const start = document.getElementById('startRecording');
  const stop = document.getElementById('stopRecording');
  const download = document.getElementById('downloadRecording');
  const status = document.getElementById('recordingStatus');
  const timer = document.getElementById('recordingTimer');
  let recorder = null, stream = null, chunks = [], interval = null, startedAt = 0, objectUrl = null, pending = false;
  function message(text) { status.textContent = text; }
  function releaseStream() { if (stream) stream.getTracks().forEach(track => track.stop()); stream = null; }
  function finish() {
    clearInterval(interval); interval = null; releaseStream();
    document.body.classList.remove('recording'); start.disabled = false; stop.disabled = true;
    if (!chunks.length) { message('没有录到画面。请重新开始，并在浏览器弹窗中选择当前标签页。'); return; }
    const blob = new Blob(chunks, {type: recorder.mimeType || 'video/webm'});
    objectUrl = URL.createObjectURL(blob);
    download.href = objectUrl;
    download.download = 'youji-real-walkthrough-' + new Date().toISOString().replace(/[:.]/g, '-') + '.webm';
    download.hidden = false;
    message('录制已结束，点击“下载录屏”保存真实视频。下载前请不要刷新或关闭此页。');
  }
  function stopRecording() {
    if (recorder && recorder.state !== 'inactive') recorder.stop();
  }
  async function startRecording() {
    if (pending || (recorder && recorder.state !== 'inactive')) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia || typeof MediaRecorder === 'undefined') {
      message('此浏览器不支持网页录屏，请使用最新版 Chrome，通过 localhost 或 HTTPS 打开。'); return;
    }
    pending = true; start.disabled = true;
    message('请在浏览器弹窗中选择当前“有迹 · 真实操作录屏”标签页，然后点击共享。');
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({video: {frameRate: {ideal: 15, max: 30}}, audio: false, preferCurrentTab: true, selfBrowserSurface: 'include', surfaceSwitching: 'exclude'});
      const mimeType = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(type => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw new Error('WEBM_UNSUPPORTED');
      recorder = new MediaRecorder(stream, {mimeType, videoBitsPerSecond: 2500000});
      if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = null; }
      download.hidden = true; chunks = []; timer.textContent = '00:00';
      recorder.ondataavailable = event => { if (event.data && event.data.size) chunks.push(event.data); };
      recorder.onstop = finish;
      recorder.onerror = () => { message('录制出现问题，正在保存已经录下的画面。'); stopRecording(); };
      stream.getVideoTracks().forEach(track => track.addEventListener('ended', stopRecording));
      recorder.start(1000); startedAt = Date.now();
      interval = setInterval(() => {
        const seconds = Math.floor((Date.now() - startedAt) / 1000);
        timer.textContent = String(Math.floor(seconds / 60)).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
      }, 500);
      stop.disabled = false; document.body.classList.add('recording');
      message('正在录制真实画面。请在下方操作网站；完成后点击“停止并生成视频”。');
    } catch (error) {
      releaseStream(); start.disabled = false; stop.disabled = true;
      message(error.name === 'NotAllowedError' || error.name === 'AbortError' ? '已取消录屏或未获得权限。点击开始可重新选择，网站操作不受影响。' : '无法开始录屏。请检查浏览器和系统的屏幕录制权限，再使用 Chrome 重试。');
    } finally { pending = false; }
  }
  start.addEventListener('click', startRecording);
  stop.addEventListener('click', stopRecording);
  window.addEventListener('beforeunload', event => {
    if (pending || (recorder && recorder.state !== 'inactive') || objectUrl) { event.preventDefault(); event.returnValue = ''; }
  });
}());
