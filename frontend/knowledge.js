'use strict';
let libraryLoad=0,sourceLoad=0;
function editableKnowledgeDocuments(docs){return docs.filter(d=>d.source_type!=='research_case');}
pageInfo.library=['KNOWLEDGE / 资料库','找到好表达，写出自己的内容。','公开案例按当前账号保存，四角色自动学习相关表达；产品事实仍以你的资料为准。'];
async function renderLibrary(){
 const request=++libraryLoad,account=activeAccountId;
 $('operationsContent').innerHTML='<section class="panel"><p class="muted">正在读取当前账号资料…</p></section>';
 try{
  const docs=await api('/api/knowledge?account_id='+encodeURIComponent(account));
  if(request!==libraryLoad||currentPage!=='library'||account!==activeAccountId)return;
  $('operationsContent').innerHTML=`<div class="section-toolbar"><div><h2>RAG 资料库</h2><p class="muted">${esc(currentAccount().name)} · ${docs.length} 份有效资料</p></div>${badge('原文与版本可追溯','neutral')}</div>${ragSearchPanel()}<details class="panel"><summary>补充自己的事实资料 / 检索验证</summary><div class="knowledge-grid"><section class="panel"><h2>添加或更新资料</h2><form id="documentForm"><label for="documentTarget">保存方式</label><select id="documentTarget"><option value="">新增资料</option>${editableKnowledgeDocuments(docs).map(d=>`<option value="${esc(d.id)}">更新：${esc(d.title)} · v${d.version}</option>`).join('')}</select><p class="helper">研究案例不在此处更新；需使用案例专用编辑接口，保留来源、资料用途和未读线索限制。</p><label for="documentTitle">资料标题</label><input id="documentTitle" maxlength="200" required placeholder="例如：品牌介绍 / 我的表达风格 / 产品事实"><label for="documentFile">上传文件</label><input id="documentFile" type="file" accept=".txt,.md,.pdf,.docx"><p class="helper">支持 UTF-8 TXT、Markdown、文本型 PDF 和 Word .docx，单份最大 3 MB；PDF 最多 50 页。扫描 PDF 暂不支持 OCR。上传只做本地解析，不调用 AI。</p><label for="documentText">或粘贴正文</label><textarea id="documentText" rows="6" maxlength="100000" placeholder="粘贴真实资料；选了文件时以文件内容为准"></textarea><button class="primary" type="submit">保存并建立检索索引</button></form></section><section class="panel"><h2>试着检索资料</h2><p class="muted">输入问题或关键词查找相关原文；检索结果会显示当前方式，得分不代表事实可信程度。</p><form id="retrieveForm" class="search-line"><input id="retrieveQuery" maxlength="300" required aria-label="资料检索词" placeholder="例如：白衬衫的面料与护理"><button class="secondary">查找原文</button></form><div id="retrievalResult" class="source-results"><p class="helper">高赞收藏表达参考自动进入新创作的四角色证据快照；额外事实资料可在创作时勾选。</p></div></section></div></details><section class="panel"><h2>已保存资料</h2><div class="source-results">${docs.map(d=>`<article class="document-row"><div><b>${esc(d.title)}</b>${ragDocumentMeta(d)}<p class="helper">v${d.version} · ${esc(({text:'粘贴文本',upload:'上传文件',web:'已读取网页',research_case:'研究案例'})[d.source_type])} · ${esc(new Date(d.updated_at*1000).toLocaleString())}</p></div><div class="buttons"><button class="quiet" data-document="${esc(d.id)}">查看原文</button><button class="quiet" data-delete-document="${esc(d.id)}">移出资料库</button></div></article>`).join('')||'<p class="helper">还没有资料。可以先上传一份品牌或账号介绍。</p>'}</div><div id="documentDetail"></div></section>`;
  bindRagSearch(account,request);
  $('documentTarget').onchange=()=>{const d=docs.find(d=>d.id===$('documentTarget').value);if(d)$('documentTitle').value=d.title;};
  $('documentForm').onsubmit=async e=>{
   e.preventDefault();const button=e.submitter;button.disabled=true;
   const data={account_id:account,title:$('documentTitle').value};
   const doc=docs.find(d=>d.id===$('documentTarget').value);if(doc){data.document_id=doc.id;data.expected_version=doc.version;}
   const file=$('documentFile').files[0];
   try{
    if(doc?.source_type==='research_case')throw new Error('研究案例请使用案例专用编辑接口，不能转为普通资料');
    if(file){if(file.size>3000000)throw new Error('文件超过 3 MB');data.filename=file.name;data.file_base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});}
    else data.text=$('documentText').value;
    await api('/api/knowledge','POST',data);toast('资料已保存，后续创作可检索');if(account===activeAccountId&&currentPage==='library')await renderLibrary();
   }catch(err){error(err);}finally{button.disabled=false;}
  };
  $('retrieveForm').onsubmit=async e=>{
   e.preventDefault();e.submitter.disabled=true;
   try{const result=await api('/api/knowledge/retrieve','POST',{account_id:account,query:$('retrieveQuery').value});if(account!==activeAccountId||currentPage!=='library')return;
    $('retrievalResult').innerHTML=`<p class="helper">${esc(result.engine)} · ${esc(result.note||'')}</p>`+(result.sources.length?result.sources.map(s=>`<article class="source-card"><b>${esc(s.title)}</b><p class="helper">v${s.version} · ${s.location_type==='paragraph'?'段落':'第 '+s.page+' 页'} ${s.location_type==='paragraph'?s.page:''} · 字符位置 ${s.offset} · 相关度 ${s.score}</p><blockquote>${esc(s.text)}</blockquote><small>${esc(s.verification)}</small></article>`).join(''):'<p class="issue">没有找到足够相关的资料。请补充资料或换更具体的关键词。</p>');
   }catch(err){error(err);}finally{e.submitter.disabled=false;}
  };
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

function ragSearchPanel(){return `<section class="panel"><h2>搜索小红书，收录高赞收藏参考</h2><p class="muted">输入主题，读取公开笔记文字和可见赞藏，符合筛选的正文直接进入当前账号 RAG。四个角色在新创作时自动检索并学习表达结构。</p><form id="ragSearchForm"><label for="ragQuery">主题关键词</label><input id="ragQuery" required minlength="2" maxlength="120" placeholder="例如：美妆 口红色号"><div class="form-grid"><div><label for="ragLikes">点赞至少</label><input id="ragLikes" type="number" min="1" max="1000000000" value="100" required></div><div><label for="ragFavorites">或收藏至少</label><input id="ragFavorites" type="number" min="1" max="1000000000" value="50" required></div><div><label for="ragSort">优先排序</label><select id="ragSort"><option value="likes">最多点赞</option><option value="favorites">最多收藏</option></select></div></div><p class="helper">只收录达到任一阈值且已读正文的公开笔记；每次最多核对 6 篇、保存 3 篇。视频仅使用文字描述。</p><button class="primary">搜索并加入 RAG</button></form><div id="ragJobResult"></div></section>`;}
function ragDocumentMeta(d){const c=d.metadata?.research_case;if(!c)return '';const m=c.metrics||{};return `<p class="helper">点赞 ${esc(m.likes??'未知')} · 收藏 ${esc(m.favorites??'未知')} · ${c.provenance?.style_library_eligible===true?'自动表达参考':'普通资料'}${d.source_url?` · <a href="${esc(d.source_url)}" target="_blank" rel="noopener noreferrer">原文来源 ↗</a>`:''}</p>`;}
async function refreshRagJobs(account,request){
 const jobs=await api('/api/research/jobs?account_id='+encodeURIComponent(account));
 if(request!==libraryLoad||account!==activeAccountId||currentPage!=='library')return;
 const names={queued:'等待读取',running:'正在搜索与核对',done:'收录完成',partial:'部分完成',failed:'没有收录到资料',interrupted:'读取中断',cancelled:'已取消'};
 $('ragJobResult').innerHTML=jobs.slice(0,3).map(j=>`<article class="document-row"><div><b>${esc(j.queries.join(' / '))}</b><p class="helper">${esc(names[j.status]||j.status)} · 本次收录 ${j.documents.length} 篇${j.error?' · '+esc(j.error):''}</p></div>${['queued','running'].includes(j.status)?'<span>处理中…</span>':`<a class="button quiet" href="/api/research/jobs/${encodeURIComponent(j.id)}/export">导出本次资料</a>`}</article>`).join('');
 if(jobs.some(j=>['queued','running'].includes(j.status)))setTimeout(()=>refreshRagJobs(account,request).catch(error),4000);
 else if(ragPendingAccounts.delete(account))await renderLibrary();
}
const ragPendingAccounts=new Set();
function bindRagSearch(account,request){
 $('ragSearchForm').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;
 try{await api('/api/research/jobs','POST',{account_id:account,queries:[$('ragQuery').value.trim()],provider:'xhs_local',targets:['xiaohongshu'],evidence_role:'expression_reference',permission_confirmed:true,key:crypto.randomUUID(),style_filters:{min_likes:Number($('ragLikes').value),min_favorites:Number($('ragFavorites').value),sort_by:$('ragSort').value}});ragPendingAccounts.add(account);await refreshRagJobs(account,request);}catch(err){error(err);}finally{b.disabled=false;}};
 refreshRagJobs(account,request).catch(error);
}
