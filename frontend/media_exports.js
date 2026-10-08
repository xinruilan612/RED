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

async function mountMediaExports(run,container){
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
 const adjust=mediaElement('section',null,'media-adjust-panel');e.adjustPanel=adjust;e.adjustTitle=mediaElement('h4','调整当前图卡');adjust.append(e.adjustTitle,mediaElement('p','看图调整（本地 AI 试用）。支持拆页或移除本页产品图；修改文案请到改稿区。先预览，再决定是否采用。','media-editor-hint'));
 const feedbackLabel=mediaElement('label','这一页怎么调整？');e.feedback=mediaElement('textarea');e.feedback.rows=3;e.feedback.maxLength=1000;e.feedback.placeholder='例如：把这一页拆成两页，保留图片；或移除这一页的产品图片';feedbackLabel.append(e.feedback);adjust.append(feedbackLabel);
 e.adjustButton=mediaElement('button','让 AI 看图并预览','secondary');e.adjustButton.type='button';e.adjustButton.onclick=()=>mediaAdjustPreview(e);adjust.append(e.adjustButton);
 e.proposalArea=mediaElement('div',null,'media-adjust-proposal');e.proposalArea.hidden=true;adjust.append(e.proposalArea);section.append(adjust);
 const buttons=mediaElement('div',null,'media-export-buttons');for(const [kind,label] of [['complete','下载全部成品包']]){
  const button=mediaElement('button',label,kind==='complete'?'primary media-export-primary':'secondary');button.type='button';button.disabled=true;button.onclick=async()=>{try{await downloadMediaBundle(e.run,kind,button,e.status);}finally{mediaSync(e);}};e.downloadButtons.push(button);buttons.append(button);
 }section.append(buttons);container.append(section);mediaSync(e);
 await mediaLoadTemplates(e);
}
