/* Personal topic ranking: account-scoped inputs and explicit prediction limits. */
'use strict';
pageInfo.topics=['TOPICS / 选题潜力','找一找，更适合你的下一个选题。','先搜同领域参考，再比较你想写的选题，选好后直接开始创作。'];
let topicsSequence=0;
let topicsState={account:'',data:null,config:null,candidates:[],result:null,busy:false,message:'',publicData:null,keyword:'',manual:{}};
const topicsMetrics={views:'阅读 / 播放',likes:'点赞',saves:'收藏',comments:'评论'};
function topicsCandidate(){return {id:crypto.randomUUID(),title:'',body:'',image:'',imageName:''};}
function resetTopics(){topicsSequence++;topicsState={account:'',data:null,config:null,candidates:[],result:null,busy:false,message:'',publicData:null,keyword:'',manual:{}};}
function topicsLive(account,sequence){return topicsState.account===account&&activeAccountId===account&&topicsSequence===sequence;}
function topicsText(value){return typeof value==='string'?value:JSON.stringify(value??'');}
function topicsNumber(value,digits=3){return typeof value==='number'&&Number.isFinite(value)?value.toFixed(digits):'—';}
function topicsSafeURL(value){try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)?u.href:'';}catch(_){return '';}}
function topicsPublicRows(rows,editable=false){return (rows||[]).map(r=>{const url=topicsSafeURL(r.url),counts=r.counts||r;return `<article class="topics-reference"><strong>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(r.title||'公开参考')} ↗</a>`:esc(r.title||'公开参考')}</strong><span class="helper">${[['likes','点赞'],['saves','收藏'],['comments','评论']].map(([k,l])=>l+' '+(Number.isFinite(counts[k])?esc(counts[k]):'未提供')).join(' · ')}${Number.isFinite(r.similarity)?' · 内容相似度 '+topicsNumber(r.similarity):''}</span><span class="helper">采集于 ${esc(r.observed_at||r.collected_at||'时间未提供')} · 公开可见计数 · ${esc(({search_summary:'搜索摘要（尚未读取正文）',detail_read:'已读取正文',manual_supplied:'手工提供'})[r.content_status]||'公开参考')}</span>${r.image_note?`<span class="helper">${esc(r.image_note)}</span>`:r.image_missing?'<span class="helper">未分析参考封面，本条参考按文字匹配。</span>':''}${editable?`<div class="buttons"><button type="button" class="quiet" data-topics-public-refresh="${esc(r.id)}" ${topicsState.busy?'disabled':''}>读取正文 / 更新互动</button><button type="button" class="quiet" data-topics-public-remove="${esc(r.id)}" ${topicsState.busy?'disabled':''}>移除参考</button></div>`:''}</article>`;}).join('');}
function topicsPublicHTML(){const s=topicsState,p=s.publicData||{},connection=p.connection;
 const connected=s.publicConnected===true||connection?.ready===true;
 const connectionMessage=typeof connection==='object'?connection.message:'';
 return `<section class="panel topics-public" id="topicsReferenceStep"><span class="eyebrow">01 / 找参考</span><h2>先看看同领域在写什么</h2><p class="helper">输入你想写的方向，例如“新手摄影 夜景构图”。已经有想法，也可以直接往下比较。</p><div class="topics-search"><label>你想了解什么？<input data-topics-keyword value="${esc(s.keyword)}" maxlength="100" placeholder="例如：新手摄影 夜景构图" ${s.busy?'disabled':''}></label><button type="button" class="primary" data-topics="public-search" ${s.busy?'disabled':''}>搜索参考</button></div><details class="topics-connection" ${s.publicQR||s.publicConnected===false?'open':''}><summary>${connected?'小红书已连接 · 管理连接':'首次使用？连接小红书'}</summary><p class="helper">第一次搜索前扫码登录。以后可直接输入关键词搜索。</p><div class="buttons"><button type="button" class="quiet" data-topics="public-qrcode" ${s.busy?'disabled':''}>扫码连接小红书</button><button type="button" class="quiet" data-topics="public-status" ${s.busy?'disabled':''}>检查搜索连接</button></div>${s.publicQR?`<div class="topics-qr"><img src="${esc(s.publicQR)}" alt="小红书登录二维码"><p class="helper">扫码完成后点击“检查搜索连接”，然后搜索参考。</p></div>`:''}${connectionMessage&&!connected?`<p class="helper">${esc(connectionMessage)}</p>`:''}</details><details><summary>查看已保存的参考（${p.samples?.length||0} 条）</summary>${topicsPublicRows(p.samples,true)||'<p class="helper">搜索后会自动保存参考，下面比较选题时会一起使用。</p>'}</details><details class="topics-details"><summary>也可以手动添加一条真实参考</summary><p class="helper">搜索暂时不可用时，从公开笔记复制内容。互动数没有看到就留空。</p>${[['url','笔记链接'],['title','笔记标题']].map(([key,label])=>`<label>${label}<input data-topics-manual="${key}" value="${esc(s.manual[key]||'')}" maxlength="${key==='url'?2000:200}" ${s.busy?'disabled':''}></label>`).join('')}<label>正文<textarea data-topics-manual="body" rows="3" maxlength="20000" ${s.busy?'disabled':''}>${esc(s.manual.body||'')}</textarea></label><div class="topics-weights">${[['likes','点赞'],['saves','收藏'],['comments','评论']].map(([key,label])=>`<label>${label}（可选）<input type="number" min="0" step="1" data-topics-manual="${key}" value="${esc(s.manual[key]??'')}" ${s.busy?'disabled':''}></label>`).join('')}</div><button type="button" class="secondary" data-topics="public-import" ${s.busy?'disabled':''}>保存这条参考</button></details><p class="helper">公开互动数用于参考，不代表你未来的流量。</p></section>`;
}
function topicsResultHTML(result,config){
 if(!result)return '';
 const rows=result.candidates||[];
 return `<section class="panel topics-result"><div class="detail-heading"><div><span class="eyebrow">03 / 选一个开始创作</span><h2>${rows.some(r=>Number.isFinite(r.estimated_value))?'历史样本支持的参考估计':'先看匹配建议'}</h2></div><button type="button" class="secondary" data-topics="download">下载这次比较</button></div><p class="helper">${rows.some(r=>Number.isFinite(r.estimated_value))?'估计针对当前账号与所选观察时长，不是平台流量承诺。':'可比较的历史数据不足时，不给出热度数字；匹配度只表示内容相关程度。'}</p>${rows.map((row,index)=>`<article class="topics-result-row"><span class="eyebrow">${index+1} · 候选选题</span><h3>${esc(row.title)}</h3><div class="topics-measures"><span>匹配分（非爆款概率） <b>${topicsNumber(row.fit_score,1)}</b></span>${Number.isFinite(row.estimated_value)?`<span>${esc(config.window)} ${esc(topicsMetrics[config.metric]||config.metric)}参考值 <b>${topicsNumber(row.estimated_value,1)}</b></span>`:''}</div><p>${esc(topicsText(row.reason))}</p><p class="helper">${row.image_mode==='multimodal'?'本次已比较文字与历史封面。':row.image_mode==='crossmodal'?'本次已加入图文跨模态匹配：图片与相关文字一起参与比较。':'本次按文字比较；补充候选或历史封面后，可以加入图文匹配。'}</p><details><summary>参考了哪些历史内容（${(row.references||[]).length} 条）</summary>${(row.references||[]).map(ref=>`<div class="topics-reference"><strong>${esc(ref.title)}</strong><span class="helper">相似度 ${topicsNumber(ref.similarity)}${ref.image_mode==='crossmodal'?' · 图文跨模态匹配':ref.image_mode==='multimodal'?' · 图文匹配':''}${Number.isFinite(ref.contribution)?' · 回测帮助值 '+topicsNumber(ref.contribution):''}</span></div>`).join('')||'<p class="helper">当前没有足够的参考作品。可以先补充历史作品与对应数据。</p>'}</details>${row.public_references?.length?`<details><summary>同领域公开参考（${row.public_references.length} 条，与个人历史分开）</summary>${topicsPublicRows(row.public_references)}</details>`:''}<button type="button" class="primary" data-topics-adopt="${esc(row.id)}">用这个选题开始创作 →</button></article>`).join('')}<details class="topics-details"><summary>方法与验证说明</summary><p>${esc(topicsText(result.method))}</p><pre>${esc(typeof result.validation==='string'?result.validation:JSON.stringify(result.validation||{},null,2))}</pre><p class="helper">借鉴 SKAPP 的检索增强思路。个性化适配与作者公开数据实验分别验证；匹配度不是爆款概率。</p></details></section>`;
}
function topicsHTML(){
 const s=topicsState,c=s.config||{},h=s.data?.history||[];
 return `<div class="topics-workspace"><ol class="topics-steps" aria-label="使用步骤"><li><b>1</b> 搜参考</li><li><b>2</b> 比较选题</li><li><b>3</b> 开始创作</li></ol>${s.message?`<p class="topics-notice" role="status">${esc(s.message)}</p>`:''}${s.data?.encoder_ready?'':'<p class="topics-notice" role="status">图文编码模型尚未准备好。可以先保存定位、录入历史作品；模型就绪后再补充封面并比较选题。</p>'}${topicsPublicHTML()}<form id="topicsForm"><fieldset ${s.busy?'disabled':''}><details class="panel topics-profile" ${!c.positioning||!c.audience?'open':''}><summary>当前方向：${esc(c.positioning||'请补充账号定位')} · 修改定位和比较设置</summary><div class="detail-heading"><div><span class="eyebrow">你的方向</span><h2>${esc(currentAccount()?.name||'当前账号')}的选题设置</h2></div><button type="button" class="quiet" data-topics="save">保存设置</button></div><p class="helper">保存会同步当前账号档案中的定位与受众；其他账号不受影响。</p><div class="two-col"><label>账号定位<textarea data-topics-config="positioning" rows="2" maxlength="800" placeholder="写下你的方向和特点，不限领域">${esc(c.positioning||'')}</textarea></label><label>希望吸引谁<textarea data-topics-config="audience" rows="2" maxlength="800" placeholder="描述目标读者的兴趣、需求或使用场景">${esc(c.audience||'')}</textarea></label></div><details class="topics-details"><summary>调整比较方式（可选）</summary><div class="two-col"><label>比较发布多久后的数据<select data-topics-config="window">${['24h','72h'].map(v=>`<option value="${v}" ${c.window===v?'selected':''}>${v==='24h'?'24 小时':'72 小时'}</option>`).join('')}</select></label><label>关心什么表现<select data-topics-config="metric">${Object.entries(topicsMetrics).map(([value,label])=>`<option value="${value}" ${c.metric===value?'selected':''}>${label}</option>`).join('')}</select></label></div><p class="helper">默认均衡比较文字、图片和账号定位。下列权重用于参考排序，不代表预测准确率。</p><div class="topics-weights">${[['text_weight','文字'],['image_weight','图片'],['profile_weight','账号定位']].map(([key,label])=>`<label>${label}权重<input type="number" data-topics-config="${key}" min="0" max="1" step="0.05" value="${esc(c[key]??0)}"></label>`).join('')}<label>最多参考几篇<input type="number" data-topics-config="neighbors" min="1" max="10" step="1" value="${esc(c.neighbors||5)}"></label></div></details></details><section class="panel" id="topicsCandidateStep"><div class="detail-heading"><div><span class="eyebrow">02 / 比较选题</span><h2>写下你想发的选题</h2></div><button type="button" class="secondary" data-topics="add" ${s.candidates.length>=5?'disabled':''}>＋ 加一个选题</button></div><p class="helper">建议比较 2–5 个，也可以先试 1 个。正文写清内容角度；暂时没有封面可以只比较文字。</p><div class="topics-candidates">${s.candidates.map((r,i)=>`<article class="topics-candidate"><div class="detail-heading"><strong>选题 ${i+1}</strong>${s.candidates.length>1?`<button type="button" class="quiet" data-topics-remove="${esc(r.id)}">移除</button>`:''}</div><label>标题<input data-topics-id="${esc(r.id)}" data-topics-field="title" value="${esc(r.title)}" maxlength="200" required placeholder="这篇准备讲什么？"></label><label>内容角度 / 正文<textarea data-topics-id="${esc(r.id)}" data-topics-field="body" rows="4" maxlength="6000" placeholder="写下核心内容，或粘贴准备发布的正文">${esc(r.body)}</textarea></label><label>封面图片（可选，JPG / PNG / WebP，最大 3 MB）<span class="helper">分析时自动缩小，原文件不变。</span><input type="file" data-topics-image="${esc(r.id)}" accept="image/jpeg,image/png,image/webp"></label>${r.image?`<div class="topics-preview"><img src="${esc(r.image)}" alt="选题 ${i+1} 的待比较封面"><span>${esc(r.imageName)}</span><button type="button" class="quiet" data-topics-clear-image="${esc(r.id)}">移除图片</button></div>`:''}</article>`).join('')}</div><div class="buttons"><button type="submit" class="primary" ${s.data?.encoder_ready?'':'disabled'}>${s.busy?'正在处理…':'比较这些选题'}</button><span class="helper">自动使用你的账号定位和已保存参考；比较后选一个开始创作。</span></div></section></fieldset></form><div id="topicsResults" aria-live="polite">${topicsResultHTML(s.result,c)}</div><details class="panel topics-details"><summary>补充自己的历史作品（可选，${h.length} 条）</summary><div class="detail-heading"><div><span class="eyebrow">比较依据</span><h2>当前账号的历史作品</h2></div><a class="secondary" href="#accounts">添加历史作品 →</a></div><p class="helper">先在“账号档案与历史”录入实际作品，在“作品与复盘”记录数据，再在这里补充封面。同一观察时长的数据才适合比较。封面分析时自动缩小，原文件不变。</p>${h.length?`<div class="topics-history">${h.map(row=>`<article><div><strong>${esc(row.title)}</strong><p class="helper">${row.eligible?'可用于当前比较':esc(topicsText(row.exclusion)||'暂不满足当前比较条件')} · ${row.has_image?'已保存封面':'还没有封面'}</p></div><label class="topics-upload-label">${row.has_image?'更换封面':'补充封面'}<input type="file" accept="image/jpeg,image/png,image/webp" data-topics-history="${esc(row.id)}" ${s.busy||!s.data?.encoder_ready?'disabled':''}></label></article>`).join('')}</div>`:'<p class="topics-notice">当前还没有历史作品，也可以先用公开参考比较选题。</p>'}<a href="#metrics">去记录作品数据 →</a><button type="button" class="quiet" data-topics="refresh" ${s.busy?'disabled':''}>刷新历史</button></details></div>`;
}
function topicsPaint(){if(currentPage!=='topics'||topicsState.account!==activeAccountId)return;$('operationsContent').innerHTML=topicsHTML();topicsBind();}
async function renderTopics(){
 const account=activeAccountId;if(!account){$('operationsContent').innerHTML='<section class="panel"><h2>先选择一个账号</h2><a href="#accounts">创建账号档案 →</a></section>';return;}
 if(topicsState.account!==account){resetTopics();topicsState.account=account;topicsState.candidates=[topicsCandidate(),topicsCandidate()];}
 if(topicsState.busy){topicsPaint();return;}
 const sequence=++topicsSequence;
 $('operationsContent').innerHTML='<section class="panel" role="status">正在读取当前账号的选题设置…</section>';
 try{const data=await api('/api/topics?account_id='+encodeURIComponent(account));if(!topicsLive(account,sequence)||currentPage!=='topics')return;
 if(topicsState.data?.version!==data.version||topicsState.data?.account_revision!==data.account_revision)topicsState.result=null;
 topicsState.data=data;topicsState.config={...data.config};topicsState.message='';topicsPaint();
 try{const publicData=await api('/api/topics/public?account_id='+encodeURIComponent(account));if(!topicsLive(account,sequence)||currentPage!=='topics')return;topicsState.publicData=publicData;if(Number.isInteger(publicData.version))topicsState.data.version=publicData.version;topicsPaint();}catch(e){if(topicsLive(account,sequence)){topicsState.publicData={samples:[],connection:{message:'公开参考暂时没有读到：'+e.message}};topicsPaint();}}}
 catch(e){if(!topicsLive(account,sequence)||currentPage!=='topics')return;$('operationsContent').innerHTML=`<section class="panel"><h2>选题设置暂时没有读到</h2><p>${esc(e.message)}</p><button id="topicsReload" class="secondary">重新读取</button></section>`;$('topicsReload').onclick=renderTopics;}
}
function topicsInvalidate(){topicsState.result=null;if(currentPage==='topics'&&$('topicsResults'))$('topicsResults').innerHTML='';}
function topicsConfigValue(key,value){return ['text_weight','image_weight','profile_weight','neighbors'].includes(key)?Number(value):value;}
function topicsPayload(){return topicsState.candidates.map(({id,title,body,image})=>({id,title:title.trim(),body:body.trim(),image}));}
async function topicsReadImage(file){
 if(!file)return '';
 if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw new Error('请使用 JPG、PNG 或 WebP 图片。');
 if(file.size>3*1024*1024)throw new Error('这张图片超过 3 MB，请压缩后再上传。');
 let bitmap;
 try{bitmap=await createImageBitmap(file);}catch(_){throw new Error('图片无法读取，请换一张静态 JPG、PNG 或 WebP 图片。');}
 try{
  if(!bitmap.width||!bitmap.height||bitmap.width*bitmap.height>16000000)throw new Error('图片超过 1600 万像素，请缩小后再上传。');
  const canvas=document.createElement('canvas'),scale=Math.min(1,1024/Math.max(bitmap.width,bitmap.height));
  canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));
  const ctx=canvas.getContext('2d',{alpha:false});if(!ctx)throw new Error('当前浏览器无法处理图片，请使用新版 Chrome 再试。');
  ctx.fillStyle='#ffffff';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);
  let encoded=canvas.toDataURL('image/jpeg',.85);
  // Bound each data URL so five candidates fit the website's 8 MB request limit.
  if(encoded.length>1000000)encoded=canvas.toDataURL('image/jpeg',.65);
  if(!encoded.startsWith('data:image/jpeg;base64,')||encoded.length>1000000)throw new Error('这张图片压缩后仍较大，请换一张尺寸更小的图片。');
  return encoded;
 }finally{bitmap.close();}
}
async function topicsAction(action,publicationId='',file=null){
 if(topicsState.busy)return;const account=activeAccountId,sequence=topicsSequence,s=topicsState;
 if(s.account!==account||!s.data)return;
 if(action==='evaluate'&&!s.data.encoder_ready){s.message='图文模型尚未准备好，请稍后刷新。';topicsPaint();return;}
 if(action==='evaluate'&&s.candidates.some(r=>!r.title.trim())){s.message='每个候选选题都需要一个标题。';topicsPaint();return;}
 s.busy=true;s.message=action==='evaluate'?'正在本机编码图文并比较历史，首次使用可能需要稍等…':'正在保存…';topicsPaint();
 try{
 if(action==='history'){
 const image=await topicsReadImage(file);if(!topicsLive(account,sequence))return;
 const data=await api('/api/topics/history-image','POST',{account_id:account,version:s.data.version,publication_id:publicationId,image});
 if(!topicsLive(account,sequence))return;s.data=data;s.result=null;s.message='封面已保存，将用于下次图文比较。';
 }else{
 const data=await api('/api/topics/config','POST',{account_id:account,version:s.data.version,config:s.config});if(!topicsLive(account,sequence))return;
 s.data=data;s.config={...data.config};s.result=null;
 if(typeof syncAccounts==='function'){const refreshed=await api('/api/operations');if(!topicsLive(account,sequence))return;ops=refreshed;syncAccounts();}
 if(action==='evaluate'){
 const result=await api('/api/topics/evaluate','POST',{account_id:account,version:data.version,candidates:topicsPayload()});if(!topicsLive(account,sequence))return;
 s.result=result;if(Number.isInteger(result.version))s.data.version=result.version;s.message='比较完成。先看匹配依据，再决定下一篇。';
 }else{s.message='当前账号的选题设置已保存。';}
 }
 }catch(e){if(!topicsLive(account,sequence))return;s.result=null;s.message=e.code==='VERSION_CONFLICT'?'设置或历史刚刚发生了变化。已保留候选选题，请点“刷新历史”后再比较。':e.message;if(typeof noticeSeverity==='function'&&noticeSeverity(e)==='critical')error(e);}
 finally{if(topicsLive(account,sequence)){s.busy=false;topicsPaint();}}
}
async function topicsSearchPublic(){
 const s=topicsState,account=activeAccountId,sequence=topicsSequence;if(s.busy||!s.data||s.account!==account)return;
 const keyword=s.keyword.trim();if(!keyword){s.message='先输入一个具体的搜索关键词。';topicsPaint();return;}
 s.busy=true;s.message='正在搜索公开参考，已有候选选题会保留…';topicsPaint();
 try{const data=await api('/api/topics/public/search','POST',{account_id:account,version:s.data.version,keyword});if(!topicsLive(account,sequence))return;s.publicData=data;s.publicConnected=true;if(Number.isInteger(data.version))s.data.version=data.version;s.result=null;s.message=(data.samples?.length?'公开参考已保存。现在可以比较候选选题。':'这次没有找到可用参考，可以换一个更具体的关键词。')+(data.warnings?.length?' '+data.warnings.join('；'):'');}
 catch(e){if(!topicsLive(account,sequence))return;s.message=e.code==='VERSION_CONFLICT'?'资料刚刚发生变化，请刷新历史后再搜索。':e.message;}
 finally{if(topicsLive(account,sequence)){s.busy=false;topicsPaint();}}
}
async function topicsManagePublic(action,sampleId=''){
 const s=topicsState,account=activeAccountId,sequence=topicsSequence;if(s.busy||!s.data||s.account!==account)return;
 const payload={account_id:account,version:s.data.version};
 if(action==='import'){
  const m=s.manual;if(!topicsSafeURL(m.url)||!m.title?.trim()){s.message='请填写有效的公开笔记链接和标题。';topicsPaint();return;}
  const counts={};for(const key of ['likes','saves','comments']){const raw=m[key];if(raw===undefined||raw.trim()===''){counts[key]=null;continue;}const n=Number(raw);if(!Number.isSafeInteger(n)||n<0){s.message='互动数请填写非负整数，没有看到的数据留空。';topicsPaint();return;}counts[key]=n;}
  payload.samples=[{url:m.url.trim(),title:m.title.trim(),body:(m.body||'').trim(),counts}];
 }else payload.sample_id=sampleId;
 s.busy=true;s.message=action==='refresh'?'正在读取正文和当前互动，已有快照会保留…':'正在保存参考库…';topicsPaint();
 try{const data=await api('/api/topics/public/'+action,'POST',payload);if(!topicsLive(account,sequence))return;s.publicData=data;if(Number.isInteger(data.version))s.data.version=data.version;s.result=null;if(action==='import')s.manual={};s.message=action==='remove'?'参考已移除。':action==='refresh'?'已更新参考；新旧互动快照分开保留。':'真实参考已保存。';if(data.warnings?.length)s.message+=' '+data.warnings.join('；');}
 catch(e){if(topicsLive(account,sequence))s.message=e.message;}
 finally{if(topicsLive(account,sequence)){s.busy=false;topicsPaint();}}
}
async function topicsConnect(mode){
 const s=topicsState,account=activeAccountId,sequence=topicsSequence;if(s.busy||s.account!==account)return;
 s.busy=true;s.message=mode==='qrcode'?'正在获取登录二维码…':'正在检查搜索连接…';topicsPaint();
 try{const response=await api('/api/topics/public/connect','POST',{account_id:account,mode});if(!topicsLive(account,sequence))return;const data=response.data||response;if(typeof data.is_logged_in==='boolean')s.publicConnected=data.is_logged_in;
 if(mode==='qrcode'){const img=data.img||data.image||data.qrcode||'';s.publicQR=/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=\s]+$/.test(img)?img:(/^[A-Za-z0-9+/=\s]+$/.test(img)&&img.length>100?'data:image/png;base64,'+img:'');s.message=s.publicQR?'请用小红书扫描二维码，再检查连接。':(data.is_logged_in?'搜索账号已登录，可以开始搜索。':'二维码暂时没有取到，请稍后重新获取。');}
 else{s.message=data.is_logged_in?'搜索账号已登录，可以开始搜索。':'尚未登录搜索账号，请点击“扫码连接小红书”。';if(data.is_logged_in)s.publicQR='';}
 }catch(e){if(topicsLive(account,sequence))s.message=e.message;}
 finally{if(topicsLive(account,sequence)){s.busy=false;topicsPaint();}}
}
function topicsDownload(){
 if(!topicsState.result)return;
 const data={...topicsState.result,account_id:topicsState.account,config:topicsState.config,exported_at:new Date().toISOString()};
 const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='youji-topic-comparison.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function topicsAdopt(id){const c=topicsState.candidates.find(r=>r.id===id),config=topicsState.config;if(!c||!topicsState.result||topicsState.account!==activeAccountId)return;if(startCreation()){$('topic').value=c.title;$('audience').value=config.audience;$('material').value=c.body;toast('已带入选题、目标读者与正文。封面比较结果保留在选题潜力页。');}}
function topicsBind(){
 const host=$('operationsContent');
 $('topicsForm').onsubmit=e=>{e.preventDefault();topicsAction('evaluate');};
 host.oninput=e=>{const t=e.target;if(topicsState.busy)return;if(t.dataset.topicsManual){topicsState.manual[t.dataset.topicsManual]=t.value;}else if(t.dataset.topicsKeyword!==undefined){topicsState.keyword=t.value;}else if(t.dataset.topicsConfig){topicsState.config[t.dataset.topicsConfig]=topicsConfigValue(t.dataset.topicsConfig,t.value);topicsInvalidate();}else if(t.dataset.topicsField){const c=topicsState.candidates.find(r=>r.id===t.dataset.topicsId);if(c){c[t.dataset.topicsField]=t.value;topicsInvalidate();}}};
 host.onchange=async e=>{const t=e.target;if(topicsState.busy)return;if(t.dataset.topicsHistory){if(t.files[0])await topicsAction('history',t.dataset.topicsHistory,t.files[0]);return;}if(t.dataset.topicsImage){const account=activeAccountId,sequence=topicsSequence,c=topicsState.candidates.find(r=>r.id===t.dataset.topicsImage);if(!c||!t.files[0])return;const file=t.files[0];topicsState.busy=true;topicsState.message='正在读取封面…';topicsPaint();try{const image=await topicsReadImage(file);if(!topicsLive(account,sequence)||!topicsState.candidates.includes(c))return;c.image=image;c.imageName=file.name;topicsInvalidate();topicsState.message='封面已加入候选，点击比较后才会处理。';topicsPaint();}catch(err){if(topicsLive(account,sequence)){topicsState.message=err.message;}}finally{if(topicsLive(account,sequence)){topicsState.busy=false;topicsPaint();}}}};
 host.onclick=e=>{const b=e.target.closest('button');if(!b||topicsState.busy)return;const d=b.dataset;if(d.topicsPublicRefresh)topicsManagePublic('refresh',d.topicsPublicRefresh);else if(d.topicsPublicRemove)topicsManagePublic('remove',d.topicsPublicRemove);else if(d.topics==='public-import')topicsManagePublic('import');else if(d.topics==='public-status')topicsConnect('status');else if(d.topics==='public-qrcode')topicsConnect('qrcode');else if(d.topics==='public-search')topicsSearchPublic();else if(d.topics==='add'){if(topicsState.candidates.length<5){topicsState.candidates.push(topicsCandidate());topicsInvalidate();topicsPaint();}}else if(d.topics==='save')topicsAction('save');else if(d.topics==='refresh')renderTopics();else if(d.topics==='download')topicsDownload();else if(d.topicsRemove){if(topicsState.candidates.length>1){topicsState.candidates=topicsState.candidates.filter(r=>r.id!==d.topicsRemove);topicsInvalidate();topicsPaint();}}else if(d.topicsClearImage){const c=topicsState.candidates.find(r=>r.id===d.topicsClearImage);if(c){c.image='';c.imageName='';topicsInvalidate();topicsPaint();}}else if(d.topicsAdopt)topicsAdopt(d.topicsAdopt);};
}
