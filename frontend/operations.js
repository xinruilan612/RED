'use strict';
let ops=null,chosenTrend=null,chosenExperiment=null,chosenPromotion=null,chosenHypothesis=null,opsBusy=false,currentPage='overview',platformFilter='all',keyword='';
let publicationLoad=0;
const platformNames={xiaohongshu:'小红书',douyin:'抖音'};
const formatNames={image_text:'图文笔记',video:'视频'};
const pubStates={AWAITING_APPROVAL:'待发布确认',APPROVED:'待执行',SIMULATED:'已演练 · 未真实发布',MANUAL_REPORTED:'已回填 · 未独立核验'};
const memoryStates={proposed:'待你决定',accepted:'已接受',rejected:'已拒绝',revoked:'已撤销',superseded:'指标已修正 · 经验失效'};
const experimentStates={proposed:'待你决定',accepted:'实验已接受',rejected:'已拒绝',revoked:'已撤销',superseded:'依据已修正 · 实验失效'};
const pageInfo={overview:['THIS WEEK / 00','把每周运营，连成长期积累。','目标、创作和复盘，都围绕当前账号展开。'],accounts:['ACCOUNT / PROFILE','认识你的账号，也记住每一次选择。','定位档案、历史作品与表达偏好，持续保存在同一个账号里。'],promotion:['SERVICE / GROWTH','把真实技能，变成可持续的接单内容。','服务、作品、推广内容和匿名咨询形成有证据的闭环。'],trends:['DISCOVER / 01','找到下一个值得写的选题。','从趋势线索出发，让每一次创作都有依据。'],studio:['CREATE / 02','把好选题，变成好内容。','受众洞察、素材研究、创作与审核，协作过程始终可见。'],publish:['PUBLISH / 03','发布之前，最后确认一次。','把准确版本交给准确账号，留下可追溯的发布记录。'],metrics:['MEASURE / 04','看看内容带来了什么。','保留数据来源与观察窗口，缺失数据不记为零。'],memory:['LEARN / 05','让下一次创作，更有依据。','从历史表现提取实验建议，由你决定哪些经验值得保留。']};
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
 if(currentPage==='promotion')renderPromotion();
 if(currentPage==='trends')renderTrends();
 if(currentPage==='trials')renderTrials();
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
 chosenTrend=trend;chosenExperiment=null;chosenPromotion=null;showPage('studio');$('newRun').click();
 $('targetPlatform').value=trend.platform;$('topic').value=trend.title;
 $('audience').value=trend.category==='穿搭'?'关注日常穿搭与服饰搭配的读者':trend.category==='学习'?'希望改善学习习惯的大学生':'关注日常生活方式的读者';
 $('audience').value=currentAccount()?.profile.audience||$('audience').value;
 $('tone').value=currentAccount()?.profile.tone||'真实、具体、有场景感';$('material').value='';
 $('mode').value='simulation';$('mode').onchange();
 $('selectedTrend').textContent=(trend.source_type==='example'?'示例选题 · 非实时热点':'用户导入来源 · 尚未联网核验')+'：'+trend.angle;
 $('selectedTrend').hidden=false;$('clearTrend').hidden=false;
}
function chooseExperiment(id){
 if(busy||opsBusy||!dirtyGuard())return;
 const experiment=accountRows('experiments').find(row=>row.id===id);
 if(!experiment||experiment.status!=='accepted'||experiment.publication_id||experiment.platform!==currentAccount()?.platform||!formatNames[experiment.format]){toast('请重新选择当前账号已接受、尚未绑定发布的有效实验');return;}
 auto=false;editing=false;$('editor').hidden=true;showPage('studio');$('newRun').click();
 chosenExperiment=experiment;chosenTrend=null;chosenPromotion=null;
 $('targetPlatform').value=experiment.platform;
 $('topic').value=experiment.hypothesis.slice(0,100);$('material').value=`实验假设：${experiment.hypothesis}\n实验控制：${experiment.control}\n本次变量：${experiment.variant}\n计划形式：${formatNames[experiment.format]}；实际执行条件需在发布中心人工申报。`;
 $('mode').value=experiment.source_type==='simulation'?'simulation':'live';$('workflow').value='professional';$('mode').onchange();
 $('selectedTrend').textContent=`已接受实验 · ${platformNames[experiment.platform]} · ${formatNames[experiment.format]} · ${experiment.window} · ${experiment.chosen_pillar}（尚未执行、没有效果结论）`;
 $('selectedTrend').hidden=false;$('clearTrend').hidden=false;
}
function experimentCreationFields(){
 const fallback={experiment_id:null,format:$('targetPlatform').value==='douyin'?'video':'image_text'};
 if(!chosenExperiment)return fallback;
 const experiment=accountRows('experiments').find(row=>row.id===chosenExperiment.id);
 const source=$('mode').value==='simulation'?'simulation':'manual';
 if(!experiment||experiment.status!=='accepted'||experiment.publication_id||experiment.platform!==$('targetPlatform').value||experiment.source_type!==source||!formatNames[experiment.format]){
  throw new Error('实验已失效、已绑定发布或与当前账号/平台/运行方式不符，请移除关联或重新选择实验。');
 }
 return {experiment_id:experiment.id,format:experiment.format};
}
function publicationExperimentHTML(pub){
 if(!pub.experiment_id)return '';
 const plan=pub.experiment_snapshot||{};
 const execution=pub.published_at?`<p>建议不是已经执行的事实。请根据实际发布内容填报；不同形式、非自然流量或栏目不一致时不会计作同条件实验。</p>${badge(pub.metadata_confirmed?'已人工申报 · 修订 '+pub.metadata_revision:'实际执行尚未申报','neutral')}<form data-execution-meta="${esc(pub.id)}"><label>实际内容形式<select name="format"><option value="image_text" ${pub.format==='image_text'?'selected':''}>图文笔记</option><option value="video" ${pub.format==='video'?'selected':''}>视频</option></select></label><label>实际栏目<input name="pillar" maxlength="80" required value="${esc(pub.pillar==='未分类'?'':pub.pillar)}" placeholder="填写实际栏目，不会自动采用建议"></label><label>实际流量类型<select name="traffic">${Object.entries({unknown:'未知（不能作为同条件观测）',organic:'自然流量',paid:'有投流'}).map(([key,label])=>`<option value="${key}" ${pub.traffic===key?'selected':''}>${label}</option>`).join('')}</select></label><label class="checkbox"><input name="confirmed" type="checkbox" required> 我确认以上为实际执行记录，不是算法自动推断</label><button class="secondary">保存实际执行条件</button></form>`:'<p class="helper">尚未完成发布或演练，当前仅为计划；完成后再人工申报实际条件。</p>';
 return `<details><summary>实验关联与实际执行条件（需人工申报）</summary><p class="helper">实验 ${esc(pub.experiment_id)}<br>计划栏目：${esc(plan.chosen_pillar||'未记录')} · 计划形式：${esc(formatNames[plan.format]||'未记录')} · 窗口：${esc(plan.window||'未记录')}</p>${execution}<button class="quiet" data-open-experiment="${esc(pub.experiment_id)}">查看实验观测与历史 →</button></details>`;
}
function renderPublications(){
 const request=++publicationLoad,account=activeAccountId;
 const current=()=>request===publicationLoad&&currentPage==='publish'&&account===activeAccountId;
 let confirmedRequest=0;
 $('operationsContent').innerHTML=`<div class="notice">国内平台 API 尚未接通。模拟稿可演练流程；真实 AI 确认稿可在你自行发布后回填链接。此处不会向平台发送内容。</div><div class="section-toolbar"><div><h2>发布队列</h2><p class="muted">内容、账号与版本一起确认，创作完成不等于发布成功。</p></div><button id="loadConfirmed" class="secondary">选择已确认稿件</button></div><div id="confirmedRuns" class="panel inline-form" hidden></div><div class="publication-list">${accountRows('publications').map(p=>`<article id="publication-${esc(p.id)}" class="panel publication-card"><div class="publication-main"><div>${badge(platformNames[p.platform])} ${badge(p.mode==='simulation'?'模拟稿':p.mode==='imported'?'历史导入':'真实 AI 稿','neutral')} ${badge(pubStates[p.status],'amber')} ${p.promotion?badge('接单推广 · '+p.promotion.goal_label,'neutral'):''}</div><h2>${esc(p.content.selected_title)}</h2><p class="muted">${esc(p.account)} · 版本 ${esc(p.draft_ref.slice(0,8))} · ${esc(dateText(p.created_at))}</p><details><summary>查看待发布正文与确认依据</summary><p class="readable">${esc(p.content.body)}</p><p>${esc(p.content.cta)}</p><p class="helper">稿件 ${esc(p.draft_ref)} · 审核 ${esc(p.review_ref||'历史导入 · 无本系统审核')}<br>内容摘要 ${esc(p.content_hash.slice(0,16))} · ${p.format==='video'?'当前为脚本，需要自行制作视频。':'图片与封面需另行准备。'}${p.promotion?`<br>服务 ${esc(p.promotion.public_service.name)} v${p.promotion.service_version} · 推广简报 ${esc(p.promotion.id.slice(0,8))} · 问题依据 ${esc(p.promotion.problem_source_label)}`:''}</p></details>${publicationExperimentHTML(p)}${p.url?`<a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">查看已回填作品 ↗</a>`:''}</div><div class="publication-actions">${p.status==='AWAITING_APPROVAL'?`<button class="primary" data-approve="${p.id}">确认此版本与账号</button>`:p.status==='APPROVED'?(p.mode==='simulation'?`<button class="primary" data-simulate="${p.id}">演练发布（不发平台）</button>`:`<form data-record="${p.id}"><label>已发布作品链接<input name="url" type="url" required placeholder="平台作品 URL"></label><label>实际发布时间（可输入秒）<input name="published_at" type="datetime-local" step="1" required></label>${p.experiment_id?'<p class="helper">实验的实际发布时间不得早于稿件进入发布中心的准备时间。</p>':''}<button class="primary">保存人工发布记录</button></form>`):`<button class="secondary" data-to-metrics="${p.id}">录入指标与复盘 →</button>`}</div></article>`).join('')||empty('还没有待发布内容','在创作工作台完成审核并确认稿件，再进入发布中心。')}</div>`;
 $('loadConfirmed').onclick=async()=>{const sequence=++confirmedRequest;try{const response=await api('/api/runs');if(!current()||sequence!==confirmedRequest)return;const rows=response.filter(r=>matchesAccount(r)&&r.run_status==='SUCCEEDED'&&!ops.publications.some(p=>p.run_id===r.run_id));$('confirmedRuns').hidden=false;$('confirmedRuns').innerHTML=rows.length?rows.map(r=>`<button class="confirmed-choice" data-prepare-run="${esc(r.run_id)}" data-ref="${esc(r.accepted_ref)}">${esc(r.context.topic)} <span>加入发布队列 →</span></button>`).join(''):'<p class="muted">暂无未加入队列的确认稿。先在创作工作台完成一份稿件。</p>';}catch(e){if(current()&&sequence===confirmedRequest)error(e);}};
 document.querySelectorAll('[data-record]').forEach(form=>form.onsubmit=async e=>{e.preventDefault();if(!current())return;await operate('record',{id:form.dataset.record,url:form.elements.url.value,published_at:new Date(form.elements.published_at.value).toISOString()});});
 document.querySelectorAll('[data-execution-meta]').forEach(form=>form.onsubmit=async e=>{
  e.preventDefault();if(!current())return;
  const f=form.elements;if(!f.confirmed.checked){error(new Error('请确认这是实际执行记录'));return;}
  await operate('post_metadata',{id:form.dataset.executionMeta,format:f.format.value,pillar:f.pillar.value,traffic:f.traffic.value});
 });
}
function latestMetrics(){const map=new Map();for(const m of accountRows('metrics'))map.set(m.publication_id+':'+m.window,m);return [...map.values()].reverse();}
function experimentResultsHTML(experiment){
 const labels={pending_publication:'待完成发布',pending_metrics:'待录入目标窗口指标',incomplete:'指标不完整',window_mismatch:'观察时间不在目标窗口',conditions_mismatch:'实际执行条件不一致',observed_no_baseline:'已观测 · 无可比基线',observed:'完整观测 · 仅描述性',superseded:'旧结果已失效',blocked:'实验不可继续结算'};
 const rows=accountRows('experiment_results').filter(r=>r.experiment_id===experiment.id).slice().sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at)));
 if(!rows.length)return '<p class="helper">尚无观测结果。接受实验后可更新状态；未发布、缺指标或无基线都不会补成成功。</p>';
 return `<div class="experiment-results">${rows.map((r,i)=>`<details ${i===0?'open':''}><summary>${esc(labels[r.status]||r.status)} · ${esc(dateText(r.created_at))}</summary><p>${esc(r.reason||'')}</p>${r.invalid_reason?`<p class="issue">失效原因：${esc(r.invalid_reason)}</p>`:''}<p>观测加权互动 / 千次阅读播放：${esc(r.observed_reward??'尚未取得')}<br>建议时基线：${esc(r.baseline_reward??'无建议时可比基线')}<br>描述性差值：${esc(r.difference??'不计算差值')}</p><p class="helper">目标窗口 ${esc(r.window)} · ${esc(formatNames[r.format]||'形式未记录')} · ${r.source_type==='simulation'?'演示数据':'人工记录，未由平台核实'}<br>指标 ${esc(r.metric_id||'暂无')} · 修订 ${esc(r.metric_revision??'暂无')}<br>建议时基线指标：${(r.baseline_metric_refs||[]).map(esc).join('、')||'无'}<br>结果标识 ${esc(r.id)}；旧结果保留用于审计，不代表当前有效结论。</p></details>`).join('')}</div>`;
}
function experimentCardHTML(x){
 const pub=accountRows('publications').find(p=>p.id===x.publication_id||p.experiment_id===x.id);
 return `<article id="experiment-${esc(x.id)}" class="panel memory-card"><div class="card-top"><div>${badge(x.algorithm)} ${badge(x.decision_mode==='explore'?'探索':'利用','amber')}</div>${badge(experimentStates[x.status]||x.status,'neutral')}</div><h2>下一篇验证「${esc(x.chosen_pillar)}」</h2><p class="memory-advice">${esc(x.hypothesis)}</p><p class="muted">${esc(platformNames[x.platform]||x.platform)} · ${esc(formatNames[x.format]||'形式未记录，需重新推荐')} · ${x.source_type==='simulation'?'演示数据':'真实人工记录'} · ${esc(x.window)}<br>${esc(x.sample_size??'未知')} 篇可用样本 · 置信信息 ${esc(x.confidence)}</p>${x.invalid_reason?`<p class="issue">失效原因：${esc(x.invalid_reason)}</p>`:''}<p>执行阶段：${esc(pub?(pubStates[pub.status]||pub.status):x.status==='accepted'?'已接受，尚未绑定发布记录':'尚未接受或已失效')}</p><details><summary>查看算法、候选分数与排除证据</summary><p>${esc(x.reward_formula)}</p>${(x.candidates||[]).map(c=>`<p><b>${esc(c.pillar)}</b> · 样本 ${esc(c.samples)} · 均值 ${esc(c.mean_reward??'待探索')} · 探索奖励 ${esc(c.exploration_bonus??'优先')} · UCB ${esc(c.ucb_score??'未采样')}</p>`).join('')}<p>控制：${esc(x.control)}<br>变量：${esc(x.variant)}<br>证据快照：${(x.metric_refs||[]).map(esc).join('、')||'暂无，优先探索未测试栏目'}</p>${(x.excluded||[]).map(row=>`<p class="helper">排除 ${esc(row.metric_id||row.publication_id||'记录')}：${esc((row.reasons||[]).join('；'))}</p>`).join('')}${(x.limitations||[]).map(v=>`<p class="helper">${esc(v)}</p>`).join('')}</details><div class="buttons">${x.status==='proposed'?`<button class="primary" data-experiment="${esc(x.id)}" data-status="accepted">接受这个实验</button><button class="quiet" data-experiment="${esc(x.id)}" data-status="rejected">拒绝</button>`:x.status==='accepted'?`${!x.publication_id?`<button class="primary" data-use-experiment="${esc(x.id)}">按这个实验创作 →</button>`:''}<button class="secondary" data-evaluate-experiment="${esc(x.id)}">更新实验观测</button><button class="quiet" data-experiment="${esc(x.id)}" data-status="revoked">撤销</button>`:''}${pub?`<button class="quiet" data-experiment-publication="${esc(pub.id)}">查看发布与实际执行条件 →</button>${pub.published_at?`<button class="secondary" data-to-metrics="${esc(pub.id)}" data-metric-window="${esc(x.window)}">录入 / 修正 ${esc(x.window)} 指标 →</button>`:''}`:''}</div><h3>观测结果与历史</h3>${experimentResultsHTML(x)}<p class="helper">差值只描述这次观察与建议时基线的数值，不代表因果增益、统计显著或预测爆款。保存指标后点击“更新实验观测”。</p></article>`;
}
function renderMemory(){
 const experiments=accountRows('experiments'),account=currentAccount();
 if(!account)return;
 const accountId=account.id;
 $('operationsContent').innerHTML=`<div class="ops-hero memory-hero"><div><span class="eyebrow">可解释运营实验引擎</span><h2>不是猜爆款，而是决定下一次值得验证什么。</h2><p>建议 → 人工接受 → 创作确认 → 发布与执行申报 → 窗口指标 → 可审计观测。</p></div>${badge(experiments.filter(x=>x.status==='accepted').length+' 个已接受实验')}</div><form id="experimentForm" class="panel inline-form"><h2>生成下一次可控实验</h2><div class="two-col"><label>当前平台<input readonly value="${esc(platformNames[account.platform])}"></label><label>保持一致的内容形式<select name="format"><option value="image_text" ${account.platform==='xiaohongshu'?'selected':''}>图文笔记</option><option value="video" ${account.platform==='douyin'?'selected':''}>视频 / 待制作脚本</option></select></label><label>数据来源<select name="source_type"><option value="manual">真实人工记录</option><option value="simulation" ${account.demo_sample?'selected':''}>演示数据</option></select></label><label>统一观察窗口<select name="window"><option value="24h">24 小时</option><option value="72h">72 小时</option><option value="7d">7 天</option></select></label></div><button class="primary">运行实验决策算法</button><p class="helper">不调用收费模型；只使用当前账号、平台、形式、来源和窗口下，自然流量且指标完整的可比记录。演示不是真实运营效果。</p></form><div class="memory-list">${experiments.map(experimentCardHTML).join('')||empty('还没有可控实验','选择内容形式与来源，先生成建议，再由你决定是否接受。')}</div><div class="section-toolbar"><div><h2>人工接受的运营经验</h2><p class="muted">保留原有描述性复盘；不把相关性写成因果。</p></div></div><div class="memory-list">${accountRows('memories').map(m=>`<article class="panel memory-card"><div class="card-top"><div>${badge(platformNames[m.platform])} ${badge(m.source_type==='simulation'?'演示经验':'用户数据经验','amber')}</div>${badge(memoryStates[m.status],'neutral')}</div><h2>${esc(m.observation.split('；')[0])}</h2><p class="memory-advice">${esc(m.text)}</p><p class="muted">${esc(m.account)} · ${m.window} · ${m.sample_size} 篇样本</p><p class="helper">${esc(m.limitation)}</p><details><summary>查看证据与使用范围</summary><p class="readable">${esc(m.observation)}</p><p>指标快照 ${esc(m.metric_id.slice(0,8))} · 发布记录 ${esc(m.publication_id.slice(0,8))}</p></details><div class="buttons">${m.status==='proposed'?`<button class="primary" data-memory="${m.id}" data-status="accepted">接受为下次实验建议</button><button class="quiet" data-memory="${m.id}" data-status="rejected">暂不采用</button>`:m.status==='accepted'?`<button class="quiet" data-memory="${m.id}" data-status="revoked">撤销此经验</button>`:''}</div></article>`).join('')||empty('还没有复盘经验','在数据复盘中录入指标并生成建议，再来决定是否采用。')}</div>`;
 $('experimentForm').onsubmit=async e=>{
  e.preventDefault();if(currentPage!=='memory'||activeAccountId!==accountId)return;
  const f=e.target.elements;
  await operate('recommend_experiment',{account_id:accountId,platform:account.platform,format:f.format.value,source_type:f.source_type.value,window:f.window.value});
 };
}
document.querySelector('.workspace-nav').onclick=e=>{const b=e.target.closest('[data-page]');if(b&&!busy&&dirtyGuard()){auto=false;showPage(b.dataset.page);}};
$('clearTrend').onclick=()=>{chosenTrend=null;chosenExperiment=null;chosenPromotion=null;$('selectedTrend').hidden=true;$('clearTrend').hidden=true;};
$('targetPlatform').onchange=()=>{if(chosenTrend&&chosenTrend.platform!==$('targetPlatform').value)$('clearTrend').click();};
$('sendToPublish').onclick=async()=>{try{if(!ops)ops=await api('/api/operations');if(await operate('prepare',{run_id:run.run_id,draft_ref:run.accepted_ref}))showPage('publish');}catch(e){error(e);}};
$('quickStart').onclick=()=>{$('workflow').value='quick';$('topic').focus();$('briefForm').scrollIntoView({behavior:'smooth',block:'start'});};
$('focusBrief').onclick=()=>{$('workflow').value='professional';$('topic').focus();$('briefForm').scrollIntoView({behavior:'smooth',block:'start'});};
$('openExperiments').onclick=()=>{showPage('memory');};
$('operationsContent').onclick=async e=>{
 const b=e.target.closest('button');if(!b||opsBusy)return;
 const account=activeAccountId,page=currentPage;
 if(b.dataset.filter){platformFilter=b.dataset.filter;renderTrends();}
 if(b.dataset.choose)chooseTrend(b.dataset.choose);
 if(b.dataset.prepareRun)await operate('prepare',{run_id:b.dataset.prepareRun,draft_ref:b.dataset.ref});
 if(b.dataset.approve)await operate('approve',{id:b.dataset.approve});
 if(b.dataset.simulate)await operate('simulate',{id:b.dataset.simulate});
 if(b.dataset.toMetrics&&accountRows('publications').some(p=>p.id===b.dataset.toMetrics&&p.published_at)){showPage('metrics');renderMetrics(b.dataset.toMetrics);if(['24h','72h','7d'].includes(b.dataset.metricWindow)&&$('metricWindow'))$('metricWindow').value=b.dataset.metricWindow;}
 if(b.dataset.learn&&await operate('analyze',{id:b.dataset.learn})&&account===activeAccountId&&page===currentPage){showPage('metrics');toast('分析已保存；有可比依据时会生成候选经验');}
 if(b.dataset.memory)await operate('memory',{id:b.dataset.memory,status:b.dataset.status});
 if(b.dataset.experiment&&accountRows('experiments').some(x=>x.id===b.dataset.experiment))await operate('experiment_status',{id:b.dataset.experiment,status:b.dataset.status});
 if(b.dataset.useExperiment)chooseExperiment(b.dataset.useExperiment);
 if(b.dataset.evaluateExperiment&&accountRows('experiments').some(x=>x.id===b.dataset.evaluateExperiment)){
  if(await operate('evaluate_experiment',{id:b.dataset.evaluateExperiment})&&account===activeAccountId&&page===currentPage)toast('观测状态已更新；请查看依据、未完成项和历史结果，不代表因果效果');
 }
 if(b.dataset.experimentPublication&&accountRows('publications').some(p=>p.id===b.dataset.experimentPublication&&p.experiment_id)){
  showPage('publish');$('publication-'+b.dataset.experimentPublication)?.scrollIntoView({block:'center'});
 }
 if(b.dataset.openExperiment&&accountRows('experiments').some(x=>x.id===b.dataset.openExperiment)){
  showPage('memory');$('experiment-'+b.dataset.openExperiment)?.scrollIntoView({block:'center'});
 }
};
