'use strict';
let libraryLoad=0,sourceLoad=0;
pageInfo.library=['KNOWLEDGE / 资料库','让每次创作，都找得到依据。','资料按当前账号保存。原文、版本与检索出处可以回查。'];

function knowledgeSourceLink(value){
 try{
  const url=new URL(value);
  return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password
   ?`<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">查看网页来源 ↗</a>`:'';
 }catch{return '';}
}
function knowledgeProvenance(metadata){
 const m=metadata||{};
 return `<p class="helper">来源：${esc(m.source_label||m.source_type||'未记录')} · 作者/归属：${esc(m.author||'未记录')} · 来源日期：${esc(m.published_at||'未记录或未核实')}</p>
  <p class="helper">使用范围：${esc(m.license||'未记录；使用前请核对授权')} ${esc(m.boundary||'')}</p>`;
}

async function renderLibrary(){
 const request=++libraryLoad,account=activeAccountId;
 const current=()=>request===libraryLoad&&currentPage==='library'&&account===activeAccountId;
 let detailRequest=0,retrieveRequest=0,previewRequest=0;
 $('operationsContent').innerHTML='<section class="panel"><p class="muted">正在读取当前账号资料…</p></section>';
 try{
  const query='?account_id='+encodeURIComponent(account);
  const [docs,packs]=await Promise.all([api('/api/knowledge'+query),api('/api/knowledge/packs'+query)]);
  if(!current())return;
  $('operationsContent').innerHTML=`<div class="section-toolbar"><div><h2>账号资料库</h2><p class="muted">${esc(currentAccount().name)} · ${docs.length} 份有效资料</p></div>${badge('原文与版本可追溯','neutral')}</div>
   <section class="panel"><h2>从原创入门资料开始</h2><p class="muted">项目自编指南，不是平台官方知识。先查看来源、使用范围和原文，再决定是否导入当前账号；不联网、不调用模型。</p>
    <div class="buttons">${packs.map(p=>`<button class="secondary" data-preview-pack="${esc(p.id)}" ${p.available?'':'disabled'}>${esc(p.title)} · v${esc(p.version)} · ${esc(p.count)} 份${p.demo_only?'（仅演示账号）':''}</button>`).join('')}</div><div id="packPreview"></div><div id="packImportResult" aria-live="polite"></div></section>
   <div class="knowledge-grid"><section class="panel"><h2>添加或更新资料</h2><form id="documentForm">
    <label for="documentTarget">保存方式</label><select id="documentTarget"><option value="">新增资料</option>${docs.map(d=>`<option value="${esc(d.id)}">更新：${esc(d.title)} · v${esc(d.version)}</option>`).join('')}</select>
    <label for="documentTitle">资料标题</label><input id="documentTitle" maxlength="200" required placeholder="例如：品牌介绍 / 我的表达风格 / 产品事实">
    <label for="documentFile">上传文件</label><input id="documentFile" type="file" accept=".txt,.md,.pdf"><p class="helper">支持 UTF-8 TXT、Markdown、文本型 PDF，最大 3 MB / 50 页。扫描件暂不支持。</p>
    <label for="documentText">或粘贴正文</label><textarea id="documentText" rows="6" maxlength="100000" placeholder="粘贴真实资料；选了文件时以文件内容为准"></textarea>
    <button class="primary" type="submit">保存并建立检索索引</button></form></section>
   <section class="panel"><h2>试着检索资料</h2><p class="muted">只检索当前有效版本。得分用于排序，不代表事实可信程度。</p><form id="retrieveForm" class="search-line"><input id="retrieveQuery" maxlength="300" required aria-label="资料检索词" placeholder="例如：资料版本与证据"><button class="secondary">查找原文</button></form><div id="retrievalResult" class="source-results"><p class="helper">创作时勾选“检索当前账号资料”，相关片段会进入四个角色的证据快照。</p></div></section></div>
   <section class="panel"><h2>已保存资料</h2><div class="source-results">${docs.map(d=>`<article class="document-row"><div><b>${esc(d.title)}</b><p class="helper">v${esc(d.version)} · ${esc(({text:'粘贴文本',upload:'上传文件',web:'已读取网页',project_guide:'项目原创指南'})[d.source_type]||'来源未记录')} · ${esc(new Date(d.updated_at*1000).toLocaleString())}</p></div><div class="buttons"><button class="quiet" data-document="${esc(d.id)}">查看原文 / 版本</button><button class="quiet" data-delete-document="${esc(d.id)}">移出资料库</button></div></article>`).join('')||'<p class="helper">还没有资料。可先预览原创指南，或上传你自己的材料。</p>'}</div><div id="documentDetail" aria-live="polite"></div></section>`;

  $('documentTarget').onchange=()=>{const d=docs.find(d=>d.id===$('documentTarget').value);if(d)$('documentTitle').value=d.title;};
  $('documentForm').onsubmit=async e=>{
   e.preventDefault();if(!current())return;
   const button=e.submitter;if(button.disabled)return;button.disabled=true;
   const data={account_id:account,title:$('documentTitle').value};
   const doc=docs.find(d=>d.id===$('documentTarget').value);if(doc){data.document_id=doc.id;data.expected_version=doc.version;}
   const file=$('documentFile').files[0],text=$('documentText').value;
   try{
    if(file){if(file.size>3000000)throw new Error('文件超过 3 MB');data.filename=file.name;data.file_base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});}
    else data.text=text;
    if(!current())return;
    await api('/api/knowledge','POST',data);
    if(current()){toast('资料已保存，后续创作可检索');await renderLibrary();}
   }catch(err){if(current())error(err);}finally{button.disabled=false;}
  };
  $('retrieveForm').onsubmit=async e=>{
   e.preventDefault();if(!current())return;
   const button=e.submitter,sequence=++retrieveRequest;button.disabled=true;
   const text=$('retrieveQuery').value;
   try{
    const result=await api('/api/knowledge/retrieve','POST',{account_id:account,query:text});
    if(!current()||sequence!==retrieveRequest)return;
    $('retrievalResult').innerHTML=result.sources.length?result.sources.map(s=>`<article class="source-card"><b>${esc(s.title)}</b><p class="helper">v${esc(s.version)} · 第 ${esc(s.page)} 页 · 字符位置 ${esc(s.offset)} · 相关度 ${esc(s.score)}</p><blockquote>${esc(s.text)}</blockquote><small>${esc(s.verification)}</small><p class="helper">SHA-256：${esc(s.fingerprint||'历史记录未保存指纹')}</p></article>`).join(''):'<p class="issue">没有找到足够相关的资料。请补充资料或换更具体的关键词。</p>';
   }catch(err){if(current()&&sequence===retrieveRequest)error(err);}finally{if(sequence===retrieveRequest)button.disabled=false;}
  };

  const loadDocument=async(identity,version)=>{
   if(!current())return;
   const sequence=++detailRequest;
   $('documentDetail').textContent='正在读取原文版本…';
   try{
    const d=await api('/api/knowledge/'+encodeURIComponent(identity)+query+(version?'&version='+encodeURIComponent(version):''));
    if(!current()||sequence!==detailRequest)return;
    $('documentDetail').innerHTML=`<hr><h3>${esc(d.title)} · v${esc(d.version)}</h3>
     <label for="documentVersion">回查版本（历史版本只读）</label><select id="documentVersion">${d.versions.map(v=>`<option value="${esc(v.version)}" ${v.version===d.version?'selected':''}>v${esc(v.version)}${v.version===d.current_version?' · 当前有效版本':' · 历史只读'} · ${esc(v.metadata.title||'标题未记录')}</option>`).join('')}</select>
     <p class="helper">${d.read_only?'历史只读版本，不进入新任务默认检索。':'当前有效版本；编辑请使用上方“更新资料”。'} · 文件：${esc(d.filename)}<br>完整原文 SHA-256：${esc(d.fingerprint)}</p>
     ${knowledgeProvenance(d.metadata)}${knowledgeSourceLink(d.source_url)}
     <p class="helper">该版入库时间：${esc(d.stored_at?new Date(d.stored_at*1000).toLocaleString():'未记录')} · 网页读取时间：${esc(d.metadata.fetched_at||'未记录')} ${d.source_recorded?'':'· 该版来源快照缺失，不以当前来源替代。'}</p>
     ${d.chunks.map(c=>`<details><summary>第 ${esc(c.page)} 页 · 字符位置 ${esc(c.offset)}</summary><pre class="source-text">${esc(c.text)}</pre></details>`).join('')}`;
    $('documentVersion').onchange=e=>loadDocument(identity,e.target.value);
   }catch(err){if(current()&&sequence===detailRequest){$('documentDetail').textContent='此资料或版本暂不可读取，请刷新后重试。';error(err);}}
  };
  document.querySelectorAll('[data-document]').forEach(b=>b.onclick=()=>loadDocument(b.dataset.document));
  document.querySelectorAll('[data-delete-document]').forEach(b=>b.onclick=async()=>{
   if(!current()||b.disabled)return;
   const d=docs.find(d=>d.id===b.dataset.deleteDocument);
   if(!window.confirm('移出资料库后，新任务不会再检索这份资料。已有任务的证据快照保留用于回查；重复导入资料包不会恢复它。'))return;
   b.disabled=true;
   try{await api('/api/knowledge/'+encodeURIComponent(d.id)+'/delete','POST',{account_id:account,version:d.version});if(current())await renderLibrary();}
   catch(err){if(current())error(err);}finally{b.disabled=false;}
  });

  document.querySelectorAll('[data-preview-pack]').forEach(b=>b.onclick=async()=>{
   if(!current())return;
   const sequence=++previewRequest;
   $('packPreview').textContent='正在读取资料包原文…';
   try{
    const packet=await api('/api/knowledge/packs/'+encodeURIComponent(b.dataset.previewPack)+query);
    if(!current()||sequence!==previewRequest)return;
    $('packPreview').innerHTML=`<h3>${esc(packet.title)} · v${esc(packet.version)}</h3><p class="helper">${esc(packet.note)}<br>资料包 SHA-256：${esc(packet.fingerprint)}</p>
     ${packet.documents.map(d=>`<details><summary>${esc(d.title)}</summary>${knowledgeProvenance(d)}<p class="helper">原文 SHA-256：${esc(d.fingerprint)}</p><pre class="source-text">${esc(d.text)}</pre></details>`).join('')}
     <p class="helper">导入到 ${esc(currentAccount().name)}。相同版本跳过；已编辑、已移除或冲突的资料不会覆盖或恢复。</p><button id="importKnowledgePack" class="primary">确认将这 ${esc(packet.documents.length)} 份资料导入当前账号</button>`;
    $('importKnowledgePack').onclick=async e=>{
     const button=e.currentTarget;
     if(!current()||sequence!==previewRequest||button.disabled)return;
     button.disabled=true;
     try{
      const result=await api('/api/knowledge/packs/'+encodeURIComponent(packet.id)+'/import','POST',{account_id:account,version:packet.version,fingerprint:packet.fingerprint});
      if(!current()||sequence!==previewRequest)return;
      // Only place the receipt in this import's refresh, never a newer page.
      const nextRequest=libraryLoad+1;
      await renderLibrary();
      if(libraryLoad!==nextRequest||currentPage!=='library'||account!==activeAccountId)return;
      $('packImportResult').innerHTML=`<p>导入完成：新增 ${esc(result.created)}，已存在跳过 ${esc(result.skipped)}，冲突未改动 ${esc(result.conflict)}。</p>${result.documents.map(d=>`<p class="helper">${esc(d.title)}：${esc(d.reason)}</p>`).join('')}`;
     }catch(err){if(current()&&sequence===previewRequest)error(err);}finally{button.disabled=false;}
    };
   }catch(err){if(current()&&sequence===previewRequest){$('packPreview').textContent='资料包暂不可读取，请重试。';error(err);}}
  });
 }catch(err){if(current()){$('operationsContent').innerHTML='<section class="panel"><p class="issue">资料库暂不可用，请重新打开本页。</p></section>';error(err);}}
}

function mountSourceSearch(){
 if(!websiteSession?.auth_required)return;
 const account=activeAccountId,mount=++sourceLoad;
 let searchRequest=0;
 const current=()=>mount===sourceLoad&&account===activeAccountId&&currentPage==='trends';
 $('operationsContent').insertAdjacentHTML('afterbegin',`<section class="panel source-search"><div class="detail-heading"><div><span class="eyebrow">PUBLIC SOURCES</span><h2>搜索真实信息来源</h2></div>${badge('公开网页 · 非平台热榜','neutral')}</div><p class="muted">搜索词会发送给公开搜索服务；仅发送你填写的关键词。摘要是线索，读取正文并保存后才会进入账号资料库。</p><form id="sourceSearchForm" class="search-line"><select id="sourceProvider" aria-label="搜索来源"><option value="wikipedia">百科资料 · 背景知识</option><option value="bing">公开网页 · 实验搜索</option></select><input id="sourceQuery" maxlength="120" minlength="2" required aria-label="搜索公开网页" placeholder="例如：衬衫 / 棉 / 亚麻"><button class="primary">联网搜索</button></form><form id="sourceUrlForm" class="search-line"><input id="sourceUrl" type="url" required aria-label="读取网页链接" placeholder="或粘贴公开网页链接 https://…"><button class="secondary">读取正文并保存</button></form><div id="sourceSearchResult" class="source-results"></div></section>`);
 const importUrl=async(url,button,keepSaved=false)=>{
  if(!current()||button.disabled)return;
  button.disabled=true;const text=button.textContent;button.textContent='正在读取…';
  try{const doc=await api('/api/sources/import','POST',{url,account_id:account});if(current()){toast('已保存到 '+(ops.accounts.find(a=>a.id===account)?.name||'原账号')+' 的资料库：'+doc.title);button.textContent='已保存正文';}}
  catch(err){if(current())error(err);button.disabled=false;button.textContent=text;}
  finally{if(!keepSaved){button.disabled=false;button.textContent=text;}}
 };
 $('sourceUrlForm').onsubmit=e=>{e.preventDefault();return importUrl($('sourceUrl').value,e.submitter);};
 $('sourceSearchForm').onsubmit=async e=>{
  e.preventDefault();if(!current())return;
  const request=++searchRequest,button=e.submitter;button.disabled=true;$('sourceSearchResult').textContent='正在搜索公开来源…';
  try{
   const result=await api('/api/sources/search','POST',{query:$('sourceQuery').value,account_id:account,provider:$('sourceProvider').value});
   if(request!==searchRequest||!current())return;
   $('sourceSearchResult').innerHTML=`<p class="helper">${esc(result.provider)} · ${esc(result.note)}</p>`+(result.results.map((r,i)=>`<article class="source-card"><div class="detail-heading"><h3>${esc(r.title)}</h3>${badge('摘要 · 正文未读取','amber')}</div><p>${esc(r.snippet)}</p><p class="helper">${esc(new URL(r.url).hostname)} · 检索时间 ${esc(new Date(r.fetched_at).toLocaleString())} · 发布时间未核实</p><div class="buttons">${knowledgeSourceLink(r.url)}<button class="secondary" data-read-source="${i}">读取正文并保存</button></div></article>`).join('')||'<p class="helper">没有搜索结果，请换一组关键词。</p>');
   document.querySelectorAll('[data-read-source]').forEach(b=>b.onclick=()=>importUrl(result.results[Number(b.dataset.readSource)].url,b,true));
  }catch(err){if(request===searchRequest&&current()){$('sourceSearchResult').textContent='来源暂不可用，没有生成替代结果。可以粘贴可访问的网页链接。';error(err);}}
  finally{if(request===searchRequest)button.disabled=false;}
 };
}
