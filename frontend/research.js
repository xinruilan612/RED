'use strict';
pageInfo.research=['RESEARCH / CASES','把案例研究，变成可引用的资料。','搜索、读取、整理和导出；表达参考与商品事实分别保存。'];
let researchLoad=0,researchTimer=null,researchBusy=false,researchPending=null;
let researchCaseEdit=null,caseEditLoad=0,transcriptBusy=false,transcriptResult=null;
function researchRequest(data){
 const fingerprint=JSON.stringify(data);
 if(!researchPending||researchPending.fingerprint!==fingerprint)researchPending={fingerprint,key:crypto.randomUUID()};
 return {...data,key:researchPending.key};
}
const researchStates={queued:'等待后台',running:'正在研究',done:'已完成',partial:'部分完成',failed:'未取得正文',interrupted:'执行中断，请核对后新建',cancelled:'已取消'};
function researchSourceLink(url,label){
 try{const u=new URL(url);if(!['https:','http:'].includes(u.protocol))return esc(label);return `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;}
 catch(_){return esc(label);}
}
function caseDocumentText(chunks){
 const pages=new Map();
 for(const c of [...(chunks||[])].sort((a,b)=>(a.page-b.page)||(a.offset-b.offset))){
  const page=pages.get(c.page)||[],text=Array.from(c.text||''),start=Number(c.offset)||0;
  if(start>page.length)throw new Error('案例原文片段缺失，请刷新后重试');
  const overlap=Math.max(0,page.length-start);
  page.push(...text.slice(overlap));pages.set(c.page,page);
 }
 return [...pages.values()].map(chars=>chars.join('')).join('\n\n');
}
function caseLocalDate(value){
 if(!value)return '';
 const d=new Date(value);if(Number.isNaN(d.getTime()))throw new Error('案例时间无效');
 return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,-1);
}
function setCaseChoice(id,value){
 const select=$(id);select.value=value;
 if(select.value!==value){const option=document.createElement('option');option.value=value;option.textContent=value;select.appendChild(option);select.value=value;}
}
function fillCaseEditor(doc,account){
 const c=doc.metadata?.research_case;
 if(doc.source_type!=='research_case'||!c)throw new Error('此资料不是可编辑的研究案例');
 const body=caseDocumentText(doc.chunks),dates={published_at:c.published_at,observed_at:c.observed_at};
 researchCaseEdit={account_id:account,document_id:doc.id,expected_version:doc.version,dates,
  dateInputs:{published_at:caseLocalDate(dates.published_at),observed_at:caseLocalDate(dates.observed_at)}};
 $('caseTitle').value=doc.title;$('caseText').value=body;$('caseUrl').value=doc.source_url||'';$('caseAuthor').value=c.author||'';
 setCaseChoice('casePlatform',c.platform);setCaseChoice('caseKind',c.content_kind);setCaseChoice('caseRole',c.evidence_role);
 $('casePublished').value=researchCaseEdit.dateInputs.published_at;$('caseObserved').value=researchCaseEdit.dateInputs.observed_at;
 for(const key of ['views','likes','favorites','comments','shares'])$('caseMetric-'+key).value=c.metrics?.[key]??'';
 $('caseMinInteractions').value=c.assessment?.policy?.min_interactions??1000;$('caseMaxAge').value=c.assessment?.policy?.max_age_days??30;
 $('casePermission').checked=false;$('caseEditorStatus').textContent=`正在编辑「${doc.title}」第 ${doc.version} 版；保存后保留历史版本，请重新确认资料使用权限。`;
 if(c.review_required){$('caseEditorStatus').textContent+=' 本地转写可能存在同音字和断句错误；未校对前不进入 RAG，请逐段核对。';}
 $('caseSaveButton').textContent=c.review_required?'已校对，保存新版本并用于检索':'保存案例新版本';$('caseCancelEdit').hidden=false;$('caseEditorDetails').open=true;
 $('researchCaseForm').scrollIntoView?.({behavior:'smooth',block:'start'});
}
function clearCaseEditor(){
 ++caseEditLoad;researchCaseEdit=null;$('researchCaseForm').reset();
 $('caseEditorStatus').textContent='';$('caseSaveButton').textContent='保存案例并建立检索';$('caseCancelEdit').hidden=true;
}
async function editResearchCase(identity,account){
 const request=++caseEditLoad,pageToken=researchLoad;
 const doc=await api('/api/knowledge/'+encodeURIComponent(identity)+'?account_id='+encodeURIComponent(account));
 if(request!==caseEditLoad||account!==activeAccountId||currentPage!=='research'||pageToken!==researchLoad)return;
 fillCaseEditor(doc,account);
}
function researchCasePayload(account){
 if(researchCaseEdit&&researchCaseEdit.account_id!==account)throw new Error('编辑账号已切换，请重新打开案例');
 const metrics=Object.fromEntries(['views','likes','favorites','comments','shares'].map(k=>[k,$('caseMetric-'+k).value===''?null:Number($('caseMetric-'+k).value)]));
 const date=(id,key)=>{const value=$(id).value;if(researchCaseEdit&&value===researchCaseEdit.dateInputs[key])return researchCaseEdit.dates[key];return value?new Date(value).toISOString():null;};
 const data={account_id:account,title:$('caseTitle').value,text:$('caseText').value,source_url:$('caseUrl').value,platform:$('casePlatform').value,author:$('caseAuthor').value,content_kind:$('caseKind').value,evidence_role:$('caseRole').value,published_at:date('casePublished','published_at'),observed_at:date('caseObserved','observed_at'),metrics,permission_confirmed:$('casePermission').checked,policy:{min_interactions:Number($('caseMinInteractions').value),max_age_days:Number($('caseMaxAge').value)}};
 if(researchCaseEdit){data.document_id=researchCaseEdit.document_id;data.expected_version=researchCaseEdit.expected_version;}
 return data;
}
function transcriptFileBase64(file){
 return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败，请重新选择'));reader.readAsDataURL(file);});
}
async function submitTranscript(event,account,pageToken){
 event.preventDefault();if(transcriptBusy)return;
 const file=$('transcriptFile').files?.[0],title=$('transcriptTitle').value.trim(),status=$('transcriptStatus'),button=event.submitter;
 const current=()=>account===activeAccountId&&currentPage==='research'&&pageToken===researchLoad;
 try{
  if(!current())throw new Error('账号或页面已变化，请重新选择文件');
  transcriptResult=null;
  if(!file||!file.size)throw new Error('请选择有内容的音频或视频文件');
  if(file.size>10*1024*1024)throw new Error('文件超过 10 MiB，请截取不超过 120 秒的片段');
  if(!/\.(mp4|mov|m4a|mp3|wav|aiff|flac|ogg|webm)$/i.test(file.name))throw new Error('文件类型不支持，请选择列表中的音频或视频格式');
  if(!title||title.length>200)throw new Error('请填写 1–200 字的标题');
  if(!$('transcriptPermission').checked)throw new Error('请先确认你有权处理这份媒体');
  transcriptBusy=true;button.disabled=true;const editorRequest=caseEditLoad;
  status.textContent='正在本机 CPU 转写，可能需要数分钟；不调用收费模型。请等待结果，文字需人工校对。';
  const file_base64=await transcriptFileBase64(file);
  if(!current())return;
  const doc=await api('/api/research/transcripts','POST',{account_id:account,title,filename:file.name,file_base64,permission_confirmed:true});
  if(!current())return;
  transcriptResult={document_id:doc.id,account_id:account,pageToken};
  status.textContent='转写已保存，尚不参与检索。请校对正文并点击“已校对，保存新版本并用于检索”。';
  if(editorRequest===caseEditLoad){++caseEditLoad;fillCaseEditor(doc,account);}
  else status.textContent='转写已保存，尚不参与检索。当前案例编辑未被覆盖，请在列表选择这份转写进行校对。';
  await refreshResearchJobs(account,pageToken);
 }catch(err){if(current())status.textContent=err.message||'转写失败，请核对文件后重试；所选文件仍保留。';}
 finally{transcriptBusy=false;if(button)button.disabled=false;if(currentPage==='research'&&$('transcriptSubmit'))$('transcriptSubmit').disabled=false;}
}
function caseCards(cases){
 return cases.map(d=>{
  const c=d.metadata?.research_case||{},a=c.assessment||{};
  return `<article class="panel"><div class="detail-heading"><h3>${esc(d.title)}</h3>${badge(c.evidence_role==='product_fact'?'商品事实 · 待核验':'表达参考','neutral')}</div><p class="helper">${esc(c.platform||'')} · ${esc(c.author||'作者未知')} · v${d.version}</p><p>${badge(c.review_required?'转写待校对 · 暂不参与检索':a.status==='high_interaction_candidate'?'高互动候选':c.content_kind==='lead'?'未读线索 · 不参与检索':'已保存案例','amber')} ${esc(a.limitation||'')}</p><p class="helper">已知互动：${a.known_interactions==null?'未知':esc(a.known_interactions)} · 观察时间：${c.observed_at?esc(dateText(c.observed_at)):'未知'}</p><p>${d.source_url?researchSourceLink(d.source_url,'查看原始来源 ↗'):'用户提供资料，无公开链接'}</p><button class="quiet" data-case-detail="${esc(d.id)}">查看正文与依据</button><button class="quiet" data-case-edit="${esc(d.id)}">编辑案例</button><div id="caseDetail-${esc(d.id)}"></div></article>`;
 }).join('')||'<section class="panel"><p>还没有案例。可以发起一次公开网页研究，或添加你有权使用的正文、字幕与指标。</p></section>';
}
function jobCards(jobs){
 return jobs.map(j=>`<article class="panel"><div class="detail-heading"><h3>${esc((j.queries||[]).join('；'))}</h3>${badge(researchStates[j.status]||j.status,j.status==='done'?'':'amber')}</div><p class="helper">${esc(j.provider||'')} · ${esc((j.targets||[]).join(' / '))} · ${esc(dateText(new Date(j.created_at*1000).toISOString()))}</p><p>已保存 ${(j.documents||[]).length} 份正文；检索覆盖与读取失败记录随研究文档导出。</p>${j.error?`<p class="issue">${esc(j.error)}</p>`:''}<div class="buttons">${['done','partial','failed','interrupted','cancelled'].includes(j.status)?`<a class="button quiet" href="/api/research/jobs/${encodeURIComponent(j.id)}/export">下载本次研究文档</a>`:''}${['queued','running'].includes(j.status)?`<button class="quiet" data-cancel-research="${esc(j.id)}">停止本次研究</button>`:''}</div><details><summary>查看读取记录</summary>${(j.reads||[]).map(r=>`<p>${researchSourceLink(r.url,r.url)}<br>${esc(r.error||r.status||'')}</p>`).join('')||'<p>尚无网页读取记录。</p>'}</details></article>`).join('')||'<p class="helper">尚未发起后台案例研究。</p>';
}
function bindCaseDetails(account){
 document.querySelectorAll('[data-case-edit]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await editResearchCase(b.dataset.caseEdit,account);}catch(e){error(e);}finally{b.disabled=false;}});
 document.querySelectorAll('[data-case-detail]').forEach(b=>b.onclick=async()=>{
  b.disabled=true;
  try{
   const d=await api('/api/knowledge/'+encodeURIComponent(b.dataset.caseDetail)+'?account_id='+encodeURIComponent(account));
   if(account!==activeAccountId||currentPage!=='research')return;
   const host=$('caseDetail-'+b.dataset.caseDetail);if(!host)return;
   host.innerHTML=(d.chunks||[]).map(c=>`<blockquote>${esc(c.text)}</blockquote>`).join('')+`<p class="helper">${esc(d.metadata?.research_case?.verification||'来源未独立核验')}</p>`;
  }catch(e){error(e);}finally{b.disabled=false;}
 });
}
async function refreshResearchJobs(account,token){
 if(currentPage!=='research'||activeAccountId!==account||token!==researchLoad)return;
 try{
  const jobs=await api('/api/research/jobs?account_id='+encodeURIComponent(account));
  if(currentPage!=='research'||activeAccountId!==account||token!==researchLoad)return;
  $('researchJobs').innerHTML=jobCards(jobs);
  document.querySelectorAll('[data-cancel-research]').forEach(b=>b.onclick=async()=>{
   b.disabled=true;
   try{await api('/api/research/jobs/'+encodeURIComponent(b.dataset.cancelResearch)+'/cancel','POST',{});await refreshResearchJobs(account,token);}
   catch(e){error(e);}finally{b.disabled=false;}
  });
  const cases=await api('/api/research/cases?account_id='+encodeURIComponent(account));
  if(currentPage!=='research'||activeAccountId!==account||token!==researchLoad)return;
  $('researchCases').innerHTML=caseCards(cases);bindCaseDetails(account);
  clearTimeout(researchTimer);
  if(jobs.some(j=>['queued','running'].includes(j.status)))researchTimer=setTimeout(()=>refreshResearchJobs(account,token),5000);
 }catch(e){if(currentPage==='research'&&token===researchLoad)error(e);}
}
function researchProviderOptions(settings){
 return (settings.providers||[]).map(p=>`<option value="${esc(p.id)}" ${p.can_attempt?'':'disabled'}>${esc(p.name)} · ${esc(p.status_note||'当前连接未核验')}</option>`).join('')+'<option value="xhs_local">小红书站内视频（需绑定本机账号；当前连接未核验）</option>';
}
async function refreshResearchProviders(account,token){
 try{
  const settings=await api('/api/search/settings');
  if(currentPage!=='research'||activeAccountId!==account||token!==researchLoad)return;
  const select=$('researchProvider'),previous=select.value;
  select.innerHTML=researchProviderOptions(settings);
  if(previous==='xhs_local'||settings.providers?.some(p=>p.id===previous&&p.can_attempt))select.value=previous;
 }catch(e){if(currentPage==='research'&&activeAccountId===account&&token===researchLoad)error(e);}
}
async function renderResearch(){
 const token=++researchLoad,account=activeAccountId;clearTimeout(researchTimer);++caseEditLoad;researchCaseEdit=null;transcriptResult=null;
 const settings={providers:[{id:'bing',name:'Bing 公开网页（实验）',can_attempt:true},{id:'wikipedia',name:'百科背景资料',can_attempt:true},{id:'baidu',name:'百度 AI 搜索',can_attempt:false,status_note:'配置状态加载中'}]};
 $('operationsContent').innerHTML=`<section class="panel"><div class="detail-heading"><h2>自动整理一次案例研究</h2><a class="button quiet" href="/api/research/cases/export?account_id=${encodeURIComponent(account)}">导出本账号案例文档</a></div><p class="muted">后台最多搜索 2 组关键词，尝试读取 6 个网页，保存最多 3 份正文。关闭页面后继续执行。搜索摘要不当作正文，未知互动不补零。</p><form id="researchCollectForm"><label for="researchQueries">搜索词（每行一组，最多两组）</label><textarea id="researchQueries" rows="2" required maxlength="241" placeholder="例如：敏感肌 防晒 产品对比&#10;品牌 产品名称 成分"></textarea><div class="two-col"><div><label for="researchProvider">搜索服务</label><select id="researchProvider">${researchProviderOptions(settings)}</select></div><div><label for="researchRole">资料用途</label><select id="researchRole"><option value="expression_reference">表达参考：学习结构与方法</option><option value="product_fact">商品事实：仍需核验产品与来源</option></select></div></div><fieldset class="research-scopes"><legend>搜索范围</legend><label class="checkbox"><input name="researchScope" type="checkbox" value="web" checked> 全网</label><label class="checkbox"><input name="researchScope" type="checkbox" value="jd"> 京东网页（域名过滤）</label><label class="checkbox"><input name="researchScope" type="checkbox" value="taobao"> 淘宝 / 天猫网页（域名过滤）</label><label class="checkbox"><input name="researchScope" type="checkbox" value="xiaohongshu"> 小红书搜索线索</label></fieldset><p class="helper">当前连接未实测；配置只表示可尝试搜索。京东、淘宝仅按搜索引擎收录域名过滤，未接通平台专用接口。搜索引擎的小红书结果仅保留线索。选择“小红书站内视频”时，通过已绑定本机账号按最多点赞查找半年内视频，最多读取 3 篇文字描述及互动；不等于视频转写。</p><label class="checkbox"><input id="researchPermission" type="checkbox" required> 我确认本次资料研究的使用权限，并授权在所选范围和次数内自动搜索、读取与保存</label><button class="primary" type="submit">开始后台研究</button></form></section><section><div class="section-toolbar"><h2>研究任务</h2><button id="refreshResearch" class="quiet">刷新</button></div><div id="researchJobs"><p>正在读取任务…</p></div></section><section class="panel"><details id="caseEditorDetails"><summary>添加或编辑已有案例、视频字幕或商品事实</summary><form id="researchCaseForm"><p id="caseEditorStatus" class="helper" aria-live="polite"></p><label for="caseTitle">标题</label><input id="caseTitle" required maxlength="200"><div class="two-col"><div><label for="casePlatform">来源平台</label><select id="casePlatform"><option value="xiaohongshu">小红书</option><option value="public_web">公开网页</option><option value="jd">京东</option><option value="taobao">淘宝 / 天猫</option><option value="owned">自有资料</option></select></div><div><label for="caseAuthor">作者 / 品牌（可选）</label><input id="caseAuthor" maxlength="200"></div></div><label for="caseUrl">原始链接（可选）</label><input id="caseUrl" type="url"><div class="two-col"><div><label for="caseKind">内容类型</label><select id="caseKind"><option value="text">已取得正文</option><option value="transcript">已有视频字幕 / 转写</option><option value="lead">只有搜索线索（不进入 RAG）</option></select></div><div><label for="caseRole">证据类别</label><select id="caseRole"><option value="expression_reference">表达参考</option><option value="product_fact">商品事实资料（待核验）</option></select></div></div><label for="caseText">正文或字幕</label><textarea id="caseText" required maxlength="100000" rows="7" placeholder="粘贴有权使用的内容；不会因提供标题就视为已读取视频"></textarea><div class="two-col"><div><label for="casePublished">发布时间（可选）</label><input id="casePublished" type="datetime-local" step="0.001"></div><div><label for="caseObserved">指标观察时间（填写指标时必填）</label><input id="caseObserved" type="datetime-local" step="0.001"></div></div><div class="research-metrics">${[['views','播放 / 阅读'],['likes','点赞'],['favorites','收藏'],['comments','评论'],['shares','分享']].map(([k,v])=>`<div><label for="caseMetric-${k}">${v}</label><input id="caseMetric-${k}" type="number" min="0" max="1000000000000" step="1" placeholder="未知留空"></div>`).join('')}</div><div class="two-col"><div><label for="caseMinInteractions">高互动候选最低已知互动量</label><input id="caseMinInteractions" type="number" value="1000" min="1" max="1000000000" required></div><div><label for="caseMaxAge">发布后观察窗口（天）</label><input id="caseMaxAge" type="number" value="30" min="1" max="3650" required></div></div><label class="checkbox"><input id="casePermission" type="checkbox" required> 我有权保存和使用这份资料，知晓案例表达不能证明我的产品功效或亲身体验</label><button id="caseSaveButton" class="primary">保存案例并建立检索</button><button id="caseCancelEdit" type="button" class="quiet" hidden>取消编辑</button></form></details></section><div class="section-toolbar"><h2>已保存案例</h2><p class="helper">可在创作工作台勾选引用，或在资料库检索与移除。</p></div><div id="researchCases"></div>`;
 document.querySelectorAll('[name="researchScope"]').forEach(box=>box.onchange=()=>{
  if(box.checked)document.querySelectorAll('[name="researchScope"]').forEach(other=>{if((box.value==='web'&&other!==box)||(box.value!=='web'&&other.value==='web'))other.checked=false;});
 });
 $('researchProvider').onchange=()=>{if($('researchProvider').value==='xhs_local'){document.querySelectorAll('[name="researchScope"]').forEach(box=>box.checked=box.value==='xiaohongshu');$('researchRole').value='expression_reference';}if($('researchProvider').value==='wikipedia')document.querySelectorAll('[name="researchScope"]').forEach(box=>box.checked=box.value==='web');};
 refreshResearchProviders(account,token);
 $('refreshResearch').onclick=()=>refreshResearchJobs(account,token);
 $('researchCollectForm').onsubmit=async e=>{
  e.preventDefault();if(researchBusy)return;
  const queries=$('researchQueries').value.split('\n').map(q=>q.trim()).filter(Boolean),targets=[...document.querySelectorAll('[name="researchScope"]:checked')].map(b=>b.value);
  if(!queries.length||queries.length>2||queries.some(q=>q.length<2||q.length>120)){error(new Error('请填写最多两组搜索词，每组 2–120 字'));return;}
  if(!targets.length){error(new Error('请选择搜索范围'));return;}
  if($('researchProvider').value==='baidu'&&!window.confirm('本次后台研究最多调用百度搜索 2 次，使用你保存的搜索密钥并可能产生费用。确认开始？'))return;
  researchBusy=true;e.submitter.disabled=true;
  try{await api('/api/research/jobs','POST',researchRequest({account_id:account,queries,provider:$('researchProvider').value,targets,evidence_role:$('researchRole').value,permission_confirmed:$('researchPermission').checked}));researchPending=null;toast('研究任务已加入后台队列');await refreshResearchJobs(account,token);}
  catch(err){error(err);}finally{researchBusy=false;e.submitter.disabled=false;}
 };
 if($('transcriptForm'))$('transcriptForm').onsubmit=e=>submitTranscript(e,account,token);
 $('transcriptFile').onchange=()=>{const file=$('transcriptFile').files?.[0];if(file&&!$('transcriptTitle').value)$('transcriptTitle').value=file.name.replace(/\.[^.]+$/,'').slice(0,200);};
 $('caseCancelEdit').onclick=()=>clearCaseEditor();
 $('researchCaseForm').onsubmit=async e=>{
  e.preventDefault();e.submitter.disabled=true;const editorRequest=caseEditLoad;
  try{
   const data=researchCasePayload(account);
   const saved=await api('/api/research/cases','POST',data);
   if(account===activeAccountId&&currentPage==='research'&&token===researchLoad){
    if(transcriptResult?.document_id===data.document_id&&transcriptResult.account_id===account&&transcriptResult.pageToken===token&&saved.id===data.document_id&&!saved.metadata?.research_case?.review_required){
     $('transcriptStatus').textContent=saved.metadata?.retrieval_eligible===true?'已校对并保存，可参与检索。':'已校对并保存；当前资料类型不参与检索。';
    }
    toast(data.document_id?'案例新版本已保存，历史版本保留':'案例已保存，可进入资料检索');
    if(editorRequest===caseEditLoad)clearCaseEditor();
    await refreshResearchJobs(account,token);
   }
  }catch(err){error(err);}finally{e.submitter.disabled=false;}
 };
 await refreshResearchJobs(account,token);
}
