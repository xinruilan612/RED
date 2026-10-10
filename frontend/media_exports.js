'use strict';
const mediaDownloadsInFlight=new Set();
async function downloadMediaBundle(run,kind,button,status){
 if(run.workflow_type!=='creation'||run.run_status!=='SUCCEEDED'||!run.accepted_ref){
  status.textContent='请先确认当前稿件，再下载成品包。';return false;
 }
 const studio=studioEditorFor(run);if(studio)return studioDownload(studio,kind,button,status);
 if(mediaDownloadsInFlight.has(run.run_id))return false;
 mediaDownloadsInFlight.add(run.run_id);
 const wasDisabled=button.disabled;button.disabled=true;
 status.textContent=(kind==='video'||kind==='complete')?'正在生成视频，请稍等，通常需要十几秒…':'正在制作成品…';
 try{
  const editor=mediaEditorFor(run);
  let result;let exportRevision=editor?.revision;
  if(editor){
   if(editor.uploading||editor.loading||editor.selecting||editor.adjusting){status.textContent='正在处理图片，请稍等后再下载。';return false;}
   if(!editor.preview||editor.previewRevision!==editor.revision){
    status.textContent='正在应用当前排版并准备下载…';
    if(!await mediaPreview(editor)){status.textContent=editor.status.textContent;return false;}
   }
   if(editor.host._mediaKey!==editor.key||editor.previewRevision!==editor.revision)return false;
   exportRevision=editor.revision;
   status.textContent=kind==='complete'?'正在打包文案、图片和视频，请稍等…':'正在制作成品…';
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
 finally{mediaDownloadsInFlight.delete(run.run_id);button.disabled=wasDisabled;const editor=mediaEditorFor(run);if(editor)mediaSync(editor);}
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
function mediaRequest(e){return {template:e.template,options:{global_style:{size:'normal',accent:'default'},...(e.productPhoto==='none'?{product_photo:'none'}:{}),...(e.cover?{cover_image:e.cover}:{}),...(e.layoutPlan?{layout_plan:e.layoutPlan}:{})},draft_ref:e.draft.ref,content_hash:e.draft.content_hash};}
function mediaElement(tag,text,cls){const node=document.createElement(tag);if(text)node.textContent=text;if(cls)node.className=cls;return node;}
function mediaSave(e){try{localStorage.setItem(`youji-media:${e.key}`,JSON.stringify({template:e.template,productPhoto:e.productPhoto,layoutPlan:e.cover?null:e.layoutPlan,coverPlanNotSaved:!!(e.cover&&e.layoutPlan)}));}catch{}}
function mediaInvalidate(e){mediaClearProposal(e);e.revision++;e.status.textContent='样式已修改。可重新预览，也可直接下载，系统会先应用新设置。';mediaSave(e);mediaSync(e);}
function mediaSync(e){
 const ready=!!e.preview&&e.previewRevision===e.revision;
 const busy=e.loading||e.uploading||e.selecting||e.adjusting||mediaDownloadsInFlight.has(e.run.run_id);
 if(e.adjustButton){e.adjustButton.disabled=busy||!ready;e.feedback.disabled=busy;e.adjustButton.textContent=e.adjusting?'正在生成修改预览…':'让 AI 看图并预览';}
 if(e.photoInput)e.photoInput.disabled=busy;
 if(e.clearPhoto)e.clearPhoto.disabled=busy;
 if(e.thumbs)e.thumbs.children&&Array.from(e.thumbs.children).forEach(b=>b.disabled=busy);
 e.previewButton.disabled=e.loading||e.uploading||e.selecting||e.adjusting||mediaDownloadsInFlight.has(e.run.run_id);e.previewButton.textContent=e.loading?'正在排版…':ready?'重新预览':'预览图卡';
 e.downloadButtons.forEach(b=>b.disabled=!e.catalogReady||e.loading||e.uploading||e.selecting||e.adjusting||mediaDownloadsInFlight.has(e.run.run_id));
 e.stale.hidden=!e.preview||ready;
 if(e.templateButtons)e.templateButtons.forEach(b=>{b.disabled=e.loading||e.uploading||e.selecting||e.adjusting||mediaDownloadsInFlight.has(e.run.run_id);b.setAttribute('aria-pressed',String(b.datasetTemplate===e.template));});
 if(e.nextTemplate)e.nextTemplate.disabled=e.loading||e.uploading||e.selecting||e.adjusting||mediaDownloadsInFlight.has(e.run.run_id);
}
async function mediaPreview(e){
 if(e.loading||e.uploading||e.selecting||e.adjusting)return false;
 if(!e.catalogReady){e.status.textContent='模板库尚未就绪，请刷新后重试。';return false;}
 const revision=e.revision,request=mediaRequest(e);e.loading=true;mediaSync(e);e.status.textContent='正在排版图卡…';
 try{
  const response=await fetch(`/api/runs/${encodeURIComponent(e.run.run_id)}/media-preview`,{method:'POST',credentials:'same-origin',headers:mediaHeaders(),body:JSON.stringify(request)});
  const data=await response.json();if(!response.ok)throw new Error(data.error?.message||data.detail?.message||data.message||'预览失败，请重试');
  if(revision!==e.revision||e.host._mediaKey!==e.key)return false;
  if(data.draft_ref!==e.draft.ref||data.content_hash!==e.draft.content_hash||!data.design_hash||!data.pages?.length)throw new Error('预览版本不一致，请重新预览');
  e.preview=data;e.previewRevision=revision;e.page=Math.min(e.page,data.pages.length-1);mediaShowPages(e);e.clearPhoto.hidden=!(e.cover||data.product_photo||e.productPhoto==='none');e.clearPhoto.textContent=e.productPhoto==='none'?'使用匹配产品图':'移除产品图';e.status.textContent=`共 ${data.pages.length} 张，预览即导出样式。使用模板原有配色和标准字号。`+(data.product_photo?` 图片：${data.product_photo.name} · ${data.product_photo.author} · ${data.product_photo.license}，完整来源见成品包。`:e.cover?' 已使用你上传的产品图。':' 当前没有产品图片，可上传真实产品图。');return true;
 }catch(error){if(revision===e.revision&&e.host._mediaKey===e.key)e.status.textContent=error.message;return false;}
 finally{e.loading=false;mediaSync(e);}
}
function mediaShowPages(e){
 e.thumbs.replaceChildren();e.preview.pages.forEach((page,index)=>{
  const b=mediaElement('button',null,'media-thumb');b.type='button';b.setAttribute('aria-label',`查看第 ${index+1} 张`);b.setAttribute('aria-pressed',String(index===e.page));
  const img=mediaElement('img');img.src=page.data_url;img.alt=`第 ${index+1} 张缩略图`;b.append(img,mediaElement('span',`${index+1}`));b.onclick=()=>{if(e.adjusting||e.loading||e.selecting||mediaDownloadsInFlight.has(e.run.run_id))return;mediaClearProposal(e);e.page=index;mediaShowPages(e);};e.thumbs.append(b);
 });
 if(e.adjustTitle)e.adjustTitle.textContent=`调整第 ${e.page+1} 张`;
 const page=e.preview.pages[e.page];e.large.src=page.data_url;e.large.alt=`第 ${e.page+1} 张图卡预览`;e.workspace.hidden=false;e.notice.textContent=page.notice||'';e.notice.hidden=!page.notice;
}
function mediaClearProposal(e){e.proposal=null;if(e.proposalArea){e.proposalArea.replaceChildren();e.proposalArea.hidden=true;}}
async function mediaAdjustPreview(e){
 if(e.adjusting||e.loading||e.uploading||e.selecting||mediaDownloadsInFlight.has(e.run.run_id))return false;
 if(!e.preview||e.previewRevision!==e.revision){e.status.textContent='请先预览当前模板，再提出排版调整。';return false;}
 const feedback=(e.feedback.value||'').trim();if(!feedback){e.status.textContent='请填写这一页的排版要求。';e.feedback.focus();return false;}
 const revision=e.revision,page=e.page,original=e.preview;mediaClearProposal(e);e.adjusting=true;mediaSync(e);e.status.textContent='正在生成排版提案，当前成品保持不变…';
 try{
  const response=await fetch(`/api/runs/${encodeURIComponent(e.run.run_id)}/media-adjust-preview`,{method:'POST',credentials:'same-origin',headers:mediaHeaders(),body:JSON.stringify({...mediaRequest(e),design_hash:original.design_hash,page_index:page,feedback})});
  const data=await response.json();if(!response.ok)throw new Error(data.error?.message||data.detail?.message||data.message||'排版调整失败，请重试');
  if(e.host._mediaKey!==e.key||revision!==e.revision||page!==e.page||original!==e.preview)return false;
  const preview=data.preview;if(data.mode!=='local_vision'||!preview?.pages?.length||!preview.design_hash||preview.draft_ref!==e.draft.ref||preview.content_hash!==e.draft.content_hash||!data.options?.layout_plan)throw new Error('修改预览与当前稿件不一致，请重试');
  const afterIndices=data.after_page_indices;if(!Array.isArray(afterIndices)||!afterIndices.length||afterIndices.some(i=>!Number.isInteger(i)||i<0||i>=preview.pages.length))throw new Error('修改预览缺少有效页码，请重试');
  e.proposal={data,revision,page,original};const area=e.proposalArea;area.hidden=false;area.append(mediaElement('p',data.summary||'排版提案已生成，采用后才会用于下载。'));if(data.observation)area.append(mediaElement('p',`AI 看到：${data.observation}`,'media-editor-hint'));if(data.model)area.append(mediaElement('p',`本地模型：${data.model}`,'media-editor-hint'));
  const comparison=mediaElement('div',null,'media-adjust-comparison');for(const [label,pages] of [['修改前',[original.pages[page]]],['修改后',afterIndices.map(i=>preview.pages[i])]]){const column=mediaElement('div');column.append(mediaElement('strong',label));for(const [index,item] of pages.entries()){const img=mediaElement('img');img.src=item.data_url;img.alt=`${label}第 ${index+1} 张`;column.append(img);}comparison.append(column);}area.append(comparison);
  const accept=mediaElement('button','采用这次排版','primary');accept.type='button';accept.onclick=()=>mediaAcceptAdjustment(e);const cancel=mediaElement('button','取消','secondary');cancel.type='button';cancel.onclick=()=>{mediaClearProposal(e);e.status.textContent='已取消，保留原排版。';};area.append(accept,cancel);area.scrollIntoView?.({behavior:'smooth',block:'start'});e.status.textContent='请比较修改前后；点击“采用这次排版”后才更新成品。';return true;
 }catch(error){if(e.host._mediaKey===e.key&&revision===e.revision)e.status.textContent=error.message;return false;}
 finally{e.adjusting=false;mediaSync(e);}
}
function mediaAcceptAdjustment(e){
 const p=e.proposal;if(!p||e.adjusting||e.host._mediaKey!==e.key||p.revision!==e.revision||p.page!==e.page||p.original!==e.preview){mediaClearProposal(e);return false;}
 e.layoutPlan=p.data.options.layout_plan;e.preview=p.data.preview;e.revision++;e.previewRevision=e.revision;e.page=Math.min(e.page,e.preview.pages.length-1);mediaClearProposal(e);mediaSave(e);mediaShowPages(e);mediaSync(e);e.workspace.scrollIntoView?.({behavior:'smooth',block:'start'});e.status.textContent='已采用这次排版，可以下载全部成品包。确认稿文字保持不变。'+(e.cover?' 自定义封面及其排版仅保留在本次页面，刷新后需重新上传并调整。':'');return true;
}
async function mediaTemplateSelection(e,action,templateId){
 const response=await fetch(`/api/runs/${encodeURIComponent(e.run.run_id)}/media/template-next`,{method:'POST',credentials:'same-origin',headers:mediaHeaders(),body:JSON.stringify({action,...(templateId?{template_id:templateId}:{}),draft_ref:e.draft.ref,content_hash:e.draft.content_hash,idempotency_key:`template-${Date.now()}-${Math.random().toString(36).slice(2)}`})});
 const data=await response.json();if(!response.ok)throw new Error(data.error?.message||data.detail?.message||'模板选择失败，请重试');
 if(data.draft_ref!==e.draft.ref||data.content_hash!==e.draft.content_hash||!e.templates.some(t=>t.id===data.template_id))throw new Error('模板与确认稿不一致，请刷新后重试');
 return data;
}
async function mediaChooseTemplate(e,action,templateId){
 if(e.selecting||e.loading||e.uploading||e.adjusting||mediaDownloadsInFlight.has(e.run.run_id))return false;
 e.selecting=true;mediaSync(e);e.status.textContent='正在切换模板…';
 try{
  const selected=await mediaTemplateSelection(e,action,templateId);
  if(e.host._mediaKey!==e.key)return false;
  e.template=selected.template_id;e.layoutPlan=null;e.page=0;mediaInvalidate(e);
 }catch(error){e.status.textContent=error.message;return false;}
 finally{e.selecting=false;mediaSync(e);}
 return mediaPreview(e);
}
async function mediaLoadTemplates(e){
 e.selecting=true;mediaSync(e);
 try{
  const response=await fetch(`/api/media/templates?run_id=${encodeURIComponent(e.run.run_id)}`,{credentials:'same-origin'});
  const data=await response.json();if(!response.ok||!Array.isArray(data.templates)||!data.templates.length)throw new Error('模板库加载失败，请刷新后重试');
  if(data.available===false)throw new Error('图卡排版服务尚未就绪，请稍后重试。');
  e.templates=data.templates;
  const selected=data.selection||await mediaTemplateSelection(e,'init');
  if(selected.draft_ref!==e.draft.ref||selected.content_hash!==e.draft.content_hash||!e.templates.some(t=>t.id===selected.template_id))throw new Error('模板与确认稿不一致，请刷新后重试');
  e.template=selected.template_id;e.layoutPlan=e.savedTemplate===e.template?e.savedLayoutPlan:null;e.savedLayoutPlan=null;e.catalogReady=true;
  const picker=mediaElement('div',null,'media-template-picker');picker.append(mediaElement('strong','选择整套模板'));
  const grid=mediaElement('div',null,'media-template-grid');e.templateButtons=[];
  for(const template of e.templates){
   const button=mediaElement('button',null,'media-template-choice');button.type='button';button.datasetTemplate=template.id;button.setAttribute('aria-label',`使用${template.name}模板`);
   const img=mediaElement('img');img.src=template.thumbnail_url;img.alt=`${template.name}模板示例`;img.loading='lazy';button.append(img,mediaElement('span',template.name));button.onclick=()=>mediaChooseTemplate(e,'select',template.id);grid.append(button);e.templateButtons.push(button);
  }
  picker.append(grid);e.nextTemplate=mediaElement('button','换一套 →','secondary');e.nextTemplate.type='button';e.nextTemplate.onclick=()=>mediaChooseTemplate(e,'next');picker.append(e.nextTemplate,mediaElement('p','点击模板即可预览；换一套按顺序轮换。当前选择会保存，刷新不会随机更换。','media-editor-hint'));
  e.templateArea.append(picker);mediaSave(e);if(e.coverPlanNotSaved)e.status.textContent='上次使用了自定义封面，刷新后已恢复匹配图片和默认排版；如需沿用，请重新上传封面并调整。';
 }catch(error){e.status.textContent=error.message;}
 finally{e.selecting=false;mediaSync(e);}
}

async function mountClassicMediaExports(run,container){
 if(run.workflow_type!=='creation'||run.run_status!=='SUCCEEDED'||!run.accepted_ref){container._mediaKey=null;container.replaceChildren();return;}
 const key=mediaKey(run);if(!key)return mountLegacyMediaExports(run,container);
 let e=mediaEditors.get(key);
 if(container._mediaKey===key&&e?.section){e.run=run;mediaSync(e);return;}
 container._mediaKey=key;container.replaceChildren();
 if(e){e.run=run;e.host=container;container.append(e.section);mediaSync(e);return;}
 let saved={};try{saved=JSON.parse(localStorage.getItem(`youji-media:${key}`)||'{}');}catch{}
 if(!saved||typeof saved!=='object'||Array.isArray(saved))saved={};
 e={key,run,draft:mediaDraft(run),host:container,template:'xhs-e',revision:0,previewRevision:-1,page:0,loading:false,preview:null,downloadButtons:[],cover:'',productPhoto:saved.productPhoto==='none'?'none':'auto',coverPlanNotSaved:!!saved.coverPlanNotSaved,savedTemplate:saved.template,savedLayoutPlan:saved.coverPlanNotSaved?null:saved.layoutPlan,layoutPlan:null,adjusting:false};mediaEditors.set(key,e);
 const section=mediaElement('section',null,'media-exports panel');e.section=section;
 section.append(mediaElement('h3','图卡预览与下载'),mediaElement('p','选择喜欢的模板，逐张检查后下载。不改动已确认文案。','media-editor-summary'));
 const controls=mediaElement('div',null,'media-editor-controls');

 const photoLabel=mediaElement('label','替换封面照片（可选，不上传也可使用匹配图片）'),photo=mediaElement('input');e.photoInput=photo;photo.type='file';photo.accept='image/png,image/jpeg';photoLabel.append(photo);controls.append(photoLabel);
 const clear=mediaElement('button','移除产品图','secondary');clear.type='button';clear.hidden=e.productPhoto!=='none';clear.textContent=e.productPhoto==='none'?'使用匹配产品图':'移除产品图';e.clearPhoto=clear;clear.onclick=()=>{if(e.adjusting)return;e.layoutPlan=null;e.uploadToken=(e.uploadToken||0)+1;e.cover='';e.productPhoto=e.productPhoto==='none'?'auto':'none';e.uploading=false;photo.value='';clear.hidden=false;clear.textContent=e.productPhoto==='none'?'使用匹配产品图':'移除产品图';mediaInvalidate(e);};controls.append(clear);
 photo.onchange=()=>{if(e.adjusting)return;const file=photo.files?.[0];if(!file)return;
  if(!['image/png','image/jpeg'].includes(file.type)||file.size>3*1024*1024){e.status.textContent='请选择不超过 3 MB 的 PNG 或 JPEG 产品图。';photo.value='';return;}
  const token=e.uploadToken=(e.uploadToken||0)+1;e.layoutPlan=null;e.uploading=true;mediaInvalidate(e);e.status.textContent='正在读取产品图…';const reader=new FileReader();reader.onload=()=>{if(token!==e.uploadToken)return;e.uploading=false;e.cover=reader.result;e.productPhoto='auto';clear.hidden=false;mediaInvalidate(e);};reader.onerror=()=>{if(token!==e.uploadToken)return;e.uploading=false;e.status.textContent='图片读取失败，请重新选择。';mediaSync(e);};reader.readAsDataURL(file);
 };
 e.previewButton=mediaElement('button','预览图卡','primary');e.previewButton.type='button';e.previewButton.onclick=()=>mediaPreview(e);controls.append(e.previewButton);section.append(controls,mediaElement('p','不上传也能使用已匹配的产品照片，罗技 M185 已提供多角度实拍图。每页优先使用不同图片，不足时后页只排文案；其他未匹配产品可自行上传。上传图片仅替换封面。','media-editor-hint'));
 e.templateArea=mediaElement('div');section.append(e.templateArea);
 e.status=mediaElement('p','可先预览，或直接下载全部成品包。下载会自动应用当前设置，无需调用 AI。','media-export-status');e.status.setAttribute('aria-live','polite');section.append(e.status);
 e.stale=mediaElement('p','下方是上次预览，尚未应用新设置。','media-preview-stale');e.stale.hidden=true;section.append(e.stale);
 const workspace=mediaElement('div',null,'media-preview-workspace');e.workspace=workspace;workspace.hidden=true;
 e.thumbs=mediaElement('div',null,'media-preview-thumbs');e.thumbs.setAttribute('aria-label','图卡列表');const main=mediaElement('div',null,'media-preview-main');e.large=mediaElement('img');main.append(e.large);
 e.notice=mediaElement('p',null,'media-editor-hint');e.notice.hidden=true;main.append(e.notice);
 workspace.append(e.thumbs,main);section.append(workspace);
 const adjust=mediaElement('section',null,'media-adjust-panel');e.adjustPanel=adjust;e.adjustTitle=mediaElement('h4','调整当前图卡');adjust.append(e.adjustTitle,mediaElement('p','看图调整（本地 AI 试用）。每次选一种：拆页、移除图片、图片放正文上方或下方、正文分点居中或左对齐。不支持组合要求或随意改写；修改文案请到改稿区。先预览，再决定是否采用。','media-editor-hint'));
 const feedbackLabel=mediaElement('label','这一页怎么调整？');e.feedback=mediaElement('textarea');e.feedback.rows=3;e.feedback.maxLength=1000;e.feedback.placeholder='例如：把这一页的产品图片放在文字下方。每次只提一种调整。';feedbackLabel.append(e.feedback);adjust.append(feedbackLabel);
 e.adjustButton=mediaElement('button','让 AI 看图并预览','secondary');e.adjustButton.type='button';e.adjustButton.onclick=()=>mediaAdjustPreview(e);adjust.append(e.adjustButton);
 e.proposalArea=mediaElement('div',null,'media-adjust-proposal');e.proposalArea.hidden=true;adjust.append(e.proposalArea);section.append(adjust);
 const buttons=mediaElement('div',null,'media-export-buttons');for(const [kind,label] of [['complete','下载全部成品包']]){
  const button=mediaElement('button',label,kind==='complete'?'primary media-export-primary':'secondary');button.type='button';button.disabled=true;button.onclick=async()=>{try{await downloadMediaBundle(e.run,kind,button,e.status);}finally{mediaSync(e);}};e.downloadButtons.push(button);buttons.append(button);
 }section.append(buttons);container.append(section);mediaSync(e);
 await mediaLoadTemplates(e);
}

// The studio owns a server revision. Local selection and speech drafts never mutate it.
const studioEditors=new Map();
const studioObjectNames={title:'标题',image:'产品图',body:'正文',background:'背景'};
function studioEditorFor(run){return studioEditors.get(mediaKey(run));}
function studioButton(text,handler,cls='studio-button'){const b=mediaElement('button',text,cls);b.type='button';b.onclick=handler;return b;}
function studioError(data,fallback){return data?.error?.message||data?.detail?.message||(typeof data?.detail==='string'?data.detail:'')||data?.message||fallback;}
function studioAlive(e){return e.host._mediaKey===e.key;}
function studioBase(e){return {draft_ref:e.draft.ref,content_hash:e.draft.content_hash,expected_revision:e.state?.revision,idempotency_key:typeof crypto!=='undefined'&&crypto.randomUUID?crypto.randomUUID():`studio-${Date.now()}-${Math.random().toString(36).slice(2)}`};}
function studioValidate(e,data){
 if(!data.state||!Number.isInteger(data.state.revision)||!data.preview?.pages?.length)throw new Error('工作台返回的数据不完整，请刷新重试。');
 if(data.preview.draft_ref!==e.draft.ref||data.preview.content_hash!==e.draft.content_hash)throw new Error('稿件版本已经变化，请重新打开工作台。');
 return data;
}
function studioApply(e,data){
 studioValidate(e,data);e.state=data.state;e.preview=data.preview;
 if(data.accepted_preview)e.acceptedPreview=data.accepted_preview;
 else if(!e.state.has_pending)e.acceptedPreview=data.preview;
 e.page=Math.max(0,Math.min(e.page,e.preview.pages.length-1));e.loading=false;studioRender(e);
}
async function studioLoad(e){
 if(e.busy)return false;e.busy=true;studioSync(e);e.status.textContent='正在恢复创作工作台…';
 try{
  let response=await fetch(`/api/runs/${encodeURIComponent(e.run.run_id)}/studio`,{credentials:'same-origin'});
  let data=await response.json();
  if(response.status===404||(response.ok&&!data.state)){response=await fetch(`/api/runs/${encodeURIComponent(e.run.run_id)}/studio`,{method:'POST',credentials:'same-origin',headers:mediaHeaders(),body:JSON.stringify({...studioBase(e),action:'init',options:{studio:{pages:{'0':{layout:'hero'}}}}})});data=await response.json();}
  if(!response.ok)throw new Error(studioError(data,'工作台暂不可用，请重试。'));
  if(!studioAlive(e))return false;studioApply(e,data);e.status.textContent=e.state.has_pending?'已恢复未采用的修改，可继续编辑或撤回。':'已载入确认稿。选择画面中的对象，开始调整。';return true;
 }catch(error){if(studioAlive(e)){e.status.textContent=error.message;e.retry.hidden=false;}return false;}
 finally{e.busy=false;studioSync(e);}
}
async function studioAction(e,action,payload={}){
 if(e.busy||!e.state||!studioAlive(e))return false;
 const revision=e.state.revision,previousDesign=JSON.stringify(e.state.current);e.busy=true;studioSync(e);e.status.textContent=action==='edit'&&payload.feedback?'正在看图并理解你的修改要求…':'正在保存并更新画布…';
 try{
  const response=await fetch(`/api/runs/${encodeURIComponent(e.run.run_id)}/studio`,{method:'POST',credentials:'same-origin',headers:mediaHeaders(),body:JSON.stringify({...studioBase(e),action,...payload})});
  const data=await response.json();if(!response.ok){if(response.status===409)e.retry.hidden=false;throw new Error(studioError(data,'修改未完成，请重试。'));}
  if(!studioAlive(e)||e.state.revision!==revision)return false;
  studioApply(e,data);const unchanged=action==='edit'&&payload.feedback&&previousDesign===JSON.stringify(e.state.current);const explanation=[...(e.state.messages||[])].reverse().find(message=>message.role==='assistant');e.status.textContent=unchanged?(explanation?.text||explanation?.content||explanation?.summary||'本次没有修改画布，请根据回复调整要求。'):action==='accept'?'已采用当前版本，可以导出成品。':action==='asset'?'素材已保存。选择产品图后，可从素材栏替换。':e.state.has_pending?'修改已保存为待采用版本。满意后点击“采用当前版本”。':'已恢复已采用版本。';return true;
 }catch(error){if(studioAlive(e))e.status.textContent=error.message;return false;}
 finally{e.busy=false;studioSync(e);}
}
function studioSync(e){
 const busy=e.busy||mediaDownloadsInFlight.has(e.run.run_id),ready=!!e.state;
 for(const control of e.controls||[])control.disabled=busy||!ready;
 e.retry.disabled=busy;e.undo.disabled=busy||!e.state?.can_undo;e.redo.disabled=busy||!e.state?.can_redo;e.undo.title=busy?'正在处理，请稍候':e.state?.can_undo?'撤销上一步画布修改':'暂无可撤销的修改';e.redo.title=busy?'正在处理，请稍候':e.state?.can_redo?'恢复刚撤销的画布修改':'撤销后可重做';e.historyHint.textContent=busy?'正在保存…':e.state?.can_undo?'可撤销上一步':e.state?.can_redo?'已撤销，可重做':'暂无可撤销的修改';e.accept.disabled=busy||!e.state?.has_pending;e.discard.disabled=busy||!e.state?.has_pending;
 e.exportButton.disabled=busy||!ready||!!e.state?.has_pending;e.send.disabled=busy||!ready;e.feedback.disabled=busy;e.voice.disabled=busy||!ready||!e.speechSupported;
 e.badge.textContent=!ready?'尚未载入':busy?'更新中…':e.state.has_pending?'待采用的修改':'已采用版本';
 e.section.setAttribute('aria-busy',String(busy));
 if(e.scale){e.scale.disabled=busy||!ready||e.selected==='background'||studioBackgroundImage(e);e.scale.title=studioBackgroundImage(e)?'背景图铺满画布；恢复前景后可拖动缩放':'';}
 if(e.placement){e.placement.hidden=e.selected!=='image'||!studioSelected(e);e.placement.textContent=studioBackgroundImage(e)?'恢复前景图片':'用作整页背景';}
 if(e.opacity){e.opacityLabel.hidden=!['title','body'].includes(e.selected);e.opacity.disabled=busy||!ready;e.opacity.value=String(Math.round((studioObjectState(e).opacity??1)*100));e.opacityValue.textContent=`${e.opacity.value}%`;}
 for(const swatch of e.swatches||[])swatch.disabled=busy||!ready||e.selected==='image';e.referenceNote.textContent=e.referenceId?'已附参考图 · 仅作为视觉参考':'可附参考图；语音先转成文字，检查后再发送';
}
function studioBoundsStyle(node,bounds){node.style.left=`${bounds.x/1080*100}%`;node.style.top=`${bounds.y/1440*100}%`;node.style.width=`${bounds.width/1080*100}%`;node.style.height=`${bounds.height/1440*100}%`;}
function studioBackgroundImage(e){return e.selected==='image'&&studioObjectState(e).placement==='background';}
function studioObjectState(e){return e.state?.current?.options?.studio?.pages?.[String(e.page)]?.[e.selected]||{};}
function studioSelected(e){return e.preview?.pages[e.page]?.elements?.find(item=>item.id===e.selected);}
function studioSelect(e,id){e.selected=id;e.region=null;studioRenderCanvas(e);studioSelectionLabel(e);}
function studioSelectionLabel(e){e.selection.textContent=`第 ${e.page+1} 张 · ${e.region?'圈选区域':studioObjectNames[e.selected]||'整页'}`;e.scale.disabled=e.busy||!e.state||e.selected==='background';const scale=Math.round((studioObjectState(e).scale||1)*100);e.scale.value=String(scale);e.scaleValue.textContent=`${scale}%`;studioSync(e);}
function studioRenderCanvas(e){
 const page=e.preview?.pages[e.page];if(!page)return;
 e.large.src=page.data_url;e.large.alt=`第 ${e.page+1} 张图卡，点击标题、产品图或正文可选择对象`;
 e.overlay.replaceChildren();
 for(const item of page.elements||[]){
  if(!item.bounds||item.id==='background')continue;
  const hit=studioButton('',()=>{if(!e.busy&&!e.boxMode)studioSelect(e,item.id);},'studio-object'+(e.selected===item.id?' is-selected':''));
  hit.setAttribute('data-studio-element',item.id);hit.setAttribute('aria-label',`选择${studioObjectNames[item.id]||item.id}；方向键移动，Shift 加方向键精细移动`);hit.setAttribute('aria-pressed',String(e.selected===item.id));studioBoundsStyle(hit,item.bounds);
  hit.append(mediaElement('span',studioObjectNames[item.id]||item.id,'studio-object-label'));
  hit.onpointerdown=event=>studioPointerDown(e,event,item,hit);hit.onkeydown=event=>{
   const movement={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];if(!movement||e.busy)return;event.preventDefault();e.selected=item.id;if(studioBackgroundImage(e)){e.status.textContent='背景图铺满画布，请先点击“恢复前景图片”再移动。';return;}const step=event.shiftKey?2:10;studioEdit(e,{dx:movement[0]*step,dy:movement[1]*step});
  };e.overlay.append(hit);
 }
 if(e.region){const box=mediaElement('div',null,'studio-region');studioBoundsStyle(box,e.region);e.overlay.append(box);}
 e.pageLabel.textContent=`${String(e.page+1).padStart(2,'0')} / ${String(e.preview.pages.length).padStart(2,'0')}`;
 e.notice.textContent=page.notice||'';e.notice.hidden=!page.notice;e.canvas.className='studio-canvas'+(e.boxMode?' is-selecting':'');
}
function studioPoint(e,event){const rect=e.canvas.getBoundingClientRect();return {x:Math.round(Math.max(0,Math.min(1080,(event.clientX-rect.left)/rect.width*1080))),y:Math.round(Math.max(0,Math.min(1440,(event.clientY-rect.top)/rect.height*1440)))};}
function studioPointerDown(e,event,item,node){
 if(e.busy||event.button!==0||e.boxMode)return;event.preventDefault();event.stopPropagation();e.selected=item.id;e.region=null;studioSelectionLabel(e);
 if(studioBackgroundImage(e)){e.status.textContent='背景图铺满画布，请先点击“恢复前景图片”再移动。';return;}
 const start=studioPoint(e,event);node.setPointerCapture?.(event.pointerId);let last=start;
 node.onpointermove=move=>{last=studioPoint(e,move);node.style.transform=`translate(${(last.x-start.x)/1080*e.canvas.getBoundingClientRect().width}px,${(last.y-start.y)/1440*e.canvas.getBoundingClientRect().height}px)`;};
 const cancel=()=>{node.onpointermove=null;node.onpointerup=null;node.onpointercancel=null;node.style.transform='';};
 node.onpointercancel=cancel;node.onpointerup=async end=>{last=studioPoint(e,end);const dx=last.x-start.x,dy=last.y-start.y;cancel();if(Math.abs(dx)+Math.abs(dy)>4)await studioEdit(e,{dx,dy});else studioRenderCanvas(e);};
}
function studioRegionStart(e,event){
 if(!e.boxMode||e.busy||event.button!==0)return;event.preventDefault();const start=studioPoint(e,event);e.canvas.setPointerCapture?.(event.pointerId);let last=start;
 const show=()=>{e.region={x:Math.min(start.x,last.x),y:Math.min(start.y,last.y),width:Math.abs(last.x-start.x),height:Math.abs(last.y-start.y)};studioRenderCanvas(e);};
 e.canvas.onpointermove=move=>{last=studioPoint(e,move);show();};
 const stop=()=>{e.canvas.onpointermove=null;e.canvas.onpointerup=null;e.canvas.onpointercancel=null;};
 e.canvas.onpointercancel=()=>{stop();e.region=null;studioRenderCanvas(e);};e.canvas.onpointerup=end=>{last=studioPoint(e,end);show();stop();if(e.region.width<8||e.region.height<8)e.region=null;else e.selected='background';e.boxMode=false;e.boxButton.setAttribute('aria-pressed','false');studioRenderCanvas(e);studioSelectionLabel(e);e.feedback.focus();};
}
function studioRender(e){
 e.retry.hidden=true;e.thumbs.replaceChildren();const elements=e.preview.pages[e.page]?.elements||[];if(e.selected!=='background'&&!elements.some(item=>item.id===e.selected))e.selected='background';
 e.preview.pages.forEach((page,index)=>{const b=studioButton('',()=>{if(e.busy)return;e.page=index;e.region=null;studioRender(e);},'studio-thumb');b.setAttribute('aria-pressed',String(index===e.page));b.setAttribute('data-studio-page',String(index));b.setAttribute('aria-label',`查看第 ${index+1} 张`);const img=mediaElement('img');img.src=page.data_url;img.alt='';b.append(img,mediaElement('span',index===0?'01 封面':`${String(index+1).padStart(2,'0')} 图卡`));e.thumbs.append(b);});
 studioRenderCanvas(e);studioSelectionLabel(e);studioRenderAssets(e);studioRenderMessages(e);studioComparison(e);studioSync(e);
}
function studioRenderAssets(e){
 e.assets.replaceChildren();const assets=e.state.assets||[];
 if(!assets.length)e.assets.append(mediaElement('p','上传你的产品实拍，或附一张喜欢的风格参考。','studio-muted'));
 for(const asset of assets){const card=studioButton('',()=>{if(e.busy)return;if(asset.role==='reference'){e.referenceId=e.referenceId===asset.id?null:asset.id;studioRenderAssets(e);studioSync(e);e.feedback.focus();}else{e.selected='image';studioEdit(e,{asset_id:asset.id});}},'studio-asset');card.setAttribute('aria-pressed',String(asset.id===e.referenceId));card.setAttribute('aria-label',`${asset.role==='reference'?'附上参考图':'替换当前页产品图'}：${asset.name}`);const img=mediaElement('img');img.src=asset.data_url;img.alt=asset.name;card.append(img,mediaElement('span',asset.name),mediaElement('small',asset.role==='reference'?'风格参考':'点击替换产品图'));e.assets.append(card);}
}
function studioRenderMessages(e){
 e.messages.replaceChildren();const messages=e.state.messages||[];
 if(!messages.length){const intro=mediaElement('div',null,'studio-chat-intro');intro.append(mediaElement('span','✦','studio-chat-symbol'),mediaElement('h4','一起把这张图改好'),mediaElement('p','选中画面中的对象，告诉我想怎么改。也可以圈出区域，再附上一张参考图。'));e.messages.append(intro);}
 for(const message of messages){const role=message.role==='user'?'user':'assistant',card=mediaElement('article',null,`studio-message studio-message-${role}`);card.append(mediaElement('small',role==='user'?'你':message.mode==='manual'?'画布操作':'创作助手'));const content=message.content||message.text||message.summary||'';card.append(mediaElement('p',typeof content==='string'?content:JSON.stringify(content)));if(message.observation)card.append(mediaElement('p',`画面观察：${message.observation}`,'studio-observation'));if(role==='assistant'&&content&&typeof speechSynthesis!=='undefined'&&typeof SpeechSynthesisUtterance!=='undefined'){card.append(studioButton('朗读',()=>{speechSynthesis.cancel();const utterance=new SpeechSynthesisUtterance(content);utterance.lang='zh-CN';speechSynthesis.speak(utterance);},'studio-speak'));}e.messages.append(card);}
 e.messages.scrollTop=e.messages.scrollHeight;
}
function studioComparison(e){
 e.comparison.hidden=!e.compareMode;e.comparison.replaceChildren();e.compare.setAttribute('aria-pressed',String(!!e.compareMode));if(!e.compareMode)return;
 const before=e.acceptedPreview?.pages?.[Math.min(e.page,e.acceptedPreview.pages.length-1)],after=e.preview?.pages[e.page];
 if(!before||!after){e.comparison.append(mediaElement('p','当前缺少已采用版本的预览，请重新载入后比较。'));return;}
 for(const [label,page] of [['已采用',before],['当前修改',after]]){const col=mediaElement('div');col.append(mediaElement('strong',label));const img=mediaElement('img');img.src=page.data_url;img.alt=label;col.append(img);e.comparison.append(col);}
}
async function studioEdit(e,changes){
 if(studioBackgroundImage(e)&&['dx','dy','scale'].some(key=>key in changes)){e.status.textContent='背景图铺满画布，请先点击“恢复前景图片”再拖动或缩放。';return false;}
 if(!changes.layout&&!changes.asset_id&&!studioSelected(e)&&e.selected!=='background'){e.status.textContent='当前页没有这个对象，请重新选择。';return false;}
 const current=studioObjectState(e),resolved={...changes};for(const axis of ['dx','dy'])if(typeof resolved[axis]==='number')resolved[axis]+=(current[axis]||0);
 return studioAction(e,'edit',{operations:[changes.layout?{page_index:e.page,layout:changes.layout}:{page_index:e.page,element_id:e.selected||'background',changes:resolved}]});
}
async function studioSend(e){
 const text=e.feedback.value.trim();if(!text||e.busy)return false;
 const payload={feedback:text,page_index:e.page,element_id:e.selected||'background',...(e.region?{region:e.region}:{}),...(e.referenceId?{reference_asset_id:e.referenceId}:{})};
 const success=await studioAction(e,'edit',payload);if(success){e.feedback.value='';e.region=null;studioRenderCanvas(e);}return success;
}
async function studioUpload(e,input,role){
 const file=input.files?.[0];if(!file||e.busy)return false;
 if(!['image/png','image/jpeg'].includes(file.type)||file.size>3*1024*1024){e.status.textContent='请选择不超过 3 MB 的 PNG 或 JPEG 图片。';input.value='';return false;}
 e.busy=true;studioSync(e);e.status.textContent='正在读取图片…';
 try{const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('图片读取失败，请重新选择。'));reader.readAsDataURL(file);});e.busy=false;if(!studioAlive(e))return false;const ok=await studioAction(e,'asset',{asset:{name:file.name,role,data_url:data}});if(ok&&role==='reference'){e.referenceId=e.state.assets?.filter(asset=>asset.role==='reference').at(-1)?.id||null;studioRenderAssets(e);studioSync(e);}return ok;}
 catch(error){e.status.textContent=error.message;return false;}finally{e.busy=false;input.value='';studioSync(e);}
}
function studioStopSpeech(e){
 const recognition=e.recognition;if(!recognition)return;e.recognition=null;e.speechObserver?.disconnect();e.speechObserver=null;recognition.onresult=null;recognition.onend=null;recognition.onerror=null;
 try{if(recognition.abort)recognition.abort();else recognition.stop();}catch{}
 e.voice.textContent='语音输入';e.voice.setAttribute('aria-pressed','false');e.voiceNote.textContent='录音已停止，已转写的文字仍可编辑。';
}
function studioStopAllSpeech(){for(const editor of studioEditors.values())studioStopSpeech(editor);}
if(typeof window!=='undefined')window.addEventListener?.('pagehide',studioStopAllSpeech);
if(typeof document!=='undefined')document.addEventListener?.('visibilitychange',()=>{if(document.hidden)studioStopAllSpeech();});
function studioWatchSpeechVisibility(e){
 if(typeof MutationObserver==='undefined'||!document.body)return;
 e.speechObserver=new MutationObserver(()=>{if(!studioAlive(e)||e.section.isConnected===false||e.section.closest?.('[hidden]')||e.section.getClientRects?.().length===0||(typeof currentPage!=='undefined'&&currentPage!=='studio'))studioStopSpeech(e);});
 e.speechObserver.observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['hidden','class','style']});
}
function studioSpeech(e){
 if(e.recognition){e.recognition.stop();return;}
 const Recognition=typeof window!=='undefined'&&(window.SpeechRecognition||window.webkitSpeechRecognition);
 if(!Recognition){e.status.textContent='当前浏览器不支持语音转写，请使用文字输入。';return;}
 const recognition=new Recognition();e.recognition=recognition;recognition.lang='zh-CN';recognition.continuous=false;recognition.interimResults=true;const prefix=e.feedback.value.trim();let finalized='';
 recognition.onresult=event=>{let interim='';for(let i=event.resultIndex;i<event.results.length;i++){if(event.results[i].isFinal)finalized+=event.results[i][0].transcript;else interim+=event.results[i][0].transcript;}e.feedback.value=[prefix,finalized+interim].filter(Boolean).join(' ');e.voiceNote.textContent='转写只填入输入框，请检查后发送。';};
 recognition.onerror=event=>{e.status.textContent=event.error==='not-allowed'?'麦克风未授权，可以继续打字。':'语音转写未完成，可以重新录入或打字。';};
 recognition.onend=()=>{e.speechObserver?.disconnect();e.speechObserver=null;e.recognition=null;e.voice.textContent='语音输入';e.voice.setAttribute('aria-pressed','false');e.feedback.focus();};
 try{recognition.start();studioWatchSpeechVisibility(e);e.voice.textContent='停止录音';e.voice.setAttribute('aria-pressed','true');e.voiceNote.textContent='正在听… 再点一次停止。';}catch{e.recognition=null;e.status.textContent='语音暂不可用，请使用文字输入。';}
}
async function studioDownload(e,kind,button,status){
 if(e.busy||mediaDownloadsInFlight.has(e.run.run_id))return false;
 if(!e.state){status.textContent='请先载入工作台。';return false;}
 if(e.state.has_pending){status.textContent='请先采用当前版本，再导出成品。';return false;}
 const revision=e.state.revision;e.busy=true;mediaDownloadsInFlight.add(e.run.run_id);const old=button.disabled;button.disabled=true;studioSync(e);status.textContent='正在打包已采用的图文与视频…';
 try{const response=await fetch(`/api/runs/${encodeURIComponent(e.run.run_id)}/studio/export`,{method:'POST',credentials:'same-origin',headers:mediaHeaders(),body:JSON.stringify({draft_ref:e.draft.ref,content_hash:e.draft.content_hash,expected_revision:e.state.revision,kind})});if(!response.ok){let data={};try{data=await response.json();}catch{}throw new Error(studioError(data,'导出失败，请重试。'));}const blob=await response.blob();if(!studioAlive(e)||revision!==e.state.revision){status.textContent='版本已经变化，请重新导出当前版本。';return false;}const url=URL.createObjectURL(blob),a=mediaElement('a');a.href=url;a.download=`youji-${kind}-${e.run.run_id.slice(0,8)}.zip`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);status.textContent='成品包已下载。请在发布前检查图片、文案和视频。';return true;}
 catch(error){status.textContent=error.message;return false;}finally{e.busy=false;mediaDownloadsInFlight.delete(e.run.run_id);button.disabled=old;studioSync(e);}
}
async function mountArchivedStudio(run,container){
 if(run.workflow_type!=='creation'||run.run_status!=='SUCCEEDED'||!run.accepted_ref){for(const old of studioEditors.values())if(old.host===container)studioStopSpeech(old);container._mediaKey=null;container.replaceChildren();return;}
 const key=mediaKey(run);if(!key)return mountLegacyMediaExports(run,container);
 let e=studioEditors.get(key);if(container._mediaKey===key&&e?.section){e.run=run;studioSync(e);return;}
 for(const old of studioEditors.values())if(old.host===container)studioStopSpeech(old);
 container._mediaKey=key;container.replaceChildren();
 if(e){e.run=run;e.host=container;container.append(e.section);studioSync(e);return;}
 e={key,run,draft:mediaDraft(run),host:container,page:0,selected:'image',state:null,preview:null,controls:[],busy:false,boxMode:false,compareMode:false,referenceId:null};studioEditors.set(key,e);
 const section=e.section=mediaElement('section',null,'media-exports studio');section.setAttribute('aria-label','多模态创作工作台');
 const head=mediaElement('header',null,'studio-header'),heading=mediaElement('div');heading.append(mediaElement('span','有迹 · 创作工作台','studio-eyebrow'),mediaElement('h3','让画面，也能听懂你的想法。'));e.badge=mediaElement('span','正在载入','studio-badge');head.append(heading,e.badge);section.append(head);
 const layout=mediaElement('div',null,'studio-layout'),left=mediaElement('aside',null,'studio-library');left.setAttribute('aria-label','页面和素材');left.append(mediaElement('h4','我的图卡'));e.thumbs=mediaElement('nav',null,'studio-thumbs');e.thumbs.setAttribute('aria-label','切换图卡');left.append(e.thumbs);
 const materialHead=mediaElement('h4','素材');left.append(materialHead);e.assets=mediaElement('div',null,'studio-assets');left.append(e.assets);
 for(const [role,label] of [['product','＋ 产品实拍'],['reference','＋ 参考图片']]){const upload=mediaElement('label',label,'studio-upload'),input=mediaElement('input');input.type='file';input.accept='image/png,image/jpeg';input.setAttribute('data-studio-upload',role);input.setAttribute('aria-label',label);input.onchange=()=>studioUpload(e,input,role);upload.append(input);left.append(upload);e.controls.push(input);}
 const center=mediaElement('div',null,'studio-center'),toolbar=mediaElement('div',null,'studio-canvas-toolbar');e.selection=mediaElement('span','选择对象','studio-selection');e.boxButton=studioButton('圈选区域',()=>{e.boxMode=!e.boxMode;e.boxButton.setAttribute('aria-pressed',String(e.boxMode));studioRenderCanvas(e);});e.boxButton.setAttribute('aria-pressed','false');const background=studioButton('选择背景',()=>studioSelect(e,'background'));e.controls.push(e.boxButton,background);e.undo=studioButton('↶ 撤销',()=>studioAction(e,'undo'));e.redo=studioButton('↷ 重做',()=>studioAction(e,'redo'));e.historyHint=mediaElement('span','暂无可撤销的修改','studio-history-hint');toolbar.setAttribute('aria-label','画布与修改历史');toolbar.append(e.undo,e.redo,e.historyHint,e.selection,background,e.boxButton);center.append(toolbar);
 const stage=mediaElement('div',null,'studio-stage');e.canvas=mediaElement('div',null,'studio-canvas');e.large=mediaElement('img');e.large.draggable=false;e.overlay=mediaElement('div',null,'studio-overlay');e.canvas.append(e.large,e.overlay);e.canvas.onpointerdown=event=>studioRegionStart(e,event);stage.append(e.canvas);center.append(stage);
 const below=mediaElement('div',null,'studio-below-canvas');below.append(mediaElement('span','点选对象 · 拖动位置 · 圈选后提要求'));e.pageLabel=mediaElement('span','— / —');below.append(e.pageLabel);center.append(below);e.notice=mediaElement('p',null,'studio-muted');e.notice.hidden=true;center.append(e.notice);
 const inspector=mediaElement('div',null,'studio-inspector');const scaleLabel=mediaElement('label','选中对象缩放');e.scale=mediaElement('input');e.scale.type='range';e.scale.min='50';e.scale.max='160';e.scale.step='5';e.scale.value='100';e.scale.setAttribute('aria-label','选中对象缩放比例');e.scaleValue=mediaElement('output','100%');e.scale.oninput=()=>e.scaleValue.textContent=`${e.scale.value}%`;e.scale.onchange=async()=>{await studioEdit(e,{scale:Number(e.scale.value)/100});studioSelectionLabel(e);};scaleLabel.append(e.scale,e.scaleValue);inspector.append(scaleLabel);e.placement=studioButton('用作整页背景',()=>studioEdit(e,{placement:studioBackgroundImage(e)?'inline':'background'}));e.controls.push(e.placement);inspector.append(e.placement);e.opacityLabel=mediaElement('label','文字不透明度');e.opacity=mediaElement('input');e.opacity.type='range';e.opacity.min='0';e.opacity.max='100';e.opacity.step='5';e.opacity.setAttribute('aria-label','选中文字不透明度');e.opacityValue=mediaElement('output','100%');e.opacity.oninput=()=>e.opacityValue.textContent=`${e.opacity.value}%`;e.opacity.onchange=()=>studioEdit(e,{opacity:Number(e.opacity.value)/100});e.opacityLabel.append(e.opacity,e.opacityValue);inspector.append(e.opacityLabel);
 const palette=mediaElement('div',null,'studio-palette');e.swatches=[];palette.append(mediaElement('span','文字 / 背景配色'));for(const [color,name] of [['#265c4b','松绿色'],['#bd915b','暖金色'],['#2b3440','深墨色'],['#f4e9d7','奶油色'],['#f1c9ca','浅粉色']]){const swatch=studioButton('',()=>studioEdit(e,{color}),'studio-swatch');swatch.style.backgroundColor=color;swatch.setAttribute('data-studio-color',color);swatch.setAttribute('aria-label',`将选中对象设为${name}`);swatch.title='选中文字或背景后调整配色';palette.append(swatch);e.swatches.push(swatch);e.controls.push(swatch);}inspector.append(palette);center.append(inspector);
 const composition=mediaElement('div',null,'studio-compositions');composition.append(mediaElement('span','试试构图'));for(const [value,label] of [['hero','大图主视觉'],['checklist','清单卡片'],['compare','图文对照']]){const b=studioButton(label,()=>studioEdit(e,{layout:value}));b.setAttribute('data-studio-layout',value);composition.append(b);e.controls.push(b);}center.append(composition);
 const themes=mediaElement('details',null,'studio-themes');themes.append(mediaElement('summary','整套风格'));e.themeGrid=mediaElement('div',null,'studio-theme-grid');themes.append(e.themeGrid);center.append(themes);
 e.comparison=mediaElement('div',null,'studio-comparison');e.comparison.hidden=true;center.append(e.comparison);
 const right=mediaElement('aside',null,'studio-assistant');right.setAttribute('aria-label','创作助手');right.append(mediaElement('h4','和画面聊一聊'),mediaElement('p','本机视觉模型 · qwen3-vl:4b','studio-model-label'));e.messages=mediaElement('div',null,'studio-messages');e.messages.setAttribute('role','log');e.messages.setAttribute('aria-live','polite');right.append(e.messages);
 const suggestions=mediaElement('div',null,'studio-suggestions');for(const text of ['让产品更突出','标题不要挡住图片','参考这张图的配色']){const b=studioButton(text,()=>{e.feedback.value=text;e.feedback.focus();},'studio-suggestion');suggestions.append(b);e.controls.push(b);}right.append(suggestions);
 const composer=mediaElement('div',null,'studio-composer');const feedbackLabel=mediaElement('label','修改要求','studio-input-label');e.feedback=mediaElement('textarea');e.feedback.rows=4;e.feedback.maxLength=1000;e.feedback.placeholder='例如：把这个产品放大一点，标题向上移，保留现在的文字。';e.feedback.setAttribute('aria-label','对当前图卡的修改要求');e.feedback.onkeydown=event=>{if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();studioSend(e);}};feedbackLabel.append(e.feedback);composer.append(feedbackLabel);
 e.referenceNote=mediaElement('p',null,'studio-muted');composer.append(e.referenceNote);const actions=mediaElement('div',null,'studio-composer-actions');e.voice=studioButton('语音输入',()=>studioSpeech(e));e.voice.setAttribute('aria-pressed','false');e.speechSupported=typeof window!=='undefined'&&!!(window.SpeechRecognition||window.webkitSpeechRecognition);e.voiceNote=mediaElement('span',e.speechSupported?'':'此浏览器暂不支持语音，可继续打字','studio-voice-note');e.send=studioButton('发送修改 ↗',()=>studioSend(e),'studio-send');actions.append(e.voice,e.send);composer.append(actions,e.voiceNote);right.append(composer);
 layout.append(left,center,right);section.append(layout);
 const footer=mediaElement('footer',null,'studio-footer'),history=mediaElement('div',null,'studio-history');e.compare=studioButton('前后对比',()=>{e.compareMode=!e.compareMode;studioComparison(e);});e.discard=studioButton('撤回未采用修改',()=>studioAction(e,'discard'));history.append(e.compare,e.discard);const delivery=mediaElement('div',null,'studio-delivery');e.accept=studioButton('采用当前版本',()=>studioAction(e,'accept'),'studio-accept');e.exportButton=studioButton('导出成品包 ↓',()=>studioDownload(e,'complete',e.exportButton,e.status),'studio-export');delivery.append(e.accept,e.exportButton);footer.append(history,delivery);section.append(footer);
 e.status=mediaElement('p','正在打开工作台…','studio-status');for(const [name,node] of Object.entries({root:e.section,feedback:e.feedback,send:e.send,accept:e.accept,undo:e.undo,redo:e.redo,export:e.exportButton,scale:e.scale,status:e.status,compare:e.compare,discard:e.discard,voice:e.voice,selection:e.selection,canvas:e.canvas,box:e.boxButton,placement:e.placement,opacity:e.opacity})){node.setAttribute('data-studio',name);}e.status.setAttribute('role','status');e.status.setAttribute('aria-live','polite');e.retry=studioButton('重新载入',()=>studioLoad(e));e.retry.hidden=true;section.append(e.status,e.retry);container.append(section);const accountBar=document.querySelector?.('.account-bar');if(accountBar){const updateToolbarOffset=()=>section.style.setProperty('--studio-toolbar-top',`${Math.ceil(accountBar.getBoundingClientRect().height)+8}px`);updateToolbarOffset();if(typeof ResizeObserver!=='undefined'){e.toolbarObserver=new ResizeObserver(updateToolbarOffset);e.toolbarObserver.observe(accountBar);}}studioSync(e);await Promise.allSettled([studioLoad(e),studioLoadThemes(e)]);
}

async function studioLoadThemes(e){
 try{const response=await fetch(`/api/media/templates?run_id=${encodeURIComponent(e.run.run_id)}`,{credentials:'same-origin'});const data=await response.json();if(!response.ok||!Array.isArray(data.templates))throw new Error('风格库暂不可用');if(!studioAlive(e))return;e.themeGrid.replaceChildren();for(const template of data.templates){const b=studioButton(template.name,()=>studioAction(e,'edit',{operations:[{template:template.id}]}));b.setAttribute('data-studio-template',template.id);const img=mediaElement('img');img.src=template.thumbnail_url;img.alt='';b.append(img);e.themeGrid.append(b);e.controls.push(b);}studioSync(e);}catch{if(studioAlive(e))e.themeGrid.replaceChildren(mediaElement('p','风格库暂不可用，仍可继续编辑当前图卡。','studio-muted'));}
}

// The public Studio now mounts only the poster workspace. Historical editing
// helpers remain for existing saved designs and export compatibility.
async function mountMediaExports(run,container){
 for(const old of studioEditors.values())if(old.host===container)studioStopSpeech(old);
 if(run.workflow_type!=='creation'||run.run_status!=='SUCCEEDED'||!run.accepted_ref){container._posterKey=null;container._mediaKey=null;container._fullTextKey=null;container.replaceChildren();return;}
 if(typeof mountPosterStudio!=='function'){container._posterKey=null;container.replaceChildren(mediaElement('p','海报工作台未载入，请刷新页面。'));return;}
 if(container._posterKey!==mediaKey(run))container._fullTextKey=null;
 await mountPosterStudio(run,container);
 if(container._posterKey===mediaKey(run))mountFullTextExports(run,container);
}


// Full manuscript export is independent of single-poster edits and AI generation.
function mountFullTextExports(run,host){
 const key=mediaKey(run);if(!key||host._fullTextKey===key)return;
 host._fullTextKey=key;
 const section=mediaElement('section',null,'media-exports panel');
 section.setAttribute('aria-label','全文分张导出');
 const status=mediaElement('p','按完整已确认文案自动分页，不额外调用模型。','media-export-status');status.setAttribute('aria-live','polite');
 const buttons=mediaElement('div',null,'media-export-buttons');
 section.append(mediaElement('h3','全文分张导出'),mediaElement('p','单张海报之外，完整正文可分成多张图片。这里使用标准图文排版，保留全文；不会采用或覆盖上方海报。'),buttons,status);
 for(const [kind,label] of [['images','下载全文图片 ZIP'],['complete','下载全文成品包']]){
  const button=mediaElement('button',label,'secondary');button.type='button';
  button.onclick=()=>downloadFullTextBundle(run,host,key,kind,button,status);
  buttons.append(button);
 }
 host.append(section);
}
async function downloadFullTextBundle(run,host,key,kind,button,status){
 if(mediaDownloadsInFlight.has(run.run_id)||host._fullTextKey!==key||mediaKey(run)!==key)return false;
 if(run.run_status!=='SUCCEEDED'||!run.accepted_ref)return false;
 const draft=mediaDraft(run),request={draft_ref:draft.ref,content_hash:draft.content_hash,template:'classic',options:{}};
 mediaDownloadsInFlight.add(run.run_id);button.disabled=true;status.textContent='正在按完整正文分页…';
 try{
  const preview=await fetch(`/api/runs/${encodeURIComponent(run.run_id)}/media-preview`,{method:'POST',credentials:'same-origin',headers:mediaHeaders(),body:JSON.stringify(request)});
  const data=await preview.json();if(!preview.ok)throw new Error(studioError(data,'全文分页失败，请重试。'));
  if(host._fullTextKey!==key||mediaKey(run)!==key)return false;
  if(data.draft_ref!==draft.ref||data.content_hash!==draft.content_hash||!data.design_hash||!data.pages?.length)throw new Error('稿件版本已变化，请刷新后重新导出。');
  status.textContent=`全文共 ${data.pages.length} 张，正在打包…`;
  const response=await fetch(`/api/runs/${encodeURIComponent(run.run_id)}/media-export`,{method:'POST',credentials:'same-origin',headers:mediaHeaders(),body:JSON.stringify({...request,kind,design_hash:data.design_hash})});
  if(!response.ok){let error={};try{error=await response.json();}catch{}throw new Error(studioError(error,'全文导出失败，请重试。'));}
  const blob=await response.blob();if(host._fullTextKey!==key||mediaKey(run)!==key)return false;
  const url=URL.createObjectURL(blob),link=mediaElement('a');link.href=url;link.download=`youji-fulltext-${kind}-${run.run_id.slice(0,8)}.zip`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
  status.textContent=`已下载全文 ${data.pages.length} 张图片${kind==='complete'?'及可用成品，请查看包内使用说明':''}。请解压逐页检查后发布。`;return true;
 }catch(error){if(host._fullTextKey===key)status.textContent=error.message;return false;}
 finally{mediaDownloadsInFlight.delete(run.run_id);button.disabled=false;}
}
