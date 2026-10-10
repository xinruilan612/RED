'use strict';
pageInfo.research=['RESEARCH / CASES','把案例研究，变成可引用的资料。','搜索、读取、整理和导出；表达参考与商品事实分别保存。'];
let researchLoad=0,researchTimer=null,researchBusy=false,researchPending=null;
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
function caseCards(cases){
 return cases.map(d=>{
  const c=d.metadata?.research_case||{},a=c.assessment||{};
  return `<article class="panel"><div class="detail-heading"><h3>${esc(d.title)}</h3>${badge(c.evidence_role==='product_fact'?'商品事实 · 待核验':'表达参考','neutral')}</div><p class="helper">${esc(c.platform||'')} · ${esc(c.author||'作者未知')} · v${d.version}</p><p>${badge(a.status==='high_interaction_candidate'?'高互动候选':c.content_kind==='lead'?'未读线索 · 不参与检索':'已保存案例','amber')} ${esc(a.limitation||'')}</p><p class="helper">已知互动：${a.known_interactions==null?'未知':esc(a.known_interactions)} · 观察时间：${c.observed_at?esc(dateText(c.observed_at)):'未知'}</p><p>${d.source_url?researchSourceLink(d.source_url,'查看原始来源 ↗'):'用户提供资料，无公开链接'}</p><button class="quiet" data-case-detail="${esc(d.id)}">查看正文与依据</button><div id="caseDetail-${esc(d.id)}"></div></article>`;
 }).join('')||'<section class="panel"><p>还没有案例。可以发起一次公开网页研究，或添加你有权使用的正文、字幕与指标。</p></section>';
}
function jobCards(jobs){
 return jobs.map(j=>`<article class="panel"><div class="detail-heading"><h3>${esc((j.queries||[]).join('；'))}</h3>${badge(researchStates[j.status]||j.status,j.status==='done'?'':'amber')}</div><p class="helper">${esc(j.provider||'')} · ${esc((j.targets||[]).join(' / '))} · ${esc(dateText(new Date(j.created_at*1000).toISOString()))}</p><p>已保存 ${(j.documents||[]).length} 份正文；检索覆盖与读取失败记录随研究文档导出。</p>${j.error?`<p class="issue">${esc(j.error)}</p>`:''}<div class="buttons">${['done','partial','failed','interrupted','cancelled'].includes(j.status)?`<a class="button quiet" href="/api/research/jobs/${encodeURIComponent(j.id)}/export">下载本次研究文档</a>`:''}${['queued','running'].includes(j.status)?`<button class="quiet" data-cancel-research="${esc(j.id)}">停止本次研究</button>`:''}</div><details><summary>查看读取记录</summary>${(j.reads||[]).map(r=>`<p>${researchSourceLink(r.url,r.url)}<br>${esc(r.error||r.status||'')}</p>`).join('')||'<p>尚无网页读取记录。</p>'}</details></article>`).join('')||'<p class="helper">尚未发起后台案例研究。</p>';
}
function bindCaseDetails(account){
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
async function renderResearch(){
 const token=++researchLoad,account=activeAccountId;clearTimeout(researchTimer);
 $('operationsContent').innerHTML=`<section class="panel"><div class="detail-heading"><h2>自动整理一次案例研究</h2><a class="button quiet" href="/api/research/cases/export?account_id=${encodeURIComponent(account)}">导出本账号案例文档</a></div><p class="muted">后台最多搜索 2 组关键词，尝试读取 6 个网页，保存最多 3 份正文。关闭页面后继续执行。搜索摘要不当作正文，未知互动不补零。</p><form id="researchCollectForm"><label for="researchQueries">搜索词（每行一组，最多两组）</label><textarea id="researchQueries" rows="2" required maxlength="241" placeholder="例如：敏感肌 防晒 产品对比&#10;品牌 产品名称 成分"></textarea><div class="two-col"><div><label for="researchProvider">搜索服务</label><select id="researchProvider"><option value="bing">Bing 公开网页（实验）</option><option value="baidu">百度 AI 搜索（需配置，可能计费）</option><option value="wikipedia">百科背景资料</option></select></div><div><label for="researchRole">资料用途</label><select id="researchRole"><option value="expression_reference">表达参考：学习结构与方法</option><option value="product_fact">商品事实：仍需核验产品与来源</option></select></div></div><fieldset class="research-scopes"><legend>搜索范围</legend><label class="checkbox"><input name="researchScope" type="checkbox" value="web" checked> 全网</label><label class="checkbox"><input name="researchScope" type="checkbox" value="jd"> 京东</label><label class="checkbox"><input name="researchScope" type="checkbox" value="taobao"> 淘宝 / 天猫</label><label class="checkbox"><input name="researchScope" type="checkbox" value="xiaohongshu"> 小红书搜索线索</label></fieldset><p class="helper">限定范围基于搜索引擎收录，不是平台站内完整搜索。小红书暂无获授权的自动正文读取渠道，其结果仅保留线索；不会自动采集。</p><label class="checkbox"><input id="researchPermission" type="checkbox" required> 我确认本次资料研究的使用权限，并授权在所选范围和次数内自动搜索、读取与保存</label><button class="primary" type="submit">开始后台研究</button></form></section><section><div class="section-toolbar"><h2>研究任务</h2><button id="refreshResearch" class="quiet">刷新</button></div><div id="researchJobs"><p>正在读取任务…</p></div></section><section class="panel"><details><summary>添加已有案例、视频字幕或商品事实</summary><form id="researchCaseForm"><label for="caseTitle">标题</label><input id="caseTitle" required maxlength="200"><div class="two-col"><div><label for="casePlatform">来源平台</label><select id="casePlatform"><option value="xiaohongshu">小红书</option><option value="public_web">公开网页</option><option value="jd">京东</option><option value="taobao">淘宝 / 天猫</option><option value="owned">自有资料</option></select></div><div><label for="caseAuthor">作者 / 品牌（可选）</label><input id="caseAuthor" maxlength="200"></div></div><label for="caseUrl">原始链接（可选）</label><input id="caseUrl" type="url"><div class="two-col"><div><label for="caseKind">内容类型</label><select id="caseKind"><option value="text">已取得正文</option><option value="transcript">已有视频字幕 / 转写</option><option value="lead">只有搜索线索（不进入 RAG）</option></select></div><div><label for="caseRole">证据类别</label><select id="caseRole"><option value="expression_reference">表达参考</option><option value="product_fact">商品事实资料（待核验）</option></select></div></div><label for="caseText">正文或字幕</label><textarea id="caseText" required maxlength="100000" rows="7" placeholder="粘贴有权使用的内容；不会因提供标题就视为已读取视频"></textarea><div class="two-col"><div><label for="casePublished">发布时间（可选）</label><input id="casePublished" type="datetime-local"></div><div><label for="caseObserved">指标观察时间（填写指标时必填）</label><input id="caseObserved" type="datetime-local"></div></div><div class="research-metrics">${[['views','播放 / 阅读'],['likes','点赞'],['favorites','收藏'],['comments','评论'],['shares','分享']].map(([k,v])=>`<div><label for="caseMetric-${k}">${v}</label><input id="caseMetric-${k}" type="number" min="0" max="1000000000000" step="1" placeholder="未知留空"></div>`).join('')}</div><div class="two-col"><div><label for="caseMinInteractions">高互动候选最低已知互动量</label><input id="caseMinInteractions" type="number" value="1000" min="1" max="1000000000" required></div><div><label for="caseMaxAge">发布后观察窗口（天）</label><input id="caseMaxAge" type="number" value="30" min="1" max="3650" required></div></div><label class="checkbox"><input id="casePermission" type="checkbox" required> 我有权保存和使用这份资料，知晓案例表达不能证明我的产品功效或亲身体验</label><button class="primary">保存案例并建立检索</button></form></details></section><div class="section-toolbar"><h2>已保存案例</h2><p class="helper">可在创作工作台勾选引用，或在资料库检索与移除。</p></div><div id="researchCases"></div>`;
 document.querySelectorAll('[name="researchScope"]').forEach(box=>box.onchange=()=>{
  if(box.checked)document.querySelectorAll('[name="researchScope"]').forEach(other=>{if((box.value==='web'&&other!==box)||(box.value!=='web'&&other.value==='web'))other.checked=false;});
 });
 $('researchProvider').onchange=()=>{if($('researchProvider').value==='wikipedia')document.querySelectorAll('[name="researchScope"]').forEach(box=>box.checked=box.value==='web');};
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
 $('researchCaseForm').onsubmit=async e=>{
  e.preventDefault();e.submitter.disabled=true;
  try{
   const metrics=Object.fromEntries(['views','likes','favorites','comments','shares'].map(k=>[k,$('caseMetric-'+k).value===''?null:Number($('caseMetric-'+k).value)]));
   const data={account_id:account,title:$('caseTitle').value,text:$('caseText').value,source_url:$('caseUrl').value,platform:$('casePlatform').value,author:$('caseAuthor').value,content_kind:$('caseKind').value,evidence_role:$('caseRole').value,published_at:$('casePublished').value?new Date($('casePublished').value).toISOString():null,observed_at:$('caseObserved').value?new Date($('caseObserved').value).toISOString():null,metrics,permission_confirmed:$('casePermission').checked,policy:{min_interactions:Number($('caseMinInteractions').value),max_age_days:Number($('caseMaxAge').value)}};
   await api('/api/research/cases','POST',data);toast('案例已保存，可进入资料检索');e.target.reset();await refreshResearchJobs(account,token);
  }catch(err){error(err);}finally{e.submitter.disabled=false;}
 };
 await refreshResearchJobs(account,token);
}
