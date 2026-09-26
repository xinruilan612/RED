'use strict';
let ops=null,chosenTrend=null,opsBusy=false,currentPage='overview',platformFilter='all',keyword='';
const platformNames={xiaohongshu:'小红书',douyin:'抖音'};
const pubStates={AWAITING_APPROVAL:'待发布确认',APPROVED:'待执行',SIMULATED:'已演练 · 未真实发布',MANUAL_REPORTED:'已回填 · 未独立核验'};
const memoryStates={proposed:'待你决定',accepted:'已接受',rejected:'已拒绝',revoked:'已撤销',superseded:'指标已修正 · 经验失效'};
const pageInfo={overview:['THIS WEEK / 00','把每周运营，连成长期积累。','目标、创作和复盘，都围绕当前账号展开。'],accounts:['ACCOUNT / PROFILE','认识你的账号，也记住每一次选择。','定位档案、历史作品与表达偏好，持续保存在同一个账号里。'],trends:['DISCOVER / 01','找到下一个值得写的选题。','从趋势线索出发，让每一次创作都有依据。'],studio:['CREATE / 02','把好选题，变成好内容。','受众洞察、素材研究、创作与审核，协作过程始终可见。'],publish:['PUBLISH / 03','发布之前，最后确认一次。','把准确版本交给准确账号，留下可追溯的发布记录。'],metrics:['MEASURE / 04','看看内容带来了什么。','保留数据来源与观察窗口，缺失数据不记为零。'],memory:['LEARN / 05','让下一次创作，更有依据。','从历史表现提取实验建议，由你决定哪些经验值得保留。']};
const dateText=value=>value?new Date(value).toLocaleString('zh-CN',{hour12:false}):'固定示例 · 无采集时间';
const badge=(text,kind='')=>`<span class="pill ${kind}">${esc(text)}</span>`;
const empty=(title,body)=>`<div class="empty-state"><span class="empty-symbol">↗</span><h2>${esc(title)}</h2><p>${esc(body)}</p></div>`;
function showPage(page){
 if(!pageInfo[page])page='overview';
 currentPage=page;location.hash=page;
 $('studioView').hidden=page!=='studio';$('operationsView').hidden=page==='studio';
 [$('pageEyebrow').textContent,$('pageTitle').textContent,$('pageDescription').textContent]=pageInfo[page];
 document.querySelectorAll('[data-page]').forEach(b=>{b.classList.toggle('active',b.dataset.page===page);b.setAttribute('aria-current',b.dataset.page===page?'page':'false');});
 clearError();if(ops&&page!=='studio')renderOperations();window.scrollTo({top:0});
}
async function initOperations(){ops=await api('/api/operations');syncAccounts();if(run&&!matchesAccount(run)){run=null;$('workbench').hidden=true;$('welcome').hidden=false;fillAccountBrief();}showPage(location.hash.slice(1)||'overview');await history();}
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
 if(currentPage==='library')renderLibrary();
 if(currentPage==='windtunnel')renderWindtunnel();
 if(currentPage==='publish')renderPublications();
 if(currentPage==='metrics')renderMetrics();
 if(currentPage==='memory')renderMemory();
}
function stat(label,value,note){return `<div><span>${esc(label)}</span><b>${esc(value)}</b><small>${esc(note)}</small></div>`;}
function renderTrends(){
 const rows=ops.trends.filter(t=>(platformFilter==='all'||t.platform===platformFilter)&&(!keyword||(t.title+t.category+t.angle).includes(keyword)));
 $('operationsContent').innerHTML=`<div class="ops-hero"><div><span class="eyebrow">从选题到复盘，形成自己的创作节奏</span><h2>发现 → 创作 → 审核 → 发布 → 复盘 → 学习</h2><p>小红书与抖音的运营工作，在一个空间里完成。</p></div>${badge(websiteSession?.auth_required?'公开来源可搜索':'热点源尚未联网','amber')}</div><div class="stats ops-stats">${stat('选题线索',ops.trends.length,'示例与用户来源分开标记')}${stat('待发布确认',accountRows('publications').filter(p=>p.status==='AWAITING_APPROVAL').length,'只接收已确认稿件')}${stat('已接受经验',accountRows('memories').filter(m=>m.status==='accepted').length,'同账号、同平台复用')}</div><div class="section-toolbar"><div><h2>选题池</h2><p class="muted">示例用于体验；导入来源后可查看观察时间与过期状态。</p></div><button id="toggleTrendForm" class="primary">＋ 导入选题来源</button></div><form id="trendForm" class="panel inline-form" hidden><h3>保存你的选题线索</h3><div class="two-col"><div><label for="trendTitle">选题标题</label><input id="trendTitle" maxlength="100" required></div><div><label for="trendPlatform">平台</label><select id="trendPlatform"><option value="xiaohongshu">小红书</option><option value="douyin">抖音</option></select></div></div><div class="two-col"><div><label for="trendUrl">来源链接（仅保存，不抓取）</label><input id="trendUrl" type="url" required placeholder="https://"></div><div><label for="trendObserved">你观察到这条线索的时间</label><input id="trendObserved" type="datetime-local" required></div></div><label for="trendCategory">领域</label><input id="trendCategory" maxlength="30" required placeholder="如：穿搭、学习、生活"><label for="trendAngle">准备从什么角度写</label><textarea id="trendAngle" rows="2" maxlength="500" required></textarea><button class="primary" type="submit">保存线索</button><p class="helper">不会生成虚构热度，也不会自动读取来源页面。</p></form><div class="filter-bar"><div class="filter-tabs">${[['all','全部平台'],['xiaohongshu','小红书'],['douyin','抖音']].map(([id,label])=>`<button data-filter="${id}" class="${platformFilter===id?'active':''}">${label}</button>`).join('')}</div><input id="trendSearch" aria-label="搜索选题" placeholder="搜索标题 / 领域" value="${esc(keyword)}"></div><div class="trend-grid">${rows.map((t,i)=>`<article class="panel trend-card"><div class="card-top"><span class="topic-number">${String(i+1).padStart(2,'0')}</span><div>${badge(platformNames[t.platform])} ${badge(t.category,'neutral')}</div></div><h2>${esc(t.title)}</h2><p class="angle">${esc(t.angle)}</p><div class="source-line">${badge(t.source_type==='example'?'演示选题 · 非实时':Date.now()-Date.parse(t.observed_at)>10800000?'超过 3 小时 · 待重查':'用户来源 · 未核验','amber')}<small>${esc(dateText(t.observed_at))}</small></div><p class="reason">${esc(t.reason)}</p>${t.source_url?`<a href="${esc(t.source_url)}" target="_blank" rel="noopener noreferrer">查看原始来源 ↗</a>`:''}<button class="secondary" data-choose="${esc(t.id)}">用这个选题创作 <span>→</span></button></article>`).join('')||empty('没有匹配的选题','换一个关键词，或导入自己的线索。')}</div><p class="section-footnote">公开搜索需手动发起；示例不代表实时趋势，保存来源也不等于独立事实核验。</p>`;
 mountSourceSearch();
 $('toggleTrendForm').onclick=()=>{$('trendForm').hidden=!$('trendForm').hidden;};
 $('trendSearch').oninput=e=>{keyword=e.target.value;const start=e.target.selectionStart;renderTrends();$('trendSearch').focus();$('trendSearch').setSelectionRange(start,start);};
 $('trendForm').onsubmit=async e=>{e.preventDefault();await operate('add_trend',{title:$('trendTitle').value,platform:$('trendPlatform').value,category:$('trendCategory').value,angle:$('trendAngle').value,source_url:$('trendUrl').value,observed_at:new Date($('trendObserved').value).toISOString()});};
}
function chooseTrend(id){
 if(busy||!dirtyGuard())return;const trend=ops.trends.find(t=>t.id===id);if(!trend)return;
 if(currentAccount()?.platform!==trend.platform){toast('请先在顶部切换到对应平台的账号');return;}
 chosenTrend=trend;showPage('studio');$('newRun').click();
 $('targetPlatform').value=trend.platform;$('topic').value=trend.title;
 $('audience').value=trend.category==='穿搭'?'关注日常穿搭与服饰搭配的读者':trend.category==='学习'?'希望改善学习习惯的大学生':'关注日常生活方式的读者';
 $('audience').value=currentAccount()?.profile.audience||$('audience').value;
 $('tone').value=currentAccount()?.profile.tone||'真实、具体、有场景感';$('material').value='';
 $('mode').value='simulation';$('mode').onchange();
 $('selectedTrend').textContent=(trend.source_type==='example'?'示例选题 · 非实时热点':'用户导入来源 · 尚未联网核验')+'：'+trend.angle;
 $('selectedTrend').hidden=false;$('clearTrend').hidden=false;
}
function renderPublications(){
 $('operationsContent').innerHTML=`<div class="notice">国内平台 API 尚未接通。模拟稿可演练流程；真实 AI 确认稿可在你自行发布后回填链接。此处不会向平台发送内容。</div><div class="section-toolbar"><div><h2>发布队列</h2><p class="muted">内容、账号与版本一起确认，创作完成不等于发布成功。</p></div><button id="loadConfirmed" class="secondary">选择已确认稿件</button></div><div id="confirmedRuns" class="panel inline-form" hidden></div><div class="publication-list">${accountRows('publications').map(p=>`<article class="panel publication-card"><div class="publication-main"><div>${badge(platformNames[p.platform])} ${badge(p.mode==='simulation'?'模拟稿':p.mode==='imported'?'历史导入':'真实 AI 稿','neutral')} ${badge(pubStates[p.status],'amber')}</div><h2>${esc(p.content.selected_title)}</h2><p class="muted">${esc(p.account)} · 版本 ${esc(p.draft_ref.slice(0,8))} · ${esc(dateText(p.created_at))}</p><details><summary>查看待发布正文与确认依据</summary><p class="readable">${esc(p.content.body)}</p><p>${esc(p.content.cta)}</p><p class="helper">稿件 ${esc(p.draft_ref)} · 审核 ${esc(p.review_ref||'历史导入 · 无本系统审核')}<br>内容摘要 ${esc(p.content_hash.slice(0,16))} · ${p.platform==='douyin'?'当前为脚本，需要自行制作视频。':'图片与封面需另行准备。'}</p></details>${p.url?`<a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">查看已回填作品 ↗</a>`:''}</div><div class="publication-actions">${p.status==='AWAITING_APPROVAL'?`<button class="primary" data-approve="${p.id}">确认此版本与账号</button>`:p.status==='APPROVED'?(p.mode==='simulation'?`<button class="primary" data-simulate="${p.id}">演练发布（不发平台）</button>`:`<form data-record="${p.id}"><label>已发布作品链接<input name="url" type="url" required placeholder="平台作品 URL"></label><label>实际发布时间<input name="published_at" type="datetime-local" required></label><button class="primary">保存人工发布记录</button></form>`):`<button class="secondary" data-to-metrics="${p.id}">录入指标与复盘 →</button>`}</div></article>`).join('')||empty('还没有待发布内容','在创作工作台完成审核并确认稿件，再进入发布中心。')}</div>`;
 $('loadConfirmed').onclick=async()=>{try{const rows=(await api('/api/runs')).filter(r=>matchesAccount(r)&&r.run_status==='SUCCEEDED'&&!ops.publications.some(p=>p.run_id===r.run_id));$('confirmedRuns').hidden=false;$('confirmedRuns').innerHTML=rows.length?rows.map(r=>`<button class="confirmed-choice" data-prepare-run="${r.run_id}" data-ref="${r.accepted_ref}">${esc(r.context.topic)} <span>加入发布队列 →</span></button>`).join(''):'<p class="muted">暂无未加入队列的确认稿。先在创作工作台完成一份稿件。</p>';}catch(e){error(e);}};
 document.querySelectorAll('[data-record]').forEach(form=>form.onsubmit=async e=>{e.preventDefault();await operate('record',{id:form.dataset.record,url:form.elements.url.value,published_at:new Date(form.elements.published_at.value).toISOString()});});
}
function latestMetrics(){const map=new Map();for(const m of accountRows('metrics'))map.set(m.publication_id+':'+m.window,m);return [...map.values()].reverse();}
function renderMemory(){
 $('operationsContent').innerHTML=`<div class="ops-hero memory-hero"><div><span class="eyebrow">从记录中学习，由你决定如何使用</span><h2>经验有来源，也可以撤销。</h2><p>指标 → 自动生成复盘建议 → 你接受 → 下次同账号创作读取。</p></div>${badge(accountRows('memories').filter(m=>m.status==='accepted').length+' 条已接受经验')}</div><div class="memory-list">${accountRows('memories').map(m=>`<article class="panel memory-card"><div class="card-top"><div>${badge(platformNames[m.platform])} ${badge(m.source_type==='simulation'?'演示经验':'用户数据经验','amber')}</div>${badge(memoryStates[m.status],'neutral')}</div><h2>${esc(m.observation.split('；')[0])}</h2><p class="memory-advice">${esc(m.text)}</p><p class="muted">${esc(m.account)} · ${m.window} · ${m.sample_size} 篇样本</p><p class="helper">${esc(m.limitation)}</p><details><summary>查看证据与使用范围</summary><p class="readable">${esc(m.observation)}</p><p>指标快照 ${esc(m.metric_id.slice(0,8))} · 发布记录 ${esc(m.publication_id.slice(0,8))}</p><p>仅用于同平台、同账号的${m.source_type==='simulation'?'模拟':'真实 AI'}创作。修正指标后，相关经验会自动失效。</p></details><div class="buttons">${m.status==='proposed'?`<button class="primary" data-memory="${m.id}" data-status="accepted">接受为下次实验建议</button><button class="quiet" data-memory="${m.id}" data-status="rejected">暂不采用</button>`:m.status==='accepted'?`<button class="quiet" data-memory="${m.id}" data-status="revoked">撤销此经验</button>`:''}</div></article>`).join('')||empty('还没有复盘经验','在数据复盘中录入指标并生成建议，再来决定是否采用。')}</div>`;
}
document.querySelector('.workspace-nav').onclick=e=>{const b=e.target.closest('[data-page]');if(b&&!busy&&dirtyGuard()){auto=false;showPage(b.dataset.page);}};
$('clearTrend').onclick=()=>{chosenTrend=null;$('selectedTrend').hidden=true;$('clearTrend').hidden=true;};
$('targetPlatform').onchange=()=>{if(chosenTrend&&chosenTrend.platform!==$('targetPlatform').value)$('clearTrend').click();};
$('sendToPublish').onclick=async()=>{try{if(!ops)ops=await api('/api/operations');if(await operate('prepare',{run_id:run.run_id,draft_ref:run.accepted_ref}))showPage('publish');}catch(e){error(e);}};
$('operationsContent').onclick=async e=>{
 const b=e.target.closest('button');if(!b||opsBusy)return;
 if(b.dataset.filter){platformFilter=b.dataset.filter;renderTrends();}
 if(b.dataset.choose)chooseTrend(b.dataset.choose);
 if(b.dataset.prepareRun)await operate('prepare',{run_id:b.dataset.prepareRun,draft_ref:b.dataset.ref});
 if(b.dataset.approve)await operate('approve',{id:b.dataset.approve});
 if(b.dataset.simulate)await operate('simulate',{id:b.dataset.simulate});
 if(b.dataset.toMetrics){showPage('metrics');renderMetrics(b.dataset.toMetrics);}
 if(b.dataset.learn&&await operate('analyze',{id:b.dataset.learn})){showPage('metrics');toast('分析已保存；有可比依据时会生成候选经验');}
 if(b.dataset.memory)await operate('memory',{id:b.dataset.memory,status:b.dataset.status});
};
