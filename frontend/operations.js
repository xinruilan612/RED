'use strict';
let ops=null,chosenTrend=null,opsBusy=false,currentPage='overview',platformFilter='all',keyword='',includeTrendExamples=false;
const platformNames={xiaohongshu:'小红书',douyin:'抖音'};
const pubStates={AWAITING_APPROVAL:'待发布确认',APPROVED:'待执行',SIMULATED:'已演练 · 未真实发布',MANUAL_REPORTED:'已发布 · 人工记录'};
const memoryStates={proposed:'待你决定',accepted:'已接受',rejected:'已拒绝',revoked:'已撤销',superseded:'指标已修正 · 经验失效'};
const pageInfo={overview:['THIS WEEK / 00','把每周运营，连成长期积累。','目标、创作和复盘，都围绕当前账号展开。'],accounts:['ACCOUNT / PROFILE','认识你的账号，也记住每一次选择。','定位档案、历史作品与表达偏好，持续保存在同一个账号里。'],trends:['DISCOVER / 01','找到下一个值得写的选题。','从趋势线索出发，让每一次创作都有依据。'],studio:['CREATE / 02','把好选题，变成好内容。','受众洞察、素材研究、创作与审核，协作过程始终可见。'],publish:['ARCHIVE / 03','发布之后，把作品留在这里。','在小红书或抖音发布后，记录实际内容、作品链接和时间，持续积累自己的作品档案。'],metrics:['MEASURE / 04','看看内容带来了什么。','记录你在平台看到的数字，得到下一篇的建议。'],memory:['LEARN / 05','让下一次创作，更有依据。','从历史表现提取实验建议，由你决定哪些经验值得保留。']};
const dateText=value=>value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'固定示例 · 无采集时间';
const badge=(text,kind='')=>`<span class="pill ${kind}">${esc(text)}</span>`;
const empty=(title,body)=>`<div class="empty-state"><span class="empty-symbol">↗</span><h2>${esc(title)}</h2><p>${esc(body)}</p></div>`;
const navigationGroup=page=>({accounts:'overview',examples:'overview',trends:'studio',windtunnel:'studio',trials:'studio',topics:'studio',metrics:'publish'})[page]||page;
function showPage(page){
 if(!pageInfo[page])page='overview';
 currentPage=page;location.hash=page;
 $('studioView').hidden=page!=='studio';$('operationsView').hidden=page==='studio';
 [$('pageEyebrow').textContent,$('pageTitle').textContent,$('pageDescription').textContent]=pageInfo[page];
 document.querySelectorAll('.workspace-nav [data-page]').forEach(b=>{const active=b.dataset.page===navigationGroup(page);b.classList.toggle('active',active);b.setAttribute('aria-current',active?'page':'false');});
 if(typeof renderPageTools==='function')renderPageTools(page);
 clearError();if(ops&&page!=='studio')renderOperations();window.scrollTo({top:0});
}
async function initOperations(){ops=await api('/api/operations');syncAccounts();if(run&&!matchesAccount(run)){run=null;$('workbench').hidden=true;$('welcome').hidden=false;fillAccountBrief();}showPage(location.hash.slice(1)||'overview');return await history();}
async function operate(action,payload){
 if(opsBusy)return false;opsBusy=true;clearError();
 document.querySelectorAll('#operationsView button').forEach(b=>b.disabled=true);
 try{ops=await api('/api/operations','POST',{action,payload,version:ops.version,key:crypto.randomUUID()});syncAccounts();renderOperations();return true;}
 catch(e){error(e);try{ops=await api('/api/operations');}catch(_){}return false;}
 finally{opsBusy=false;document.querySelectorAll('#operationsView button').forEach(b=>b.disabled=false);}
}
function renderOperations(){
 if(!ops)return;
 if(currentPage==='overview')renderOverview();
 if(currentPage==='accounts')renderAccounts();
 if(currentPage==='trends')renderTrends();
 if(currentPage==='trials')renderTrials();
 if(currentPage==='library')renderLibrary();
 if(currentPage==='windtunnel')renderWindtunnel();
 if(currentPage==='publish')renderPublications();
 if(currentPage==='metrics')renderMetrics();
 if(currentPage==='memory')renderMemory();
 if(currentPage==='examples')renderExamples();
 if(currentPage==='topics'&&typeof renderTopics==='function')renderTopics();
 if(currentPage==='skapp'&&typeof renderSkapp==='function')renderSkapp();
}
function stat(label,value,note){return `<div><span>${esc(label)}</span><b>${esc(value)}</b><small>${esc(note)}</small></div>`;}
function renderTrends(){
 const rows=ops.trends.filter(t=>(includeTrendExamples||t.source_type!=='example')&&(platformFilter==='all'||t.platform===platformFilter)&&(!keyword||(t.title+t.category+t.angle).includes(keyword)));
 $('operationsContent').innerHTML=`<div class="ops-hero"><div><span class="eyebrow">从选题到复盘，形成自己的创作节奏</span><h2>发现 → 创作 → 审核 → 发布 → 复盘 → 学习</h2><p>小红书与抖音的运营工作，在一个空间里完成。</p></div>${badge(websiteSession?.auth_required?'公开来源可搜索':'热点源尚未联网','amber')}</div><div class="stats ops-stats">${stat('选题线索',ops.trends.length,'示例与用户来源分开标记')}${stat('已发布归档',accountRows('publications').filter(p=>p.status==='MANUAL_REPORTED').length,'按实际发布内容记录')}${stat('已接受经验',accountRows('memories').filter(m=>m.status==='accepted').length,'同账号、同平台复用')}</div><div class="section-toolbar"><div><h2>选题池</h2><p class="muted">示例用于体验；导入来源后可查看观察时间与过期状态。</p></div><button id="toggleTrendForm" class="primary">＋ 导入选题来源</button></div><form id="trendForm" class="panel inline-form" hidden><h3>保存你的选题线索</h3><div class="two-col"><div><label for="trendTitle">选题标题</label><input id="trendTitle" maxlength="100" required></div><div><label for="trendPlatform">平台</label><select id="trendPlatform"><option value="xiaohongshu">小红书</option><option value="douyin">抖音</option></select></div></div><div class="two-col"><div><label for="trendUrl">来源链接（仅保存，不抓取）</label><input id="trendUrl" type="url" required placeholder="https://"></div><div><label for="trendObserved">你观察到这条线索的时间</label><input id="trendObserved" type="datetime-local" required></div></div><label for="trendCategory">领域</label><input id="trendCategory" maxlength="30" required placeholder="如：穿搭、学习、生活"><label for="trendAngle">准备从什么角度写</label><textarea id="trendAngle" rows="2" maxlength="500" required></textarea><button class="primary" type="submit">保存线索</button><p class="helper">不会生成虚构热度，也不会自动读取来源页面。</p></form><div class="filter-bar"><div class="filter-tabs">${[['all','全部平台'],['xiaohongshu','小红书'],['douyin','抖音']].map(([id,label])=>`<button data-filter="${id}" class="${platformFilter===id?'active':''}">${label}</button>`).join('')}</div><input id="trendSearch" aria-label="搜索选题" placeholder="搜索标题 / 领域" value="${esc(keyword)}"></div><div class="trend-grid">${rows.map((t,i)=>`<article class="panel trend-card"><div class="card-top"><span class="topic-number">${String(i+1).padStart(2,'0')}</span><div>${badge(platformNames[t.platform])} ${badge(t.category,'neutral')}</div></div><h2>${esc(t.title)}</h2><p class="angle">${esc(t.angle)}</p><div class="source-line">${badge(t.source_type==='example'?'演示选题 · 非实时':Date.now()-Date.parse(t.observed_at)>10800000?'超过 3 小时 · 待重查':'用户来源 · 未核验','amber')}<small>${esc(dateText(t.observed_at))}</small></div><p class="reason">${esc(t.reason)}</p>${t.source_url?`<a href="${esc(t.source_url)}" target="_blank" rel="noopener noreferrer">查看原始来源 ↗</a>`:''}<button class="secondary" data-choose="${esc(t.id)}">用这个选题创作 <span>→</span></button></article>`).join('')||empty('没有匹配的选题','换一个关键词，或导入自己的线索。')}</div><p class="section-footnote">公开搜索需手动发起；示例不代表实时趋势，保存来源也不等于独立事实核验。</p>`;
 mountSourceSearch();
 $('operationsContent').insertAdjacentHTML('beforeend',`<button id="toggleTrendExamples" class="quiet">${includeTrendExamples?'隐藏':'查看'}固定示例选题（非实时）</button>`);
 $('toggleTrendExamples').onclick=()=>{includeTrendExamples=!includeTrendExamples;renderTrends();};
 $('toggleTrendForm').onclick=()=>{$('trendForm').hidden=!$('trendForm').hidden;};
 $('trendSearch').oninput=e=>{keyword=e.target.value;const start=e.target.selectionStart;renderTrends();$('trendSearch').focus();$('trendSearch').setSelectionRange(start,start);};
 $('trendForm').onsubmit=async e=>{e.preventDefault();await operate('add_trend',{title:$('trendTitle').value,platform:$('trendPlatform').value,category:$('trendCategory').value,angle:$('trendAngle').value,source_url:$('trendUrl').value,observed_at:new Date($('trendObserved').value).toISOString()});};
}
function chooseTrend(id){
 if(busy)return;const trend=ops.trends.find(t=>t.id===id);if(!trend)return;
 if(currentAccount()?.platform!==trend.platform){toast('请先在顶部切换到对应平台的账号');return;}
 if(!startCreation({trend}))return;
 $('targetPlatform').value=trend.platform;$('topic').value=trend.title;
 $('audience').value=trend.category==='穿搭'?'关注日常穿搭与服饰搭配的读者':trend.category==='学习'?'希望改善学习习惯的大学生':'关注日常生活方式的读者';
 $('audience').value=currentAccount()?.profile.audience||$('audience').value;
 $('tone').value=currentAccount()?.profile.tone||'真实、具体、有场景感';$('material').value='';
 $('mode').value=trend.source_type!=='example'&&provider?.ready?'live':'simulation';$('mode').onchange();
 $('selectedTrend').textContent=(trend.source_type==='example'?'示例选题 · 非实时热点':'用户导入来源 · 尚未联网核验')+'：'+trend.angle;
 $('selectedTrend').hidden=false;$('clearTrend').hidden=false;
}
let archiveDrafts=[];
function renderPublications(){
 const simulationOpen=!!$('simulationArchive')?.open;
 const published=accountRows('publications').filter(p=>p.status==='MANUAL_REPORTED').sort((a,b)=>Date.parse(b.published_at)-Date.parse(a.published_at));
 $('operationsContent').innerHTML=`<div class="section-toolbar"><div><h2>已发布作品</h2><p class="muted">先去平台发布，再在这里归档。保存的是你填写的实际内容；作品图片可通过原链接查看。</p></div><button id="recordPublished" class="primary">＋ 记录已发布</button></div><form id="publishedArchiveForm" class="panel inline-form" hidden><h3>记录已发布作品</h3><p class="helper">账号：${esc(currentAccount()?.name||'请先选择账号')} · ${esc(platformNames[currentAccount()?.platform]||'')}。请填写平台上实际发布的内容，保存不会向平台发送任何内容。</p><label>关联创作稿件（可选）<select id="archiveRun"><option value="">不关联稿件，直接记录作品</option></select></label><label>实际发布标题<input id="archiveTitle" maxlength="200" required></label><label>实际发布正文<textarea id="archiveBody" rows="8" maxlength="6000" required></textarea></label><label>话题标签<input id="archiveTags" placeholder="用逗号分隔，如：新手护肤，日常分享"></label><div class="two-col"><label>作品链接<input id="archiveUrl" type="text" inputmode="url" required placeholder="粘贴作品链接或完整分享文案（含一个链接）"></label><label>实际发布时间<input id="archivePublishedAt" type="datetime-local" required></label></div><div class="buttons"><button class="primary" type="submit">保存为已发布并归档</button><button id="closeArchiveForm" class="quiet" type="button">取消填写</button></div><p class="helper">发布状态按你的记录保存，尚未通过平台核验；不会自动抓取笔记或图片。</p></form><div class="publication-list">${published.map(p=>`<article class="panel publication-card"><div class="publication-main"><div>${badge(platformNames[p.platform])} ${badge('已发布 · 人工记录','amber')}</div><h2>${esc(p.content.selected_title)}</h2><p class="muted">${esc(p.account)} · 发布于 ${esc(dateText(p.published_at))}</p><details><summary>查看归档正文与来源</summary><p class="readable">${esc(p.content.body)}</p>${p.content.cta?`<p>${esc(p.content.cta)}</p>`:''}<p>${(p.content.tags||[]).map(t=>'#'+esc(t)).join(' ')}</p><p class="helper">${p.run_id?'已关联创作稿件，原稿与实际发布内容分别保留。':'直接记录的作品，无关联创作稿件。'}${(p.source_acceptance||p.acceptance)?.mode==='manual_override'?' 来源稿由用户人工采用，不代表 AI 审核通过。':''} 平台状态未独立核验。</p></details><a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">查看平台作品与图片 ↗</a></div><div class="publication-actions"><button class="secondary" data-to-metrics="${p.id}">录入数据与复盘 →</button></div></article>`).join('')||empty('还没有已发布作品','发布完成后，点击“记录已发布”，将作品内容和链接归档。')}</div>`;
 $('recordPublished').onclick=()=>openPublishedArchive();
 $('closeArchiveForm').onclick=()=>{$('publishedArchiveForm').hidden=true;};
 $('archiveRun').onchange=()=>fillArchiveDraft();
 $('publishedArchiveForm').onsubmit=savePublishedArchive;
 renderSimulatedPublications(simulationOpen);
}
function renderSimulatedPublications(open=false){
 const pubs=accountRows('publications').filter(p=>p.mode==='simulation');
 if(!pubs.length)return;
 $('operationsContent').insertAdjacentHTML('beforeend',`<details id="simulationArchive" class="process-disclosure"><summary>模拟发布演练 · ${pubs.length} 条（未真实发布）</summary><section class="panel"><p>不向平台发送内容；演练指标和经验仅用于模拟，不进入真实历史。</p>${pubs.map(p=>`<article class="publication-card"><h3>${esc(p.content.selected_title)}</h3><p>${badge(pubStates[p.status],'neutral')} · ${esc(p.account)}</p>${p.status==='AWAITING_APPROVAL'?`<button data-approve="${p.id}">批准此模拟版本与账号</button>`:p.status==='APPROVED'?`<button data-simulate="${p.id}">执行模拟发布（不发到平台）</button>`:p.status==='SIMULATED'?`<button data-to-metrics="${p.id}">录入演练数据与复盘 →</button>`:''}</article>`).join('')}</section></details>`);
 $('simulationArchive').open=open;
}
async function openPublishedArchive(runId=null){
 try{
  archiveDrafts=(await api('/api/runs')).filter(r=>matchesAccount(r)&&r.mode==='live'&&r.run_status==='SUCCEEDED'&&!ops.publications.some(p=>p.run_id===r.run_id&&p.status==='MANUAL_REPORTED'));
  $('archiveRun').innerHTML='<option value="">不关联稿件，直接记录作品</option>'+archiveDrafts.map(r=>`<option value="${esc(r.run_id)}">${esc(r.context.topic)} · 已采用稿件</option>`).join('');
  $('archiveRun').value=archiveDrafts.some(r=>r.run_id===runId)?runId:'';
  fillArchiveDraft();$('archiveUrl').value='';$('archivePublishedAt').value='';
  $('publishedArchiveForm').hidden=false;$('publishedArchiveForm').scrollIntoView({behavior:'smooth',block:'start'});
 }catch(e){error(e);}
}
function fillArchiveDraft(){
 const source=archiveDrafts.find(r=>r.run_id===$('archiveRun').value),content=source?.drafts.find(d=>d.ref===source.accepted_ref)?.content;
 $('archiveTitle').value=content?.selected_title||'';
 $('archiveBody').value=[content?.body,content?.cta].filter(Boolean).join('\n\n');
 $('archiveTags').value=(content?.tags||[]).join('，');
}
function extractPublishedUrl(value){
 const matches=String(value||'').match(/https?:\/\/[^\s<>"'\[\]（）【】“”‘’，。；！？]+/gi)||[];
 if(matches.length!==1)throw new Error(matches.length?'检测到多个链接，请只保留要归档的一个作品链接':'请粘贴包含一个 http 或 https 作品链接的分享文案');
 return matches[0].replace(/[)]+$/, '');
}
async function savePublishedArchive(e){
 e.preventDefault();
 try{
  const account=currentAccount();if(!account)throw new Error('请先选择运营账号');
  const source=archiveDrafts.find(r=>r.run_id===$('archiveRun').value);
  const url=extractPublishedUrl($('archiveUrl').value);$('archiveUrl').value=url;
  const data={title:$('archiveTitle').value,body:$('archiveBody').value,tags:$('archiveTags').value.split(/[,，\n]/).map(t=>t.trim().replace(/^#/,'' )).filter(Boolean),url,published_at:new Date($('archivePublishedAt').value).toISOString()};
  const action=source?'archive_published':'import_post';
  const payload=source?{...data,run_id:source.run_id,draft_ref:source.accepted_ref}:{...data,account_id:account.id,format:account.platform==='douyin'?'video':'image_text',pillar:'未分类',traffic:'unknown'};
  if(await operate(action,payload))toast('已记录为已发布，内容与链接已归档。');
 }catch(errorValue){error(errorValue);}
}

function latestMetrics(){const map=new Map();for(const m of accountRows('metrics'))map.set(m.publication_id+':'+m.window,m);return [...map.values()].reverse();}
function renderMemory(){
 const memories=accountRows('memories');
 const suggestions=accountRows('analyses').filter(a=>a.status!=='superseded'&&a.source_type==='manual'&&!memories.some(m=>m.metric_id===a.metric_id&&m.status==='accepted')).slice(0,3);
 const pending=suggestions.map(a=>{const r=reviewAdvice(a),p=ops.publications.find(x=>x.id===a.publication_id);return `<article class="panel"><h3>${esc(p?.content.selected_title||'下一次尝试')}</h3><p>${esc(r.change)}</p><p class="helper">${esc(r.check_next)}</p><button class="secondary" data-review-create="${esc(a.id)}">带着这个建议写下一篇 →</button></article>`;}).join('');
 const cards=memories.map(m=>`<article class="panel memory-card"><div class="card-top"><div>${badge(platformNames[m.platform])} ${badge(m.source_type==='simulation'?'演示经验':'用户数据经验','amber')}</div>${badge(memoryStates[m.status],'neutral')}</div><h2>${esc(ops.publications?.find(p=>p.id===m.publication_id)?.content?.selected_title||'下一次内容实验建议')}</h2><p class="memory-advice">${esc(m.text)}</p><p class="muted">${esc(m.account)} · ${m.window} · ${m.sample_size} 篇样本</p><p class="helper">${esc(m.limitation)}</p><details><summary>查看证据与使用范围</summary><p class="readable">${esc(m.observation)}</p><p>指标快照 ${esc(m.metric_id.slice(0,8))} · 发布记录 ${esc(m.publication_id.slice(0,8))}</p><p>仅用于同平台、同账号的${m.source_type==='simulation'?'模拟':'真实 AI'}创作。修正指标后，相关经验会自动失效。</p></details><div class="buttons">${m.status==='proposed'?`<button class="primary" data-memory="${m.id}" data-status="accepted">接受为下次实验建议</button><button class="quiet" data-memory="${m.id}" data-status="rejected">暂不采用</button>`:m.status==='accepted'?`<button class="secondary" data-memory-create="${esc(m.id)}">用这条经验创作 →</button><button class="quiet" data-memory="${m.id}" data-status="revoked">撤销此经验</button>`:''}</div></article>`).join('');
 $('operationsContent').innerHTML=`<div class="ops-hero memory-hero"><div><span class="eyebrow">有证据才积累，不强行得出结论</span><h2>经验有来源，也可以撤销。</h2><p>记录实际表现 → 分析 → 你接受建议 → 下次同账号复用。</p></div>${badge(memories.filter(m=>m.status==='accepted').length+' 条已接受经验')}</div><div class="memory-list">${cards||empty('目前没有可采用的经验',memoryNextStep())+'<button class="secondary" data-go-page="metrics">查看数据复盘与下一步 →</button>'}</div>${pending?`<div class="section-toolbar"><div><h2>下一次可以试什么</h2><p>来自已保存复盘，尚未验证；不会自动加入长期经验。</p></div></div><div class="memory-list">${pending}</div>`:''}`;
}
function memoryNextStep(){
 const reports=accountRows('analyses').filter(a=>a.status!=='superseded');
 if(!reports.length)return '还没有分析记录。先在“作品与复盘”保存一次指标，再点“分析这条记录”。';
 if(reports.every(a=>a.status==='insufficient'))return '每篇复盘都有下一步建议。先尝试并记录后续表现，积累可比较的作品后再保存长期经验。';
 return '已有复盘，但尚无满足证据条件的候选经验。查看复盘的限制与下一次建议；不会强行生成经验。';
}
 document.querySelector('.workspace-nav').onclick=e=>{const b=e.target.closest('[data-page]');if(b&&!busy&&dirtyGuard()){auto=false;showPage(b.dataset.page);}};
$('clearTrend').onclick=()=>{chosenTrend=null;$('selectedTrend').hidden=true;$('clearTrend').hidden=true;};
$('targetPlatform').onchange=()=>{if(chosenTrend&&chosenTrend.platform!==$('targetPlatform').value)$('clearTrend').click();};
$('sendToPublish').onclick=async()=>{try{if(!ops)ops=await api('/api/operations');if(run.mode==='simulation'){if(!ops.publications.some(p=>p.run_id===run.run_id&&p.draft_ref===run.accepted_ref)){if(!await operate('prepare',{run_id:run.run_id,draft_ref:run.accepted_ref}))return;}showPage('publish');if($('simulationArchive'))$('simulationArchive').open=true;return;}showPage('publish');await openPublishedArchive(run.run_id);}catch(e){error(e);}};
$('operationsContent').onclick=async e=>{
 const b=e.target.closest('button');if(!b||opsBusy)return;
 if(b.dataset.aiReviewOpen){$('ai-review-confirm-'+b.dataset.aiReviewOpen).hidden=false;return;}
 if(b.dataset.aiReviewClose){$('ai-review-confirm-'+b.dataset.aiReviewClose).hidden=true;return;}
 if(b.dataset.reviewCreate){const a=ops.analyses.find(x=>x.id===b.dataset.reviewCreate);if(!a||a.status==='superseded')return;const brief=nextReviewBrief(a);if(startCreation()){$('topic').value=brief.topic;$('material').value=brief.material;if(a.source_type==='simulation'){$('mode').value='simulation';$('mode').onchange();}toast('已带入选题、保留项、一个改动和数据记录计划；请补充本篇事实资料。');}return;}
 if(b.dataset.aiReview){
  opsBusy=true;b.disabled=true;b.textContent='正在真实调用 AI，请稍候…';
  try{const result=await api('/api/operations/ai-review','POST',{id:b.dataset.aiReview,version:ops.version,key:crypto.randomUUID(),acknowledge:true});ops=result.operations;renderMetrics();toast('真实 AI 复盘已保存，调用记录可查看。');}
  catch(err){error(err);b.textContent='生成未完成，请查看提示';b.disabled=false;}
  finally{opsBusy=false;}return;
 }
 if(b.dataset.filter){platformFilter=b.dataset.filter;renderTrends();}
 if(b.dataset.choose)chooseTrend(b.dataset.choose);
 if(b.dataset.prepareRun)await operate('prepare',{run_id:b.dataset.prepareRun,draft_ref:b.dataset.ref});
 if(b.dataset.approve)await operate('approve',{id:b.dataset.approve});
 if(b.dataset.simulate)await operate('simulate',{id:b.dataset.simulate});
 if(b.dataset.toMetrics){showPage('metrics');renderMetrics(b.dataset.toMetrics);}
 if(b.dataset.learn&&await operate('analyze',{id:b.dataset.learn})){showPage('metrics');toast('复盘已保存；下方可以查看下一篇建议');}
 if(b.dataset.memoryCreate){const m=accountRows('memories').find(x=>x.id===b.dataset.memoryCreate&&x.status==='accepted');if(!m)return;if(startCreation()){$('topic').value=((ops.publications||[]).find(p=>p.id===m.publication_id)?.content?.selected_title||'围绕当前栏目继续创作').slice(0,100);$('material').value=`【同账号已接受的实验建议，不是已证实效果】\n${m.text}\n依据：${m.observation}\n限制：${m.limitation}\n请另行补充本篇事实素材。`;if(m.source_type==='simulation'){$('mode').value='simulation';$('mode').onchange();}}return;}
 if(b.dataset.memory)await operate('memory',{id:b.dataset.memory,status:b.dataset.status});
};
