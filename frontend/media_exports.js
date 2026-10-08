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
  const editor=mediaEditorFor(run);
  let result;const exportRevision=editor?.revision;
  if(editor){
   if(editor.uploading||!editor.preview||editor.previewRevision!==editor.revision){status.textContent='请先预览当前图卡样式，再下载成品包。';editor.section?.scrollIntoView?.({block:'start',behavior:'smooth'});editor.previewButton?.focus();return false;}
   result=await fetch(`/api/runs/${encodeURIComponent(run.run_id)}/media-export`,{method:'POST',credentials:'same-origin',headers:mediaHeaders(),body:JSON.stringify({...mediaRequest(editor),kind,design_hash:editor.preview.design_hash})});
  }else result=await fetch(`/api/runs/${encodeURIComponent(run.run_id)}/media-export?kind=${encodeURIComponent(kind)}`,{credentials:'same-origin'});
  if(!result.ok){let message='制作失败，请重试';try{const data=await result.json();message=data.error?.message||data.detail?.message||data.message||message;}catch{}throw new Error(message);}
  const blob=await result.blob();
  if(editor&&(editor.revision!==exportRevision||editor.host._mediaKey!==editor.key)){status.textContent='设置或稿件已切换，请预览当前版本后重新下载。';return false;}
  const url=URL.createObjectURL(blob),a=document.createElement('a');
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
async function mountLegacyMediaExports(run, container) {
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
  const choices=[['complete','下载全部成品包',caps.complete_available]];
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

const mediaEditors=new Map();
function mediaDraft(run){return (run.drafts||[]).find(d=>d.ref===run.accepted_ref);}
function mediaKey(run){const d=mediaDraft(run);return d?`${run.run_id}:${d.ref}:${d.content_hash}`:null;}
function mediaEditorFor(run){return mediaEditors.get(mediaKey(run));}
function mediaHeaders(){return {'Content-Type':'application/json','X-CSRF-Token':typeof csrf==='undefined'?'':csrf};}
function mediaRequest(e){return {template:e.template,options:{page_styles:e.styles,...(e.productPhoto==='none'?{product_photo:'none'}:{}),...(e.cover?{cover_image:e.cover}:{})},draft_ref:e.draft.ref,content_hash:e.draft.content_hash};}
function mediaElement(tag,text,cls){const node=document.createElement(tag);if(text)node.textContent=text;if(cls)node.className=cls;return node;}
function mediaValidStyles(value){
 if(!value||typeof value!=='object'||Array.isArray(value))return {};
 const styles={};for(const [key,item] of Object.entries(value)){if(!/^(0|[1-9]\d*)$/.test(key)||Number(key)>99||!item||typeof item!=='object'||Array.isArray(item))continue;
 if(!['normal','large'].includes(item.size)||!['green','orange','blue'].includes(item.accent))continue;styles[key]={size:item.size,accent:item.accent};}return styles;
}
function mediaSave(e){try{localStorage.setItem(`youji-media:${e.key}`,JSON.stringify({template:e.template,styles:e.styles,productPhoto:e.productPhoto}));}catch{}}
function mediaInvalidate(e){e.revision++;e.status.textContent='样式已修改，请重新预览后下载。';mediaSave(e);mediaSync(e);}
function mediaSync(e){
 const ready=!!e.preview&&e.previewRevision===e.revision;
 e.previewButton.disabled=e.loading||e.uploading;e.previewButton.textContent=e.loading?'正在排版…':ready?'重新预览':'预览图卡';
 e.downloadButtons.forEach(b=>b.disabled=!ready||e.loading||e.uploading||mediaDownloadsInFlight.has(e.run.run_id));
 e.stale.hidden=!e.preview||ready;
}
async function mediaPreview(e){
 if(e.loading||e.uploading)return false;
 const revision=e.revision,request=mediaRequest(e);e.loading=true;mediaSync(e);e.status.textContent='正在排版图卡…';
 try{
  const response=await fetch(`/api/runs/${encodeURIComponent(e.run.run_id)}/media-preview`,{method:'POST',credentials:'same-origin',headers:mediaHeaders(),body:JSON.stringify(request)});
  const data=await response.json();if(!response.ok)throw new Error(data.error?.message||data.detail?.message||data.message||'预览失败，请重试');
  if(revision!==e.revision||e.host._mediaKey!==e.key)return false;
  if(data.draft_ref!==e.draft.ref||data.content_hash!==e.draft.content_hash||!data.design_hash||!data.pages?.length)throw new Error('预览版本不一致，请重新预览');
  e.preview=data;e.previewRevision=revision;e.page=Math.min(e.page,data.pages.length-1);mediaShowPages(e);e.clearPhoto.hidden=!(e.cover||data.product_photo||e.productPhoto==='none');e.clearPhoto.textContent=e.productPhoto==='none'?'使用匹配产品图':'移除产品图';e.status.textContent=`共 ${data.pages.length} 张，预览即导出样式。可选择一张图调整字号或强调色。`+(data.product_photo?` 图片：${data.product_photo.name} · ${data.product_photo.author} · ${data.product_photo.license}，完整来源见成品包。`:e.cover?' 已使用你上传的产品图。':' 当前没有产品图片，可上传真实产品图。');return true;
 }catch(error){if(revision===e.revision&&e.host._mediaKey===e.key)e.status.textContent=error.message;return false;}
 finally{e.loading=false;mediaSync(e);}
}
function mediaShowPages(e){
 e.thumbs.replaceChildren();e.preview.pages.forEach((page,index)=>{
  const b=mediaElement('button',null,'media-thumb');b.type='button';b.setAttribute('aria-label',`查看第 ${index+1} 张`);b.setAttribute('aria-pressed',String(index===e.page));
  const img=mediaElement('img');img.src=page.data_url;img.alt=`第 ${index+1} 张缩略图`;b.append(img,mediaElement('span',`${index+1}`));b.onclick=()=>{e.page=index;mediaShowPages(e);};e.thumbs.append(b);
 });
 const page=e.preview.pages[e.page];e.large.src=page.data_url;e.large.alt=`第 ${e.page+1} 张图卡预览`;e.workspace.hidden=false;e.pageLabel.textContent=`仅调整第 ${e.page+1} 张`;
 const style=e.styles[String(e.page)]||{};e.size.value=style.size||'normal';e.accent.value=style.accent||'green';e.notice.textContent=page.notice||'';
}
function mediaSelect(label,choices){const wrap=mediaElement('label',label),select=mediaElement('select');for(const [value,text] of choices){const opt=mediaElement('option',text);opt.value=value;select.append(opt);}wrap.append(select);return [wrap,select];}
async function mountMediaExports(run,container){
 if(run.workflow_type!=='creation'||run.run_status!=='SUCCEEDED'||!run.accepted_ref){container._mediaKey=null;container.replaceChildren();return;}
 const key=mediaKey(run);if(!key)return mountLegacyMediaExports(run,container);
 let e=mediaEditors.get(key);
 if(container._mediaKey===key&&e?.section){e.run=run;mediaSync(e);return;}
 container._mediaKey=key;container.replaceChildren();
 if(e){e.run=run;e.host=container;container.append(e.section);mediaSync(e);return;}
 let saved={};try{saved=JSON.parse(localStorage.getItem(`youji-media:${key}`)||'{}');}catch{}
 if(!saved||typeof saved!=='object'||Array.isArray(saved))saved={};
 e={key,run,draft:mediaDraft(run),host:container,template:['classic','checklist'].includes(saved.template)?saved.template:'classic',styles:mediaValidStyles(saved.styles),revision:0,previewRevision:-1,page:0,loading:false,preview:null,downloadButtons:[],cover:'',productPhoto:saved.productPhoto==='none'?'none':'auto'};mediaEditors.set(key,e);
 const section=mediaElement('section',null,'media-exports panel');e.section=section;
 section.append(mediaElement('h3','图卡预览与下载'),mediaElement('p','选择版式，逐张检查。只调整图片排版，不改动已确认文案。','media-editor-summary'));
 const controls=mediaElement('div',null,'media-editor-controls');
 const [templateLabel,template]=mediaSelect('图卡风格',[['classic','清爽杂志'],['checklist','重点清单']]);template.value=e.template;template.onchange=()=>{e.template=template.value;mediaInvalidate(e);};controls.append(templateLabel);
 const photoLabel=mediaElement('label','替换产品实拍图（可选）'),photo=mediaElement('input');photo.type='file';photo.accept='image/png,image/jpeg';photoLabel.append(photo);controls.append(photoLabel);
 const clear=mediaElement('button','移除产品图','secondary');clear.type='button';clear.hidden=e.productPhoto!=='none';clear.textContent=e.productPhoto==='none'?'使用匹配产品图':'移除产品图';e.clearPhoto=clear;clear.onclick=()=>{e.uploadToken=(e.uploadToken||0)+1;e.cover='';e.productPhoto=e.productPhoto==='none'?'auto':'none';e.uploading=false;photo.value='';clear.hidden=false;clear.textContent=e.productPhoto==='none'?'使用匹配产品图':'移除产品图';mediaInvalidate(e);};controls.append(clear);
 photo.onchange=()=>{const file=photo.files?.[0];if(!file)return;const token=e.uploadToken=(e.uploadToken||0)+1;
  if(!['image/png','image/jpeg'].includes(file.type)||file.size>3*1024*1024){e.status.textContent='请选择不超过 3 MB 的 PNG 或 JPEG 产品图。';photo.value='';return;}
  e.uploading=true;mediaInvalidate(e);e.status.textContent='正在读取产品图…';const reader=new FileReader();reader.onload=()=>{if(token!==e.uploadToken)return;e.uploading=false;e.cover=reader.result;e.productPhoto='auto';clear.hidden=false;mediaInvalidate(e);};reader.onerror=()=>{if(token!==e.uploadToken)return;e.uploading=false;e.status.textContent='图片读取失败，请重新选择。';mediaSync(e);};reader.readAsDataURL(file);
 };
 e.previewButton=mediaElement('button','预览图卡','primary');e.previewButton.type='button';e.previewButton.onclick=()=>mediaPreview(e);controls.append(e.previewButton);const reset=mediaElement('button','恢复默认排版（保留产品图）','secondary');reset.type='button';reset.onclick=()=>{e.template='classic';template.value='classic';e.styles={};e.page=0;if(e.preview)mediaShowPages(e);mediaInvalidate(e);};controls.append(reset);section.append(controls,mediaElement('p','实拍图按型号匹配，每页使用不同图片；图片用完后，后页只排文案。上传单图仅用于封面，刷新后需重新选择。','media-editor-hint'));
 e.status=mediaElement('p','先预览，再下载。无需调用 AI。','media-export-status');e.status.setAttribute('aria-live','polite');section.append(e.status);
 e.stale=mediaElement('p','下方是上次预览，尚未应用新设置。','media-preview-stale');e.stale.hidden=true;section.append(e.stale);
 const workspace=mediaElement('div',null,'media-preview-workspace');e.workspace=workspace;workspace.hidden=true;
 e.thumbs=mediaElement('div',null,'media-preview-thumbs');e.thumbs.setAttribute('aria-label','图卡列表');const main=mediaElement('div',null,'media-preview-main');e.large=mediaElement('img');main.append(e.large);
 const pageTools=mediaElement('div',null,'media-page-tools');e.pageLabel=mediaElement('strong');pageTools.append(e.pageLabel);
 const [sizeLabel,size]=mediaSelect('字号',[['normal','标准'],['large','稍大']]),[accentLabel,accent]=mediaSelect('强调色',[['green','森林绿'],['orange','暖橙'],['blue','深蓝']]);e.size=size;e.accent=accent;pageTools.append(sizeLabel,accentLabel);e.notice=mediaElement('p',null,'media-editor-hint');pageTools.append(e.notice);
 const change=()=>{e.styles[String(e.page)]={size:size.value,accent:accent.value};mediaInvalidate(e);};size.onchange=change;accent.onchange=change;
 workspace.append(e.thumbs,main,pageTools);section.append(workspace);
 const buttons=mediaElement('div',null,'media-export-buttons');for(const [kind,label] of [['complete','下载全部成品包']]){
  const button=mediaElement('button',label,kind==='complete'?'primary media-export-primary':'secondary');button.type='button';button.disabled=true;button.onclick=async()=>{try{await downloadMediaBundle(e.run,kind,button,e.status);}finally{mediaSync(e);}};e.downloadButtons.push(button);buttons.append(button);
 }section.append(buttons);container.append(section);mediaSync(e);
}
