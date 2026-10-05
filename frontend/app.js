'use strict';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names={audience:'受众与竞品洞察',research:'素材与证据研究',content:'内容策划创作',reviewer:'基础审核',human:'人工处理 / 确认'};
const stages={analysis:'分析',audience:'受众分析',research:'素材分析',strategy:'策略',outline:'提纲',hook:'开头',title:'标题',body:'正文',revise:'按意见改稿',review:'审核'};
const states={QUEUED:'准备开始',RUNNING:'可以继续执行',WAITING_USER:'等待你的决定',SUCCEEDED:'已确认完成',CANCELLED:'已取消',FAILED:'执行失败',RETRY_WAIT:'等待重试',EXPIRED:'已过期'};
const checks={brief_fit:'符合需求',audience_fit:'受众相关',usefulness_and_readability:'实用与易读',title_body_alignment:'标题与正文一致',evidence_integrity:'证据完整',experience_authenticity:'经历真实',originality_risk:'原创风险',privacy_and_policy:'隐私与规则'};
let provider=null,polling=false,materialDocsCache=[],confirmedLiveRuns=new Set(),materialRefreshes=new Map();
let csrf='',run=null,selected='audience',busy=false,auto=false,editing=false,viewVersion=null,detailStage=null,toastTimer,chosenHypothesis=null;
let cancellationRun=null;
let creationSequence=0;
let pendingLiveBudget=null;
async function api(path,method='GET',body){
 const r=await fetch(path,{method,headers:method==='POST'?{'Content-Type':'application/json','X-CSRF-Token':csrf}:{},body:body===undefined?undefined:JSON.stringify(body)});
 const data=await r.json(); if(!r.ok){const failure=new Error(data.error?.message||'请求失败');failure.code=data.error?.code;throw failure;}return data;
}
let errorSource=null;
function error(e,source='request'){$('error').textContent=e.message||String(e);$('error').hidden=false;errorSource=source;}
function clearError(){$('error').hidden=true;errorSource=null;}
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3500);}
function json(value){return '<pre class="json">'+esc(JSON.stringify(value,null,2))+'</pre>';}
function dirtyGuard(){return !editing||window.confirm('有尚未保存的编辑，确定放弃吗？');}
function audienceWebObservations(value){
 return (value.observations||[]).map(o=>{const source=(run.context.evidence||[]).find(s=>s.source_id===o.source_id);return `<article class="source-card"><h3>有原文依据的观察</h3><blockquote>${esc(o.quote)}</blockquote><p>${esc(o.interpretation)}</p>${source?.url?`<a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.title||'查看来源')}</a>`:''}</article>`;}).join('');
}
function renderWebResearch(){
 const host=$('webResearchReport'),web=run.context.web_research||{};host.hidden=!web.enabled;if(!web.enabled)return;
 const labels={pending:'等待启动联网调查',searching:'正在搜索并读取网页',complete:'已读取公开来源',insufficient:'没有足够的相关正文，未调用模型'};
 host.innerHTML=`<h2>本次联网调查 · ${esc(labels[web.status]||'调查未完成')}</h2><p class="helper">公开网页线索，不等于平台热榜或已核实事实。搜索和网页读取有次数上限；此步骤不调用模型。</p><p>搜索词：${esc((web.queries||[]).join('；'))}</p>${(web.searches||[]).map(s=>`<details><summary>${esc(s.query)} · ${s.results.length} 条搜索线索</summary>${s.effective_query?`<p class="helper">实际搜索词：${esc(s.effective_query)} · ${esc(s.provider||'公开搜索')}</p>`:''}${s.error?`<p class="issue">${esc(s.error)}</p>`:''}${s.results.map(r=>`<p><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}</a> · 搜索摘要，未代表已读正文</p>`).join('')}</details>`).join('')}${(web.sources||[]).map(s=>`<article class="source-card"><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a><p class="helper">读取时间：${esc(s.fetched_at)} · 页面声明发布时间：${esc(s.published_at||'未知')} · 平台热度：未知</p><blockquote>${esc(s.text)}</blockquote></article>`).join('')}${(web.reads||[]).filter(r=>r.error).map(r=>`<p class="issue">${esc(r.url)}：${esc(r.error)}</p>`).join('')}${web.status==='insufficient'?'<p>本次没有读到足够正文，因此未调用模型。可在下面修改关键词，留在这个任务重新搜索。</p>':''}`;
 if(['insufficient','searching'].includes(web.status)&&!run.in_flight&&run.current_stage==='brief'){host.insertAdjacentHTML('beforeend',`<form id="retryWebResearch"><label for="retryQuery1">调整搜索词（用核心词，如：新手 护肤 顺序）</label><input id="retryQuery1" required minlength="2" maxlength="120" value="${esc(web.queries?.[0]||'')}"><label for="retryQuery2">第二组关键词（可选）</label><input id="retryQuery2" maxlength="120" value="${esc(web.queries?.[1]||'')}"><button class="primary" type="submit">重新搜索这一步（不调用模型）</button></form>`);$('retryWebResearch').onsubmit=async e=>{e.preventDefault();await backgroundCommand('retry_research',{queries:[$('retryQuery1').value,$('retryQuery2').value].map(q=>q.trim()).filter(Boolean)});};}
}
function renderMaterialUploads(){
 const host=$('materialUploads');if(!host)return;
 const docs=materialDocsCache.filter(d=>d.account_id===currentAccount()?.id),picker=$('materialDocumentSelect');
 const selected=new Set([...picker.selectedOptions].map(o=>o.value));
 picker.innerHTML=docs.map(d=>`<option value="${esc(d.id)}" ${selected.has(d.id)?'selected':''}>${esc(d.title)} · v${d.version} · ${d.text_chars} 字 · ${d.location_type==='paragraph'?'段落':'页'} ${d.locations}</option>`).join('');
 host.innerHTML=docs.length?'<p class="helper">文件正文已解析并保存在当前账号资料库；选中的最多 3 份会在创作时检索，不会把整份文件塞进模型。</p>':'<p class="helper">当前账号资料库暂无可选文件。</p>';
}
async function refreshMaterialDocuments(){
 if(!websiteSession?.auth_required||!currentAccount())return;
 const account=currentAccount().id;
 if(materialRefreshes.has(account))return materialRefreshes.get(account);
 const request=(async()=>{
  try{const docs=await api('/api/knowledge?account_id='+encodeURIComponent(account));materialDocsCache=materialDocsCache.filter(d=>d.account_id!==account).concat(docs.map(d=>({id:d.id,account_id:account,title:d.title,version:d.version,filename:d.filename||d.title,locations:d.metadata?.page_count||0,location_type:d.metadata?.location_type||'page',text_chars:d.metadata?.extracted_chars||0})));if(currentAccount()?.id===account)renderMaterialUploads();}
  catch(e){if(currentAccount()?.id===account)error(e);}
 })();
 materialRefreshes.set(account,request);
 try{await request;}finally{if(materialRefreshes.get(account)===request)materialRefreshes.delete(account);}
}
function confirmLiveBudget(resume){
 if(!run||run.mode!=='live'||!provider)return true;
 if(confirmedLiveRuns.has(run.run_id))return true;
 const calls=provider.run_attempts_max??16,tokens=provider.run_tokens_max??80000,runUsd=provider.run_budget_usd??0.10,dayUsd=provider.day_budget_usd??0.50;
 const experiment=run.testing_budget;
 const experimentNotice=experiment?`本轮参考预算：¥${Number(experiment.target_cny).toFixed(2)}，希望约写 ${experiment.target_runs} 轮；已计入约¥${Number(experiment.spent_cny).toFixed(4)}，已进行 ${experiment.run_count} 轮（包含未完成任务）。\n参考目标用于查看用量，不影响继续创作。\n\n`:'';
 pendingLiveBudget={runId:run.run_id,snapshotId:run.snapshot_id,resume};
 $('liveBudgetMessage').textContent=`即将调用真实模型，可能产生费用。\n\n${experimentNotice}\n本任务硬上限：最多 ${calls} 次调用、${tokens.toLocaleString()} Token、$${Number(runUsd).toFixed(2)}；今日累计上限 $${Number(dayUsd).toFixed(2)}。\n上传资料最多 3 段，联网资料最多再加 3 段（每段最多 400 字）；达到任一上限会由服务器停止，不自动重试。`;
 $('liveBudgetConfirmation').hidden=false;$('liveBudgetConfirmation').scrollIntoView({behavior:'smooth',block:'center'});
 return false;
}
$('declineLiveBudget').onclick=()=>{pendingLiveBudget=null;$('liveBudgetConfirmation').hidden=true;};
$('approveLiveBudget').onclick=async()=>{
 const pending=pendingLiveBudget;pendingLiveBudget=null;$('liveBudgetConfirmation').hidden=true;
 if(!pending)return;
 if(busy||run?.run_id!==pending.runId||run.snapshot_id!==pending.snapshotId){error(new Error('任务或素材已变化，请重新确认费用。'));return;}
 confirmedLiveRuns.add(pending.runId);await pending.resume();
};
let historyDeleted=false,historyRequest=0,historyMenuRun=null,historyMenuOpener=null;
async function history(){
 const request=++historyRequest,deleted=historyDeleted;
 const rows=(await api('/api/runs'+(deleted?'?deleted=true':''))).filter(r=>r.workflow_type!=='windtunnel'&&(typeof matchesAccount!=='function'||matchesAccount(r)));
 if(request!==historyRequest)return rows;
 $('history').innerHTML=rows.length?rows.map(r=>`<button data-run="${esc(r.run_id)}" data-title="${esc(r.context.topic||'旧任务')}" class="${run?.run_id===r.run_id?'selected':''}" title="右键${deleted?'恢复':'删除'}这条创作记录">${esc(r.context.topic||'旧任务')}<small>${deleted?'已删除 · 右键恢复':esc(r.background?.status==='blocked'?'已暂停 · 查看原因':states[r.run_status])+' · '+r.drafts.length+' 个版本'}</small></button>`).join(''):`<p class="helper">${deleted?'没有已删除的创作':'还没有创作记录'}</p>`;
 $('historyTrash').textContent=deleted?'返回最近的创作':'已删除的创作';
 return rows;
}
function closeHistoryMenu(){ $('historyContextMenu').hidden=true;historyMenuRun=null; }
function openHistoryMenu(button,x,y){
 if(busy)return;
 historyMenuOpener=button;historyMenuRun={id:button.dataset.run,title:button.dataset.title,deleted:historyDeleted};
 const menu=$('historyContextMenu');$('historyDelete').textContent=historyDeleted?'恢复这条创作':'删除这条创作';
 menu.hidden=false;menu.style.left=Math.max(8,Math.min(x,window.innerWidth-200))+'px';menu.style.top=Math.max(8,Math.min(y,window.innerHeight-65))+'px';$('historyDelete').focus();
}
$('history').addEventListener('contextmenu',e=>{const b=e.target.closest('[data-run]');if(!b)return;e.preventDefault();openHistoryMenu(b,e.clientX,e.clientY);});
$('history').addEventListener('keydown',e=>{if(e.key!=='ContextMenu'&&!(e.shiftKey&&e.key==='F10'))return;const b=e.target.closest('[data-run]');if(!b)return;e.preventDefault();const r=b.getBoundingClientRect();openHistoryMenu(b,r.left,r.bottom);});
$('historyTrash').onclick=async()=>{if(busy||!dirtyGuard())return;closeHistoryMenu();historyDeleted=!historyDeleted;try{await history();}catch(e){error(e);}};
$('historyDelete').onclick=async()=>{
 const target=historyMenuRun;if(!target||busy||!dirtyGuard())return;closeHistoryMenu();
 try{
  await api('/api/runs/'+encodeURIComponent(target.id)+'/visibility','POST',{deleted:!target.deleted});
  if(!target.deleted&&run?.run_id===target.id){auto=false;editing=false;run=null;viewVersion=null;$('editor').hidden=true;$('workbench').hidden=true;$('welcome').hidden=false;}
  await history();toast(target.deleted?'创作已恢复，可在最近的创作中打开。':'创作已删除，可在“已删除的创作”中恢复。');
 }catch(e){error(e);}
};
document.addEventListener('click',e=>{if(!e.target.closest('#historyContextMenu'))closeHistoryMenu();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('historyContextMenu').hidden){closeHistoryMenu();historyMenuOpener?.focus();}});
window.addEventListener('resize',closeHistoryMenu);
function currentAgent(){if(!run)return 'audience';if(run.run_status==='WAITING_USER'||run.run_status==='SUCCEEDED'||(!run.in_flight&&run.review?.decision==='revision_required'&&run.allowed_actions.includes('edit')))return 'human';if(run.current_stage==='brief')return 'audience';return run.current_stage;}
function renderTestingBudget(){
 const budget=run?.testing_budget,host=$('testingBudget');
 $('usageDetails').hidden=!budget;host.hidden=!budget;
 const money=value=>Number.isFinite(Number(value))?'¥'+Number(value).toFixed(2):'待统计';
 host.textContent=budget?`累计用量：${money(budget.spent_cny)}。参考目标：${money(budget.target_cny)}。参考目标用于查看用量，不影响继续创作。`:'';
}

function renderMode(mode){
 const live=mode==='live';
 $('modeBadge').textContent=live?'真实 AI · DeepSeek':'模拟运行';
 $('modeNotice').textContent=live?'四个角色调用 DeepSeek；每次输出与用量可查看。可结合账号资料与已读取来源；事实仍需核查，最终由你确认。':'这是免费模拟流程，使用固定模板和本地规则，没有调用真实 AI。';
 $('detailMode').textContent=live?'真实 AI 产物':'模拟产物';
}
function unresolvedUsage(task){
 return Number(task.usage?.unknown_calls||0)>0||(task.calls||[]).some(c=>c.tokens===null);
}
function modelFailureGuidance(task){
 if(task.in_flight||!['FAILED'].includes(task.run_status)&&task.background?.status!=='blocked')return '';
 const last=(task.events||[]).filter(e=>e.type==='agent.failed').at(-1);
 const message=task.background?.error||last?.payload?.message||'';
 const failed=[...(task.calls||[])].reverse().find(c=>['invalid','failed'].includes(c.status));
 if(!/格式|JSON|MODEL_OUTPUT_INVALID|模型返回|用量不确定|用量未知/.test(message)&&!failed)return '';
 const stage=(failed?.stage==='analysis'?stages[failed?.agent]:stages[failed?.stage])||stages[failed?.agent]||'当前步骤';
 const saved='已完成的分析、资料和稿件都保留，不用重新上传。';
 if(unresolvedUsage(task))return `${stage}暂时停止：这次调用未保存完整的结果或用量记录。${saved}为避免重复计费，当前不能直接重试，需要先核对这次调用的用量；不要另建任务反复提交。`;
 if((task.allowed_actions||[]).includes('recover'))return `${stage}的模型结果未能通过检查。${saved}可以点击“从失败步骤继续”，保留已有进度和累计用量；新的模型请求仍受原来的额度限制。`;
 if((task.allowed_actions||[]).includes('next'))return `${stage}的模型结果未能通过检查。${saved}可以点击“重试未完成步骤”，已成功的步骤会复用；新的模型请求仍受原来的额度限制。`;
 return `${stage}的模型结果未能通过检查。${saved}请查看运行记录中的具体原因，当前没有可执行的重试步骤。`;
}
function nextStepGuidance(task){
 const allowed=task.allowed_actions||[];
 if(task.run_status==='SUCCEEDED')return '稿件已确认，可以下载。真实发布需你在平台完成后回到“作品与复盘”记录；模拟发布只用于演练。';
 if(editing&&task.review_execution?.exhausted)return '保存会创建新版本，不调用 AI。但本任务复审次数已用完，保存后只能继续手动修改，或知晓问题后人工采用；旧审核不会变成新版本通过。';
 if(editing)return '你正在修改稿件。保存会创建新版本，不调用 AI；之后可申请复审，或知晓问题后人工采用。';
 if(task.in_flight)return '正在处理，结果会自动保存并更新。可以先阅读已有稿件；无需重复点击或刷新。';
 const failure=modelFailureGuidance(task);if(failure)return failure;
 if(task.review_execution?.blocked)return task.review_execution.message;
 if(allowed.includes('supplement'))return '请先补充下方缺失素材或选择假设权限，再继续分析；不能用虚构经历填补证据。';
 if(task.current_stage==='reviewer'&&task.drafts.length&&!task.review)return '新版本已保存，尚未完成复审。点击“复审当前版本”查看审核意见；真实 AI 复审会计入费用。';
 if(task.review?.decision==='revision_required')return '先看下方具体问题，再手动修改或按意见改稿。读者理解检查可选，不代替基础审核。';
 if(allowed.includes('accept'))return '先检查正文和事实，再确认当前版本。需要修改时另存新版本，原审核不沿用。';
 if(allowed.includes('adopt_manual'))return '当前版本尚未通过有效审核。可继续修改/复审，或明确知晓已有问题后人工采用。';
 if(task.run_status==='FAILED')return '本次执行失败，已有稿件和记录保留。先看具体错误，再决定是否从失败步骤继续，不必新建重复任务。';
 if(['CANCELLED','EXPIRED'].includes(task.run_status))return '本任务已停止，旧版本仍可查看。需要继续创作时新建一份需求。';
 return '需求已保存。点“连续运行”生成初稿并停在人工处理处；想逐步了解过程，可点“执行下一步”。过程和来源在下方按需展开。';
}
function render(){
 if(!run)return;
 if(errorSource==='run')clearError();
 renderWebResearch();
 renderMode(run.mode);
 renderTestingBudget();
 $('workbenchGuide').textContent=nextStepGuidance(run);
 document.querySelector('#editor .editor-note').textContent=run.review_execution?.exhausted?'保存会创建新版本，不覆盖旧稿，也不调用 AI。本任务复审次数已用完；保存后可继续手动修改，或知晓问题后人工采用，不能沿用旧审核。':'保存会创建新版本，不会覆盖旧稿，也不会自动调用 AI。保存后可点击“复审”，或知晓已有问题后人工采用；未保存修改不进入最终稿。';
 $('modelCalls').textContent=(run.usage?.model_calls||0)+' 次';
 $('modelCost').textContent=run.mode==='live'?'≤ $'+Number(run.usage.cost_upper_estimate_usd||0).toFixed(4)+' 估算':'¥0.00（模拟）';
 if(run.run_status==='FAILED'){const last=run.events.filter(e=>e.type==='agent.failed').at(-1);error(new Error(modelFailureGuidance(run)||last?.payload.message||'执行失败，请查看运行记录'),'run');}
 $('welcome').hidden=true;$('workbench').hidden=false;
 $('runTitle').textContent=run.context.topic;
 $('runSummary').textContent=`${run.context.operations?.platform==='douyin'?'抖音 · 口播脚本':'小红书 · 图文笔记'} · 写给 ${run.context.audience} · ${run.context.tone} · ${run.snapshot_id.slice(0,8)} 输入快照`;
 const background=run.background;
 const jobLabels={queued:background?.worker_online?'已排队，后台即将执行':'已排队，等待 Worker 启动',running:'正在执行 · 结果保存后自动更新',pausing:'正在暂停，等待当前节点保存',paused:'本步已停止 · 查看结果后继续',blocked:'后台等待处理',waiting:'等待你的审核'};
 $('statusLabel').textContent=jobLabels[background?.status]|| (run.in_flight?'AI 正在处理，请稍候':states[run.run_status]);
 if(background?.error)error(new Error(['insufficient','searching'].includes(run.context.web_research?.status)?'联网调查未完成。请在上方修改关键词，点击“重新搜索这一步”；无需新建任务。':modelFailureGuidance(run)||background.error),'run');$('versionCount').textContent=run.drafts.length+' 个';
 const allowed=run.allowed_actions;
 $('recover').hidden=!allowed.includes('recover');$('next').hidden=!allowed.includes('next');$('auto').hidden=!allowed.includes('next');$('cancel').hidden=!allowed.includes('cancel');
 $('next').textContent=run.current_stage==='reviewer'?'执行复审 / 审核 →':run.review?.decision==='revision_required'?'按意见改稿 →':'执行下一步 →';
 $('auto').textContent=background?(run.in_flight?'暂停后台任务':'后台运行到人工处理'):(auto?'停止自动运行':'自动运行到人工处理');
 if(background){$('next').hidden=!allowed.includes('next')||run.in_flight;$('auto').hidden=!allowed.includes('next')&&!run.in_flight;$('auto').textContent=run.in_flight?'暂停执行':'连续运行到人工处理';$('next').textContent=run.current_stage==='reviewer'?'复审当前版本，看审核意见 →':run.current_stage==='brief'&&run.context.web_research?.enabled&&run.context.web_research.status!=='complete'?'执行一步：联网搜索 →':'执行下一步，看结果 →';}
 if(!run.in_flight&&run.background?.status==='blocked'&&modelFailureGuidance(run)&&!unresolvedUsage(run))$('next').textContent='重试未完成步骤 →';
 if(!run.in_flight&&unresolvedUsage(run)&&['FAILED','RUNNING','QUEUED'].includes(run.run_status)){$('next').hidden=true;$('auto').hidden=true;$('recover').hidden=true;}
 if(run.review_execution?.blocked&&!run.in_flight){$('next').hidden=true;$('auto').hidden=true;}
 if(['insufficient','searching'].includes(run.context.web_research?.status)&&!run.in_flight){$('next').hidden=true;$('auto').hidden=true;}
 const node=(key,num,sub)=>{
 const logs=run.node_runs.filter(n=>n.agent===key&&n.snapshot_id===run.snapshot_id);
 const isCurrent=(key===currentAgent()||(run.current_stage==='brief'&&key==='research'&&run.run_status!=='WAITING_USER'))&&!['SUCCEEDED','CANCELLED','FAILED'].includes(run.run_status);
 const done=key==='human'?run.run_status==='SUCCEEDED':logs.length>0;
 const human=key==='human'&&(run.run_status==='WAITING_USER'||(!run.in_flight&&run.review?.decision==='revision_required'&&run.allowed_actions.includes('edit')));
 const label=human?'◈ 等你处理':isCurrent?'◉ 当前步骤':done?'✓ 已有产物':'○ 尚未执行';
 return `<button class="node ${isCurrent?'current':''} ${done?'done':''} ${human?'human':''} ${selected===key?'selected':''}" data-agent="${key}" aria-pressed="${selected===key}"><span class="node-top"><span>${key==='human'?'由你决定':'AGENT '+num}</span><span>${label}</span></span><b>${names[key]}</b><small>${sub}</small></button>`;
 };
 const contentStages=['strategy','outline','hook','title','body'].map(s=>`<button class="stage-chip ${run.artifacts.some(a=>a.stage===s)?'done':''}" data-stage="${s}">${stages[s]}</button>`).join('');
 $('flow').innerHTML=`<div class="parallel">${node('audience','01','理解读者 · 明确假设')}${node('research','02','收录素材 · 标记缺口')}</div><div class="connector">同一份需求 · 并行分析<span>↓ 汇合 ↓</span></div>${node('content','03','策略与写作 · 同一角色负责返修')}<div class="stages">${contentStages}</div><div class="connector"><span>↓</span></div>${node('reviewer','04','问题定位 · 修改建议 · 再次审核')}<div class="connector">审核意见保留 ↓ 最后由你决定</div>${node('human','YOU','补资料 / 改稿 / 比较版本 / 最后确认')}`;
 renderDetails();renderHuman();renderRecovery();renderDraft();renderTimeline();renderCalls();
 document.querySelectorAll('#workbench button').forEach(b=>{if(!b.closest('#flow')&&b.id!=='auto')b.disabled=busy||(b.dataset.titleChoice!==undefined&&run.artifacts.find(a=>a.stage==='title')?.value.candidates[Number(b.dataset.titleChoice)]===run.drafts.at(-1)?.content.selected_title);});
 $('cancel').disabled=busy&&!run.in_flight;$('reviewConfirmUnavailable').disabled=true;$('confirmationPending').disabled=true;
 $('checkReaders').disabled=busy||editing||run.in_flight;
 if(background&&run.in_flight){for(const id of ['editButton','accept','adoptManual','revise','recover'])$(id).disabled=true;}
 if(editing){$('next').disabled=true;$('auto').disabled=true;$('accept').disabled=true;$('adoptManual').disabled=true;$('revise').disabled=true;$('editButton').disabled=true;}
 else $('auto').disabled=busy&&!auto;
}
function friendly(agent,stage,value){
 const p=text=>'<p class="readable">'+esc(text)+'</p>';
 const list=items=>'<ol class="readable">'+items.map(t=>'<li>'+esc(t)+'</li>').join('')+'</ol>';
 if(agent==='audience')return p('目标读者：'+value.primary_audience)+p('可用历史作品：'+(value.sample_size||0)+' 条 · 可信程度：低（待验证）')+p(value.basis)+list(value.content_opportunities||[])+audienceWebObservations(value)+(value.competitor_observations?.length?'<h3>同类账号观察 · 用户记录</h3>'+list(value.competitor_observations.map(c=>c.name+'：'+c.observation)):'');
 if(agent==='research')return (value.topic_card?'<h3>结构化选题卡</h3>'+p('为什么现在：'+value.topic_card.why_now)+p('账号关联：'+value.topic_card.account_fit)+list(value.topic_card.content_angles):'')+p(value.scope)+(value.trend_context?p('选题线索：'+value.trend_context.title)+p(value.trend_context.source_type==='example'?'固定示例，不是实时热点':'来源链接仅保存，未抓取页面：'+value.trend_context.source_url):'')+(value.sources.length?value.sources.map(source=>'<h3>'+esc(source.title||'用户提供的素材')+'</h3>'+p(source.page?'第 '+source.page+' 页 · 资料版本 '+source.version:'本次输入')+p(source.text)+p(source.verification)+(source.url?'<a href="'+esc(source.url)+'" target="_blank" rel="noopener noreferrer">查看来源 ↗</a>':'')).join(''):p('没有可用素材，不能虚构经历或效果数字。'))+list(value.gaps||[]);
 if(agent==='reviewer')return p(({approved:'审核通过，等待你确认',revision_required:'发现问题，需要修改',needs_human:'需要你补充信息'})[value.decision])+list(value.limitations||[]);
 if(stage==='strategy')return (value.content_brief?'<h3>创作简报</h3>'+p('目标：'+value.content_brief.goal)+p('内容形式：'+value.content_brief.content_type)+p('推荐依据：'+value.content_brief.recommendation_reason)+p('禁用表达：'+(value.content_brief.banned||'未设置'))+p('互动引导：'+value.content_brief.cta)+p(value.content_brief.publishing_window):'')+p('创作角度：'+value.angle)+p('服务读者：'+value.reader)+p('内容承诺：'+value.promise)+p('表达风格：'+value.tone)+list(value.assumptions||[])+((value.next_experiments||[]).length?'<h3>已接受的实验建议</h3>'+list(value.next_experiments):'');
 if(stage==='outline')return list(value);
 if(stage==='hook')return p(value);
 if(stage==='title')return list(value.candidates.map((t,i)=>t+' — '+(value.reasons?.[i]||'历史版本未保存比较理由')))+p('当前选择：'+value.selected)+p(value.note);
 return '<h3>'+esc(value.selected_title)+'</h3>'+p(value.body)+p(value.cta)+p((value.tags||[]).map(t=>'#'+t).join(' '));
}
function renderDetails(){
 $('detailTitle').textContent=names[selected]||'步骤详情';
 if(selected==='human'){
 $('details').innerHTML='<div class="detail-block"><h3>最后决定由你做</h3><p>修改会创建新版本。你可以申请 AI 复审，也可以知晓现有问题后人工采用准确版本；人工采用不会标为 AI 审核通过。</p></div>'+ (run.accepted_ref?'<p>✓ 已确认版本 '+esc(run.accepted_ref.slice(0,8))+'</p>':'<p class="muted">尚未确认任何版本。</p>');return;
 }
 const previousLogs=run.node_runs.filter(n=>n.agent===selected&&n.snapshot_id!==run.snapshot_id);
 const previousHistory=previousLogs.length?'<details><summary>之前输入的历史记录（'+previousLogs.length+'，不代表本轮产物）</summary>'+previousLogs.map(l=>'<h3>'+esc(stages[l.stage])+' · '+esc(l.snapshot_id.slice(0,8))+'</h3>'+friendly(l.agent,l.stage,l.output)).join('')+'</details>':'';
 const logs=run.node_runs.filter(n=>n.agent===selected&&n.snapshot_id===run.snapshot_id);
 if(!logs.length){$('details').innerHTML='<div class="empty">本次输入尚无通过校验的产物。<br>执行完成后，可以查看它的输入和产物。</div>'+previousHistory;return;}
 const matches=detailStage?logs.filter(n=>n.stage===detailStage):logs;
 if(!matches.length){$('details').innerHTML='<div class="empty">本次输入的这个创作阶段还没有执行。</div>'+previousHistory;return;}
 const current=matches[matches.length-1];
 $('details').innerHTML=`${selected==='content'&&run.drafts.length>1?'<p class="editor-note">这些是生成时保存的阶段记录。最新修改后的稿件，请查看下方“文案与版本对比”。</p>':''}<p class="muted">最近阶段：${esc(stages[current.stage])} · ${current.duration_ms} ms · 真实模型调用 ${current.model_calls||0} 次 · ${current.tokens??'未知'} Token</p><div class="detail-block"><h3>当前产物</h3>${friendly(current.agent,current.stage,current.output)}<details><summary>查看原始结构化记录</summary>${json(current.output)}</details></div><details><summary>查看这一阶段的输入</summary>${json(current.input)}</details><div class="detail-block"><h3>工具与记忆</h3><p>${run.context.evidence?.length?'已使用资料检索快照，来源与片段可在本阶段输入中查看。':'本次未使用检索片段。'}${esc(current.memory)}</p><p>${run.mode==='live'?'由 DeepSeek 生成；审核不代表外部事实已核实。':'采用固定模板 / 本地规则，未使用模型推理。'}</p></div>${logs.length>1?'<details><summary>所有阶段与历史记录（'+logs.length+'）</summary>'+logs.map(l=>'<h3>'+esc(stages[l.stage])+' · '+esc(l.snapshot_id.slice(0,8))+'</h3>'+friendly(l.agent,l.stage,l.output)).join('')+'</details>':''}${previousHistory}`;
 if(selected==='reviewer'&&!run.review)$('details').insertAdjacentHTML('afterbegin','<p class="notice">以下是之前版本的审核记录，不代表当前稿已通过；当前版本尚未完成有效复审。</p>');
 if(selected==='reviewer'&&run.review){$('details').insertAdjacentHTML('afterbegin',run.review.checks.map(c=>`<div class="review-check"><span>${esc(checks[c.name])}</span><span class="${esc(c.result)}">${c.result==='pass'?(run.mode==='live'?'模型判断通过':'模拟通过'):c.result==='fail'?'发现问题':'未完成'}</span></div>`).join(''));}
}
function renderRecovery(){
 const canRepair=run.allowed_actions.includes('repair_review');
 const stopped=['SUCCEEDED','CANCELLED','EXPIRED'].includes(run.run_status);
 const blocked=!stopped&&(canRepair||(run.current_stage==='reviewer'&&run.drafts.length&&!run.review&&!run.allowed_actions.includes('accept')&&!run.allowed_actions.includes('adopt_manual')));
 $('reviewRecovery').hidden=!blocked;
 $('repairReview').hidden=!canRepair;
 $('repairReview').textContent=run.review_recovery?.next_action==='request_human'?'查看审核问题并进入人工处理（不调用 AI）':'查看审核问题并进入改稿（不调用 AI）';
 if(!blocked)return;
 $('reviewRecoveryTitle').textContent=canRepair?'稿件已保存，先处理审核问题':'稿件已保存，审核尚未完成';
 $('reviewRecoveryMessage').textContent=canRepair?(run.review_recovery?.reason||'审核结果未通过格式校验。可以免费整理已收到的意见，保留稿件和问题，进入人工处理，不再次调用模型。'):run.in_flight?'正在审核，完成后这里会显示下一步。你可以先阅读下方稿件。':'当前不能确认稿件。请查看上方具体错误与运行记录；不要反复启动同一个失败步骤。';
 const rejected=[...(run.calls||[])].reverse().find(c=>c.stage==='review'&&c.status==='invalid'&&!c.inherited);
 $('reviewRecoveryIssues').innerHTML=(rejected?.diagnostic_response?.issues||[]).map(i=>`<div class="issue"><b>${esc(i.excerpt||i.location||'稿件问题')}</b><p>${esc(i.reason)}</p><p>修改建议：${esc(i.suggestion)}</p></div>`).join('');
 if(canRepair){$('next').hidden=true;$('auto').hidden=true;}
}
function renderHuman(){
 const allowed=run.allowed_actions,review=run.review;
 const issueReview=review||run.prior_review||[...(run.calls||[])].reverse().find(c=>c.stage==='review'&&c.status==='invalid'&&!c.inherited)?.diagnostic_response;
 const revision=review?.decision==='revision_required';
 const visible=run.run_status==='WAITING_USER'||revision||allowed.includes('adopt_manual')||run.run_status==='SUCCEEDED';
 $('humanPanel').hidden=!visible;
 $('supplyForm').hidden=!allowed.includes('supplement');
 $('revise').hidden=!(revision&&allowed.includes('next')&&!run.review_execution?.blocked);
 $('confirmationPending').hidden=allowed.includes('accept')||allowed.includes('adopt_manual')||run.run_status==='SUCCEEDED';
 $('adoptManual').hidden=!allowed.includes('adopt_manual');
 $('adoptManual').textContent=`已知晓问题，采用当前版本（第 ${run.drafts.length} 版）`;
 $('editButton').hidden=!allowed.includes('edit');$('accept').hidden=!allowed.includes('accept');$('export').hidden=!allowed.includes('export');
 $('export').href=`/api/runs/${run.run_id}/export`;
 $('sendToPublish').hidden=run.run_status!=='SUCCEEDED';
 $('sendToPublish').textContent=run.mode==='simulation'?'进入模拟发布演练 →':'记录已发布 →';
 let title='需要你的决定',message='';
 if(run.run_status==='SUCCEEDED'){title=run.acceptance?.mode==='manual_override'?'稿件已确认 · 人工采用，无需再次确认':'稿件已确认，无需再次确认';message='下一步：下载确认稿，或到下方导出图文和视频素材，再前往平台发布。'+(run.acceptance?.mode==='manual_override'?'本版本由人工采用，不表示 AI 审核通过。':'')+'这里还没有实际发布；发布后再记录作品链接。';}
 else if(run.wait_reason==='missing_material'){title='资料还不够，请补充';message='请提供缺失的真实素材。保存后，两个分析角色会使用新快照重新执行。';}
 else if(run.wait_reason==='hypothesis_permission'){title='没有历史数据，需要你选择';message='本次账号快照没有可用的历史指标。可以允许明确标注的假设模式；也可取消任务，导入历史指标后新建创作。';}
 else if(run.review_execution?.blocked){title='复审次数已用完，由你处理';message=run.review_execution.message;}
 else if(run.wait_reason==='revision_limit'){title='已达到自动改稿上限';message='AI 自动改稿已停止。'+(run.review_execution?.exhausted?'复审次数也已用完。':'')+'你仍可手动修改，或知晓下方问题后采用当前版本；人工采用会单独记录，不表示 AI 审核通过。';}
 else if(revision){title='主编发现了问题，最后由你决定';message='你可以按意见改稿、手动修改，或知晓问题后人工采用当前版本。';}
 else if(allowed.includes('adopt_manual')){title='当前稿件，最后由你决定';message='这个版本尚未通过 AI 审核。可以继续修改或复审，也可以知晓问题后人工采用。';}
 else if(allowed.includes('accept')){title='审核结束，最后由你决定';message='请检查正文与素材。你可以先修改，也可以确认当前版本；修改后必须重新审核。';}
 if(run.run_status==='WAITING_USER'&&['missing_material','hypothesis_permission'].includes(run.wait_reason)&&!allowed.includes('supplement')){title='已达到本轮补充上限';message=allowed.includes('adopt_manual')?'你仍可修改现有稿件，或知晓问题后人工采用。':'已有记录会保留。请取消本任务，带着完整资料新建创作。';}
 $('humanTitle').textContent=title;$('humanMessage').textContent=message;
 const issueHTML=(!review&&issueReview?'<p class="helper">以下为已有审核意见，仅供参考；当前版本尚未完成有效复审。</p>':'')+(issueReview?.human_questions||[]).map(q=>'<p class="issue">'+esc(q)+'</p>').join('')+(issueReview?.issues||[]).map(i=>`<div class="issue"><b>${esc(({selected_title:'标题',body:'正文',cta:'互动引导',tags:'标签'})[i.location]||i.location)} · ${esc(i.excerpt)}</b><p>${esc(i.reason)}</p><p>修改建议：${esc(i.suggestion)}</p></div>`).join('');
 $('issues').innerHTML=run.run_status==='SUCCEEDED'&&issueHTML?'<details><summary>查看此前审核记录（仅供回看）</summary><p class="helper">稿件确认已完成。此前意见保留供回看，不代表还有待办，也不表示这些问题已经通过 AI 复审。</p>'+issueHTML+'</details>':issueHTML;
}
function draftHTML(d,index,changed=false){const c=d.content;return `<article class="draft-copy ${changed?'changed':''}"><span class="version-tag">版本 ${index+1} · ${d.actor==='user'?'你手动修改':run.mode==='live'?'AI 创作':'模拟创作'} · ${esc(d.ref.slice(0,8))}${run.accepted_ref===d.ref?' · 已确认':''}</span><h3>${esc(c.selected_title)}</h3><pre>${esc(c.body)}</pre><p>${esc(c.cta)}</p><div>${(c.tags||[]).map(t=>'<span class="tag">#'+esc(t)+'</span>').join('')}</div></article>`;}
function renderDraft(){
 if(typeof mountMediaExports==='function'&&$('mediaExports'))mountMediaExports(run,$('mediaExports'));
 $('draftPanel').hidden=!run.drafts.length;if(!run.drafts.length)return;
 // null follows new Worker drafts; only a user-selected older version is pinned.
 if(viewVersion!==null&&(!Number.isInteger(viewVersion)||viewVersion<0||viewVersion>=run.drafts.length))viewVersion=null;
 const i=viewVersion??run.drafts.length-1,d=run.drafts[i],prev=run.drafts[i-1];
 $('versionSelect').innerHTML=run.drafts.map((d,index)=>`<option value="${index}" ${index===i?'selected':''}>版本 ${index+1}${run.accepted_ref===d.ref?' · 已确认':''}</option>`).join('');
 $('compareVersionsWrap').hidden=!prev;
 if(!prev)$('compareVersions').checked=false;
 const compare=prev&&$('compareVersions').checked;
 const changes=prev?['selected_title','body','cta','tags'].filter(k=>JSON.stringify(prev.content[k])!==JSON.stringify(d.content[k])).map(k=>({selected_title:'标题',body:'正文',cta:'互动引导',tags:'标签'})[k]):[];
 $('draftView').innerHTML=(compare?'<p class="change-summary">与上一版相比：'+(changes.length?'修改了 '+changes.join('、'):'文字内容未变化')+'。左侧旧稿，右侧当前所选稿。</p><div class="draft-columns">'+draftHTML(prev,i-1)+draftHTML(d,i,true)+'</div>':draftHTML(d,i));
 $('checkReaders').hidden=!websiteSession?.auth_required;$('readerCheckHelp').hidden=$('checkReaders').hidden;
 $('checkReaders').textContent=`用版本 ${i+1} 做读者理解检查（可选） →`;
 $('checkReaders').disabled=busy||editing||run.in_flight;
 const candidates=run.artifacts.find(a=>a.stage==='title')?.value;
 if(candidates&&run.allowed_actions.includes('edit')&&!editing)$('draftView').insertAdjacentHTML('beforeend','<details><summary>比较候选标题 / '+(run.review_execution?.exhausted?'另存新版本，不再复审':'选择后重新审核')+'</summary>'+candidates.candidates.map((t,n)=>`<div class="candidate-row"><div><b>${esc(t)}</b><p class="muted">${esc(candidates.reasons?.[n]||'历史版本未记录理由')}</p></div><button data-title-choice="${n}" ${t===run.drafts.at(-1).content.selected_title?'disabled':''}>${run.review_execution?.exhausted?'选用并另存':'选用并复审'}</button></div>`).join('')+'</details>');
}
$('draftView').onclick=async e=>{const b=e.target.closest('[data-title-choice]');if(!b||busy||editing)return;const title=run.artifacts.find(a=>a.stage==='title')?.value.candidates[Number(b.dataset.titleChoice)];if(title&&title!==run.drafts.at(-1).content.selected_title&&await act('edit',{...run.drafts.at(-1).content,selected_title:title})){viewVersion=null;render();toast(run.review_execution?.exhausted?'标题已另存；复审次数已用完，请自行核对正文后决定是否采用':'标题另存为新版本，请重新审核正文是否匹配');}};
function renderTimeline(){
 const labels={'run.queued':'任务已保存','run.started':'开始执行','agent.started':'角色开始','agent.failed':'执行失败','agent.completed':'角色阶段完成','branch.completed':'分析分支完成','join.completed':'两分支已汇合','artifact.created':'产物已保存','review.completed':'审核完成','human.accepted':'你确认了当前版本','run.completed':'任务完成','run.cancelled':'你取消了任务','workflow.transition':'状态更新'};
 $('timeline').innerHTML=run.events.slice().reverse().map(e=>`<div class="event"><time>${esc(new Date(e.occurred_at).toLocaleTimeString('zh-CN',{hour12:false}))}<br>#${e.seq}</time><div>${esc(labels[e.type]||e.type)} ${esc(names[e.payload.agent]||'')} ${esc(stages[e.payload.stage]||'')}<small>${esc(e.payload.run_status?states[e.payload.run_status]:e.payload.decision?({approved:'审核通过，等待确认',revision_required:'发现问题，需要修改',needs_human:'需要补充信息'})[e.payload.decision]:e.payload.message|| (e.payload.mode==='simulation'?'固定模板 / 模拟执行':e.payload.mode==='live'?'真实 AI 执行':'已持久化'))}</small></div></div>`).join('');
}
function renderCalls(){
 if(run.mode!=='live')return;
 const rows=(run.calls||[]).map(c=>'<div class="event"><time>'+esc((c.provider||'历史记录')+' / '+(c.model||'未知模型'))+'</time><div>'+esc(names[c.agent])+' · '+esc(stages[c.stage])+'<small>'+esc(({calling:'请求中 / 中断后先核对用量，不自动重发',received:'已收到响应',validated:'校验通过',invalid:'输出格式校验失败',failed:'请求失败'})[c.status]||c.status)+' · '+(c.tokens===null?'用量未知，已保留预算':c.tokens+' Token')+(c.inherited?' · 沿用原任务计数':'')+(c.error?' · '+esc(c.error):'')+'</small>'+(c.diagnostic_response?'<details><summary>查看被拒绝的模型响应</summary>'+json(c.diagnostic_response)+'</details>':'')+'</div></div>').join('');
 $('timeline').insertAdjacentHTML('afterbegin',rows);
}
async function act(action,payload={}){
 if(action==='next'&&websiteSession?.auth_required)return backgroundCommand('step');
 if(action==='next'&&run?.review_execution?.blocked){error(new Error(run.review_execution.message));return false;}
 if(action==='next'&&run?.mode==='live'&&!confirmLiveBudget(()=>act(action,payload)))return false;
 if(busy||!run)return false;busy=true;clearError();if(action==='next'&&run.mode==='live')run.in_flight=true;render();
 try{run=await api(`/api/runs/${run.run_id}/actions`,'POST',{action,version:run.status_version,key:crypto.randomUUID(),payload});clearError();viewVersion=null;selected=currentAgent();detailStage=null;if(action==='edit'){ops=await api('/api/operations');syncAccounts();}await history();return true;}
 catch(e){auto=false;error(e);try{run=await api('/api/runs/'+run.run_id);}catch(_){}return false;}
 finally{busy=false;render();}
}
async function backgroundCommand(action,extra={}){
 if(busy||!run)return false;
 if(['start','step'].includes(action)&&run.review_execution?.blocked){error(new Error(run.review_execution.message));return false;}
 const searchOnly=action==='step'&&run.current_stage==='brief'&&run.context.web_research?.enabled&&run.context.web_research.status!=='complete';
 if(['start','step'].includes(action)&&!searchOnly&&run.mode==='live'&&!confirmLiveBudget(()=>backgroundCommand(action,extra)))return false;
 let commandError=null;busy=true;clearError();render();
 try{run=action==='pause'?await pauseBackground(run.run_id):await api(`/api/runs/${run.run_id}/background`,'POST',{action,version:run.status_version,key:crypto.randomUUID(),...extra});clearError();selected=currentAgent();detailStage=null;await history();return true;}
 catch(e){commandError=e;error(e);try{run=await api('/api/runs/'+run.run_id);}catch(_){}return false;}
 finally{busy=false;render();if(commandError)error(commandError);}
}
async function pauseBackground(runId){
 // Refresh a moving Worker version only for stopping work, never for paid starts.
 for(let attempt=0;attempt<2;attempt++){
  const latest=await api('/api/runs/'+runId);
  if(!latest.in_flight)return latest;
  try{return await api(`/api/runs/${runId}/background`,'POST',{action:'pause',version:latest.status_version,key:crypto.randomUUID()});}
  catch(e){if(e.code!=='VERSION_CONFLICT'||attempt===1)throw e;}
 }
}
async function autoRun(){
 if(websiteSession?.auth_required)return backgroundCommand(run.in_flight?'pause':'start');
 if(!auto&&run?.review_execution?.blocked){error(new Error(run.review_execution.message));return;}
 if(run?.mode==='live'&&!confirmLiveBudget(()=>autoRun()))return;
 if(auto){auto=false;render();return;}auto=true;render();
 while(auto&&run?.allowed_actions.includes('next')){
  if(!await act('next'))break;
  if(run.review?.decision==='revision_required')break;
  // Yield browser paint; elapsed times remain actual server work, not this presentation pause.
  await new Promise(resolve=>setTimeout(resolve,150));
 }
 auto=false;render();
}
$('briefForm').addEventListener('submit',async e=>{e.preventDefault();if(busy)return;busy=true;clearError();e.submitter.disabled=true;
 try{const accountId=currentAccount()?.id,documentIds=[...$('materialDocumentSelect').selectedOptions].map(o=>o.value);if(documentIds.length>3)throw new Error('本次最多选择 3 份资料');run=await api('/api/runs','POST',{...(websiteSession?.auth_required?{knowledge:{enabled:$('useKnowledge').checked,document_ids:$('useKnowledge').checked?documentIds:[]}}:{}),...($('useWebResearch').checked?{web_research:{enabled:true,queries:[$('webQuery1').value,$('webQuery2').value].map(q=>q.trim()).filter(Boolean)}}:{}),mode:$('mode').value,topic:$('topic').value,audience:$('audience').value,tone:$('tone').value,material:$('material').value,scenario:$('scenario').value,allow_hypothesis:$('hypothesis').checked,operations:{platform:$('targetPlatform').value,account_id:accountId,account:$('accountName').value,trend_id:chosenTrend?.id||null,hypothesis_id:chosenHypothesis?.id||null}});chosenHypothesis=null;selected='audience';detailStage=null;viewVersion=null;editing=false;$('editor').hidden=true;render();await history();}
 catch(err){error(err);}finally{busy=false;e.submitter.disabled=false;if(run&&!$('workbench').hidden)render();}});
$('history').addEventListener('click',async e=>{const b=e.target.closest('[data-run]');if(!b||busy||!dirtyGuard())return;if(historyDeleted){const box=b.getBoundingClientRect();openHistoryMenu(b,box.left,box.bottom);return;}auto=false;editing=false;$('editor').hidden=true;clearError();showPage('studio');try{run=await api('/api/runs/'+b.dataset.run);viewVersion=null;detailStage=null;selected=currentAgent();render();await history();}catch(err){error(err);}});
function startCreation({trend=null,hypothesis=null}={}){
 if(busy||!dirtyGuard())return false;
 creationSequence++;
 showPage('studio');auto=false;editing=false;run=null;viewVersion=null;chosenTrend=trend;chosenHypothesis=hypothesis;window.activeTrialHypothesisId=null;
 $('selectedTrend').hidden=!trend;$('clearTrend').hidden=!trend;
 $('editor').hidden=true;$('workbench').hidden=true;$('welcome').hidden=false;$('topic').value='';$('material').value='';
 $('mode').value=provider?.ready?'live':'simulation';$('mode').onchange();fillAccountBrief();clearError();refreshMaterialDocuments();return true;
}
$('newRun').onclick=()=>startCreation();
$('flow').onclick=e=>{const chip=e.target.closest('[data-stage]');const b=e.target.closest('[data-agent]');if(chip){selected='content';detailStage=chip.dataset.stage;render();}else if(b){selected=b.dataset.agent;detailStage=null;render();}};
$('recover').onclick=()=>act('recover');
$('repairReview').onclick=async()=>{if(await act('repair_review')){clearError();selected='human';render();$('humanPanel').scrollIntoView({behavior:'smooth',block:'center'});toast('已有审核意见已整理。请按提示补充资料或修改稿件；本次没有调用 AI。');}};
$('next').onclick=()=>act('next');$('auto').onclick=autoRun;
$('cancel').onclick=async()=>{
 cancellationRun=run.run_id;$('cancelConfirmation').hidden=false;$('cancelConfirmation').scrollIntoView({behavior:'smooth',block:'center'});
};
$('keepTask').onclick=()=>{$('cancelConfirmation').hidden=true;};
$('confirmCancel').onclick=async()=>{
 $('cancelConfirmation').hidden=true;
 if(run?.run_id!==cancellationRun){error(new Error('当前任务已变化，请重新选择要取消的任务。'));return;}
 auto=false;editing=false;$('editor').hidden=true;
 if(!busy){await act('cancel');return;}
 try{
  const latest=await api('/api/runs/'+run.run_id);
  run=await api('/api/runs/'+latest.run_id+'/actions','POST',{action:'cancel',version:latest.status_version,key:crypto.randomUUID(),payload:{}});
  render();await history();
 }catch(e){error(e);}
};
$('revise').onclick=()=>act('next');
$('editButton').onclick=()=>{auto=false;const c=run.drafts.at(-1).content;$('editTitle').value=c.selected_title;$('editBody').value=c.body;$('editCta').value=c.cta;$('editTags').value=c.tags.join('，');editing=true;$('editor').hidden=false;render();$('editor').scrollIntoView({behavior:'smooth',block:'center'});$('editTitle').focus();};
$('discardEdit').onclick=()=>{editing=false;$('editor').hidden=true;render();};
$('editor').onsubmit=async e=>{e.preventDefault();const data={selected_title:$('editTitle').value,body:$('editBody').value,cta:$('editCta').value,tags:$('editTags').value.split(/[,，]/).map(x=>x.trim()).filter(Boolean)};if(await act('edit',data)){editing=false;$('editor').hidden=true;render();toast('新版本已保存。可以申请复审，也可以知晓问题后人工采用。');}};
$('accept').onclick=async()=>{if(await act('accept',{draft_ref:run.drafts.at(-1).ref,review_ref:run.review.ref}))toast('已确认当前版本，可以下载。');};
$('adoptManual').onclick=async()=>{const draft=run.drafts.at(-1);if(await act('adopt_manual',{draft_ref:draft.ref,content_hash:draft.content_hash,acknowledge:true})){clearError();toast('已人工采用当前版本，审核意见保留，可以下载。');}};
$('supplyForm').onsubmit=async e=>{e.preventDefault();if(await act('supplement',{material:$('supply').value,allow_hypothesis:$('supplyHypothesis').checked}))toast('补充已保存，请启动运行重新分析。');};
$('versionSelect').onchange=e=>{const version=Number(e.target.value);viewVersion=version===run.drafts.length-1?null:version;renderDraft();};
$('compareVersions').onchange=()=>renderDraft();
$('checkReaders').onclick=async()=>{
 if(busy||editing||run?.in_flight||!run?.drafts.length)return;
 const draft=run.drafts[viewVersion??run.drafts.length-1];
 if(draft&&typeof openDraftReaderCheck==='function')await openDraftReaderCheck(run,draft.ref);
};
window.addEventListener('beforeunload',e=>{if(editing){e.preventDefault();e.returnValue='';}});
document.addEventListener('DOMContentLoaded',async()=>{try{const session=await api('/api/session');csrf=session.csrf;if(session.auth_required&&!session.user){showLogin(session);return;}showWebsiteUser(session);provider=session.provider;$('configMessage').textContent=provider.message+' · 执行前可查看用量上限';$('liveOption').disabled=!provider.ready;$('liveOption').textContent=provider.ready?'真实 AI · DeepSeek（消耗接口额度）':'真实 AI · DeepSeek（先填写 .env）';$('connectionStatus').textContent='DeepSeek：'+(provider.ready?'已配置':'未配置');$('mode').value=provider.ready?'live':'simulation';$('scenario').disabled=$('mode').value==='live';renderMode($('mode').value);const rows=await history();if(rows.length){run=rows[0];selected=currentAgent();render();await history();}await initOperations();}catch(e){error(e);}});

const materialFiles=$('materialFiles');
$('useWebResearch').onchange=()=>{if($('useWebResearch').checked&&$('mode').value!=='live'){$('useWebResearch').checked=false;error(new Error('请先选择“真实 AI”运行方式；模拟模式不会联网。'));} $('webResearchFields').hidden=!$('useWebResearch').checked;if($('useWebResearch').checked){const topic=$('topic').value.trim().slice(0,90);if(!$('webQuery1').value)$('webQuery1').value=topic;if(!$('webQuery2').value)$('webQuery2').value=($('targetPlatform').value==='douyin'?'抖音 ':'小红书 ')+topic+' 讨论';}};
const materialDocumentSelect=$('materialDocumentSelect');
if(materialDocumentSelect)materialDocumentSelect.addEventListener('change',()=>{if(materialDocumentSelect.selectedOptions.length>3){[...materialDocumentSelect.options].forEach(o=>{if(!o.selected)return;const before=[...materialDocumentSelect.options].slice(0,o.index).filter(x=>x.selected).length;if(before>=3)o.selected=false;});error(new Error('本次最多选择 3 份资料'));}});
if(materialFiles)materialFiles.addEventListener('change',async()=>{
 const files=[...materialFiles.files];materialFiles.value='';
 if(!websiteSession?.auth_required){error(new Error('请登录后上传账号资料'));return;}
 for(const file of files){
  if(file.size>3000000){error(new Error(`${file.name} 超过 3 MB`));continue;}
  if(!/\.(pdf|docx)$/i.test(file.name)){error(new Error('目前仅支持 PDF 和 DOCX Word 文件'));continue;}
  try{
   const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});
   const doc=await api('/api/knowledge','POST',{account_id:currentAccount()?.id,title:file.name.replace(/\.(pdf|docx)$/i,''),filename:file.name,file_base64:encoded});
   await refreshMaterialDocuments();const option=[...materialDocumentSelect.options].find(o=>o.value===doc.id);if(option){const chosen=[...materialDocumentSelect.selectedOptions];if(chosen.length<3)option.selected=true;else error(new Error('文件已保存；本次最多选 3 份，请先取消一项再选择它。'));}
   $('useKnowledge').checked=true;renderMaterialUploads();toast(`${file.name} 已解析并保存到当前账号资料库；上传未调用 AI。`);
  }catch(err){error(err);}
 }
});

$('mode').onchange=()=>{renderMode($('mode').value);$('scenario').disabled=$('mode').value==='live';};
setInterval(async()=>{
 if(!run?.in_flight||polling)return;
 polling=true;
 try{const latest=await api('/api/runs/'+run.run_id);if(run?.run_id===latest.run_id){const changed=run.status_version!==latest.status_version;run=latest;render();if(changed){if(!run.in_flight){selected=currentAgent();const last=run.node_runs.at(-1);if(last){selected=last.agent;detailStage=last.stage;}render();}await history();}}}
 catch(_){}finally{polling=false;}
},1500);
