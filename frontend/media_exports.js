'use strict';
const mediaDownloadsInFlight=new Set();
async function downloadMediaBundle(run,kind,button,status){
 if(run.workflow_type!=='creation'||run.run_status!=='SUCCEEDED'||!run.accepted_ref){
  status.textContent='请先确认当前稿件，再下载成品包。';return false;
 }
 if(mediaDownloadsInFlight.has(run.run_id))return false;
 mediaDownloadsInFlight.add(run.run_id);
 const wasDisabled=button.disabled;button.disabled=true;
 status.textContent=(kind==='video'||kind==='complete')?'正在生成视频，请稍等，通常需要十几秒…':'正在制作成品…';
 try{
  const result=await fetch(`/api/runs/${encodeURIComponent(run.run_id)}/media-export?kind=${encodeURIComponent(kind)}`,{credentials:'same-origin'});
  if(!result.ok){let message='制作失败，请重试';try{const data=await result.json();message=data.error?.message||data.detail?.message||data.message||message;}catch{}throw new Error(message);}
  const blob=await result.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download=`youji-${kind}-${run.run_id.slice(0,8)}.zip`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
  status.textContent=kind==='complete'?'完整成品包已下载。先看使用说明.txt；缺少的媒体会有明确说明。':'已下载。解压后可预览成品，caption.txt 是配套发布文案。';
  return true;
 }catch(error){status.textContent=error.message;return false;}
 finally{mediaDownloadsInFlight.delete(run.run_id);button.disabled=wasDisabled;}
}
async function downloadCompleteBundle(run,button,status){
 return downloadMediaBundle(run,'complete',button,status);
}
// Mount into the confirmed draft screen; all downloads use authenticated endpoints.
async function mountMediaExports(run, container) {
 container.replaceChildren();
 if(run.workflow_type!=='creation'||run.run_status!=='SUCCEEDED'||!run.accepted_ref)return;
 const section=document.createElement('section');section.className='media-exports panel';
 const title=document.createElement('h3');title.textContent='下一步：下载发布前成品';
 const summary=document.createElement('p');summary.textContent='一次下载文案、图片、无声视频和字幕。本机排版，不额外调用模型。';
 const status=document.createElement('p');status.className='media-export-status';status.textContent='正在检查导出工具…';status.setAttribute('aria-live','polite');
 const buttons=document.createElement('div');buttons.className='media-export-buttons';
 section.append(title,summary,buttons,status);container.append(section);
 try {
  const response=await fetch(`/api/runs/${encodeURIComponent(run.run_id)}/media/capabilities`,{credentials:'same-origin'});
  if(!response.ok)throw new Error('导出工具暂不可用，请刷新后重试');
  const caps=await response.json();
  const choices=[['complete','下载全部成品包',caps.complete_available],['images','下载图文包',caps.images_available],['video','下载无声图文视频',caps.video_available],['storyboard','下载分镜与字幕',caps.storyboard_available]];
  for(const [kind,label,available] of choices){
   const button=document.createElement('button');button.textContent=label;button.className=kind==='complete'?'primary media-export-primary':'secondary';button.disabled=!available;
   button.addEventListener('click',async()=>{
    buttons.querySelectorAll('button').forEach(b=>b.disabled=true);
    try{await downloadMediaBundle(run,kind,button,status);}
    finally{buttons.querySelectorAll('button').forEach((b,i)=>b.disabled=!choices[i][2]);}
   });buttons.append(button);
  }
  status.textContent=caps.video_message+' 图文包包含封面、完整正文图片和发布文案；不含自动生成插画。';
 }catch(error){status.textContent=error.message;}
}
