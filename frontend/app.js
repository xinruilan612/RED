'use strict';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names={audience:'受众与竞品洞察',research:'热点与证据研究',content:'内容策划创作',reviewer:'主编审核',human:'人工处理 / 确认'};
const stages={analysis:'分析',audience:'受众分析',research:'素材分析',strategy:'策略',outline:'提纲',hook:'开头',title:'标题',body:'正文',revise:'按意见改稿',review:'审核'};
const states={QUEUED:'准备开始',RUNNING:'可以继续执行',WAITING_USER:'等待你的决定',SUCCEEDED:'已确认完成',CANCELLED:'已取消',FAILED:'执行失败',RETRY_WAIT:'等待重试',EXPIRED:'已过期'};
const checks={brief_fit:'符合需求',audience_fit:'受众相关',usefulness_and_readability:'实用与易读',title_body_alignment:'标题与正文一致',evidence_integrity:'证据完整',experience_authenticity:'经历真实',originality_risk:'原创风险',privacy_and_policy:'隐私与规则'};
let provider=null,polling=false,materialDocsCache=[],confirmedLiveRuns=new Set(),materialRefreshes=new Map();
let cancellationRun=null,pendingLiveBudget=null;
let commentNotesLoad=0,commentNotesAccount=null,revisionBinding=null,revisionCommand=null;
let webResearchPreference=null,generatedWebQueries=['',''],editedWebQueries=new Set();
let csrf='',run=null,selected='audience',busy=false,auto=false,editing=false,viewVersion=null,detailStage=null,toastTimer,chosenHypothesis=null;
async function api(path,method='GET',body){
 let r;
 const recovery=method==='GET'?'请检查网络和本地服务，再重试当前操作。':'请检查网络和本地服务；提交结果尚未确认，请先查看列表或任务状态，避免重复提交。';
 const write=method==='POST'||method==='DELETE';
 try{r=await fetch(path,{method,headers:write?{'Content-Type':'application/json','X-CSRF-Token':csrf}:{},body:body===undefined?undefined:JSON.stringify(body)});}
 catch(cause){throw new Error('无法连接服务。'+recovery)}
 let data;try{data=await r.json();}catch(cause){throw new Error('服务未返回可识别的结果。'+recovery)}
 if(!r.ok){
  const code=data.error?.code;
  const hints={AUTH_REQUIRED:'登录已失效。请重新登录后继续。',RATE_LIMITED:'操作过于频繁。请稍等片刻，再重试当前操作。',INTERNAL_ERROR:'服务处理失败。请先查看当前任务或资料是否已保存；若未完成，请稍后重试。若仍失败，请反馈操作步骤和此提示。'};
  const failure=new Error(hints[code]||data.error?.message||('请求未完成。'+recovery));failure.status=r.status;failure.code=code;throw failure;
 }return data;
}
let errorSource=null,errorField=null;
function error(e,source='request'){$('error').textContent=e.message||String(e);$('error').hidden=false;errorSource=source;errorField=e.field||null;}
function clearError(){$('error').hidden=true;errorSource=null;errorField=null;}
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3500);}
function json(value){return '<pre class="json">'+esc(JSON.stringify(value,null,2))+'</pre>';}
function hasUnsavedRevision(){return Boolean($('revisionInstruction')?.value?.trim());}
function dirtyGuard(){
 if(!editing&&!hasUnsavedRevision())return true;
 if(!window.confirm('有尚未保存的编辑或改稿要求，确定放弃吗？'))return false;
 if($('revisionInstruction'))$('revisionInstruction').value='';revisionBinding=null;
 return true;
}
function audienceWebObservations(value){
 return (value.observations||[]).map(o=>{const source=(run.context.evidence||[]).find(s=>s.source_id===o.source_id);return `<article class="source-card"><h3>有原文依据的观察</h3><blockquote>${esc(o.quote)}</blockquote><p>${esc(o.interpretation)}</p>${source?.url?`<a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.title||'查看来源')}</a>`:''}</article>`;}).join('');
}
function renderWebResearch(){
 const host=$('webResearchReport'),web=run.context.web_research||{};host.hidden=!web.enabled;if(!web.enabled)return;
 // Background polling must not close evidence or erase a query being edited.
 const retryForm=host.querySelector?.('#retryWebResearch');
 if(!run.in_flight&&typeof document!=='undefined'&&retryForm?.contains(document.activeElement))return;
 const detailState=new Map(Array.from(host.querySelectorAll?.('details[data-research-key]')||[]).map(d=>[d.dataset.researchKey,d.open]));
 const labels={pending:'等待启动联网调查',searching:'正在搜索并读取网页',complete:'已读取公开来源',insufficient:'没有足够的相关正文，未调用模型'};
 if(web.reused_sources)labels.complete='已恢复本任务此前读到的正文';
 // 两组搜索词命中同一批链接时只渲染一次，避免整段重复；已读正文默认收起，展开前不占屏。
 const seenResults=new Set(),searches=[];
 for(const search of (web.searches||[])){
  const results=(search.results||[]).filter((r,i,list)=>list.findIndex(x=>x.url===r.url)===i);
  const key=results.map(r=>r.url).sort().join('\n');
  if(key&&seenResults.has(key))continue;
  if(key)seenResults.add(key);
  searches.push({search,results});
 }
 const searchesHTML=searches.map(({search,results})=>`<details data-research-key="search:${esc(search.query)}"><summary>${esc(search.query)} · ${results.length} 条搜索线索</summary>${search.effective_query?`<p class="helper">实际搜索词：${esc(search.effective_query)} · ${esc(search.provider||'公开搜索')}</p>`:''}${search.error?`<p class="issue">${esc(search.error)}</p>`:''}${results.map(r=>`<p><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}</a> · 搜索摘要，未代表已读正文</p>`).join('')}</details>`).join('');
 const sourcesHTML=(web.sources||[]).map(s=>`<details class="source-card" data-research-key="source:${esc(s.url)}"><summary>${esc(s.title)}<span class="helper">读取时间：${esc(s.fetched_at)} · 页面声明发布时间：${esc(s.published_at||'未知')} · 平台热度：未知</span></summary><p><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">打开原文 ↗</a></p><blockquote>${esc(s.text)}</blockquote></details>`).join('');
 const failedReads=(web.reads||[]).filter(r=>r.error||r.status==='failed');
 const recoveryHTML=(web.reads||[]).some(r=>r.status==='skipped')?'<p class="helper">同一站点拒绝读取后，已跳过该站其他链接，保留读取名额查找其他来源。403 表示网站拒绝程序访问；未采用的链接不会进入创作证据。</p>':'';
 const failuresHTML=failedReads.length?`<details class="research-failures" data-research-key="failures"${web.sources?.length?'':' open'}><summary>${web.sources?.length?'另有':'本次'} ${failedReads.length} 条候选未采用（访问受限或不匹配）</summary>${failedReads.map(r=>`<p class="issue"><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.url)}</a>：${esc(r.error||'未取得可用正文')}</p>`).join('')}</details>`:'';
 host.innerHTML=`<h2>本次联网调查 · ${esc(labels[web.status]||'调查未完成')}</h2>${web.reused_sources?'<p class="helper">本次搜索没有新增正文；下面复用的是这条任务此前的实际读取记录，原读取时间保留。恢复资料本身不调用模型。</p>':''}<p class="helper">公开网页线索，不等于平台热榜或已核实事实。搜索和网页读取有次数上限；此步骤不调用模型。</p><p>搜索词：${esc((web.queries||[]).join('；'))}</p>${searchesHTML}${sourcesHTML?`<p class="helper">以下 ${web.sources.length} 份正文默认收起，点标题展开。</p>${sourcesHTML}`:''}${recoveryHTML}${failuresHTML}${web.status==='insufficient'?'<p>本次没有读到足够正文，因此未调用模型。可在下面修改关键词，留在这个任务重新搜索。</p>':''}`;
 const canRefreshReferences=web.status==='complete'&&/https?:\/\//.test(run.context.material||'')&&!run.artifacts?.length&&!run.node_runs?.length&&!Object.keys(run.branches||{}).length;
 if((['insufficient','searching'].includes(web.status)||canRefreshReferences)&&!run.in_flight&&run.current_stage==='brief'){
  const form=`<form id="retryWebResearch"><p class="helper">优先读取本次参考资料中的公开链接，再用搜索补充；保留此前调查记录。${web.provider==='baidu'?'重新搜索会使用已配置的百度服务，可能计费；可选择仅重读链接。':''}</p><label for="retryQuery1">调整搜索词（用核心词，如：新手 护肤 顺序）</label><input id="retryQuery1" required minlength="2" maxlength="120" value="${esc(web.queries?.[0]||'')}"><label for="retryQuery2">第二组关键词（可选）</label><input id="retryQuery2" maxlength="120" value="${esc(web.queries?.[1]||'')}">${/https?:\/\//.test(run.context.material||'')?'<label><input id="retryReferencesOnly" type="checkbox" checked>仅重新读取参考链接（不搜索、不调用模型）</label>':''}<button class="primary" type="submit">更新本次调查（不调用模型）</button></form>`;
  host.insertAdjacentHTML('beforeend',canRefreshReferences?`<details data-research-key="refresh"><summary>重新读取参考链接或调整搜索</summary>${form}</details>`:form);
  $('retryWebResearch').onsubmit=async e=>{e.preventDefault();await backgroundCommand('retry_research',{queries:[$('retryQuery1').value,$('retryQuery2').value].map(q=>q.trim()).filter(Boolean),...($('retryReferencesOnly')?.checked?{references_only:true}:{})});};
 }
 for(const details of (host.querySelectorAll?.('details[data-research-key]')||[])){
  if(detailState.has(details.dataset.researchKey))details.open=detailState.get(details.dataset.researchKey);
 }
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
function resetCommentSelection(){
 commentNotesLoad++;commentNotesAccount=null;
 if(!$('useCommentFeedback'))return;
 $('useCommentFeedback').checked=false;$('commentFeedbackFields').hidden=true;$('commentNoteSelect').innerHTML='';
}
async function refreshCommentNotes(){
 const account=currentAccount()?.id,token=++commentNotesLoad,select=$('commentNoteSelect');
 if(!account)return;
 const selected=commentNotesAccount===account?new Set([...select.selectedOptions].map(o=>o.value)):new Set();
 commentNotesAccount=null;select.innerHTML='';$('commentFeedbackStatus').textContent='正在读取已核实的公开笔记…';
 try{
  const notes=await api('/api/social/sync/notes?account_id='+encodeURIComponent(account));
  if(token!==commentNotesLoad||currentAccount()?.id!==account||!$('useCommentFeedback').checked)return;
  const visible=notes.filter(n=>n.visibility==='public');
  select.innerHTML=visible.map(n=>`<option value="${esc(n.id)}" ${selected.has(n.id)?'selected':''}>${esc(n.title||n.id)} · ${esc(n.id)}</option>`).join('');
  commentNotesAccount=account;$('commentFeedbackStatus').textContent=visible.length?'最多选 3 篇。创建任务时冻结已取得的部分评论；后续同步不会改写这次输入。':'暂无已核实的公开笔记；请检查账号连接，或关闭评论参考后继续。';
 }catch(e){if(token===commentNotesLoad&&currentAccount()?.id===account)$('commentFeedbackStatus').textContent='读取失败，可点击刷新重试、检查账号连接，或关闭评论参考继续。';}
}
function commentFeedbackRequest(){
 if(!$('useCommentFeedback')?.checked)return {enabled:false};
 const ids=[...$('commentNoteSelect').selectedOptions].map(o=>o.value);
 if(commentNotesAccount!==currentAccount()?.id||!ids.length||ids.length>3)throw new Error('请选 1 至 3 篇当前账号的公开笔记，或关闭评论参考。');
 return {enabled:true,note_ids:ids};
}
function revisionTargetsLatest(){return viewVersion===null||viewVersion===run?.drafts.length-1;}
function revisionRequestStatus(request){
 if(request.status!=='applied')return ({pending:'已保存，等待执行',superseded_by_edit:'已由手动编辑替代',superseded_by_material:'已因补料失效'})[request.status]||request.status;
 const draft=(run.drafts||[]).find(d=>d.ref===request.result_draft_ref);
 if(!draft)return '已生成新版本，仍需完整复审';
 if(run.accepted_ref===draft.ref)return run.acceptance?.mode==='manual_override'?'已生成新版本，已由你人工采用（不表示 AI 审核通过）':'已生成新版本，已由你确认';
 const review=[run.prior_review,...(run.reviews||[]),run.review].filter(r=>r&&draft.snapshot_id&&r.draft_ref===draft.ref&&r.snapshot_id===draft.snapshot_id&&(!r.content_hash||r.content_hash===draft.content_hash)).at(-1);
 return ({approved:'已生成新版本，复审通过，等待你确认',revision_required:'已生成新版本，复审发现问题，请按意见修改',needs_human:'已生成新版本，复审存在待确认信息'})[review?.decision]||'已生成新版本，仍需完整复审';
}
function renderFeedbackAndRevision(){
 const feedback=run.context.comment_feedback,host=$('commentFeedbackSummary');
 if(host){host.hidden=!feedback?.enabled;if(feedback?.enabled)host.innerHTML=`<h2>本次评论参考</h2><p>${esc(feedback.limitation)}</p><p>已冻结 ${esc(feedback.sample_size)} 条样本 · ${esc(feedback.frozen_at)}</p>${(feedback.notes||[]).map(n=>`<p>${esc(n.title||n.note_id)} · 笔记 ID：${esc(n.note_id)}</p>`).join('')}`;}
 const panel=$('revisionConversation');if(!panel)return;
 const requests=run.context.revision_requests||[],allowed=run.allowed_actions.includes('request_revision')&&!run.in_flight,viewingHistory=!revisionTargetsLatest();
 panel.hidden=!(allowed||requests.length);$('revisionRequestForm').hidden=!allowed||viewingHistory;
 $('revisionConversationHistory').innerHTML=(allowed&&viewingHistory?'<p role="status" class="helper">正在查看历史稿件，不能把这版要求自动套用到最新稿。请在“查看版本”中选择最新版本，阅读后再提交改稿要求。</p>':'')+requests.map(r=>`<p><b>你的要求：</b>${esc(r.instruction)}</p><p class="helper">针对 ${esc(r.draft_ref)} · ${esc(revisionRequestStatus(r))}</p>`).join('');
 if(revisionBinding?.runId!==run.run_id){revisionBinding=null;$('revisionInstruction').value='';}
}
function liveBudgetKey(task){return JSON.stringify([task.run_id,task.snapshot_id,task.model_policy||task.context?.model_policy||null]);}
function confirmLiveBudget(resume,scope=''){
 if(!run||run.mode!=='live'||!provider)return true;
 // One cost confirmation per creation snapshot. Scope changes (step/revise)
 // must not re-show the same warning for every call in the same run.
 const confirmationKey=liveBudgetKey(run)+(scope.startsWith('research_and_regenerate')?':'+scope:'');
 if(confirmedLiveRuns.has(confirmationKey))return true;
 const frozen=Object.values(run.model_policy?.routes||run.context?.model_policy?.routes||{})[0]||provider;
 const calls=provider.run_attempts_max??16,tokens=provider.run_tokens_max??80000,runUsd=frozen.run_budget_usd??0.10,dayUsd=frozen.day_budget_usd??0.50;
 const experiment=run.testing_budget;
 const experimentNotice=experiment?`本轮参考预算：¥${Number(experiment.target_cny).toFixed(2)}，希望约写 ${experiment.target_runs} 轮；已计入约¥${Number(experiment.spent_cny).toFixed(4)}，已进行 ${experiment.run_count} 轮（包含未完成任务）。\n接近或超过参考预算会提示，不因金额或轮数超出而停止。${experiment.warning||''}\n\n`:'';
 pendingLiveBudget={runId:run.run_id,snapshotId:run.snapshot_id,budgetKey:liveBudgetKey(run),confirmationKey,scope,statusVersion:run.status_version,resume};
 $('liveBudgetMessage').textContent=`即将调用真实模型，可能产生费用。\n\n${experimentNotice}\n本任务硬上限：最多 ${calls} 次调用、${tokens.toLocaleString()} Token、$${Number(runUsd).toFixed(2)}；今日累计上限 $${Number(dayUsd).toFixed(2)}。\n按本次冻结分类读取通用方法、匹配样例与独立事实；实际材料可在稿件依据中查看；达到任一上限会由服务器停止，不自动重试。`;
 $('liveBudgetConfirmation').hidden=false;$('liveBudgetConfirmation').scrollIntoView({behavior:'smooth',block:'center'});
 return false;
}
$('declineLiveBudget').onclick=()=>{pendingLiveBudget=null;$('liveBudgetConfirmation').hidden=true;};
$('approveLiveBudget').onclick=async()=>{
 const pending=pendingLiveBudget;pendingLiveBudget=null;$('liveBudgetConfirmation').hidden=true;
 if(!pending)return;
 if(busy||run?.run_id!==pending.runId||run.snapshot_id!==pending.snapshotId||liveBudgetKey(run)!==pending.budgetKey||(pending.scope&&run.status_version!==pending.statusVersion)){error(new Error('任务或素材已变化，请重新确认费用。'));return;}
 confirmedLiveRuns.add(pending.confirmationKey||pending.budgetKey);if(typeof pending.resume==='function')await pending.resume();
};
async function history(){
 const rows=(await api('/api/runs')).filter(r=>r.workflow_type!=='windtunnel'&&(typeof matchesAccount!=='function'||matchesAccount(r)));
 $('history').innerHTML=rows.length?rows.map(r=>`<button data-run="${esc(r.run_id)}" class="${run?.run_id===r.run_id?'selected':''}">${esc(r.context.topic||'旧任务')}<small>${esc(states[r.run_status])} · ${r.drafts.length} 个版本</small></button>`).join(''):'<p class="helper">还没有创作记录</p>';
 return rows;
}
let contextRunId=null;
function hideRunMenu(){const m=$('runContextMenu');if(m)m.hidden=true;contextRunId=null;}
document.addEventListener('contextmenu',e=>{
 const target=e.target.closest('[data-run],[data-wt="open"][data-id]');
 if(!target)return;
 e.preventDefault();
 contextRunId=target.dataset.run||target.dataset.id;
 const menu=$('runContextMenu');if(!menu)return;
 menu.hidden=false;
 const x=Math.min(e.clientX,window.innerWidth-220),y=Math.min(e.clientY,window.innerHeight-90);
 menu.style.left=Math.max(8,x)+'px';menu.style.top=Math.max(8,y)+'px';
});
document.addEventListener('click',e=>{if(!e.target.closest('#runContextMenu'))hideRunMenu();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')hideRunMenu();});
document.addEventListener('scroll',hideRunMenu,{passive:true});
$('runContextMenu').addEventListener('click',async e=>{
 const item=e.target.closest('[data-run-action="delete"]');if(!item||!contextRunId)return;
 const id=contextRunId;
 hideRunMenu();
 if(!window.confirm('删除这条记录？\n\n删除后不可恢复。稿件、检查记录和运行记录都会删除；模型计费审计保留。'))return;
 try{
  await api('/api/runs/'+id,'DELETE');
  if(run?.run_id===id){run=null;selected='audience';viewVersion=null;editing=false;$('editor').hidden=true;$('workbench').hidden=true;$('welcome').hidden=false;}
  await history();
  if(typeof wt!=='undefined'){wt.run=null;wt.form=null;if(typeof renderWindtunnel==='function'&&currentPage==='windtunnel')await renderWindtunnel();}
  toast('已删除，不可恢复。');
 }catch(err){error(err);}
});
function currentAgent(){if(!run)return 'audience';if(run.run_status==='WAITING_USER'||run.run_status==='SUCCEEDED'||(!run.in_flight&&run.review?.decision==='revision_required'&&run.allowed_actions.includes('edit')))return 'human';if(run.current_stage==='brief')return 'audience';return run.current_stage;}
const creationStageLabels={strategy:'策略',outline:'提纲',hook:'开头',title:'标题',body:'正文',review:'审核'};
function nextCreationStage(task){
 if(!task||task.current_stage==='reviewer')return 'review';
 const done=new Set((task.artifacts||[]).map(a=>a.stage));
 return ['strategy','outline','hook','title','body'].find(stage=>!done.has(stage))||'review';
}
function renderTestingBudget(){
 const warning=run?.testing_budget?.warning,host=$('testingBudget');
 host.hidden=!warning;host.textContent=warning?`预算提醒：${warning}`:'';
}

function renderMode(mode){
 const live=mode==='live';
 const frozen=Object.values(run?.model_policy?.routes||{})[0];
 const modelName=frozen?.model||provider?.model||'所选模型';
 $('modeBadge').textContent=live?'真实 AI · '+modelName:'模拟运行';
 $('modeNotice').textContent=live?'四个角色调用所选模型；每次输出与用量可查看。可结合账号资料与已读取来源；事实仍需核查，最终由你确认。':'这是免费模拟流程，使用固定模板和本地规则，没有调用真实 AI。';
 $('detailMode').textContent=live?'真实 AI 产物':'模拟产物';
}
function canResearchAndRegenerate(task){return task.mode==='live'&&task.workflow_type!=='windtunnel'&&['WAITING_USER','RUNNING'].includes(task.run_status)&&!task.in_flight&&!['queued','running','pausing'].includes(task.background?.status)&&((task.drafts||[]).length>0||availableMaterialContinuation(task));}
function algorithmQuestions(task){
 const state=task?.context?.algorithm_state;
 if(task?.workflow_type==='windtunnel'||task?.run_status!=='WAITING_USER'||task?.wait_reason!=='missing_material'||(state?.snapshot_id&&state.snapshot_id!==task.snapshot_id))return [];
 return Array.isArray(state?.gap_ranking?.questions)?state.gap_ranking.questions.filter(q=>q&&typeof q.question==='string'&&q.question.trim()):[];
}
function algorithmOptionsRequest(){
 const enabled=$('useCreationAlgorithms')?.checked!==false;
 return {enabled,ask_questions:enabled&&!!$('askMaterialQuestions')?.checked};
}
function algorithmPlanHTML(task){
 const state=task?.context?.algorithm_state;
 if(!state||typeof state!=='object')return '';
 if(state.snapshot_id&&state.snapshot_id!==task.snapshot_id)return '<p class="helper">这份规划属于旧输入；当前输入的规划尚未生成。</p>';
 const rows=value=>Array.isArray(value)?value:[];
 const text=value=>typeof value==='string'||typeof value==='number'?String(value):'';
 const planning=state.planning||{},structure=state.structure||{};
 const fields={firsthand_record:'亲测记录',use_steps:'使用步骤',comparison_specs:'对比参数',product_specs:'产品参数',user_need:'用户需求',limitations:'使用限制'};
 const fieldLabel=value=>fields[text(value)]||(/[\u3400-\u9fff]/.test(text(value))?text(value):'对应资料');
 const requirements=new Map(rows(planning.requirements).filter(r=>r&&typeof r==='object').map(r=>[text(r.id),text(r.question)]));
 const modules=rows(planning.selected_modules).filter(m=>m&&typeof m==='object').map(m=>{
  const answers=rows(m.covers).map(id=>requirements.get(text(id))||(!/^r\d+$/.test(text(id))?text(id):'')).filter(Boolean);
  return `<li><b>${esc(text(m.title)||'内容模块')}</b>${m.length?` · 预计 ${esc(text(m.length))} 字`:''}${answers.length?`<p class="helper">计划回答：${esc(answers.join('、'))}</p>`:''}${rows(m.source_ids).length?`<p class="helper">有 ${rows(m.source_ids).length} 份资料依据</p>`:''}</li>`;
 }).join('');
 const slots=rows(structure.slots).filter(slot=>slot&&typeof slot==='object').map(slot=>`<li>${esc(text(slot.function)||'段落安排')}${rows(slot.needs).length?`<span class="helper"> · 需要：${esc(slot.needs.map(fieldLabel).join('、'))}</span>`:''}</li>`).join('');
 const adaptations=rows(structure.adaptations).map(a=>{
  if(typeof a==='string')return `<li>${esc(a)}</li>`;
  if(!a||typeof a!=='object')return '';
  const missing=rows(a.missing_fields).map(fieldLabel);
  const reason=text(a.reason)||'调整为待核对事项，并缩小表达范围。';
  return `<li>${missing.length?'缺少'+esc(missing.join('、'))+'。':''}${esc(reason)}</li>`;
 }).join('');
 const coverage=Number(planning.weighted_coverage);
 return `<p class="helper">${(task.mode||task.context?.mode)==='simulation'?'本地规则规划 · 当前为模拟运行，正文采用固定模板。':'本地规则规划 · 正文由选定模型生成。'}计划不等于正文已覆盖，最终仍需检查稿件与审核记录。</p><h4>优先写什么</h4>${state.active_modules?.coverage===false?'<p class="helper">本任务未启用需求覆盖优化。</p>':`${modules?`<ol>${modules}</ol>`:'<p class="helper">尚无可用内容规划。</p>'}${typeof planning.weighted_coverage==='number'&&Number.isFinite(coverage)?`<p class="helper">计划加权覆盖度：${esc((coverage*100).toFixed(1))}%（规划指标）</p>`:''}`}<h4>怎样组织文章</h4>${state.active_modules?.structure===false?'<p class="helper">本任务未启用篇章结构迁移。</p>':`${slots?`<ol>${slots}</ol>`:'<p class="helper">尚无可用结构。</p>'}${structure.fallback?'<p class="helper">采用通用结构；当前没有适用的参考结构。</p>':''}${adaptations?`<p>根据现有资料调整：</p><ul>${adaptations}</ul>`:''}`}<details><summary>查看本次规划记录</summary>${json(state)}</details>`;
}
function renderAlgorithmPlan(){
 const host=$('algorithmPlan'),details=$('algorithmPlanDetails');if(!host||!details)return;
 const html=algorithmPlanHTML(run);details.hidden=!html;host.innerHTML=html;
}
function availableMaterialContinuation(task){return task.workflow_type!=='windtunnel'&&task.run_status==='WAITING_USER'&&['missing_material','hypothesis_permission'].includes(task.wait_reason)&&!algorithmQuestions(task).length;}
function nextStepGuidance(task){
 const allowed=task.allowed_actions||[];
 if(task.run_status==='SUCCEEDED')return '稿件已确认，可以下载。如需发布，请另行确认账号与稿件；确认创作不等于发布成功。';
 if(editing&&task.review_execution?.exhausted)return '保存会创建新版本，不调用 AI。但本任务复审次数已用完，保存后只能继续手动修改，或知晓问题后人工采用；旧审核不会变成新版本通过。';
 if(editing)return '你正在修改稿件。保存会创建新版本，不调用 AI；之后可申请复审，或知晓问题后人工采用。';
 if(task.in_flight)return '正在处理，结果会自动保存并更新。可以先阅读已有稿件；无需重复点击或刷新。';
 if(task.review_execution?.blocked)return task.review_execution.message;
 if(algorithmQuestions(task).length)return '可以一次补充下方关键问题，也可跳过。跳过后按现有资料继续，缺失事实不会编造。';
 if(availableMaterialContinuation(task))return '点击“按现有资料继续生成”，直接使用已有资料完成稿件。缺失事实不会编造，没有历史数据时不推测个人受众画像。';
 if(task.current_stage==='reviewer'&&task.drafts.length&&!task.review)return '新版本已保存，尚未完成复审。点击“复审当前版本”查看审核意见；真实 AI 复审会计入费用。';
 if(task.review?.decision==='revision_required')return '先看下方具体问题，再手动修改或按意见改稿。改稿后仍需重新审核。';
 if(allowed.includes('accept'))return '先检查正文和事实，再确认当前版本。需要修改时另存新版本，原审核不沿用。';
 if(allowed.includes('adopt_manual'))return '当前版本尚未通过有效审核。可继续修改/复审，或明确知晓已有问题后人工采用。';
 if(task.run_status==='FAILED')return '本次执行失败，已有稿件和记录保留。先看具体错误，再决定是否从失败步骤继续，不必新建重复任务。';
 if(['CANCELLED','EXPIRED'].includes(task.run_status))return '本任务已停止，旧版本仍可查看。需要继续创作时新建一份需求。';
 return '需求已保存。点“连续运行”连续生成并审核，最后确认稿件；想逐步了解过程，可点“执行下一步”。过程和来源在下方按需展开。';
}
function render(){
 if(!run)return;
 if(errorSource==='run')clearError();
 renderWebResearch();
 renderMode(run.mode);
 renderTestingBudget();
 renderAlgorithmPlan();
 renderFeedbackAndRevision();
 if($('workbenchGuide'))$('workbenchGuide').textContent=nextStepGuidance(run);
 $('modelCalls').textContent=(run.usage?.model_calls||0)+' 次';
 $('modelCost').innerHTML=run.mode==='live'?'≤ $'+Number(run.usage.cost_upper_estimate_usd||0).toFixed(4)+' <small>估算</small>':'¥0.00 <small>模拟</small>';
 if(run.run_status==='FAILED'){const last=run.events.filter(e=>e.type==='agent.failed').at(-1);error(new Error(last?.payload.message||'执行失败，请查看运行记录'),'run');}
 $('welcome').hidden=true;$('workbench').hidden=false;
 $('runTitle').textContent=run.context.topic;
 if($('creationReport'))$('creationReport').innerHTML=creationReferenceHTML(run.context);
 $('runSummary').textContent=`${run.context.operations?.platform==='douyin'?'抖音':'小红书'} · ${({note:'图文笔记',video_script:'短视频口播',product_detail:'商品详情'})[run.context.creation_classification?.format]||'图文笔记'} · 写给 ${run.context.audience} · ${run.context.tone} · ${run.snapshot_id.slice(0,8)} 输入快照`;
 const background=run.background;
 const jobLabels={queued:background?.worker_online?'已排队，后台即将执行':'已排队，等待 Worker 启动',running:'正在执行 · 结果保存后自动更新',pausing:'正在暂停，等待当前节点保存',paused:'本步已停止 · 查看结果后继续',blocked:'后台等待处理',waiting:'等待你的审核'};
 const nextStage=nextCreationStage(run);
 let statusText=jobLabels[background?.status]|| (run.in_flight?'AI 正在处理，请稍候':states[run.run_status]);
 const paused=background?.status==='paused'&&!run.in_flight;
 if(paused&&!availableMaterialContinuation(run)&&!['insufficient','searching'].includes(run.context.web_research?.status))statusText=`本步已停止 · 下一步：${creationStageLabels[nextStage]||'审核'}；点“执行下一步”继续`;
 $('statusLabel').textContent=statusText;
 if(background?.error)error(new Error(['insufficient','searching'].includes(run.context.web_research?.status)?'联网调查未完成。请在上方修改关键词，点击“重新搜索这一步”；无需新建任务。':background.error),'run');$('versionCount').textContent=run.drafts.length+' 个';
 const allowed=run.allowed_actions;
 if($('researchAndRegenerate')){$('researchAndRegenerate').hidden=!canResearchAndRegenerate(run);$('researchAndRegenerate').disabled=busy||editing;}
 $('recover').hidden=!allowed.includes('recover');$('next').hidden=!allowed.includes('next');$('auto').hidden=!allowed.includes('next');$('cancel').hidden=!allowed.includes('cancel');
 $('next').textContent=run.current_stage==='reviewer'?'执行复审 / 审核 →':run.review?.decision==='revision_required'?'按意见改稿 →':'执行下一步 →';
 $('auto').textContent=background?(run.in_flight?'暂停后台任务':'后台运行到人工处理'):(auto?'停止自动运行':'自动运行到人工处理');
 if(background){$('next').hidden=!allowed.includes('next')||run.in_flight;$('auto').hidden=!allowed.includes('next')&&!run.in_flight;$('auto').textContent=run.in_flight?'暂停执行':'连续运行到人工处理';$('next').textContent=run.current_stage==='brief'&&run.context.web_research?.enabled&&run.context.web_research.status!=='complete'?'执行一步：联网搜索 →':run.current_stage==='reviewer'?'复审当前版本 →':`执行下一步：${creationStageLabels[nextStage]||'审核'} →`;}
 if(availableMaterialContinuation(run)&&!run.in_flight){$('next').hidden=true;$('auto').hidden=false;$('auto').textContent='按现有资料继续生成';$('statusLabel').textContent='可按现有资料继续生成';}
 if(['insufficient','searching'].includes(run.context.web_research?.status)&&!run.in_flight&&!availableMaterialContinuation(run)){$('next').hidden=true;$('auto').hidden=true;}
 if(algorithmQuestions(run).length&&!run.in_flight){$('next').hidden=true;$('auto').hidden=true;$('statusLabel').textContent='可补充关键资料或跳过';}
 if(paused&&run.node_runs.length&&!run.drafts.length&&$('processDetails'))$('processDetails').open=true;
 const node=(key,num,sub)=>{
 const logs=run.node_runs.filter(n=>n.agent===key&&n.snapshot_id===run.snapshot_id);
 const isCurrent=(key===currentAgent()||(run.current_stage==='brief'&&key==='research'&&run.run_status!=='WAITING_USER'))&&!['SUCCEEDED','CANCELLED','FAILED'].includes(run.run_status);
 const done=key==='human'?run.run_status==='SUCCEEDED':logs.length>0;
 const human=key==='human'&&(run.run_status==='WAITING_USER'||(!run.in_flight&&run.review?.decision==='revision_required'&&run.allowed_actions.includes('edit')));
 const label=human?'◈ 等你处理':isCurrent?'◉ 当前步骤':done?'✓ 已有产物':'○ 尚未执行';
 return `<button class="node ${isCurrent?'current':''} ${done?'done':''} ${human?'human':''} ${selected===key?'selected':''}" data-agent="${key}" aria-pressed="${selected===key}"><span class="node-top"><span>${key==='human'?'由你决定':'AGENT '+num}</span><span>${label}</span></span><b>${names[key]}</b><small>${sub}</small></button>`;
 };
 const contentStages=['strategy','outline','hook','title','body'].map(s=>`<button class="stage-chip ${run.artifacts.some(a=>a.stage===s)?'done':''}" data-stage="${s}">${stages[s]}</button>`).join('');
 $('flow').innerHTML=`<div class="parallel">${node('audience','01','理解需求 · 按已有信息')}${node('research','02','收录素材 · 标记缺口')}</div><div class="connector">同一份需求 · 并行分析<span>↓ 汇合 ↓</span></div>${node('content','03','策略与写作 · 同一角色负责返修')}<div class="stages">${contentStages}</div><div class="connector"><span>↓</span></div>${node('reviewer','04','问题定位 · 修改建议 · 再次审核')}<div class="connector">审核意见保留 ↓ 最后由你决定</div>${node('human','YOU','改稿 / 比较版本 / 最后确认')}`;
 renderDetails();renderHuman();renderRecovery();renderDraft();renderTimeline();renderCalls();
 document.querySelectorAll('#workbench button').forEach(b=>{if(!b.closest('#flow')&&b.id!=='auto')b.disabled=busy||(b.dataset.titleChoice!==undefined&&run.artifacts.find(a=>a.stage==='title')?.value.candidates[Number(b.dataset.titleChoice)]===run.drafts.at(-1)?.content.selected_title);});
 $('cancel').disabled=busy&&!run.in_flight;$('reviewConfirmUnavailable').disabled=true;$('confirmationPending').disabled=true;
 if(background&&run.in_flight){for(const id of ['editButton','accept','adoptManual','revise','recover'])$(id).disabled=true;}
 if(editing){$('next').disabled=true;$('auto').disabled=true;$('accept').disabled=true;$('adoptManual').disabled=true;$('revise').disabled=true;$('editButton').disabled=true;if($('researchAndRegenerate'))$('researchAndRegenerate').disabled=true;}
 else $('auto').disabled=busy&&!auto;
}
function friendly(agent,stage,value){
 const p=text=>'<p class="readable">'+esc(text)+'</p>';
 const list=items=>'<ol class="readable">'+items.map(t=>'<li>'+esc(t)+'</li>').join('')+'</ol>';
 if(agent==='audience')return p('目标读者：'+value.primary_audience)+p('可用历史作品：'+(value.sample_size||0)+' 条 · 可信程度：低（待验证）')+p(value.basis)+list(value.content_opportunities||[])+audienceWebObservations(value)+(value.competitor_observations?.length?'<h3>同类账号观察 · 用户记录</h3>'+list(value.competitor_observations.map(c=>c.name+'：'+c.observation)):'');
 if(agent==='research')return (value.topic_card?'<h3>结构化选题卡</h3>'+p('为什么现在：'+value.topic_card.why_now)+p('账号关联：'+value.topic_card.account_fit)+list(value.topic_card.content_angles):'')+p(value.scope)+(value.trend_context?p('选题线索：'+value.trend_context.title)+p(value.trend_context.source_type==='example'?'固定示例，不是实时热点':'来源链接仅保存，未抓取页面：'+value.trend_context.source_url):'')+(value.sources.length?value.sources.map(source=>'<h3>'+esc(source.title||'用户提供的素材')+'</h3>'+p(source.page?'第 '+source.page+' 页 · 资料版本 '+source.version:'本次输入')+p(source.text)+p(source.verification)+(source.url?'<a href="'+esc(source.url)+'" target="_blank" rel="noopener noreferrer">查看来源 ↗</a>':'')).join(''):p('没有可用素材，不能虚构经历或效果数字。'))+list(value.gaps||[]);
 if(agent==='reviewer')return p(({approved:'审核通过，等待你确认',revision_required:'发现问题，需要修改',needs_human:'审核有待确认信息'})[value.decision])+list(value.limitations||[]);
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
 $('details').innerHTML=`${selected==='content'&&run.drafts.length>1?'<p class="editor-note">这些是生成时保存的阶段记录。最新修改后的稿件，请查看下方“文案与版本对比”。</p>':''}<p class="muted">最近阶段：${esc(stages[current.stage])} · ${current.duration_ms} ms · 真实模型调用 ${current.model_calls||0} 次 · ${current.tokens??'未知'} Token</p><div class="detail-block"><h3>当前产物</h3>${friendly(current.agent,current.stage,current.output)}<details><summary>查看原始结构化记录</summary>${json(current.output)}</details></div><details><summary>查看这一阶段的输入</summary>${json(current.input)}</details><div class="detail-block"><h3>工具与记忆</h3><p>${run.context.evidence?.length?'已使用资料检索快照，来源与片段可在本阶段输入中查看。':'本次未使用检索片段。'}${esc(current.memory)}</p><p>${run.mode==='live'?'由本任务选定的模型生成；审核不代表外部事实已核实。':'采用固定模板 / 本地规则，未使用模型推理。'}</p></div>${logs.length>1?'<details><summary>所有阶段与历史记录（'+logs.length+'）</summary>'+logs.map(l=>'<h3>'+esc(stages[l.stage])+' · '+esc(l.snapshot_id.slice(0,8))+'</h3>'+friendly(l.agent,l.stage,l.output)).join('')+'</details>':''}${previousHistory}`;
 if(selected==='reviewer'&&run.review){$('details').insertAdjacentHTML('afterbegin',run.review.checks.map(c=>`<div class="review-check"><span>${esc(checks[c.name])}</span><span class="${esc(c.result)}">${c.result==='pass'?(run.mode==='live'?'模型判断通过':'模拟通过'):c.result==='fail'?'发现问题':'未完成'}</span></div>`).join(''));}
}
function reviewIssues(value){return Array.isArray(value)?value.filter(i=>i&&typeof i==='object'&&!Array.isArray(i)).map(i=>Object.fromEntries(['issue_id','severity','state','location','excerpt','reason','suggestion'].map(k=>[k,typeof i[k]==='string'?i[k]:'']))):[];}
function reviewQuestions(value){return Array.isArray(value)?value.filter(q=>typeof q==='string'):[];}
function issueGroup(list,label,cls){return list.length?`<h3 class="issue-group ${cls}">${label} · ${list.length} 项</h3>`+list.map(i=>`<div class="issue ${cls}"><b>${esc(({selected_title:'标题',body:'正文',cta:'互动引导',tags:'标签'})[i.location]||i.location)} · ${esc(i.excerpt)}</b><p>${esc(i.reason)}</p><p>修改建议：${esc(i.suggestion)}</p></div>`).join(''):'';}
function renderRecovery(){
 const canRepair=run.allowed_actions.includes('repair_review');
 // This panel exists only for the free "repair the rejected review" path.
 // Invalid/stale review notices otherwise belong to the human decision panel;
 // keeping a second panel with a disabled confirm only confuses the user.
 const blocked=canRepair&&run.current_stage==='reviewer'&&run.drafts.length&&!run.review&&!run.allowed_actions.includes('accept')&&!run.allowed_actions.includes('adopt_manual');
 $('reviewRecovery').hidden=!blocked;
 $('repairReview').hidden=!canRepair;
 if(!blocked)return;
 $('reviewRecoveryTitle').textContent='稿件已保存，先处理审核问题';
 $('reviewRecoveryMessage').textContent=run.review_recovery?.reason||'审核结果未通过格式校验。可以免费整理已收到的意见，保留稿件和问题，进入人工处理，不再次调用模型。';
 const rejected=[...(run.calls||[])].reverse().find(c=>c.stage==='review'&&c.status==='invalid'&&!c.inherited);
 $('reviewRecoveryIssues').innerHTML=reviewIssues(rejected?.diagnostic_response?.issues).map(i=>`<div class="issue"><b>${esc(i.excerpt||i.location||'稿件问题')}</b><p>${esc(i.reason)}</p><p>修改建议：${esc(i.suggestion)}</p></div>`).join('');
 $('next').hidden=true;$('auto').hidden=true;
}
function renderHuman(){
 const allowed=run.allowed_actions,review=run.review;
 const issueReview=review||run.prior_review||[...(run.calls||[])].reverse().find(c=>c.stage==='review'&&c.status==='invalid'&&!c.inherited)?.diagnostic_response;
 const revision=review?.decision==='revision_required';
 const issues=reviewIssues(issueReview?.issues);
 const isSystemIssue=i=>/模型未能提供有效审核结论|模型引用无法匹配原始素材/.test(`${i.excerpt||''} ${i.reason||''}`);
 const contentIssues=issues.filter(i=>!isSystemIssue(i));
 const mustFix=contentIssues.filter(i=>i.severity==='blocker'||i.severity==='major');
 const minor=contentIssues.filter(i=>i.severity==='minor');
 const unclassified=contentIssues.filter(i=>!['blocker','major','minor'].includes(i.severity));
 const stale=!review&&Boolean(issueReview);
 const needsReview=allowed.includes('review_current')&&!run.in_flight;
 const visible=run.run_status==='WAITING_USER'||revision||needsReview||allowed.includes('adopt_manual')||run.run_status==='SUCCEEDED';
 $('humanPanel').hidden=!visible;
 const questions=algorithmQuestions(run);
 $('supplyForm').hidden=!questions.length||!allowed.includes('supplement');
 if($('algorithmQuestions')){$('algorithmQuestions').hidden=!questions.length;$('algorithmQuestions').innerHTML=questions.length?'<h3>优先补充这些资料</h3><ol>'+questions.map(q=>'<li>'+esc(q.question)+(q.reason?'<p class="helper">'+esc(q.reason)+'</p>':'')+'</li>').join('')+'</ol><p class="helper">可在下方一次回答；没有的信息可以留空，不必编造。</p>':'';}
 if($('skipAlgorithmQuestions'))$('skipAlgorithmQuestions').hidden=!questions.length||!allowed.includes('skip_questions');
 $('supplyHypothesis').disabled=!!questions.length;if(questions.length)$('supplyHypothesis').checked=false;
 $('reviewCurrent').hidden=!needsReview;
 $('revise').hidden=!(revision&&allowed.includes('next'));
 if(revision)$('revise').textContent=mustFix.length?`按必须修改项自动改稿（${mustFix.length}项）`:'按审核意见自动改稿';
 $('confirmationPending').hidden=!!questions.length||availableMaterialContinuation(run)||allowed.includes('accept')||allowed.includes('adopt_manual')||run.run_status==='SUCCEEDED';
 $('adoptManual').hidden=!allowed.includes('adopt_manual');
 $('adoptManual').textContent=`已知晓问题，采用当前版本（第 ${run.drafts.length} 版）`;
 $('editButton').hidden=!allowed.includes('edit');$('accept').hidden=!allowed.includes('accept');$('export').hidden=!allowed.includes('export');
 $('export').href=`/api/runs/${run.run_id}/export?format=docx`;
 $('sendToPublish').hidden=run.run_status!=='SUCCEEDED';
 if($('retitleButton'))$('retitleButton').hidden=!allowed.includes('retitle');
 let title='需要你的决定',message='';
 if(run.run_status==='SUCCEEDED'){title=run.acceptance?.mode==='manual_override'?'这个版本，已由你人工采用':'这个版本，已由你确认';message=run.acceptance?.mode==='manual_override'?'你已知晓审核问题并采用此版本。审核意见仍保留，这不表示 AI 审核通过；可以下载，发布需另行批准。':'可以下载已确认稿件。审核不能保证事实正确，发布前仍需你检查。';}
 else if(questions.length){title='有几项关键资料需要你选择补充';message='本任务已开启关键缺口询问。补充一次后重新分析，也可以跳过，按现有资料继续。';}
 else if(availableMaterialContinuation(run)){title='按现有资料完成稿件';message='无需补充材料。点击上方“按现有资料继续生成”；未提供的事实会省略或明确说明，最终稿和审核意见仍由你确认。';}
 else if(needsReview){title='这版还没复审';message='下面是你上一版的问题，仅供参考。先点“复审当前版本”，让 AI 只检查这一版；复审完成前不要人工采用。';}
 else if(run.wait_reason==='revision_limit'){title='已达到自动改稿上限';message='AI 自动改稿已停止。你仍可手动修改，或知晓下方问题后采用当前版本；人工采用会单独记录，不表示 AI 审核通过。';}
 else if(revision){title='主编发现了问题，最后由你决定';message=mustFix.length?`有 ${mustFix.length} 项必须修改、${minor.length} 项小问题。建议先按必须修改项自动改稿，再复审。`:'只有小问题；可以按意见改稿，也可以人工采用。';}
 else if(allowed.includes('adopt_manual')){title='当前稿件，最后由你决定';message='这个版本尚未通过 AI 审核。可以继续修改或复审，也可以知晓问题后人工采用。';}
 else if(allowed.includes('accept')){title='审核结束，最后由你决定';message='请检查正文与素材。你可以先修改，也可以确认当前版本；修改后必须重新审核。';}
 $('humanTitle').textContent=title;$('humanMessage').textContent=message;
 $('issues').innerHTML=(stale?'<p class="helper">以下为已有审核意见，仅供参考；当前版本尚未完成有效复审（旧问题仍未复审）。</p>':'')+reviewQuestions(issueReview?.human_questions).map(q=>'<p class="issue">'+esc(q)+'</p>').join('')+issueGroup(mustFix,stale?'上一版必须修改（仅供参考）':'必须修改','must-fix')+issueGroup(minor,stale?'上一版小问题（仅供参考）':'小问题','minor')+issueGroup(unclassified,stale?'上一版其他问题（仅供参考）':'其他问题','minor');
}
function diffTokens(text){return String(text||'').match(/[\u3400-\u9fff]|[A-Za-z0-9]+|[\s\S]/g)||[];}
function diffSegments(a,b){
 const A=diffTokens(a),B=diffTokens(b);
 if(!A.length||!B.length)return [...A.map(text=>({type:'del',text})),...B.map(text=>({type:'add',text}))];
 if(A.length*B.length>4_000_000){
  let p=0,s=0;while(p<A.length&&p<B.length&&A[p]===B[p])p++;while(s<A.length-p&&s<B.length-p&&A[A.length-1-s]===B[B.length-1-s])s++;
  return [...A.slice(0,p).map(text=>({type:'same',text})),...A.slice(p,A.length-s).map(text=>({type:'del',text})),...B.slice(p,B.length-s).map(text=>({type:'add',text})),...A.slice(A.length-s).map(text=>({type:'same',text}))];
 }
 const dp=Array.from({length:A.length+1},()=>new Uint32Array(B.length+1));
 for(let i=1;i<=A.length;i++)for(let j=1;j<=B.length;j++)dp[i][j]=A[i-1]===B[j-1]?dp[i-1][j-1]+1:Math.max(dp[i-1][j],dp[i][j-1]);
 const out=[];let i=A.length,j=B.length;
 while(i>0&&j>0){
  if(A[i-1]===B[j-1]){out.push({type:'same',text:A[i-1]});i--;j--;}
  else if(dp[i-1][j]>=dp[i][j-1]){out.push({type:'del',text:A[i-1]});i--;}
  else {out.push({type:'add',text:B[j-1]});j--;}
 }
 while(i>0)out.push({type:'del',text:A[--i]});
 while(j>0)out.push({type:'add',text:B[--j]});
 return out.reverse().reduce((list,part)=>{const last=list[list.length-1];if(last&&last.type===part.type)last.text+=part.text;else list.push({...part});return list;},[]);
}
function diffText(a,b,side){
 if(!side||a===b)return esc(b||'');
 return diffSegments(a,b).map(part=>{
  if(part.type==='same')return esc(part.text);
  if(part.type==='del'&&side==='left')return `<span class="diff-del">${esc(part.text)}</span>`;
  if(part.type==='add'&&side==='right')return `<span class="diff-add">${esc(part.text)}</span>`;
  return '';
 }).join('');
}
function draftHTML(d,index,changed=false,side='',other=null){
 const c=d.content,o=other||{};
 const before=side==='right'?o:c,after=side==='left'?o:c;
 const tagClass=tag=>side==='right'&&!(o.tags||[]).includes(tag)?' diff-add':side==='left'&&!(o.tags||[]).includes(tag)?' diff-del':'';
 return `<article class="draft-copy ${changed?'changed':''} ${side?'diff-side':''}"><span class="version-tag">版本 ${index+1} · ${d.actor==='user'?'你手动修改':run.mode==='live'?'AI 创作':'模拟创作'} · ${esc(d.ref.slice(0,8))}${run.accepted_ref===d.ref?' · 已确认':''}</span><h3>${diffText(before.selected_title||'',after.selected_title||'',side)}</h3><pre>${diffText(before.body||'',after.body||'',side)}</pre><p>${diffText(before.cta||'',after.cta||'',side)}</p><div>${(c.tags||[]).map(t=>`<span class="tag${tagClass(t)}">#${esc(t)}</span>`).join('')}</div></article>`;
}
function domainFieldError(id,message){
 const host=$(id+'Picker');
 if(host){const status=host.querySelector('[data-domain-status]');if(status){status.textContent=message;status.setAttribute('role','alert');}host.setAttribute('aria-invalid','true');for(let node=host.parentElement;node;node=node.parentElement)if(node.tagName==='DETAILS')node.open=true;host.focus();}
 const failure=new Error(message);failure.field=id;return failure;
}
async function selectedDomains(id){
 const values=[...new Set(($(id)?.value||'').split(/[,，、]/).map(v=>v.trim()).filter(Boolean))];
 if(!values.length)return [];
 if(values.length>8)throw domainFieldError(id,`已选 ${values.length} 个领域，最多可选 8 个。请取消 ${values.length-8} 个后再提交。`);
 let cfg;try{cfg=await api('/api/creation/taxonomy');}catch(e){throw domainFieldError(id,'暂时无法核对领域选项。请检查本地服务是否运行，点击领域下方“重新加载选项”后再提交；当前输入保留。');}
 const mapped=values.map(value=>Object.keys(cfg.domains).find(key=>key===value||cfg.domains[key].label===value));
 const invalid=values.filter((_,i)=>!mapped[i]);
 if(invalid.length)throw domainFieldError(id,`领域“${invalid.join('、')}”不在可选范围。请在领域选项中重新选择；没有合适类别可选“综合”。`);
 return [...new Set(mapped)];
}
async function mountDomainPicker(id){
 const input=$(id),host=$(id+'Picker');if(!input||!host)return;
 const ticket={};host.domainLoad=ticket;
 host.innerHTML='<p class="helper" data-domain-status>正在加载领域选项…</p>';
 try{
  const cfg=await api('/api/creation/taxonomy');if($(id+'Picker')!==host||host.domainLoad!==ticket)return;
  const selected=(input.value||'').split(/[,，、]/).filter(Boolean),keys=Object.keys(cfg.domains);
  const chosen=selected.map(value=>keys.find(key=>key===value||cfg.domains[key].label===value)||value);
  const unknown=chosen.filter(value=>!keys.includes(value));
  host.innerHTML=`<div class="domain-options">${keys.map(key=>`<label class="domain-option"><input type="checkbox" value="${esc(key)}" ${chosen.includes(key)?'checked':''}><span>${esc(cfg.domains[key].label)}</span></label>`).join('')}</div><p class="helper" data-domain-status aria-live="polite"></p><button type="button" class="quiet" data-domain-retry>重新加载选项</button>`;
  const boxes=[...host.querySelectorAll('input[type="checkbox"]')],status=host.querySelector('[data-domain-status]');
  const sync=()=>{const count=boxes.filter(b=>b.checked).length;boxes.forEach(b=>b.disabled=count>=8&&!b.checked);status.textContent=`已选 ${count}/8 个领域。${count>=8?'已达上限，请先取消一项再换选。':host.dataset.emptyHint||'可选多个；没有合适类别可选“综合”。'}`;host.removeAttribute('aria-invalid');status.removeAttribute('role');};
  sync();
  if(unknown.length){status.textContent=`原分类“${unknown.join('、')}”已不可用。请重新勾选领域后再提交；没有合适类别可选“综合”。`;status.setAttribute('role','alert');host.setAttribute('aria-invalid','true');}
  host.onchange=()=>{if(typeof errorField!=='undefined'&&errorField===id)clearError();input.value=boxes.filter(b=>b.checked).map(b=>b.value).join(',');sync();input.dispatchEvent(new Event('input',{bubbles:true}));};
  host.querySelector('[data-domain-retry]').onclick=()=>mountDomainPicker(id);
 }catch(e){if($(id+'Picker')!==host||host.domainLoad!==ticket)return;host.innerHTML='<p class="issue" data-domain-status role="alert">领域选项加载失败。请确认本地服务仍在运行，再点击“重新加载选项”；其他输入无需重填。</p><button type="button" class="secondary" data-domain-retry>重新加载选项</button>';host.querySelector('[data-domain-retry]').onclick=()=>mountDomainPicker(id);}
}
async function creationRequest(){
 const request={channel:'xiaohongshu'},domains=await selectedDomains('creationDomains');
 if(domains.length)request.domains=domains;
 const format=$('creationFormat')?.value,goal=$('creationGoal')?.value?.trim(),words=$('creationWordCount')?.value;
 if(format)request.format=format;if(goal)request.goal=goal;if(words)request.word_count=Number(words);
 return request;
}
function draftEvidenceNode(d){
 if(d.actor==='user'||!d.snapshot_id)return null;
 const nodes=(run.node_runs||[]).filter(n=>n.snapshot_id===d.snapshot_id&&n.agent==='content'&&['body','revise'].includes(n.stage)&&n.mode==='live');
 const same=(a,b)=>{if(a===b)return true;if(!a||!b||typeof a!=='object'||typeof b!=='object'||Array.isArray(a)!==Array.isArray(b))return false;const keys=Object.keys(a);return keys.length===Object.keys(b).length&&keys.every(k=>Object.hasOwn(b,k)&&same(a[k],b[k]));};
 const candidates=nodes.filter(n=>same(n.output,d.content));
 const events=run.events||[],created=events.findIndex(e=>e.type==='artifact.created'&&e.payload?.artifact_ref===d.ref);
 if(created>=0){for(let i=created-1;i>=0;i--){const e=events[i];if(e.type==='artifact.created'&&e.payload?.artifact_ref)break;if(e.type==='agent.completed'&&e.payload?.agent==='content'&&['body','revise'].includes(e.payload?.stage)){return candidates.find(n=>n.id===e.payload.node_ref)||null;}}}
 return candidates.length===1?candidates[0]:null;
}
function creationReferenceHTML(input){
 const report=input?.creation_retrieval,classification=input?.creation_classification||report?.classification;
 if(!report&&!classification)return '';
 const formats={note:'图文笔记',video_script:'短视频口播',product_detail:'商品详情'};
 const groups=report?.groups||report||{};
 const sourceBody=source=>{if(source.text)return source.text;const matches=(input?.materials||[]).filter(item=>item.source_id===source.source_id&&(source.version===undefined||item.version===source.version));return matches.length===1?matches[0].text||'未留存正文':'未留存正文';};
 return `<details class="source-card"><summary>本次分类与三组检索材料</summary><p>领域：${esc((classification?.domains||[]).join('、')||'待确认')} · 渠道：${esc(classification?.channel||'未知')} · 形式：${esc(formats[classification?.format]||classification?.format||'待确认')}</p><p>检索方式：${esc(report?.engine||'未记录')}</p><details><summary>实际检索条件</summary><pre>${esc(JSON.stringify(report?.filters||{},null,2))}</pre></details>${[['methods','通用创作方法'],['examples','领域参考样例'],['facts','独立事实依据']].map(([key,label])=>`<h4>${label}</h4>${(groups[key]||[]).map(source=>`<article><b>${esc(source.title||source.source_id||'未命名')}</b><p class="helper">来源 ID：${esc(source.source_id||'未知')} · 版本：${esc(source.version??'未知')} · 分类：${esc(JSON.stringify(source.classification||{}))}</p><blockquote>${esc(sourceBody(source))}</blockquote></article>`).join('')||'<p>无匹配材料</p>'}`).join('')}${(report?.gaps||[]).map(gap=>`<p class="issue">${esc(typeof gap==='string'?gap:JSON.stringify(gap))}</p>`).join('')}</details>`;
}
function draftEvidenceHTML(d){
 const node=draftEvidenceNode(d),input=node?.input;
 const refs=Array.isArray(input?.retrieved_references)?input.retrieved_references:[],materials=Array.isArray(input?.materials)?input.materials:[];
 const frozenGroups=input?.creation_retrieval?.groups||input?.creation_retrieval||{};
 const resolvedRefs=refs.map(source=>{if(source.text)return source;const matches=(frozenGroups.examples||[]).filter(item=>item.source_id===source.source_id&&(source.version===undefined||item.version===source.version));return matches.length===1?{...source,text:matches[0].text}:source;});
 const sources=[],seen=new Set();for(const source of [...resolvedRefs,...materials]){const key=JSON.stringify([source.source_id,source.version,source.text]);if(!seen.has(key)){seen.add(key);sources.push(source);}}
 const link=(url,label)=>{try{const parsed=new URL(url);if(['https:','http:'].includes(parsed.protocol))return `<a href="${esc(parsed.href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;}catch(_){}return esc(label);};
 const sourceHTML=source=>`<article class="source-card"><h4>${link(source.url,source.title||source.source_id||'未命名资料')}</h4><p class="helper">来源 ID：${esc(source.source_id||'未知')} · 资料版本：${esc(source.version??'未知')} · 页码：${esc(source.page??'未知')} · 原文位置：${esc(source.offset??'未知')} · 获取时间：${esc(source.fetched_at??source.observed_at??source.case_ref?.observed_at??'未知')}</p><p>${source.evidence_role==='expression_reference'?'表达参考：学习结构和方法，不能当作产品事实。':'事实/用户材料：已送入本次创作，真实性仍需核查。'}</p><blockquote>${esc(source.text||'历史记录未保存正文')}</blockquote></article>`;
 const reviews=[run.prior_review,...(run.reviews||[]),run.review].filter(r=>r&&d.snapshot_id&&r.draft_ref===d.ref&&r.snapshot_id===d.snapshot_id),review=reviews.at(-1);
 const claims=Array.isArray(review?.claim_map)?review.claim_map:[];
 const records=review?.reference_records,adoption=Array.isArray(records?.adoption_notes)?records.adoption_notes.filter(Boolean):[];
 const learned=adoption.length?adoption:Array.isArray(review?.learned_from)?review.learned_from:Array.isArray(node?.output?.learned_from)?node.output.learned_from:[];
 return `<details class="draft-evidence"><summary>查看本稿资料依据</summary><p class="helper">稿件：${esc(d.ref)} · 输入快照：${esc(d.snapshot_id||'未知')}。仅显示所选版本留存的调用和审核记录。</p>${creationReferenceHTML(input)}<h3>送入创作模型的参考</h3><p>送入模型不等于稿件实际引用，也不表示来源事实已核实。</p>${input?(sources.map(sourceHTML).join('')||(Array.isArray(input.materials)&&Array.isArray(input.retrieved_references)?'<p>本次调用未送入资料或表达参考。</p>':'<p>历史调用缺少完整资料字段，无法确认参考范围。</p>')):`<p>${d.actor==='user'?'本版由你手动修改，没有对应的创作模型调用。':'未找到能唯一对应本版稿件的创作调用，资料依据未知。'}不会使用当前任务资料替代历史依据。</p>`}<h3>本版审核记录中的事实引用</h3>${review?(claims.length?claims.map(c=>`<article class="source-card"><p>稿件原文：${esc(c.excerpt)}</p><p>来源 ID：${esc(c.source_id||'未知')}</p><blockquote>${esc(c.quote||'未记录原文引句')}</blockquote></article>`).join(''):'<p>该审核未记录事实引用；不代表稿件所有事实都已核实。</p>'):'<p>尚无与本版稿件和快照匹配的审核，实际引用未知。</p>'}<h3>已记录的表达借鉴</h3>${records?`<p class="helper">${esc(records.scope||'采用说明由创作过程记录；不代表独立真实性或全网原创核验。')}</p><details><summary>审核所对应的参考范围（不等于全部采用）</summary><pre>${esc(JSON.stringify(records.groups||{},null,2))}</pre></details>`:''}${learned.length?learned.map(item=>`<p>${esc(typeof item==='string'?item:JSON.stringify(item))}</p>`).join(''):'<p>未记录逐项表达借鉴，不能把全部参考资料称为已采用。</p>'}${review?.limitations?.length?'<details><summary>查看本版审核的借鉴说明与限制</summary>'+review.limitations.map(item=>`<p>${esc(item)}</p>`).join('')+'</details>':''}</details>`;
}
function renderDraft(){
 $('draftPanel').hidden=!run.drafts.length;if(!run.drafts.length)return;
 if(viewVersion!==null&&(!Number.isInteger(viewVersion)||viewVersion<0||viewVersion>=run.drafts.length))viewVersion=null;
 const i=viewVersion??run.drafts.length-1,d=run.drafts[i],prev=run.drafts[i-1];
 $('versionSelect').innerHTML=run.drafts.map((d,index)=>`<option value="${index}" ${index===i?'selected':''}>版本 ${index+1}${run.accepted_ref===d.ref?' · 已确认':''}</option>`).join('');
 if($('compareVersionsWrap'))$('compareVersionsWrap').hidden=!prev;
 if(!prev&&$('compareVersions'))$('compareVersions').checked=false;
 const compare=prev&&$('compareVersions')?.checked;
 const changes=prev?['selected_title','body','cta','tags'].filter(k=>JSON.stringify(prev.content[k])!==JSON.stringify(d.content[k])).map(k=>({selected_title:'标题',body:'正文',cta:'互动引导',tags:'标签'})[k]):[];
 $('draftView').innerHTML=(compare?'<p class="change-summary">与上一版相比：'+(changes.length?'修改了 '+changes.join('、'):'文字内容未变化')+'。<span class="diff-legend"><span class="diff-add">绿色</span> 新增/修改，<span class="diff-del">红色删除线</span> 删除；仅对比标注，不写进导出稿。</span></p><div class="draft-columns">'+draftHTML(prev,i-1,true,'left',d.content)+draftHTML(d,i,true,'right',prev.content)+'</div>':draftHTML(d,i));
 $('draftView').insertAdjacentHTML('beforeend',draftEvidenceHTML(d));
 const candidates=run.artifacts.find(a=>a.stage==='title')?.value;
 if(candidates&&run.allowed_actions.includes('edit')&&!editing)$('draftView').insertAdjacentHTML('beforeend','<details><summary>比较候选标题 / 选择后重新审核</summary>'+candidates.candidates.map((t,n)=>`<div class="candidate-row"><div><b>${esc(t)}</b><p class="muted">${esc(candidates.reasons?.[n]||'历史版本未记录理由')}</p></div><button data-title-choice="${n}" ${t===run.drafts.at(-1).content.selected_title?'disabled':''}>选用并复审</button></div>`).join('')+'</details>');
}
$('draftView').onclick=async e=>{const b=e.target.closest('[data-title-choice]');if(!b||busy||editing)return;const title=run.artifacts.find(a=>a.stage==='title')?.value.candidates[Number(b.dataset.titleChoice)];if(title&&title!==run.drafts.at(-1).content.selected_title&&await act('edit',{...run.drafts.at(-1).content,selected_title:title})){viewVersion=null;render();toast('标题另存为新版本，请重新审核正文是否匹配');}};
function renderTimeline(){
 const labels={'run.queued':'任务已保存','run.started':'开始执行','agent.started':'角色开始','agent.failed':'执行失败','agent.completed':'角色阶段完成','branch.completed':'分析分支完成','join.completed':'两分支已汇合','artifact.created':'产物已保存','review.completed':'审核完成','human.accepted':'你确认了当前版本','run.completed':'任务完成','run.cancelled':'你取消了任务','workflow.transition':'状态更新'};
 $('timeline').innerHTML=run.events.slice().reverse().map(e=>`<div class="event"><time>${esc(new Date(e.occurred_at).toLocaleTimeString('zh-CN',{hour12:false}))}<br>#${e.seq}</time><div>${esc(labels[e.type]||e.type)} ${esc(names[e.payload.agent]||'')} ${esc(stages[e.payload.stage]||'')}<small>${esc(e.payload.run_status?states[e.payload.run_status]:e.payload.decision?({approved:'审核通过，等待确认',revision_required:'发现问题，需要修改',needs_human:'审核有待确认信息'})[e.payload.decision]:e.payload.message|| (e.payload.mode==='simulation'?'固定模板 / 模拟执行':e.payload.mode==='live'?'真实 AI 执行':'已持久化'))}</small></div></div>`).join('');
}
function renderCalls(){
 if(run.mode!=='live')return;
 const rows=(run.calls||[]).map(c=>'<div class="event"><time>'+esc((c.provider||'历史记录')+' / '+(c.model||'未知模型'))+'</time><div>'+esc(names[c.agent])+' · '+esc(stages[c.stage])+'<small>'+esc(({calling:'请求中 / 中断后先核对用量，不自动重发',received:'已收到响应',validated:'校验通过',invalid:'输出格式校验失败',failed:'请求失败',not_sent:'未发送至模型，未产生用量'})[c.status]||c.status)+' · '+(c.tokens===null?'用量未知，已保留预算':c.tokens+' Token')+(c.inherited?(c.status==='not_sent'?' · 原任务未发送记录':' · 沿用原任务计数'):'')+(c.error?' · '+esc(c.error):'')+'</small>'+(c.diagnostic_response?'<details><summary>查看被拒绝的模型响应</summary>'+json(c.diagnostic_response)+'</details>':'')+'</div></div>').join('');
 $('timeline').insertAdjacentHTML('afterbegin',rows);
}
async function act(action,payload={}){
 if(action==='next'&&websiteSession?.auth_required)return backgroundCommand('step');
 if(action==='next'&&run?.mode==='live'&&!confirmLiveBudget(()=>act(action,payload)))return false;
 if(busy||!run)return false;busy=true;clearError();if(action==='next'&&run.mode==='live')run.in_flight=true;render();
 try{let command={action,version:run.status_version,key:crypto.randomUUID(),payload};if(action==='request_revision'){const signature=JSON.stringify([run.run_id,payload]);if(revisionCommand?.signature===signature)command=revisionCommand.command;else revisionCommand={signature,command};}run=await api(`/api/runs/${run.run_id}/actions`,'POST',command);if(action==='request_revision')revisionCommand=null;clearError();viewVersion=null;selected=currentAgent();detailStage=null;try{if(action==='edit'){ops=await api('/api/operations');syncAccounts();}await history();}catch(refreshError){error(new Error('操作已保存，但列表暂未刷新。请刷新页面查看最新记录；无需重复提交。'),'refresh');}return true;}
 catch(e){if(action==='request_revision'&&e.status>=400&&e.status<500&&e.status!==408)revisionCommand=null;auto=false;error(e);try{run=await api('/api/runs/'+run.run_id);}catch(_){}return false;}
 finally{busy=false;render();}
}
async function backgroundCommand(action,extra={}){
 if(busy||!run)return false;
 const searchOnly=action==='step'&&run.current_stage==='brief'&&run.context.web_research?.enabled&&run.context.web_research.status!=='complete';
 if(['start','step','research_and_regenerate'].includes(action)&&!searchOnly&&run.mode==='live'&&!confirmLiveBudget(()=>backgroundCommand(action,extra),action==='research_and_regenerate'?'research_and_regenerate:'+run.status_version:''))return false;
 let commandError=null;busy=true;clearError();render();
 try{run=await api(`/api/runs/${run.run_id}/background`,'POST',{action,version:run.status_version,key:crypto.randomUUID(),...extra});clearError();selected=currentAgent();detailStage=null;try{await history();}catch(refreshError){error(new Error('运行指令已保存，但列表暂未刷新。请刷新页面查看任务状态；不要重复启动。'),'refresh');}return true;}
 catch(e){commandError=e;error(e);try{run=await api('/api/runs/'+run.run_id);}catch(_){}return false;}
 finally{busy=false;render();if(commandError)error(commandError);}
}
async function autoRun(){
 if(availableMaterialContinuation(run))return backgroundCommand('start');
 if(websiteSession?.auth_required)return backgroundCommand(run.in_flight?'pause':'start');
 if(run?.mode==='live'&&!confirmLiveBudget(autoRun))return;
 if(auto){auto=false;render();return;}auto=true;render();
 while(auto&&run?.allowed_actions.includes('next')){
  if(!await act('next'))break;
  if(run.review?.decision==='revision_required')break;
  // Yield browser paint; elapsed times remain actual server work, not this presentation pause.
  await new Promise(resolve=>setTimeout(resolve,150));
 }
 auto=false;render();
}
$('briefForm').addEventListener('submit',async e=>{e.preventDefault();if(busy)return;syncNewResearchChoice();busy=true;clearError();e.submitter.disabled=true;
 try{const accountId=currentAccount()?.id,documentIds=[...$('materialDocumentSelect').selectedOptions].map(o=>o.value);if(documentIds.length>3)throw new Error('本次最多选择 3 份资料');run=await api('/api/runs','POST',{algorithm_options:algorithmOptionsRequest(),comment_feedback:commentFeedbackRequest(),creation:await creationRequest(),knowledge:{enabled:!!accountId&&$('useKnowledge').checked,automatic_references:!!accountId&&$('useAutomaticReferences').checked,...(accountId&&$('useKnowledge').checked&&documentIds.length?{document_ids:documentIds}:{})},...($('mode').value==='live'?{web_research:{enabled:$('useWebResearch').checked,provider:$('webSearchProvider').value||'bing',targets:[$('webSearchTarget').value||'web'],queries:[$('webQuery1').value,$('webQuery2').value].map(q=>q.trim()).filter(Boolean)}}:{}),mode:$('mode').value,topic:$('topic').value,audience:$('audience').value,tone:$('tone').value,material:$('material').value,scenario:$('scenario').value,allow_hypothesis:$('hypothesis').checked,operations:{platform:$('targetPlatform').value,account_id:accountId,account:$('accountName').value,trend_id:chosenTrend?.id||null,hypothesis_id:chosenHypothesis?.id||null}});chosenHypothesis=null;selected='audience';detailStage=null;viewVersion=null;editing=false;$('editor').hidden=true;render();await history();}
 catch(err){error(err);}finally{busy=false;e.submitter.disabled=false;if(run&&!$('workbench').hidden)render();}});
$('history').addEventListener('click',async e=>{const b=e.target.closest('[data-run]');if(!b||busy||!dirtyGuard())return;busy=true;auto=false;editing=false;$('editor').hidden=true;clearError();showPage('studio');try{run=await api('/api/runs/'+b.dataset.run);viewVersion=null;detailStage=null;selected=currentAgent();render();await history();}catch(err){error(err);}finally{busy=false;if(run)render();}});
$('newRun').onclick=()=>{if(busy||!dirtyGuard())return;showPage('studio');auto=false;editing=false;$('editor').hidden=true;$('workbench').hidden=true;$('welcome').hidden=false;renderMode($('mode').value);fillAccountBrief();syncNewResearchChoice();clearError();};
$('flow').onclick=e=>{const chip=e.target.closest('[data-stage]');const b=e.target.closest('[data-agent]');if(chip){selected='content';detailStage=chip.dataset.stage;render();}else if(b){selected=b.dataset.agent;detailStage=null;render();}};
$('recover').onclick=()=>act('recover');
if($('researchAndRegenerate'))$('researchAndRegenerate').onclick=()=>{if(busy||editing||!run||!canResearchAndRegenerate(run)||!dirtyGuard())return;return backgroundCommand('research_and_regenerate');};
$('repairReview').onclick=async()=>{if(await act('repair_review')){clearError();selected='human';render();$('humanPanel').scrollIntoView({behavior:'smooth',block:'center'});toast('已有审核意见已整理。请按提示补充资料或修改稿件；本次没有调用 AI。');}};
$('next').onclick=()=>run?.background?backgroundCommand('step'):act('next');$('auto').onclick=autoRun;
if($('retitleButton'))$('retitleButton').onclick=async()=>{
 if(busy||!run?.drafts?.length)return;
 const current=run.drafts.at(-1).content.selected_title;
 const title=window.prompt('小红书标题最多20个字符（含标点）。请输入新标题：',current.slice(0,20));
 if(title===null)return;
 if(await act('retitle',{title}))toast('标题已改短；正文、审核与版本记录保留，可以重新导出。');
};
$('cancel').onclick=async()=>{
 cancellationRun={runId:run.run_id,snapshotId:run.snapshot_id};$('cancelConfirmation').hidden=false;$('cancelConfirmation').scrollIntoView({behavior:'smooth',block:'center'});
};
$('keepTask').onclick=()=>{cancellationRun=null;$('cancelConfirmation').hidden=true;};
$('confirmCancel').onclick=async()=>{
 const pending=cancellationRun;cancellationRun=null;
 $('cancelConfirmation').hidden=true;
 if(!pending||run?.run_id!==pending.runId||run.snapshot_id!==pending.snapshotId){error(new Error('当前任务已变化，请重新选择要取消的任务。'));return;}
 auto=false;editing=false;$('editor').hidden=true;
 if(!busy){await act('cancel');return;}
 try{
  const latest=await api('/api/runs/'+pending.runId);
  if(run?.run_id!==pending.runId||run.snapshot_id!==pending.snapshotId){error(new Error('当前任务已变化，请重新确认取消。'));return;}
  run=await api('/api/runs/'+latest.run_id+'/actions','POST',{action:'cancel',version:latest.status_version,key:crypto.randomUUID(),payload:{}});
  render();await history();
 }catch(e){error(e);}
};
$('revise').onclick=()=>run?.background?backgroundCommand('step'):act('next');
$('reviewCurrent').onclick=async()=>{if(!await act('review_current'))return;if(run?.background)await backgroundCommand('step');else await act('next');};
$('editButton').onclick=()=>{auto=false;const c=run.drafts.at(-1).content;$('editTitle').maxLength=run.context.operations?.platform==='xiaohongshu'?20:200;$('editTitle').title=run.context.operations?.platform==='xiaohongshu'?'小红书标题最多20个字符（含标点）':'标题';if($('editTitleLimit'))$('editTitleLimit').hidden=run.context.operations?.platform!=='xiaohongshu';$('editTitle').value=c.selected_title;$('editBody').value=c.body;$('editCta').value=c.cta;$('editTags').value=c.tags.join('，');editing=true;$('editor').hidden=false;render();$('editor').scrollIntoView({behavior:'smooth',block:'center'});$('editTitle').focus();};
$('discardEdit').onclick=()=>{editing=false;$('editor').hidden=true;render();};
$('editor').onsubmit=async e=>{e.preventDefault();const data={selected_title:$('editTitle').value,body:$('editBody').value,cta:$('editCta').value,tags:$('editTags').value.split(/[,，]/).map(x=>x.trim()).filter(Boolean)};if(await act('edit',data)){editing=false;$('editor').hidden=true;render();toast('新版本已保存。可以申请复审，也可以知晓问题后人工采用。');}};
$('accept').onclick=async()=>{if(await act('accept',{draft_ref:run.drafts.at(-1).ref,review_ref:run.review.ref}))toast('已确认当前版本，可以下载。');};
$('adoptManual').onclick=async()=>{const draft=run.drafts.at(-1);if(await act('adopt_manual',{draft_ref:draft.ref,content_hash:draft.content_hash,acknowledge:true})){clearError();toast('已人工采用当前版本，审核意见保留，可以下载。');}};
if($('useCreationAlgorithms'))$('useCreationAlgorithms').onchange=()=>{$('askMaterialQuestions').disabled=!$('useCreationAlgorithms').checked;};
if($('skipAlgorithmQuestions'))$('skipAlgorithmQuestions').onclick=async()=>{if(!algorithmQuestions(run).length||!run.allowed_actions.includes('skip_questions'))return;if(await act('skip_questions',{}))toast('已跳过提问。继续运行时只使用已有资料。');};
$('supplyForm').onsubmit=async e=>{e.preventDefault();if(await act('supplement',{material:$('supply').value,allow_hypothesis:algorithmQuestions(run).length?false:$('supplyHypothesis').checked}))toast('补充已保存，请启动运行重新分析。');};
$('versionSelect').onchange=e=>{const version=Number(e.target.value);viewVersion=version===run.drafts.length-1?null:version;renderDraft();renderFeedbackAndRevision();};
if($('useCommentFeedback'))$('useCommentFeedback').onchange=()=>{if(!$('useCommentFeedback').checked){resetCommentSelection();return;}$('commentFeedbackFields').hidden=false;refreshCommentNotes();};
if($('refreshCommentNotes'))$('refreshCommentNotes').onclick=refreshCommentNotes;
if($('activeAccount'))$('activeAccount').addEventListener('change',resetCommentSelection);
if($('revisionInstruction'))$('revisionInstruction').addEventListener('input',()=>{if(!revisionBinding&&run?.drafts.length&&revisionTargetsLatest()){const d=run.drafts.at(-1);revisionBinding={runId:run.run_id,draftRef:d.ref,contentHash:d.content_hash};}});
if($('revisionRequestForm'))$('revisionRequestForm').onsubmit=async e=>{
 e.preventDefault();if(busy||!run?.drafts.length)return;
 if(!revisionTargetsLatest()){error(new Error('当前查看的是历史稿件，请切回最新版本，阅读后再提交改稿要求。'));return;}
 const d=run.drafts.at(-1),binding=revisionBinding||{runId:run.run_id,draftRef:d.ref,contentHash:d.content_hash};
 if(binding.runId!==run.run_id||binding.draftRef!==d.ref||binding.contentHash!==d.content_hash){revisionBinding=null;error(new Error('稿件已变化，请查看最新稿后重新确认改稿要求。文字已保留。'));return;}
 if(await act('request_revision',{draft_ref:binding.draftRef,content_hash:binding.contentHash,instruction:$('revisionInstruction').value})){$('revisionInstruction').value='';revisionBinding=null;toast('改稿要求已保存。点击连续运行执行 AI 改稿和复审，沿用本任务预算。');}
};
if($('compareVersions'))$('compareVersions').onchange=()=>renderDraft();
window.addEventListener('beforeunload',e=>{if(editing||hasUnsavedRevision()){e.preventDefault();e.returnValue='';}});
document.addEventListener('DOMContentLoaded',async()=>{try{const session=await api('/api/session');csrf=session.csrf;if(session.auth_required&&!session.user){showLogin(session);return;}showWebsiteUser(session);applyModelStatus(session.provider);$('mode').value='simulation';$('scenario').disabled=$('mode').value==='live';renderMode($('mode').value);const rows=await history();if(rows.length){run=rows[0];selected=currentAgent();render();await history();}await initOperations();}catch(e){error(e);}});

const materialFiles=$('materialFiles');
const webProviderChoices=new Map();
let webProviderLoad=0;
async function refreshWorkbenchSearchProviders(){
 const account=currentAccount()?.id;if(!account)return;const token=++webProviderLoad;
 try{
  const settings=await api('/api/search/settings');if(token!==webProviderLoad||currentAccount()?.id!==account)return;
  const providers=(settings.providers||[]).filter(p=>p.id!=='xhs_local');if(!providers.length)return;
  let preferred=webProviderChoices.get(account);if(!preferred)try{preferred=localStorage.getItem('red.web.provider.'+account);}catch(_){}
  const select=$('webSearchProvider');for(const option of Array.from(select.options||[])){const p=providers.find(p=>p.id===option.value);option.disabled=!p?.can_attempt;option.textContent=({bing:'Bing 公开网页',baidu:'百度 AI 搜索',wikipedia:'百科背景资料'})[option.value]+(p?.can_attempt?'':' · 未启用');}
  const available=providers.filter(p=>p.can_attempt);select.value=available.find(p=>p.id===preferred)?.id||available.find(p=>p.id==='baidu')?.id||available[0]?.id||'';
 }catch(_){}
}
$('webSearchProvider').onchange=()=>{const account=currentAccount()?.id;if(!account)return;webProviderChoices.set(account,$('webSearchProvider').value);try{localStorage.setItem('red.web.provider.'+account,$('webSearchProvider').value);}catch(_){}};
function fillPublicSearchQueries(){
 // 只自动填第一组：第二组以前固定拼“事实 资料”，搜索服务忽略后缀、返回同一批链接，两组就长得一模一样。
 // 第二组改为留给用户自己填不同方向（可选），空着不发送。
 const topic=$('topic').value.trim().slice(0,90),values=[topic,''];
 ['webQuery1','webQuery2'].forEach((id,index)=>{if(!editedWebQueries.has(id)&&(!$(id).value||$(id).value===generatedWebQueries[index]))$(id).value=values[index];});generatedWebQueries=values;
}
function syncNewResearchChoice(){
 const live=$('mode').value==='live';$('useWebResearch').checked=live&&webResearchPreference!==false;$('webResearchFields').hidden=!$('useWebResearch').checked;
 if($('useWebResearch').checked)fillPublicSearchQueries();
}
$('useWebResearch').onchange=()=>{
 if($('mode').value!=='live'){$('useWebResearch').checked=false;$('webResearchFields').hidden=true;return;}
 webResearchPreference=$('useWebResearch').checked;$('webResearchFields').hidden=!webResearchPreference;if(webResearchPreference)fillPublicSearchQueries();
};
$('topic').addEventListener('input',()=>{if($('useWebResearch').checked)fillPublicSearchQueries();});
for(const id of ['webQuery1','webQuery2'])$(id).addEventListener('input',()=>editedWebQueries.add(id));
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

$('mode').onchange=()=>{syncNewResearchChoice();renderMode($('mode').value);$('scenario').disabled=$('mode').value==='live';};
setInterval(async()=>{
 if(!run?.in_flight||polling)return;
 polling=true;
 try{const latest=await api('/api/runs/'+run.run_id);if(run?.run_id===latest.run_id){const changed=run.status_version!==latest.status_version;run=latest;render();if(changed){if(!run.in_flight){selected=currentAgent();const last=run.node_runs.at(-1);if(last){selected=last.agent;detailStage=last.stage;toast('本步完成：'+(creationStageLabels[last.stage]||last.stage));}render();}await history();}}}
 catch(_){}finally{polling=false;}
},1500);

function applyModelStatus(value){
 provider=value;
 const message=provider.ready?provider.message:'尚未连接可用模型。可继续免费模拟，或前往“连接与设置 → 模型与搜索设置”选择厂商，填写模型、API Key 和连接地址；保存并用于新任务后，可测试连接（可能计费）。';
 $('configMessage').textContent=message+' · 整单最多'+(provider.run_attempts_max??16)+'次 / '+(provider.run_tokens_max??80000).toLocaleString()+' Token';
 $('configureModelConnection').hidden=Boolean(provider.ready);
 $('liveOption').disabled=!provider.ready;
 $('liveOption').textContent=provider.ready?'真实 AI · '+provider.model+'（消耗接口额度）':'真实 AI（请配置模型连接）';
 $('connectionStatus').textContent=(provider.provider||'模型')+'：'+(provider.ready?'已配置':'未配置');
}
async function refreshModelStatus(){const session=await api('/api/session');applyModelStatus(session.provider);websiteSession=session;csrf=session.csrf;}
