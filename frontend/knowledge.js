'use strict';
let libraryLoad=0,sourceLoad=0,classificationEdit=0;
const documentDrafts=new Map();
function editableKnowledgeDocuments(docs){return docs.filter(d=>d.source_type!=='research_case');}
pageInfo.library=['RESEARCH / 主题研究','先找资料，确认后再用于创作。','输入主题查看研究结果，选中需要的资料后加入当前账号，后续创作自动检索。'];
async function renderLibrary(){
 const request=++libraryLoad,account=activeAccountId;
 $('operationsContent').innerHTML='<section class="panel"><p class="muted">正在读取当前账号资料…</p></section>';
 try{
  const docs=await api('/api/knowledge?account_id='+encodeURIComponent(account));
  if(request!==libraryLoad||currentPage!=='library'||account!==activeAccountId)return;
  $('operationsContent').innerHTML=`<div class="section-toolbar"><div><h2>主题研究</h2><p id="ragLibraryCount" class="muted">${esc(currentAccount().name)} · ${docs.length} 份已有资料</p></div>${badge('原文与版本可追溯','neutral')}</div>${ragSearchPanel()}<details class="panel"><summary>补充自己的资料 / 高级检索</summary><div class="knowledge-grid"><section class="panel"><h2>添加或更新资料</h2><form id="documentForm"><label for="documentTarget">保存方式</label><select id="documentTarget"><option value="">新增资料</option>${editableKnowledgeDocuments(docs).map(d=>`<option value="${esc(d.id)}">更新：${esc(d.title)} · v${d.version}</option>`).join('')}</select><p class="helper">研究案例不在此处更新；需使用案例专用编辑接口，保留来源、资料用途和未读线索限制。</p><label for="documentTitle">资料标题</label><input id="documentTitle" maxlength="200" required placeholder="例如：品牌介绍 / 我的表达风格 / 产品事实"><label for="documentDomains">领域标签</label><input id="documentDomains" maxlength="250" placeholder="留空自动识别；多个领域用逗号分隔"><label for="documentMaterialType">材料用途</label><select id="documentMaterialType"><option value="fact">事实资料</option><option value="method">通用创作方法</option><option value="example">领域参考样例</option></select><label for="documentChannel">适用渠道</label><select id="documentChannel"><option value="">通用</option><option value="xiaohongshu">小红书</option></select><label for="documentFormat">适用形式</label><select id="documentFormat"><option value="">通用</option><option value="note">图文笔记</option><option value="video_script">短视频口播</option><option value="product_detail">商品详情</option></select><label for="documentFile">上传文件</label><input id="documentFile" type="file" accept=".txt,.md,.pdf,.docx"><p class="helper">支持 UTF-8 TXT、Markdown、文本型 PDF 和 Word .docx，单份最大 3 MB；PDF 最多 50 页。扫描 PDF 暂不支持 OCR。上传只做本地解析，不调用 AI。</p><label for="documentText">或粘贴正文</label><textarea id="documentText" rows="6" maxlength="100000" placeholder="粘贴真实资料；选了文件时以文件内容为准"></textarea><button class="primary" type="submit">保存并建立检索索引</button></form></section><section class="panel"><h2>试着检索资料</h2><p class="muted">输入问题或关键词查找相关原文；检索结果会显示当前方式，得分不代表事实可信程度。</p><form id="retrieveForm" class="search-line"><input id="retrieveQuery" maxlength="300" required aria-label="资料检索词" placeholder="例如：白衬衫的面料与护理"><button class="secondary">查找原文</button></form><div id="retrievalResult" class="source-results"><p class="helper">确认加入的参考资料用于后续创作；额外事实资料可在创作时勾选。</p></div></section></div></details><details class="panel"><summary id="ragExistingSummary">已有资料（${docs.length} 份）</summary><div id="ragExistingDocuments" class="source-results">${ragExistingDocuments(docs)}</div><div id="documentDetail"></div></details>`;
  bindRagSearch(account,request);
  $('documentTarget').onchange=()=>{const d=docs.find(d=>d.id===$('documentTarget').value);if(d)$('documentTitle').value=d.title;const c=d?.classification||d?.metadata?.classification||{};$('documentDomains').value=(c.domains||[]).join('、');$('documentMaterialType').value=c.material_type||'fact';$('documentChannel').value=c.channel||'';$('documentFormat').value=c.format||'';};
  bindDocumentInput(account,request,docs);
  $('retrieveForm').onsubmit=async e=>{
   e.preventDefault();e.submitter.disabled=true;
   try{const result=await api('/api/knowledge/retrieve','POST',{account_id:account,query:$('retrieveQuery').value});if(account!==activeAccountId||currentPage!=='library')return;
    $('retrievalResult').innerHTML=`<p class="helper">${esc(result.engine)} · ${esc(result.note||'')}</p>`+(result.sources.length?result.sources.map(s=>`<article class="source-card"><b>${esc(s.title)}</b><p class="helper">v${s.version} · ${s.location_type==='paragraph'?'段落':'第 '+s.page+' 页'} ${s.location_type==='paragraph'?s.page:''} · 字符位置 ${s.offset} · 相关度 ${s.score}</p><blockquote>${esc(s.text)}</blockquote><small>${esc(s.verification)}</small></article>`).join(''):'<p class="issue">没有找到足够相关的资料。请补充资料或换更具体的关键词。</p>');
   }catch(err){error(err);}finally{e.submitter.disabled=false;}
  };
  bindKnowledgeDocuments(docs,account);
 }catch(err){error(err);}
}

function documentInputCurrent(account,request){return account===activeAccountId&&currentPage==='library'&&request===libraryLoad;}
function documentInputFields(){return ['Target','Title','Domains','MaterialType','Channel','Format','Text'];}
function captureDocumentInput(state){for(const name of documentInputFields())state.fields[name]=$('document'+name).value;}
function readDocumentFile(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败，请换文件或改为粘贴；当前文字保留。'));reader.readAsDataURL(file);});}
function documentPreviewMarkup(preview){
 return `<h3>校对解析结果（尚未入库）</h3><p class="helper">原文件保留不变；只有点击下方确认按钮后，校对正文才用于 RAG。${preview.warnings.map(esc).join(' ')}</p>${preview.pages.map((p,i)=>`<label for="reviewedDocument-${i}">文本块 / 页 ${esc(p.page)}</label><textarea id="reviewedDocument-${i}" data-document-review="${i}" rows="6" maxlength="100000">${esc(p.text)}</textarea><details><summary>查看此块原始提取文字</summary><pre class="source-text">${esc(p.original_text)}</pre></details>`).join('')}<p id="documentReviewStatus" class="helper" aria-live="polite"></p><button id="confirmDocumentInput" class="primary" type="button">已校对，确认存入资料库</button><button id="backDocumentInput" class="quiet" type="button">返回修改 / 取消入库</button>`;
}
function bindDocumentInput(account,request,docs){
 const form=$('documentForm'),state=documentDrafts.get(account)||{fields:{},file:null,preview:null,serial:0};
 documentDrafts.set(account,state);
 for(const [name,value] of Object.entries(state.fields))if($('document'+name))$('document'+name).value=value;
 form.querySelector('button[type="submit"]').textContent='解析并预览（尚不入库）';
 form.insertAdjacentHTML('afterend','<p id="documentInputStatus" class="helper" aria-live="polite"></p><button id="clearDocumentFile" class="quiet" type="button">清除所选文件，改用粘贴</button><section id="documentInputPreview" class="panel" hidden></section>');
 const current=()=>documentInputCurrent(account,request);
 const showFile=()=>{$('documentInputStatus').textContent=state.file?'已保留待解析文件：'+state.file.name+'；选择新文件可替换。':'可以上传文件或粘贴文本。返回修改会保留输入；刷新浏览器后需重新选择文件。';};
 const invalidate=()=>{state.serial++;state.preview=null;state.payload=null;state.submitted=null;if(current()){$('documentInputPreview').hidden=true;$('documentInputPreview').innerHTML='';}};
 form.addEventListener('input',()=>{captureDocumentInput(state);invalidate();});
 form.addEventListener('change',()=>{captureDocumentInput(state);invalidate();});
 $('documentFile').onchange=()=>{state.file=$('documentFile').files[0]||null;invalidate();showFile();};
 $('clearDocumentFile').onclick=()=>{state.file=null;$('documentFile').value='';invalidate();showFile();$('documentText').focus();};
 const showPreview=()=>{
  const panel=$('documentInputPreview');panel.hidden=false;panel.innerHTML=documentPreviewMarkup(state.preview);
  state.preview.pages.forEach((page,i)=>{$('reviewedDocument-'+i).oninput=()=>{page.text=$('reviewedDocument-'+i).value;};});
  $('backDocumentInput').onclick=()=>{invalidate();showFile();$('documentText').focus();};
  $('confirmDocumentInput').onclick=async()=>{
   const button=$('confirmDocumentInput'),serial=state.serial;button.disabled=true;
   $('backDocumentInput').disabled=true;
   state.preview.pages.forEach((_,i)=>{$('reviewedDocument-'+i).readOnly=true;});
   if(!state.submitted)state.submitted={...state.payload,input_review:{confirmed:true,source_sha256:state.preview.source_sha256,confirmation_id:state.confirmationId,pages:state.preview.pages.map(({page,text})=>({page,text}))}};
   const submitted=state.submitted;
   $('documentReviewStatus').textContent='正在保存校对版本…';
   try{
    const saved=await api('/api/knowledge','POST',submitted),receipt=saved.input_confirmation;
    // A user may have started another input or switched accounts meanwhile.
    if(documentDrafts.get(account)===state&&state.serial===serial)documentDrafts.delete(account);
    if(current()&&state.serial===serial){
     const notice=receipt&&receipt.confirmed_version!==receipt.current_version
      ?'先前校对版本 v'+receipt.confirmed_version+' 已保存；当前资料已更新至 v'+receipt.current_version+'，本次重试未覆盖新版本'
      :'已确认入库'+(receipt?'（v'+receipt.confirmed_version+'）':'')+'；原文件与校对版本均已保留';
     toast(notice);await renderLibrary();
    }
   }catch(err){if(current()&&state.serial===serial){$('documentReviewStatus').textContent='保存未确认：'+err.message+'。输入已保留；重试会沿用同一次确认，不重复入库。要改正文请先返回修改并重新预览。';error(err);}}
   finally{button.disabled=false;if(current()&&state.serial===serial)$('backDocumentInput').disabled=false;}
  };
 };
 form.onsubmit=async e=>{
  e.preventDefault();captureDocumentInput(state);invalidate();const serial=state.serial,button=e.submitter;button.disabled=true;
  const data={account_id:account,title:state.fields.Title},file=state.file,text=state.fields.Text;
  const doc=docs.find(d=>d.id===state.fields.Target);if(doc){data.document_id=doc.id;data.expected_version=doc.version;}
  try{
   data.classification=await documentClassificationRequest();
   if(file){if(file.size>3000000)throw new Error('文件超过 3 MB，请换文件或改为粘贴');data.filename=file.name;data.file_base64=await readDocumentFile(file);}else data.text=text;
   const preview=await api('/api/knowledge/preview','POST',data);
   if(state.serial!==serial)return;
   state.payload=data;state.preview=preview;state.confirmationId=crypto.randomUUID();
   if(current()){showPreview();$('documentInputStatus').textContent='解析完成，尚未入库。请校对后确认，也可返回修改。';}
  }catch(err){if(current()&&state.serial===serial){$('documentInputStatus').textContent='解析失败：'+err.message+'。原输入已保留，可换文件或清除文件后粘贴文字。';error(err);}}
  finally{button.disabled=false;}
 };
 showFile();if(state.preview){showPreview();if(state.submitted)state.preview.pages.forEach((_,i)=>{$('reviewedDocument-'+i).readOnly=true;});}
}

function ragExistingDocuments(docs){return docs.map(d=>`<article class="document-row"><div><b>${esc(d.title)}</b>${ragDocumentMeta(d)}<p class="helper">v${d.version} · ${esc(({text:'粘贴文本',upload:'上传文件',web:'已读取网页',research_case:'研究案例'})[d.source_type])} · ${esc(new Date(d.updated_at*1000).toLocaleString())}</p></div><div class="buttons"><button class="quiet" data-document="${esc(d.id)}">查看原文</button><button class="quiet" data-classify-document="${esc(d.id)}">调整分类</button><button class="quiet" data-delete-document="${esc(d.id)}">移出资料库</button></div></article>`).join('')||'<p class="helper">还没有资料。可以先上传一份品牌或账号介绍。</p>';}
function bindKnowledgeDocuments(docs,account){
  document.querySelectorAll('[data-classify-document]').forEach(b=>b.onclick=()=>openClassificationEditor(b.dataset.classifyDocument,account));
  document.querySelectorAll('[data-document]').forEach(b=>b.onclick=async()=>{
   try{const d=await api('/api/knowledge/'+b.dataset.document+'?account_id='+encodeURIComponent(account));if(account!==activeAccountId||currentPage!=='library')return;
    $('documentDetail').innerHTML=`<hr><h3>${esc(d.title)} · v${d.version}</h3><p class="helper">${d.versions.length} 个版本 · 原文指纹 ${esc(d.fingerprint.slice(0,16))}</p>${d.source_url?`<a href="${esc(d.source_url)}" target="_blank" rel="noopener noreferrer">查看网页来源 ↗</a>`:''}<p class="helper">${d.metadata.fetched_at?'读取时间：'+esc(d.metadata.fetched_at):''} ${d.metadata.published_at?'页面声明发布时间：'+esc(d.metadata.published_at):'发布时间未提供或未核实'}</p>${d.chunks.map(c=>`<details><summary>${d.metadata.location_type==='paragraph'?'段落 '+c.page:'第 '+c.page+' 页'} · 字符位置 ${c.offset}</summary><pre class="source-text">${esc(c.text)}</pre></details>`).join('')}`;
    if(['text','upload'].includes(d.source_type))$('documentDetail').innerHTML+=`<p>${d.versions.map(v=>`<a class="button quiet" href="/api/knowledge/${encodeURIComponent(d.id)}/original?account_id=${encodeURIComponent(account)}&amp;version=${v.version}">下载 v${v.version} 原始输入</a>`).join(' ')}</p>${d.metadata.input_review?'<p class="helper">上方为已确认的校对正文；原始输入未被覆盖，下载可作对照。</p>':''}`;
   }catch(err){error(err);}
  });
  document.querySelectorAll('[data-delete-document]').forEach(b=>b.onclick=async()=>{
   const d=docs.find(d=>d.id===b.dataset.deleteDocument);if(!window.confirm('移出资料库后，新任务不会再检索这份资料。已有任务的证据快照保留用于回查。'))return;
   try{await api('/api/knowledge/'+d.id+'/delete','POST',{account_id:account,version:d.version});if(account===activeAccountId&&currentPage==='library')await renderLibrary();}catch(err){error(err);}
  });
}
async function refreshRagDocuments(account,request){
 const docs=await api('/api/knowledge?account_id='+encodeURIComponent(account));
 if(request!==libraryLoad||account!==activeAccountId||currentPage!=='library')return;
 const scroll=typeof window!=='undefined'?window.scrollY:0;
 $('ragLibraryCount').textContent=currentAccount().name+' · '+docs.length+' 份已有资料';
 $('ragExistingSummary').textContent='已有资料（'+docs.length+' 份）';
 $('ragExistingDocuments').innerHTML=ragExistingDocuments(docs);
 bindKnowledgeDocuments(docs,account);
 if(typeof window!=='undefined')window.scrollTo?.(0,scroll);
}

function mountSourceSearch(){
 if(!websiteSession?.auth_required)return;
 const account=activeAccountId;
 $('operationsContent').insertAdjacentHTML('afterbegin',`<section class="panel source-search"><div class="detail-heading"><div><span class="eyebrow">PUBLIC SOURCES</span><h2>搜索真实信息来源</h2></div>${badge('公开网页 · 非平台热榜','neutral')}</div><p class="muted">搜索词会发送给公开搜索服务；仅发送你填写的关键词。摘要是线索，读取正文并保存后才会进入账号资料库。</p><form id="sourceSearchForm" class="search-line"><select id="sourceProvider" aria-label="搜索来源"><option value="bing">Bing 公开网页 · 实验搜索</option><option value="baidu">百度 AI 搜索（需配置）</option><option value="wikipedia">百科资料 · 背景知识</option></select><select id="sourceTarget" aria-label="搜索范围"><option value="web">全网公开网页</option><option value="jd">京东</option><option value="taobao">淘宝 / 天猫</option><option value="xiaohongshu">小红书索引线索（无自动读取权限）</option></select><input id="sourceQuery" maxlength="120" minlength="2" required aria-label="搜索公开网页" placeholder="例如：衬衫 / 棉 / 亚麻"><button class="primary">联网搜索</button></form><form id="sourceUrlForm" class="search-line"><input id="sourceUrl" type="url" required aria-label="读取网页链接" placeholder="或粘贴公开网页链接 https://…"><button class="secondary">读取正文并保存</button></form><div id="sourceSearchResult" class="source-results"></div></section>`);
 $('sourceProvider').onchange=()=>{if($('sourceProvider').value==='wikipedia')$('sourceTarget').value='web';$('sourceTarget').disabled=$('sourceProvider').value==='wikipedia';};
 const importUrl=async(url,button)=>{
  button.disabled=true;const text=button.textContent;button.textContent='正在读取…';
  try{const doc=await api('/api/sources/import','POST',{url,account_id:account});toast('已保存到 '+(ops.accounts.find(a=>a.id===account)?.name||'原账号')+' 的资料库：'+doc.title);button.textContent='已保存正文';}
  catch(err){error(err);button.disabled=false;button.textContent=text;}
 };
 $('sourceUrlForm').onsubmit=e=>{e.preventDefault();importUrl($('sourceUrl').value,e.submitter);};
 $('sourceSearchForm').onsubmit=async e=>{
  e.preventDefault();const request=++sourceLoad;const button=e.submitter;button.disabled=true;$('sourceSearchResult').textContent='正在搜索公开来源…';
  try{
   const result=await api('/api/sources/search','POST',{query:$('sourceQuery').value,account_id:account,provider:$('sourceProvider').value,targets:[$('sourceTarget').value]});
   if(request!==sourceLoad||account!==activeAccountId||currentPage!=='trends')return;
   $('sourceSearchResult').innerHTML=`<p class="helper">${esc(result.provider)} · ${esc(result.note)} ${esc(result.coverage||'')}</p>`+((result.results.map((r,i)=>`<article class="source-card"><div class="detail-heading"><h3>${esc(r.title)}</h3>${badge('摘要 · 正文未读取','amber')}</div><p>${esc(r.snippet)}</p><p class="helper">${esc(new URL(r.url).hostname)} · 检索时间 ${esc(new Date(r.fetched_at).toLocaleString())} · 发布时间未核实</p><div class="buttons"><a class="button quiet" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">打开来源 ↗</a><button class="secondary" data-read-source="${i}">读取正文并保存</button></div></article>`).join('')||'<p class="helper">没有搜索结果，请换一组关键词。</p>'));
   document.querySelectorAll('[data-read-source]').forEach(b=>b.onclick=()=>importUrl(result.results[Number(b.dataset.readSource)].url,b));
  }catch(err){if(request===sourceLoad&&account===activeAccountId&&currentPage==='trends'){$('sourceSearchResult').textContent='来源暂不可用，没有生成替代结果。可以粘贴可访问的网页链接。';error(err);}}
  finally{button.disabled=false;}
 };
}

function ragSearchPanel(){return `<section class="panel"><h2>想研究什么主题？</h2><p class="muted">研究助手先寻找并读取资料。预览结果、勾选确认后，资料才会加入当前账号供后续创作使用。</p><form id="ragSearchForm"><label for="ragQuery">主题</label><input id="ragQuery" required minlength="2" maxlength="120" placeholder="例如：适合通勤的口红色号"><label for="ragProvider">资料来源</label><select id="ragProvider"><option value="xhs_local">小红书公开笔记 · 正在核对连接</option><option value="bing">通用网页 · 未核验</option><option value="baidu">百度搜索 · 未核验</option><option value="wikipedia">百科资料 · 未核验</option></select><p id="ragCapabilityNote" class="helper">正在读取来源配置；配置存在不等于当前搜索已接通。</p><div id="ragWebScope"><label for="ragTarget">网页搜索范围</label><select id="ragTarget"><option value="web">通用网页</option><option value="jd">京东 · 搜索引擎收录范围</option><option value="taobao">淘宝 / 天猫 · 搜索引擎收录范围</option></select><p class="helper">京东、淘宝是搜索引擎站点限定，不是商城专用接口；可能没有可读取正文。</p></div><details id="ragAdvanced"><summary>高级筛选（可选）</summary><div class="rag-filters"><div><label for="ragLikes">点赞至少</label><input id="ragLikes" type="number" min="1" max="1000000000" value="100" required></div><div><label for="ragFavorites">或收藏至少</label><input id="ragFavorites" type="number" min="1" max="1000000000" value="50" required></div><div><label for="ragSort">优先排序</label><select id="ragSort"><option value="likes">最多点赞</option><option value="favorites">最多收藏</option></select></div></div><p class="helper">仅对本次平台返回的候选按可得互动排序，不代表全站最高；优先展示达到任一赞藏阈值的笔记，不足阈值或指标未知时标为相关候选。最多核对 6 篇、提供 3 篇候选；视频仅使用文字描述。</p></details><button id="ragSearchButton" class="primary" disabled>搜索资料</button></form><div id="ragRecovery" class="helper"><button type="button" id="ragRefresh" class="quiet">刷新研究记录</button><button type="button" id="ragPaste" class="quiet">改为粘贴资料</button></div><div id="ragJobResult" aria-live="polite"></div></section>`;}
function researchSourceLink(url,label='打开原始来源'){
 try{const parsed=new URL(url);if(!['https:','http:'].includes(parsed.protocol))return '';return `<a href="${esc(parsed.href)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;}catch(_){return '';}
}
function ragDocumentMeta(d){const c=d.metadata?.research_case;if(!c)return '';const m=c.metrics||{};return `<p class="helper">点赞 ${esc(m.likes??'未知')} · 收藏 ${esc(m.favorites??'未知')}${d.source_url?' · '+researchSourceLink(d.source_url,'原文来源'):''}</p>`;}
const ragSourceCapabilities=new Map(),ragSearchAttempts=new Map();
const ragSelections=new Map(),ragConfirmKeys=new Map(),ragConfirmingJobs=new Set(),ragPendingAccounts=new Set();
const ragViewState=new Map(),ragRefreshVersions=new Map(),ragSubmitting=new Set(),ragActiveJobs=new Map(),ragJobsCache=new Map(),ragPollFailures=new Map(),ragSubmitVersions=new Map();
function saveRagView(account){
 const state=ragViewState.get(account)||{};
 for(const id of ['ragQuery','ragProvider','ragTarget','ragLikes','ragFavorites','ragSort'])state[id]=$(id).value;
 state.scroll=typeof window!=='undefined'?window.scrollY:0;ragViewState.set(account,state);
 try{sessionStorage.setItem('red.rag.'+account,JSON.stringify({...state,selections:[...ragSelections].filter(([key])=>key.startsWith(account+'/')).map(([key,ids])=>[key,[...ids]])}));}catch(_){}
}
function restoreRagView(account){
 let state=ragViewState.get(account);
 if(!state)try{state=JSON.parse(sessionStorage.getItem('red.rag.'+account)||'null');}catch(_){}
 if(!state)return;
 state.restoreScroll=true;ragViewState.set(account,state);
 for(const id of ['ragQuery','ragProvider','ragTarget','ragLikes','ragFavorites','ragSort'])if(state[id]!==undefined)$(id).value=state[id];
 for(const [key,ids]of state.selections||[])ragSelections.set(key,new Set(ids));
}
function ragMetricText(metrics,display,key){return metrics[key]!=null?String(metrics[key]):typeof display?.[key]==='string'&&display[key].trim()?display[key]+'（平台原值）':'未知';}
function ragCandidateSaved(job,id){return (job.items||[]).some(i=>i.candidate_id===id&&i.status==='saved');}
function ragCandidateUsable(c){return typeof c.packet?.text==='string'&&c.packet.text.trim().length>=10&&c.importable!==false;}
function ragCoverUrl(url,platform){
 if(platform!=='xiaohongshu')return '';
 try{const u=new URL(url);return ['https:','http:'].includes(u.protocol)&&!u.username&&!u.password&&!u.port&&['.xhscdn.com','.xiaohongshu.com'].some(domain=>u.hostname.endsWith(domain))?u.href:'';}catch(_){return '';}
}
function bindRagCovers(form){
 form.querySelectorAll('[data-rag-cover]').forEach(img=>{
  const failed=()=>{img.hidden=true;if(img.nextElementSibling)img.nextElementSibling.hidden=false;};
  img.onerror=failed;img.onload=()=>{img.hidden=false;if(img.nextElementSibling)img.nextElementSibling.hidden=true;};
  if(img.complete&&!img.naturalWidth)failed();
 });
}

function ragSelectionKey(account,job){return account+'/'+job;}
function ragCandidatePanel(job,account){
 const key=ragSelectionKey(account,job.id),selected=ragSelections.get(key)||new Set(),busy=ragConfirmingJobs.has(key)||job.status==='confirming';
 if(job.confirmation?.candidate_ids)for(const id of job.confirmation.candidate_ids)selected.add(id);
 const candidates=job.candidates||[],saved=candidates.filter(c=>ragCandidateSaved(job,c.id)).length;
 const lockedSelection=job.confirmation?.candidate_ids;
 const canConfirm=['awaiting_confirmation','partial','interrupted','cancelled','confirming'].includes(job.status||'awaiting_confirmation');
 return `<form data-rag-confirm="${esc(job.id)}"><p class="helper">搜索到 ${candidates.length} 条候选${saved?` · 已加入 ${saved} 条资料`:'，尚未加入资料库'}。请先预览，再勾选需要的资料。</p>${candidates.map(c=>{
  const p=c.packet||{},m=p.metrics||{},meta=c.preview||{},isSaved=ragCandidateSaved(job,c.id),usable=ragCandidateUsable(c),kind=p.content_type||meta.content_type||p.note_type,cover=ragCoverUrl(p.cover_url||meta.cover_url,p.platform),video=kind==='video';
  return `<article class="source-card"><label><input type="checkbox" data-rag-candidate value="${esc(c.id)}" ${selected.has(c.id)?'checked':''} ${busy||isSaved||!usable||!canConfirm||(lockedSelection&&!lockedSelection.includes(c.id))?'disabled':''}> ${esc(p.title||'标题未取得')}</label><p class="helper">${isSaved?'已入库':busy&&selected.has(c.id)?'导入中':usable?'待选择':'只有链接或内容不足，暂不能作为创作资料'} · ${video?'视频 · 仅文字说明，未读取音轨或转写':kind==='normal'||kind==='image'?'图文':'内容类型未知'}</p>${cover?`<img src="${esc(cover)}" alt="笔记封面" class="rag-candidate-cover" data-rag-cover loading="lazy" referrerpolicy="no-referrer"><p class="helper" hidden>封面暂时无法显示，仍可浏览正文和打开原文。</p>`:'<p class="helper">封面未取得</p>'}<p class="helper">${researchSourceLink(p.source_url,p.platform==='xiaohongshu'?'查看小红书原文':'查看原文')} · 获取时间 ${esc(p.observed_at||c.fetched_at||'未知')} · 发布日期 ${esc(p.published_at||meta.published_at||'未知')}${p.platform==='xiaohongshu'?` · 点赞 ${esc(ragMetricText(m,meta.metric_display,'likes'))} · 收藏 ${esc(ragMetricText(m,meta.metric_display,'favorites'))} · 评论 ${esc(ragMetricText(m,meta.metric_display,'comments'))}`:''}</p><p class="helper">${p.content_scope==='summary'||meta.content_scope==='summary'||meta.body_kind==='summary'?'搜索摘要 · 不是已读取正文':video?'平台实际取得的文字说明':'实际取得的笔记正文'}${p.platform==='xiaohongshu'?(c.provenance?.high_engagement_supported===true?' · 达到所选互动阈值':m.likes==null&&m.favorites==null&&!meta.metric_display?.likes&&!meta.metric_display?.favorites?' · 相关候选，暂无真实互动依据':' · 相关候选，未确认达到所选互动阈值'):''}</p><p>${esc((p.text||'').slice(0,360))}</p><details><summary>查看完整候选正文</summary><pre class="source-text">${esc(p.text||'尚未取得可用正文')}</pre></details></article>`;
 }).join('')}<button class="primary" type="submit" ${busy||!canConfirm||!candidates.some(c=>selected.has(c.id)&&ragCandidateUsable(c)&&!ragCandidateSaved(job,c.id))?'disabled':''}>${busy?'正在导入…':'加入知识库'}</button><p class="helper">未勾选的候选不会加入资料库；打开原文不表示已核实或入库。</p></form>`;
}
async function confirmRagSelection(account,request,job,ids,form){
 const key=ragSelectionKey(account,job.id);
 if(request!==libraryLoad||account!==activeAccountId||currentPage!=='library'||ragConfirmingJobs.has(key))return;
 ids=[...new Set(ids)].filter(id=>(job.candidates||[]).some(c=>c.id===id&&ragCandidateUsable(c)&&!ragCandidateSaved(job,c.id)));
 if(!ids.length)return;
 const attempt=key+'/'+JSON.stringify([...ids].sort());
 if(!ragConfirmKeys.has(attempt))ragConfirmKeys.set(attempt,crypto.randomUUID());
 const confirmation=job.confirmation||{candidate_ids:ids,key:ragConfirmKeys.get(attempt)};
 ragConfirmingJobs.add(key);form.querySelectorAll('button,input').forEach(el=>el.disabled=true);
 try{
  saveRagView(account);
  await api('/api/research/jobs/'+encodeURIComponent(job.id)+'/confirm','POST',{candidate_ids:confirmation.candidate_ids,key:confirmation.key});
  ragConfirmingJobs.delete(key);ragPendingAccounts.delete(account);toast('导入操作完成，实际结果见候选状态');
  if(request===libraryLoad&&account===activeAccountId&&currentPage==='library'){await refreshRagJobs(account,request);await refreshRagDocuments(account,request);}
 }catch(err){if(request===libraryLoad&&account===activeAccountId&&currentPage==='library')error(err);}
 finally{ragConfirmingJobs.delete(key);form.querySelectorAll('[data-rag-candidate]').forEach(el=>{const c=(job.candidates||[]).find(c=>c.id===el.value);el.disabled=!c||!ragCandidateUsable(c)||ragCandidateSaved(job,c.id)||(job.confirmation?.candidate_ids&&!job.confirmation.candidate_ids.includes(c.id));});const submit=form.querySelector?.('button[type="submit"]');if(submit)submit.disabled=!Array.from(form.querySelectorAll('[data-rag-candidate]')).some(el=>el.checked&&!el.disabled);}
}
function bindRagCandidates(jobs,account,request){
 document.querySelectorAll('[data-rag-confirm]').forEach(form=>{
  const job=jobs.find(j=>j.id===form.dataset.ragConfirm);if(!job)return;
  const key=ragSelectionKey(account,job.id);bindRagCovers(form);
  form.querySelectorAll('a[target="_blank"]').forEach(a=>a.onclick=()=>saveRagView(account));
  const selected=()=>Array.from(form.querySelectorAll('[data-rag-candidate]')).filter(el=>el.checked&&!el.disabled).map(el=>el.value);
  form.querySelectorAll('[data-rag-candidate]').forEach(el=>el.onchange=()=>{const ids=selected();ragSelections.set(key,new Set(ids));saveRagView(account);form.querySelector('button[type="submit"]').disabled=!ids.length;});
  form.onsubmit=e=>{e.preventDefault();return confirmRagSelection(account,request,job,selected(),form);};
 });
}
function ragPastDeadline(job){const end=job.status==='queued'?job.queue_deadline_at:job.deadline_at;return ragPending(job)&&typeof end==='number'&&Date.now()>end*1000;}
function ragPending(job){return ['queued','running','confirming'].includes(job.status);}
function ragCanonicalQuery(value){return String(value||'').trim().replace(/\s+/g,' ');}
function ragScope(payload){
 const provider=payload.provider||'',targets=payload.targets||(provider==='xhs_local'?['xiaohongshu']:['web']);
 const filters=provider==='xhs_local'?(payload.style_filters||{min_likes:100,min_favorites:50,sort_by:'likes'}):{};
 return JSON.stringify({account:payload.account_id||activeAccountId,queries:(payload.queries||[]).map(ragCanonicalQuery),provider,targets:[...targets].sort(),role:payload.evidence_role||'expression_reference',confirmation:payload.confirmation_required!==false,filters:{min_likes:filters.min_likes,min_favorites:filters.min_favorites,sort_by:filters.sort_by}});
}
function ragSearchPayload(account){
 const provider=$('ragProvider').value,payload={account_id:account,queries:[$('ragQuery').value],provider,targets:[provider==='xhs_local'?'xiaohongshu':provider==='wikipedia'?'web':$('ragTarget').value||'web'],evidence_role:'expression_reference',permission_confirmed:true,confirmation_required:true};
 if(provider==='xhs_local')payload.style_filters={min_likes:Number($('ragLikes').value),min_favorites:Number($('ragFavorites').value),sort_by:$('ragSort').value};
 return payload;
}
function ragCurrentJob(account,jobs){
 const state=ragViewState.get(account)||{};
 if(state.jobId){const job=jobs.find(j=>j.id===state.jobId);if(job&&(!state.scope||ragScope(job)===state.scope))return job;}
 if(state.scope)return null;
 return jobs.find(j=>!$('ragQuery').value||ragScope(j)===ragScope(ragSearchPayload(account)))||null;
}
function ragJobStatus(j,stale=false){
 if(stale&&ragPending(j))return '状态刷新中断，以下为上次记录';
 if(j.status==='cancelled')return '已取消';
 const outcome=typeof j.outcome==='string'?j.outcome:j.outcome?.kind;
 const count=(j.candidates||[]).length,failures=[...(j.items||[]),...(j.attempts||[])].some(i=>i.error);
 if(j.status==='done'&&(j.documents||[]).length)return '导入已完成';
 if(['zero_results','empty','no_results','empty_results'].includes(outcome))return '搜索完成，平台未返回候选';
 if(outcome==='invalid_results')return '平台返回内容无法解析为候选';
 if(outcome==='filtered_all')return '平台返回了结果，本次均不符合可用条件';
 if(outcome==='timeout'||outcome==='queue_timeout')return outcome==='queue_timeout'?'任务排队超时':'搜索或读取超时';
 if(outcome==='search_failed')return count?'搜索中断，已有候选保留':'搜索失败，未取得候选';
 if(['all_details_failed','all_reads_failed','detail_failed'].includes(outcome))return '候选详情全部读取失败';
 if(['partial_success','partial','partial_results'].includes(outcome)||(count&&failures))return '部分成功，已有候选保留';
 if(['done','failed','partial','interrupted'].includes(j.status)&&!count){
  if(failures||j.error)return '搜索或读取失败，未取得可用候选';
  return j.status==='done'?'搜索完成，本次没有可用候选':'搜索未完成，尚未取得可用候选';
 }
 return ({queued:'等待研究',running:'正在后台搜索与读取',confirming:'正在导入所选资料',awaiting_confirmation:'待你确认',done:'搜索完成',partial:'部分成功',failed:'搜索失败',interrupted:'读取中断'})[j.status]||j.status;
}
function ragJobTrace(j){
 const queries=j.canonical_queries||j.queries||[],raw=j.raw_queries||[],trace=Array.isArray(j.trace)?j.trace:[],counts=j.counts||{},reuse=j.reuse||{};
 const phaseNames={queued:'排队等待',identity_initial:'核对连接账号',search:'平台搜索',detail:'读取笔记详情',identity_final:'复核连接账号',complete:'已结束'};
 const countNames={raw_count:'原始结果',parsed_count:'可解析结果',filtered_count:'过滤数量',detail_success_count:'详情成功',detail_failed_count:'详情失败',candidate_count:'候选',importable_count:'可入库'};
 const summary=Object.entries(countNames).filter(([key])=>counts[key]!=null).map(([key,name])=>name+' '+counts[key]).join(' · ');
 return `<p class="helper">实际查询：${esc(queries.join(' / '))}${raw.length&&JSON.stringify(raw)!==JSON.stringify(queries)?' · 输入原文：'+esc(raw.join(' / ')):''}${j.reused_running===true||reuse.kind==='active_task'?' · 复用同范围运行中任务':reuse.kind==='idempotent_task'?' · 恢复同一次提交':''}${reuse.cache_hit===false?' · 未使用结果缓存':''}</p>${j.phase?`<p class="helper">阶段：${esc(phaseNames[j.phase]||j.phase)}${summary?' · '+esc(summary):''}</p>`:''}${j.error_origin||j.mcp_http_status?`<p class="helper">错误来源：${esc(j.error_origin||'未提供')}${j.mcp_http_status?' · 本机 MCP HTTP '+esc(j.mcp_http_status):''}；不能据此推断平台上游 HTTP 状态。</p>`:''}${trace.length?`<details><summary>本次搜索读取记录</summary>${trace.map(t=>`<p class="helper">${esc(phaseNames[t.phase]||t.phase||'读取')} · ${esc(t.query||'')} · ${esc(t.status||'')} ${t.error?' · '+esc(ragErrorText(t.error)):''}${t.mcp_http_status?' · 本机 MCP HTTP '+esc(t.mcp_http_status):''}</p>`).join('')}</details>`:''}`;
}
function ragJobPanel(j,account,stale=false){
 const state=ragViewState.get(account)||{};if(state.jobId===j.id&&state.reuse&&!j.reuse)j={...j,reuse:state.reuse};
 const pending=ragPending;
 return `<article class="detail-block"><h3>${esc((j.queries||[]).join(' / '))}</h3><p class="helper">${esc(ragJobStatus(j,stale))} · 搜索到 ${(j.candidates||[]).length} 条候选${(j.documents||[]).length?` · 已加入 ${j.documents.length} 条资料`:''}${j.error?' · '+esc(ragErrorText(j.error)):''}</p>${j.error==='XHS_LOGIN_REQUIRED'?'<a class="button quiet" href="#connections">登录 / 重新连接</a>':''}${pending(j)&&!stale?`<p class="helper">正在搜索 / 读取，已有 ${Array.isArray(j.reads)?j.reads.length:0} 条读取记录；已有候选保留在下方。</p><button type="button" class="quiet" data-rag-cancel="${esc(j.id)}">取消任务</button>`:''}${['failed','interrupted','partial','cancelled'].includes(j.status)?'<p class="helper">已取得的候选保留；可保留关键词重新搜索，或使用“改为粘贴资料”。</p>':''}${[...(j.items||[]),...(j.attempts||[])].filter(i=>i.error).length?`<details><summary>${(j.candidates||[]).length?'部分读取未完成':'读取失败记录'}（${[...(j.items||[]),...(j.attempts||[])].filter(i=>i.error).length}）</summary>${[...(j.items||[]),...(j.attempts||[])].filter(i=>i.error).map(i=>`<p class="helper">${esc(i.title||'单篇笔记')}：${esc(ragErrorText(i.error))}</p>`).join('')}</details>`:''}${ragJobTrace(j)}${(j.candidates||[]).length?ragCandidatePanel(j,account):pending(j)?'<p>候选将显示在本页；搜索不会打开外站或自动入库。</p>':''}${(j.documents||[]).length?`<a class="button quiet" href="/api/research/jobs/${encodeURIComponent(j.id)}/export">导出已确认资料</a>`:''}</article>`;
}
function renderRagJobList(account,request,jobs,stale=false){
 const current=ragCurrentJob(account,jobs),history=jobs.filter(j=>j.id!==current?.id),state=ragViewState.get(account)||{};
 const scroll=state.restoreScroll?state.scroll||0:typeof window!=='undefined'?window.scrollY:0;state.restoreScroll=false;
 const interrupted=stale?'<p class="issue">状态刷新中断，不能确认后台当前进度。已取得的候选保留；请使用“刷新研究记录”恢复。</p>':'';
 $('ragJobResult').innerHTML=interrupted+(current?`<section aria-label="当前搜索">${ragJobPanel(current,account,stale)}</section>`:'<p class="helper">当前输入尚无已选择的搜索任务，点击“搜索资料”开始。</p>')+(history.length?`<details data-rag-history><summary>历史研究（${history.length} 条，不属于当前搜索）</summary>${history.map(j=>ragJobPanel(j,account,stale)).join('')}</details>`:'');
 bindRagCandidates(jobs,account,request);
 document.querySelectorAll('[data-rag-cancel]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{await api('/api/research/jobs/'+encodeURIComponent(button.dataset.ragCancel)+'/cancel','POST',{});ragSearchAttempts.delete(account);await refreshRagJobs(account,request);}catch(err){error(err);button.disabled=false;}});
 if(typeof window!=='undefined')window.scrollTo?.(0,scroll);
 return current;
}
function ragUpdateSearchButton(account){
 const cap=ragSourceCapabilities.get(account)?.find(p=>p.id===$('ragProvider').value);
 $('ragSearchButton').disabled=ragSubmitting.has(account)||cap?.can_attempt===false;
}
async function ragBoundedRequest(path,method='GET',body){
 let timer;try{return await Promise.race([api(path,method,body),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('状态请求超时，请刷新研究记录；不会自动重发搜索')),20000);})]);}
 finally{if(typeof clearTimeout==='function')clearTimeout(timer);}
}
async function refreshRagJobs(account,request,automatic=false){
 if(request!==libraryLoad||account!==activeAccountId||currentPage!=='library')return;
 const version=(ragRefreshVersions.get(account)||0)+1;ragRefreshVersions.set(account,version);
 if(!automatic)ragPollFailures.delete(account);
 const valid=()=>request===libraryLoad&&account===activeAccountId&&currentPage==='library'&&version===ragRefreshVersions.get(account);
 let jobs;
 try{jobs=await ragBoundedRequest('/api/research/jobs?account_id='+encodeURIComponent(account));}
 catch(err){
  if(!valid())return;
  const failures=(ragPollFailures.get(account)||0)+1;ragPollFailures.set(account,failures);
  renderRagJobList(account,request,ragJobsCache.get(account)||[],true);ragUpdateSearchButton(account);
  if(failures<=2)setTimeout(()=>{if(valid())refreshRagJobs(account,request,true);},4000*failures);
  return;
 }
 if(!valid())return;
 ragPollFailures.delete(account);ragJobsCache.set(account,jobs);ragActiveJobs.set(account,jobs.filter(ragPending));
 const expired=ragCurrentJob(account,jobs);const current=renderRagJobList(account,request,jobs,!!expired&&ragPastDeadline(expired));ragUpdateSearchButton(account);
 if(current&&ragPending(current)&&!ragPastDeadline(current)){ragPendingAccounts.add(account);setTimeout(()=>{if(valid())refreshRagJobs(account,request,true);},4000);}
 else{ragPendingAccounts.delete(account);if(current)ragSearchAttempts.delete(account);}
}
async function loadRagCapabilities(account,request){
 const [settings,sync]=await Promise.all([api('/api/search/settings'),api('/api/social/sync?account_id='+encodeURIComponent(account))]);
 if(request!==libraryLoad||account!==activeAccountId||currentPage!=='library')return;
 const providers=(settings.providers||[]).map(p=>({...p,can_attempt:p.can_attempt===true}));
 providers.push({id:'xhs_local',can_attempt:sync.bound===true&&sync.enabled!==false,status_note:sync.bound?'已绑定本机连接；当前搜索可用性仍需本次读取验证':'尚未绑定小红书，请到账号数据连接页处理'});
 ragSourceCapabilities.set(account,providers);
 for(const option of Array.from($('ragProvider').options||[])){
  const cap=providers.find(p=>p.id===option.value);option.disabled=!cap?.can_attempt;
  const label=({xhs_local:'小红书公开笔记',bing:'通用网页',baidu:'百度搜索',wikipedia:'百科资料'})[option.value];
  option.textContent=label+(cap?.can_attempt?' · 可尝试，尚未核验':' · 当前不可用');
 }
 const previousProvider=$('ragProvider').value;
 const selected=providers.find(p=>p.id===previousProvider);
 if(!selected?.can_attempt)$('ragProvider').value=providers.find(p=>p.can_attempt)?.id||'';
 $('ragSearchButton').disabled=!providers.some(p=>p.can_attempt);
 if(previousProvider!==$('ragProvider').value)$('ragProvider').onchange();
 else $('ragCapabilityNote').textContent=selected?.status_note||'来源尚未实测';
}
function ragSearchRequest(account,payload){
 const fingerprint=ragScope(payload),previous=ragSearchAttempts.get(account);
 if(previous?.fingerprint===fingerprint)return {...payload,key:previous.key};
 const attempt={fingerprint,key:crypto.randomUUID()};ragSearchAttempts.set(account,attempt);return {...payload,key:attempt.key};
}
function bindRagSearch(account,request){
 restoreRagView(account);
 const updateSource=()=>{const provider=$('ragProvider').value,isXhs=provider==='xhs_local';$('ragAdvanced').hidden=!isXhs;for(const id of ['ragLikes','ragFavorites','ragSort'])$(id).disabled=!isXhs;
  $('ragTarget').disabled=isXhs||provider==='wikipedia';$('ragWebScope').hidden=isXhs;
  const cap=ragSourceCapabilities.get(account)?.find(p=>p.id===provider);
  $('ragCapabilityNote').textContent=cap?.status_note||'来源尚未实测；本次成功取得正文才构成读取证据。';
 };
 const changeScope=()=>{
  const state=ragViewState.get(account)||{},scope=ragScope(ragSearchPayload(account));
  if(state.scope!==scope){state.scope=scope;state.jobId=null;ragViewState.set(account,state);ragRefreshVersions.set(account,(ragRefreshVersions.get(account)||0)+1);ragSubmitVersions.set(account,(ragSubmitVersions.get(account)||0)+1);renderRagJobList(account,request,ragJobsCache.get(account)||[]);}
  saveRagView(account);ragUpdateSearchButton(account);
 };
 $('ragProvider').onchange=()=>{updateSource();changeScope();};updateSource();
 for(const id of ['ragQuery','ragTarget','ragLikes','ragFavorites','ragSort'])$(id).oninput=changeScope;
 $('ragRefresh').onclick=()=>refreshRagJobs(account,request).catch(error);
 $('ragPaste').onclick=()=>{const form=$('documentForm');const details=form?.closest?.('details');if(details)details.open=true;$('documentText')?.focus?.();};
 $('ragSearchForm').onsubmit=async e=>{
  e.preventDefault();if(ragSubmitting.has(account))return;
  const payload=ragSearchPayload(account),scope=ragScope(payload),sequence=(ragSubmitVersions.get(account)||0)+1;
  ragSubmitVersions.set(account,sequence);ragSubmitting.add(account);e.submitter.disabled=true;saveRagView(account);
  const state=ragViewState.get(account)||{};state.scope=scope;state.jobId=null;ragViewState.set(account,state);
  ragRefreshVersions.set(account,(ragRefreshVersions.get(account)||0)+1);
  const valid=()=>request===libraryLoad&&account===activeAccountId&&currentPage==='library'&&sequence===ragSubmitVersions.get(account)&&scope===ragScope(ragSearchPayload(account));
  try{
   const cap=ragSourceCapabilities.get(account)?.find(p=>p.id===payload.provider);
   if(cap&&!cap.can_attempt)throw new Error('此来源当前不可用，请切换来源或粘贴有权使用的资料');
   let job=(ragActiveJobs.get(account)||[]).find(j=>ragScope(j)===scope);
   if(job)job={...job,reused_running:true,reuse:{kind:'active_task',cache_hit:false}};
   else{renderRagJobList(account,request,ragJobsCache.get(account)||[]);job=await ragBoundedRequest('/api/research/jobs','POST',ragSearchRequest(account,payload));}
   if(!valid())return;
   const currentState=ragViewState.get(account)||{};currentState.jobId=job.id;currentState.scope=scope;currentState.reuse=job.reuse;ragViewState.set(account,currentState);saveRagView(account);
   const cached=[job,...(ragJobsCache.get(account)||[]).filter(j=>j.id!==job.id)];ragJobsCache.set(account,cached);renderRagJobList(account,request,cached);
   ragPendingAccounts.add(account);await refreshRagJobs(account,request);
  }catch(err){if(valid())error(err);}
  finally{ragSubmitting.delete(account);if(request===libraryLoad&&account===activeAccountId&&currentPage==='library')ragUpdateSearchButton(account);}
 };
 loadRagCapabilities(account,request).catch(err=>{if(request===libraryLoad&&account===activeAccountId&&currentPage==='library'){$('ragCapabilityNote').textContent='无法核对来源配置，请刷新页面后重试，或粘贴自己的资料。';error(err);}});
 refreshRagJobs(account,request).catch(error);
}

function ragErrorText(code){
 if(/^XHS_SEARCH_HTTP_[0-9]{3}$/.test(code))return '本机 MCP 搜索接口返回 HTTP '+code.slice(-3)+'；未证实是平台上游状态，请查看读取记录';
 return ({XHS_TIMEOUT:'笔记读取超时，已有候选保留，可稍后重新搜索',XHS_CONNECTION:'本机连接器无法连接，请恢复服务后重试',XHS_PARSE:'连接器响应解析失败，不代表登录失效',XHS_STRUCTURE:'平台页面结构变化或笔记不匹配，需检查连接器适配',XHS_RESTRICTED:'平台限制了本次访问，请稍后再试，不会自动绕过或反复登录',XHS_IDENTITY_CHANGED:'连接器登录账号与当前绑定不同，请到账号连接页核对',XHS_SEARCH_TIMEOUT:'平台页面读取超时，本次没有生成替代资料',XHS_SEARCH_CONNECTION:'本机搜索连接器未连通，请检查服务',XHS_TRANSPORT:'连接器读取失败，请检查本机服务后重试',XHS_PARSE_FAILED:'平台内容解析失败，已取得的候选会保留',XHS_PAGE_CHANGED:'平台页面结构变化，连接器需要适配',XHS_LOGIN_REQUIRED:'需要本人重新登录小红书',XHS_STOPPED:'账号连接已暂停，请先恢复',XHS_BUSY:'账号正在同步，完成后可发起搜索',SOURCE_VISIBILITY_CHANGED:'资料的公开状态已变化，已隐藏相关内容'})[code]||'读取未完成，请检查来源状态后再试';
}

async function documentClassificationRequest(prefix='document',explicit=false){
 const result={material_type:$(prefix+'MaterialType')?.value||'fact'},domains=($(prefix+'Domains')?.value||'').split(/[,，、]/).map(v=>v.trim()).filter(Boolean),channel=$(prefix+'Channel')?.value,format=$(prefix+'Format')?.value;
 if(domains.length){const cfg=await api('/api/creation/taxonomy');result.domains=[...new Set(domains.map(value=>Object.keys(cfg.domains).find(key=>key===value||cfg.domains[key].label===value)||value))];}
 else if(result.material_type==='fact'){if(explicit)throw new Error('事实资料请填写所属领域');if(channel||format)throw new Error('指定渠道或形式时，请同时填写事实资料的所属领域');return undefined;}
 else if(result.material_type==='example')throw new Error('参考样例请填写所属领域');
 if(channel)result.channel=channel;
 if(format)result.format=format;
 return result;
}

async function openClassificationEditor(id,account){
 const ticket=++classificationEdit;
 try{
  const d=await api('/api/knowledge/'+encodeURIComponent(id)+'?account_id='+encodeURIComponent(account));
  if(ticket!==classificationEdit||account!==activeAccountId||currentPage!=='library')return;
  const c=d.classification||d.metadata?.classification||{};
  $('documentDetail').innerHTML=`<section class="panel"><h3>调整分类：${esc(d.title)}</h3><p class="helper">资料版本 ${esc(d.version)} · 当前标签来源：${esc(({user:'用户指定',inferred:'自动识别',backfill:'历史补充'})[c.origin]||c.origin||'未知')}。未知标签请补充；保存会建立新版本，保留原文与来源。</p><form id="classificationForm"><label for="classificationDomains">领域（多个用逗号分隔）</label><input id="classificationDomains" maxlength="250" placeholder="例如：美妆、摄影、数码、家具"><label for="classificationMaterialType">材料用途</label><select id="classificationMaterialType"><option value="">请选择用途</option><option value="method">通用创作方法</option><option value="example">领域参考样例</option><option value="fact">事实资料</option></select><label for="classificationChannel">适用渠道</label><select id="classificationChannel"><option value="any">通用 / 不限渠道</option><option value="xiaohongshu">小红书</option></select><label for="classificationFormat">适用形式</label><select id="classificationFormat"><option value="any">通用 / 不限形式</option><option value="note">图文笔记</option><option value="video_script">短视频口播</option><option value="product_detail">商品详情</option></select><button type="submit" class="primary">保存分类新版本</button><button id="classificationCancel" type="button" class="quiet">取消</button></form></section>`;
  $('classificationDomains').value=(c.domains||[]).join('、');$('classificationMaterialType').value=c.material_type||'';$('classificationChannel').value=c.channel||'any';$('classificationFormat').value=c.format||'any';
  $('classificationCancel').onclick=()=>{++classificationEdit;$('documentDetail').innerHTML='';};
  $('classificationForm').onsubmit=e=>saveDocumentClassification(e,d,account,ticket);
 }catch(err){if(ticket===classificationEdit&&account===activeAccountId&&currentPage==='library')error(err);}
}
async function saveDocumentClassification(e,d,account,ticket){
 e.preventDefault();if(ticket!==classificationEdit||account!==activeAccountId||currentPage!=='library')return;
 const button=e.submitter;if(button.disabled)return;button.disabled=true;
 try{
  if(!$('classificationMaterialType').value)throw new Error('请选择材料用途');
  const classification=await documentClassificationRequest('classification',true);
  if(ticket!==classificationEdit||account!==activeAccountId||currentPage!=='library')return;
  await api('/api/knowledge/'+encodeURIComponent(d.id)+'/classification','POST',{account_id:account,version:d.version,classification});
  if(ticket!==classificationEdit||account!==activeAccountId||currentPage!=='library')return;
  toast('分类已保存为新版本，后续任务按新分类检索');++classificationEdit;await renderLibrary();
 }catch(err){if(ticket===classificationEdit&&account===activeAccountId&&currentPage==='library')error(err);}finally{button.disabled=false;}
}
