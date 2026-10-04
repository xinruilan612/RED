'use strict';
let libraryLoad=0,sourceLoad=0;
pageInfo.library=['KNOWLEDGE / 资料库','让每次创作，都找得到依据。','常用产品资料存一次，以后写同一产品可以重复使用；只用这一次的素材，直接粘贴到创作页即可。'];
async function renderLibrary(){
 const request=++libraryLoad,account=activeAccountId;
 $('operationsContent').innerHTML='<section class="panel"><p class="muted">正在读取当前账号资料…</p></section>';
 try{
  const docs=await api('/api/knowledge?account_id='+encodeURIComponent(account));
  if(request!==libraryLoad||currentPage!=='library'||account!==activeAccountId)return;
  await refreshMaterialDocuments();
  if(request!==libraryLoad||currentPage!=='library'||account!==activeAccountId)return;
  $('operationsContent').innerHTML=`<div class="section-toolbar"><div><h2>账号资料库</h2><p class="muted">${esc(currentAccount().name)} · ${docs.length} 份有效资料</p></div>${badge('原文与版本可追溯','neutral')}</div><div class="knowledge-grid"><section class="panel"><h2>添加或更新资料</h2><form id="documentForm"><label for="documentTarget">保存方式</label><select id="documentTarget"><option value="">新增资料</option>${docs.map(d=>`<option value="${esc(d.id)}">更新：${esc(d.title)} · v${d.version}</option>`).join('')}</select><label for="documentTitle">资料标题</label><input id="documentTitle" maxlength="200" required placeholder="例如：品牌介绍 / 我的表达风格 / 产品事实"><label for="documentFile">上传文件</label><input id="documentFile" type="file" accept=".txt,.md,.pdf,.docx"><p class="helper">支持 UTF-8 TXT、Markdown、文本型 PDF 和 Word .docx，单份最大 3 MB；PDF 最多 50 页。扫描 PDF 暂不支持 OCR。上传只做本地解析，不调用 AI。</p><label for="documentText">或粘贴正文</label><textarea id="documentText" rows="6" maxlength="100000" placeholder="粘贴真实资料；选了文件时以文件内容为准"></textarea><button class="primary" type="submit">保存资料</button></form></section><section class="panel"><h2>试着检索资料</h2><p class="muted">使用关键词查找相关原文；得分只用于排序，不代表事实可信程度。</p><form id="retrieveForm" class="search-line"><input id="retrieveQuery" maxlength="300" required aria-label="资料检索词" placeholder="例如：白衬衫的面料与护理"><button class="secondary">查找原文</button></form><div id="retrievalResult" class="source-results"><p class="helper">点击已保存资料的“用这份资料创作”，写稿时会查找相关原文并保留出处。资料来自哪里、是否可靠，仍需你确认。</p></div></section></div><section class="panel"><h2>已保存资料</h2><div class="source-results">${docs.map(d=>`<article class="document-row"><div><b>${esc(d.title)}</b><p class="helper">v${d.version} · ${esc(({text:'粘贴文本',upload:'上传文件',web:'已读取网页'})[d.source_type])} · ${esc(new Date(d.updated_at*1000).toLocaleString())}</p></div><div class="buttons"><button class="secondary" data-create-document="${esc(d.id)}">用这份资料创作</button><button class="quiet" data-document="${esc(d.id)}">查看原文</button><button class="quiet" data-delete-document="${esc(d.id)}">移出资料库</button></div></article>`).join('')||'<p class="helper">还没有资料。可以先上传一份品牌或账号介绍。</p>'}</div><div id="documentDetail"></div></section>`;
  $('documentTarget').onchange=()=>{const d=docs.find(d=>d.id===$('documentTarget').value);if(d)$('documentTitle').value=d.title;};
  $('documentForm').onsubmit=async e=>{
   e.preventDefault();const button=e.submitter;button.disabled=true;
   const data={account_id:account,title:$('documentTitle').value};
   const doc=docs.find(d=>d.id===$('documentTarget').value);if(doc){data.document_id=doc.id;data.expected_version=doc.version;}
   const file=$('documentFile').files[0];
   try{
    if(file){if(file.size>3000000)throw new Error('文件超过 3 MB');data.filename=file.name;data.file_base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});}
    else data.text=$('documentText').value;
    await api('/api/knowledge','POST',data);toast('资料已保存，后续创作可检索');if(account===activeAccountId&&currentPage==='library')await renderLibrary();
   }catch(err){error(err);}finally{button.disabled=false;}
  };
  $('retrieveForm').onsubmit=async e=>{
   e.preventDefault();e.submitter.disabled=true;
   try{const result=await api('/api/knowledge/retrieve','POST',{account_id:account,query:$('retrieveQuery').value});if(account!==activeAccountId||currentPage!=='library')return;
    $('retrievalResult').innerHTML=result.sources.length?result.sources.map(s=>`<article class="source-card"><b>${esc(s.title)}</b><p class="helper">v${s.version} · ${s.location_type==='paragraph'?'段落':'第 '+s.page+' 页'} ${s.location_type==='paragraph'?s.page:''} · 字符位置 ${s.offset} · 相关度 ${s.score}</p><blockquote>${esc(s.text)}</blockquote><small>${esc(s.verification)}</small></article>`).join(''):'<p class="issue">没有找到足够相关的资料。请补充资料或换更具体的关键词。</p>';
   }catch(err){error(err);}finally{e.submitter.disabled=false;}
  };
  document.querySelectorAll('[data-create-document]').forEach(b=>b.onclick=()=>createFromLibrary(b.dataset.createDocument,account));
  document.querySelectorAll('[data-document]').forEach(b=>b.onclick=async()=>{
   try{const d=await api('/api/knowledge/'+b.dataset.document+'?account_id='+encodeURIComponent(account));if(account!==activeAccountId||currentPage!=='library')return;
    $('documentDetail').innerHTML=`<hr><h3>${esc(d.title)} · v${d.version}</h3><p class="helper">${d.versions.length} 个版本 · 原文指纹 ${esc(d.fingerprint.slice(0,16))}</p>${d.source_url?`<a href="${esc(d.source_url)}" target="_blank" rel="noopener noreferrer">查看网页来源 ↗</a>`:''}<p class="helper">${d.metadata.fetched_at?'读取时间：'+esc(d.metadata.fetched_at):''} ${d.metadata.published_at?'页面声明发布时间：'+esc(d.metadata.published_at):'发布时间未提供或未核实'}</p>${d.chunks.map(c=>`<details><summary>${d.metadata.location_type==='paragraph'?'段落 '+c.page:'第 '+c.page+' 页'} · 字符位置 ${c.offset}</summary><pre class="source-text">${esc(c.text)}</pre></details>`).join('')}`;
   }catch(err){error(err);}
  });
  document.querySelectorAll('[data-delete-document]').forEach(b=>b.onclick=async()=>{
   const d=docs.find(d=>d.id===b.dataset.deleteDocument);if(!window.confirm('移出资料库后，新任务不会再检索这份资料。已有任务的证据快照保留用于回查。'))return;
   try{await api('/api/knowledge/'+d.id+'/delete','POST',{account_id:account,version:d.version});if(account===activeAccountId&&currentPage==='library')await renderLibrary();}catch(err){error(err);}
  });
 }catch(err){error(err);}
}

async function createFromLibrary(documentId,account){
 if(account!==activeAccountId||!startCreation())return;
 const sequence=creationSequence;
 await refreshMaterialDocuments();
 if(account!==activeAccountId||currentPage!=='studio'||run!==null||sequence!==creationSequence)return;
 const picker=$('materialDocumentSelect');
 const option=[...picker.options].find(o=>o.value===documentId);
 if(!option){error(new Error('这份资料已不可用，请回资料库刷新后重新选择。'));return;}
 [...picker.options].forEach(o=>o.selected=o===option);
 $('useKnowledge').checked=true;
 $('materialFileBox').hidden=false;$('materialFileBox').open=true;
 toast('已选中这份资料。填写选题后再开始创作；当前未调用 AI。');
}

function mountSourceSearch(){
 if(!websiteSession?.auth_required)return;
 const account=activeAccountId;
 $('operationsContent').insertAdjacentHTML('afterbegin',`<section class="panel source-search"><div class="detail-heading"><div><span class="eyebrow">PUBLIC SOURCES</span><h2>搜索真实信息来源</h2></div>${badge('公开网页 · 非平台热榜','neutral')}</div><p class="muted">搜索词会发送给公开搜索服务；仅发送你填写的关键词。摘要是线索，读取正文并保存后才会进入账号资料库。</p><form id="sourceSearchForm" class="search-line"><select id="sourceProvider" aria-label="搜索来源"><option value="bing">免费公开网页搜索</option><option value="wikipedia">百科资料 · 背景知识</option><option value="brave">Brave 网页搜索 · 需独立密钥</option></select><input id="sourceQuery" maxlength="120" minlength="2" required aria-label="搜索公开网页" placeholder="例如：衬衫 / 棉 / 亚麻"><button class="primary">联网搜索</button></form><form id="sourceUrlForm" class="search-line"><input id="sourceUrl" type="url" required aria-label="读取网页链接" placeholder="或粘贴公开网页链接 https://…"><button class="secondary">读取正文并保存</button></form><div id="sourceImportStatus" role="status"></div><div id="sourceSearchResult" class="source-results"></div></section>`);
 const importUrl=async(url,button)=>{
  if(account!==activeAccountId)return;
  button.disabled=true;const text=button.textContent;button.textContent='正在读取…';
  $('sourceImportStatus').textContent='';
  try{const doc=await api('/api/sources/import','POST',{url,account_id:account});toast('已保存到 '+(ops.accounts.find(a=>a.id===account)?.name||'原账号')+' 的资料库：'+doc.title);button.textContent='已保存正文';}
  catch(err){
   button.disabled=false;button.textContent=text;
   if(account!==activeAccountId||currentPage!=='trends')return;
   $('sourceImportStatus').innerHTML=`<div class="issue"><p>这次没能读取网页：${esc(err.message||'读取失败')}</p><p>可以自行打开来源，将可使用的原文粘贴到资料库，并注明链接和日期。系统不会自动重试，也不会把搜索摘要当成已读正文。</p><button class="secondary" id="sourceManualFallback">去资料库粘贴原文 →</button></div>`;
   $('sourceManualFallback').onclick=()=>showPage('library');
  }
 };
 $('sourceUrlForm').onsubmit=e=>{e.preventDefault();importUrl($('sourceUrl').value,e.submitter);};
 $('sourceSearchForm').onsubmit=async e=>{
  e.preventDefault();const request=++sourceLoad;const button=e.submitter;button.disabled=true;$('sourceSearchResult').textContent='正在搜索，最长约 20 秒；不会调用 AI…';
  try{
   const result=await api('/api/sources/search','POST',{query:$('sourceQuery').value,account_id:account,provider:$('sourceProvider').value});
   if(request!==sourceLoad||account!==activeAccountId||currentPage!=='trends')return;
   $('sourceSearchResult').innerHTML=`<p class="helper">${esc(result.provider)} · ${result.cache_hit?'复用最近 5 分钟结果 · ':''}${esc(result.note)}</p>`+((result.results.map((r,i)=>`<article class="source-card"><div class="detail-heading"><h3>${esc(r.title)}</h3>${badge('摘要 · 正文未读取','amber')}</div><p>${esc(r.snippet)}</p><p class="helper">${esc(new URL(r.url).hostname)} · 检索时间 ${esc(new Date(r.fetched_at).toLocaleString())} · 发布时间未核实</p><div class="buttons"><a class="button quiet" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">打开来源 ↗</a><button class="secondary" data-read-source="${i}">读取正文并保存</button></div></article>`).join('')||'<p class="helper">没有找到相关结果。试试更短的关键词，或粘贴来源链接；也可以到资料库直接粘贴原文 / 上传文件，然后继续创作。</p>'));
   document.querySelectorAll('[data-read-source]').forEach(b=>b.onclick=()=>importUrl(result.results[Number(b.dataset.readSource)].url,b));
  }catch(err){if(request===sourceLoad&&account===activeAccountId&&currentPage==='trends'){$('sourceSearchResult').textContent='搜索暂不可用。已保存的资料仍可使用；你可以重试、粘贴网页链接，或到资料库粘贴原文 / 上传文件继续。';error(err);}}
  finally{button.disabled=false;}
 };
}
