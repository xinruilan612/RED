'use strict';
// Drafts stay scoped to the current social account; late responses never fill another account.
const productImageDrafts=new Map();
function productImagePanel(){
 return `<section class="panel" id="productImagePanel"><span class="eyebrow">PRODUCT IMAGE</span><h2>上传一张图，整理产品资料</h2><p class="muted">可上传商品包装、铭牌或详情截图。先看识别结果，修改确认后再用于介绍产品。</p><form id="productImageForm"><label for="productImageFile">产品图片</label><input id="productImageFile" type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"><p class="helper">JPG / PNG / WebP，最大 3 MB、1200 万像素，一次识别一张。原图保存在当前账号的本地记录中。</p><img id="productImageThumbnail" alt="待识别产品图片" hidden class="product-image-thumbnail"><label for="productImageMode">识别方式</label><select id="productImageMode"><option value="local">免费本机识别包装文字</option><option value="vision">视觉模型识别产品（需自行配置）</option></select><p id="productImageModeHint" class="helper">图片不会发往模型服务；适合有清晰文字的包装和详情图。只有外观、没有文字时，请使用视觉模型。</p><div id="productImageVision" hidden><label for="productImageConnection">支持看图的模型连接</label><select id="productImageConnection"><option value="">请先添加支持图片输入的模型连接</option></select><button id="productImageSettings" class="quiet" type="button">去配置视觉模型 →</button><p class="helper">使用 Chat Completions 兼容接口。连接保存成功不代表模型支持看图；请填写供应商提供的视觉模型 ID。</p><label class="checkbox"><input id="productImageCost" type="checkbox"> 同意将这张图片发送给所选模型服务识别，可能产生费用</label></div><div class="buttons"><button class="primary" id="productImageRecognize" type="submit">识别图片</button><button class="quiet" id="productImageClear" type="button">清除图片与结果</button></div></form><p id="productImageStatus" class="helper" role="status" aria-live="polite"></p><section id="productImageReview" hidden></section></section>`;
}
function productImageCurrent(account,request){return account===activeAccountId&&currentPage==='library'&&request===libraryLoad;}
function productImageReviewMarkup(preview){
 return `<h3>核对产品识别结果</h3><p class="helper">${esc(preview.engine)} · 尚未加入资料库。品牌、型号和功效请对照原图核对，无法确认的内容保留为未知。</p><label for="productImageTitle">产品 / 资料名称</label><input id="productImageTitle" maxlength="200" value="${esc(preview.title)}"><label for="productImageText">用于介绍产品的资料（可修改）</label><textarea id="productImageText" rows="12" maxlength="15000">${esc(preview.text)}</textarea><p class="helper">${preview.result.uncertainties.map(esc).join(' ')}</p><a href="/api/product-images/${encodeURIComponent(preview.id)}/original">下载原始产品图片</a><p><label class="checkbox"><input id="productImageReviewed" type="checkbox"> 我已对照图片检查名称、型号和文字，并修正不确定内容</label></p><div class="buttons"><button id="productImageSave" class="secondary" type="button">确认，存入资料库</button><button id="productImageUse" class="primary" type="button">确认，用它介绍产品 →</button></div>`;
}
async function mountProductImages(account,request){
 const container=$('operationsContent');
 container.insertAdjacentHTML('afterbegin',productImagePanel());
 const state=productImageDrafts.get(account)||{mode:'local',file:null,preview:null,requestId:null,connection:'',busy:false};
 productImageDrafts.set(account,state);
 const current=()=>productImageCurrent(account,request);
 const status=message=>{if(current())$('productImageStatus').textContent=message;};
 $('productImageMode').value=state.mode;
 const lock=busy=>{if(!current())return;for(const id of ['productImageRecognize','productImageFile','productImageMode','productImageConnection','productImageCost','productImageClear'])$(id).disabled=busy;};
 const showFile=async()=>{const image=$('productImageThumbnail'),file=state.file;image.hidden=true;if(!file)return;if(file.size>3000000||!/^image\/(jpeg|png|webp)$/.test(file.type))return;try{const encoded=await readDocumentFile(file);if(current()&&state.file===file){image.src='data:'+file.type+';base64,'+encoded;image.hidden=false;}}catch(err){status(err.message);}};
 const mode=()=>{$('productImageVision').hidden=state.mode!=='vision';$('productImageModeHint').textContent=state.mode==='vision'?'可识别产品名称线索、外观及可见文字。模型结果仍需核对，不会自动搜索或补全参数。':'图片不会发往模型服务；适合有清晰文字的包装和详情图。只有外观、没有文字时，请使用视觉模型。';};
 const invalidate=()=>{state.preview=null;state.requestId=null;state.confirmation=null;state.reviewed=false;$('productImageCost').checked=false;$('productImageReview').hidden=true;status('输入已更新，识别后再核对。');};
 const review=()=>{
  if(!state.preview)return;
  const panel=$('productImageReview');panel.hidden=false;panel.innerHTML=productImageReviewMarkup(state.preview);
  $('productImageReviewed').checked=Boolean(state.reviewed);
  if(state.confirmation){$('productImageTitle').readOnly=true;$('productImageText').readOnly=true;}
  $('productImageTitle').oninput=()=>{state.preview.title=$('productImageTitle').value;state.reviewed=false;$('productImageReviewed').checked=false;};
  $('productImageText').oninput=()=>{state.preview.text=$('productImageText').value;state.reviewed=false;$('productImageReviewed').checked=false;};
  $('productImageReviewed').onchange=()=>{state.reviewed=$('productImageReviewed').checked;};
  const confirm=async use=>{
   if(!state.reviewed){status('请先对照图片校对，并勾选确认。');return;}
   if(!$('productImageTitle').value.trim()||!$('productImageText').value.trim()){status('请填写产品名称和校对后的资料正文。');return;}
   if(state.busy)return;
   state.busy=true;const title=$('productImageTitle'),text=$('productImageText');
   const content=state.confirmation?.text||text.value,productTitle=state.confirmation?.title||title.value;
   title.readOnly=true;text.readOnly=true;$('productImageSave').disabled=true;$('productImageUse').disabled=true;
   // Freeze a confirmation payload: a network retry cannot create a second document.
   state.confirmation=state.confirmation||{account_id:account,title:productTitle,text:content,confirmed:true};
   try{
    const saved=await api('/api/product-images/'+state.preview.id+'/confirm','POST',state.confirmation);
    if(!current())return;
    status('已保存到当前账号资料库：'+saved.title);
    if(use){
     if(typeof dirtyGuard==='function'&&!dirtyGuard())return;
     const existing=$('material').value.trim(),combined=existing.includes(content)?existing:[existing,content].filter(Boolean).join('\n\n');
     if(combined.length>8000)throw new Error('资料已保存，但与现有素材合计超过 8000 字；请精简素材后从资料库选择使用。');
     $('material').value=combined;
     if(!$('topic').value.trim())$('topic').value=('介绍'+productTitle).slice(0,100);
     if(typeof refreshMaterialDocuments==='function')await refreshMaterialDocuments();
     if(!current())return;
     const select=$('materialDocumentSelect');
     if(select){const option=[...select.options].find(o=>o.value===saved.id);if(option&&select.selectedOptions.length<3)option.selected=true;}
     $('useKnowledge').checked=true;
     showPage('studio');if(typeof auto!=='undefined')auto=false;if(typeof editing!=='undefined')editing=false;
     $('editor').hidden=true;$('workbench').hidden=true;$('welcome').hidden=false;
     toast('产品资料已带入创作；请补充介绍目标，再开始创作。');
    }else{
     if(typeof refreshRagDocuments==='function')await refreshRagDocuments(account,request);
    }
   }catch(err){if(err.code==='INVALID_INPUT')state.confirmation=null;status(err.message+' 原图和识别结果仍保留。');}
   finally{state.busy=false;if(current()){$('productImageSave').disabled=false;$('productImageUse').disabled=false;if(!state.confirmation){title.readOnly=false;text.readOnly=false;}}}
  };
  $('productImageSave').onclick=()=>confirm(false);$('productImageUse').onclick=()=>confirm(true);
 };
 $('productImageFile').onchange=()=>{state.file=$('productImageFile').files[0]||null;invalidate();showFile();};
 $('productImageClear').onclick=()=>{state.file=null;$('productImageFile').value='';invalidate();showFile();status('已清除页面中的图片与结果，可以选择自己的产品图。');};
 $('productImageMode').onchange=()=>{state.mode=$('productImageMode').value;invalidate();mode();};
 $('productImageConnection').onchange=()=>{state.connection=$('productImageConnection').value;invalidate();};
 $('productImageSettings').onclick=()=>showPage('models');
 $('productImageForm').onsubmit=async e=>{
  e.preventDefault();if(state.busy)return;
  if(!state.file){status('请先选择一张产品图片。');return;}
  if(state.file.size>3000000||!/^image\/(jpeg|png|webp)$/.test(state.file.type)){status('请选择不超过 3 MB 的 JPG、PNG 或 WebP 图片。');return;}
  if(state.mode==='vision'&&!state.connection){status('尚未配置视觉模型，请先点击“去配置视觉模型”。也可使用免费本机文字识别。');return;}
  if(state.mode==='vision'&&!$('productImageCost').checked){status('请先确认图片发送与可能产生的模型费用。');return;}
  state.busy=true;lock(true);state.requestId=state.requestId||crypto.randomUUID();
  status(state.mode==='local'?'正在本机识别包装文字，首次加载约需数秒…':'正在请求所选视觉模型，请勿重复提交…');
  try{
   const encoded=await readDocumentFile(state.file);
   const preview=await api('/api/product-images/preview','POST',{account_id:account,request_id:state.requestId,filename:state.file.name,file_base64:encoded,mode:state.mode,...(state.mode==='vision'?{connection_id:state.connection,acknowledge_cost:true}:{})});
   state.preview=preview;state.reviewed=false;
   if(!current())return;
   review();status('识别完成，请核对后确认；尚未入库。');
  }catch(err){status(err.message+' 原图保留；重试不会自动重复同一模型请求。');}
  finally{state.busy=false;lock(false);}
 };
 showFile();mode();review();lock(state.busy);
 try{
  const models=await api('/api/models');if(!current())return;
  const connections=models.connections.filter(c=>(c.protocol||'openai')==='openai');
  $('productImageConnection').innerHTML='<option value="">选择支持看图的模型连接</option>'+connections.map(c=>`<option value="${esc(c.id)}">${esc(c.label)} · ${esc(c.model)}</option>`).join('');
  $('productImageConnection').value=state.connection;
 }catch(_){status('暂未加载模型连接；可使用本机文字识别，或稍后再打开此页。');}
}
