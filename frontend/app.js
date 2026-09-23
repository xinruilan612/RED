'use strict';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names={audience:'受众与竞品洞察',research:'热点与证据研究',content:'内容策划创作',reviewer:'主编审核',human:'人工处理 / 确认'};
const stages={analysis:'分析',audience:'受众分析',research:'素材分析',quick:'极速初稿',strategy:'策略',outline:'提纲',hook:'开头',title:'标题',body:'正文',revise:'按意见改稿',review:'审核'};
const states={QUEUED:'准备开始',RUNNING:'可以继续执行',WAITING_USER:'等待你的决定',SUCCEEDED:'已确认完成',CANCELLED:'已取消',FAILED:'执行失败',RETRY_WAIT:'等待重试',EXPIRED:'已过期'};
const checks={brief_fit:'符合需求',audience_fit:'受众相关',usefulness_and_readability:'实用与易读',title_body_alignment:'标题与正文一致',evidence_integrity:'证据完整',experience_authenticity:'经历真实',originality_risk:'原创风险',privacy_and_policy:'隐私与规则'};
let provider=null,polling=false;
let csrf='',run=null,selected='audience',busy=false,auto=false,editing=false,viewVersion=null,detailStage=null,toastTimer;
async function api(path,method='GET',body){
 const r=await fetch(path,{method,headers:method==='POST'?{'Content-Type':'application/json','X-CSRF-Token':csrf}:{},body:body===undefined?undefined:JSON.stringify(body)});
 const data=await r.json(); if(!r.ok)throw new Error(data.error?.message||'请求失败');return data;
}
function error(e){$('error').textContent=e.message||String(e);$('error').hidden=false;}
function clearError(){$('error').hidden=true;}
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3500);}
function json(value){return '<pre class="json">'+esc(JSON.stringify(value,null,2))+'</pre>';}
function dirtyGuard(){return !editing||window.confirm('有尚未保存的编辑，确定放弃吗？');}
async function history(){
 const rows=(await api('/api/runs')).filter(r=>typeof matchesAccount!=='function'||matchesAccount(r));
 $('history').innerHTML=rows.length?rows.map(r=>`<button data-run="${esc(r.run_id)}" class="${run?.run_id===r.run_id?'selected':''}">${esc(r.context.topic||'旧任务')}<small>${esc(states[r.run_status])} · ${r.drafts.length} 个版本</small></button>`).join(''):'<p class="helper">还没有创作记录</p>';
 return rows;
}
function currentAgent(){if(!run)return 'audience';if(run.run_status==='WAITING_USER'||run.run_status==='SUCCEEDED')return 'human';if(run.current_stage==='brief')return run.context.workflow==='quick'?'content':'audience';return run.current_stage;}
function renderMode(mode){
 const live=mode==='live';
 const workflow=$('workbench')?.hidden?$('workflow')?.value:run?.context?.workflow;
 const quick=workflow==='quick';
 $('modeBadge').textContent=live?'真实 AI · DeepSeek':'模拟运行';
 $('studioRouteSummary').textContent=quick?'极速生成与独立审核 · 发布后由分析角色复盘':'四个创作角色协作 · 发布后由分析角色复盘';
 $('modeNotice').textContent=live?(quick?'内容生成与独立审核各调用一次 DeepSeek；用量可查看，事实仍需核查，最终由你确认。':'四个角色调用 DeepSeek；每次输出与用量可查看。可结合账号资料与已读取来源；事实仍需核查，最终由你确认。'):'这是免费模拟流程，使用固定模板和本地规则，没有调用真实 AI。';
 $('detailMode').textContent=live?'真实 AI 产物':'模拟产物';
}
function render(){
 if(!run)return;
 renderMode(run.mode);
 $('modelCalls').textContent=(run.usage?.model_calls||0)+' 次';
 $('modelCost').textContent=run.mode==='live'?'≤ $'+Number(run.usage.cost_upper_estimate_usd||0).toFixed(4)+' 估算':'¥0.00（模拟）';
 if(run.run_status==='FAILED'){const last=run.events.filter(e=>e.type==='agent.failed').at(-1);error(new Error(last?.payload.message||'执行失败，请查看运行记录'));}
 document.querySelector('.entry-paths').hidden=true;$('welcome').hidden=true;$('workbench').hidden=false;
 $('runTitle').textContent=run.context.topic;
 $('runSummary').textContent=`${run.context.operations?.platform==='douyin'?'抖音':'小红书'} · ${(run.context.operations?.format||(run.context.operations?.platform==='douyin'?'video':'image_text'))==='video'?'视频脚本（非成片）':'图文笔记'} · 写给 ${run.context.audience} · ${run.context.tone} · ${run.snapshot_id.slice(0,8)} 输入快照`;
 const background=run.background;
 const jobLabels={queued:background?.worker_online?'已排队，后台即将执行':'已排队，等待 Worker 启动',running:'后台执行中 · 关闭页面后继续',pausing:'正在暂停，等待当前节点保存',paused:'后台已暂停',blocked:'后台等待处理',waiting:'等待你的审核'};
 $('statusLabel').textContent=jobLabels[background?.status]|| (run.in_flight?'AI 正在处理，请稍候':states[run.run_status]);
 if(background?.error)error(new Error(background.error));$('versionCount').textContent=run.drafts.length+' 个';
 const allowed=run.allowed_actions;
 $('recover').hidden=!allowed.includes('recover');$('next').hidden=!allowed.includes('next');$('auto').hidden=!allowed.includes('next');$('cancel').hidden=!allowed.includes('cancel');
 $('next').textContent=run.current_stage==='reviewer'?'执行复审 / 审核 →':run.review?.decision==='revision_required'?'按意见改稿 →':'执行下一步 →';
 $('auto').textContent=background?(run.in_flight?'暂停后台任务':'后台运行到人工处理'):(auto?'停止自动运行':'自动运行到人工处理');
 if(background){$('next').hidden=true;$('auto').hidden=!allowed.includes('next')&&!run.in_flight;}
 const node=(key,num,sub)=>{
 const logs=run.node_runs.filter(n=>n.agent===key&&n.snapshot_id===run.snapshot_id);
 const isCurrent=(key===currentAgent()||(run.current_stage==='brief'&&key==='research'&&run.run_status!=='WAITING_USER'))&&!['SUCCEEDED','CANCELLED','FAILED'].includes(run.run_status);
 const done=key==='human'?run.run_status==='SUCCEEDED':logs.length>0;
 const human=key==='human'&&run.run_status==='WAITING_USER';
 const label=human?'◈ 等你处理':isCurrent?'◉ 当前步骤':done?'✓ 已有产物':'○ 尚未执行';
 return `<button class="node ${isCurrent?'current':''} ${done?'done':''} ${human?'human':''} ${selected===key?'selected':''}" data-agent="${key}" aria-pressed="${selected===key}"><span class="node-top"><span>${key==='human'?'由你决定':'AGENT '+num}</span><span>${label}</span></span><b>${names[key]}</b><small>${sub}</small></button>`;
 };
 const quick=run.context.workflow==='quick';
 const contentStages=(quick?['quick']:['strategy','outline','hook','title','body']).map(s=>`<button class="stage-chip ${run.artifacts.some(a=>a.stage===s)?'done':''}" data-stage="${s}">${stages[s]}</button>`).join('');
 const professionalStart=`<div class="parallel">${node('audience','01','理解读者 · 明确假设')}${node('research','02','收录素材 · 标记缺口')}</div><div class="connector">同一份需求 · 并行分析<span>↓ 汇合 ↓</span></div>`;
 $('flow').innerHTML=(quick?'':professionalStart)+node('content',quick?'01':'03',quick?'一次完成可读初稿':'策略与写作 · 同一角色负责返修')+`<div class="stages">${contentStages}</div><div class="connector"><span>↓</span></div>${node('reviewer',quick?'02':'04','独立检查 · 问题定位 · 再次审核')}<div class="connector">不通过 ↺ 回到创作 / 通过 ↓</div>${node('human','YOU','改稿 / 比较版本 / 最后确认')}`;
 renderDetails();renderHuman();renderDraft();renderTimeline();renderCalls();
 document.querySelectorAll('#workbench button').forEach(b=>{if(!b.closest('#flow')&&b.id!=='auto')b.disabled=busy||(b.dataset.titleChoice!==undefined&&run.artifacts.find(a=>a.stage==='title')?.value.candidates[Number(b.dataset.titleChoice)]===run.drafts.at(-1)?.content.selected_title);});
 $('cancel').disabled=busy&&!run.in_flight;
 if(background&&run.in_flight){for(const id of ['editButton','accept','revise','recover'])$(id).disabled=true;}
 if(editing){$('next').disabled=true;$('auto').disabled=true;$('accept').disabled=true;$('revise').disabled=true;$('editButton').disabled=true;}
 else $('auto').disabled=busy&&!auto;
}
function friendly(agent,stage,value){
 const p=text=>'<p class="readable">'+esc(text)+'</p>';
 const list=items=>'<ol class="readable">'+items.map(t=>'<li>'+esc(t)+'</li>').join('')+'</ol>';
 if(agent==='audience')return p('目标读者：'+value.primary_audience)+p('可用历史作品：'+(value.sample_size||0)+' 条 · 可信程度：低（待验证）')+p(value.basis)+list(value.content_opportunities||[])+(value.competitor_observations?.length?'<h3>同类账号观察 · 用户记录</h3>'+list(value.competitor_observations.map(c=>c.name+'：'+c.observation)):'');
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
 $('details').innerHTML='<div class="detail-block"><h3>最后决定由你做</h3><p>修改会创建新版本，必须再次审核。只有你确认准确版本后才能导出。</p></div>'+ (run.accepted_ref?'<p>✓ 已确认版本 '+esc(run.accepted_ref.slice(0,8))+'</p>':'<p class="muted">尚未确认任何版本。</p>');return;
 }
 const logs=run.node_runs.filter(n=>n.agent===selected);
 if(!logs.length){$('details').innerHTML='<div class="empty">这个角色还没有执行。<br>启动运行后，可以查看它的输入和产物。</div>';return;}
 const matches=detailStage?logs.filter(n=>n.stage===detailStage):logs;
 if(!matches.length){$('details').innerHTML='<div class="empty">这个创作阶段还没有执行。</div>';return;}
 const current=matches[matches.length-1];
 $('details').innerHTML=`${selected==='content'&&run.drafts.length>1?'<p class="editor-note">这些是生成时保存的阶段记录。最新修改后的稿件，请查看下方“文案与版本对比”。</p>':''}<p class="muted">最近阶段：${esc(stages[current.stage])} · ${current.duration_ms} ms · 真实模型调用 ${current.model_calls||0} 次 · ${current.tokens??'未知'} Token</p><div class="detail-block"><h3>当前产物</h3>${friendly(current.agent,current.stage,current.output)}<details><summary>查看原始结构化记录</summary>${json(current.output)}</details></div><details><summary>查看这一阶段的输入</summary>${json(current.input)}</details><div class="detail-block"><h3>工具与记忆</h3><p>${run.context.evidence?.length?'已使用资料检索快照，来源与片段可在本阶段输入中查看。':'本次未使用检索片段。'}${esc(current.memory)}</p><p>${run.mode==='live'?'由 DeepSeek 生成；审核不代表外部事实已核实。':'采用固定模板 / 本地规则，未使用模型推理。'}</p></div>${logs.length>1?'<details><summary>所有阶段与历史记录（'+logs.length+'）</summary>'+logs.map(l=>'<h3>'+esc(stages[l.stage])+' · '+esc(l.snapshot_id.slice(0,8))+'</h3>'+friendly(l.agent,l.stage,l.output)).join('')+'</details>':''}`;
 if(selected==='reviewer'&&run.review){$('details').insertAdjacentHTML('afterbegin',run.review.checks.map(c=>`<div class="review-check"><span>${esc(checks[c.name])}</span><span class="${esc(c.result)}">${c.result==='pass'?(run.mode==='live'?'模型判断通过':'模拟通过'):c.result==='fail'?'发现问题':'未完成'}</span></div>`).join(''));}
}
function renderHuman(){
 const allowed=run.allowed_actions,review=run.review;
 const revision=review?.decision==='revision_required';
 const visible=run.run_status==='WAITING_USER'||revision||run.run_status==='SUCCEEDED';
 $('humanPanel').hidden=!visible;
 $('supplyForm').hidden=!allowed.includes('supplement');
 $('revise').hidden=!(revision&&allowed.includes('next'));
 $('editButton').hidden=!allowed.includes('edit');$('accept').hidden=!allowed.includes('accept');$('export').hidden=!allowed.includes('export');
 $('export').href=`/api/runs/${run.run_id}/export`;
 $('sendToPublish').hidden=run.run_status!=='SUCCEEDED';
 let title='需要你的决定',message='';
 if(run.run_status==='SUCCEEDED'){title='这个版本，已由你确认';message='可以下载已确认稿件。审核不能保证事实正确，发布前仍需你检查。';}
 else if(run.wait_reason==='missing_material'){title='资料还不够，请补充';message='请提供缺失的真实素材。保存后，两个分析角色会使用新快照重新执行。';}
 else if(run.wait_reason==='hypothesis_permission'){title='没有历史数据，需要你选择';message='本次账号快照没有可用的历史指标。可以允许明确标注的假设模式；也可取消任务，导入历史指标后新建创作。';}
 else if(run.wait_reason==='revision_limit'){title='已达到自动改稿上限';message='没有自动通过。请查看未解决的问题，取消本任务后带着补充资料新建任务。';}
 else if(revision){title='主编发现了问题，你可以介入';message='选择自动改稿，或亲自修改。两种方式都会保存新版本，然后再次审核。';}
 else if(allowed.includes('accept')){title='审核结束，最后由你决定';message='请检查正文与素材。你可以先修改，也可以确认当前版本；修改后必须重新审核。';}
 if(run.run_status==='WAITING_USER'&&['missing_material','hypothesis_permission'].includes(run.wait_reason)&&!allowed.includes('supplement')){title='已达到本轮补充上限';message='已有记录会保留。请取消本任务，带着完整资料新建创作。';}
 $('humanTitle').textContent=title;$('humanMessage').textContent=message;
 $('issues').innerHTML=(review?.human_questions||[]).map(q=>'<p class="issue">'+esc(q)+'</p>').join('')+(review?.issues||[]).map(i=>`<div class="issue"><b>${esc(({selected_title:'标题',body:'正文',cta:'互动引导',tags:'标签'})[i.location]||i.location)} · ${esc(i.excerpt)}</b><p>${esc(i.reason)}</p><p>修改建议：${esc(i.suggestion)}</p></div>`).join('');
}
function draftHTML(d,index,changed=false){const c=d.content;return `<article class="draft-copy ${changed?'changed':''}"><span class="version-tag">版本 ${index+1} · ${d.actor==='user'?'你手动修改':run.mode==='live'?'AI 创作':'模拟创作'} · ${esc(d.ref.slice(0,8))}${run.accepted_ref===d.ref?' · 已确认':''}</span><h3>${esc(c.selected_title)}</h3><pre>${esc(c.body)}</pre><p>${esc(c.cta)}</p><div>${(c.tags||[]).map(t=>'<span class="tag">#'+esc(t)+'</span>').join('')}</div></article>`;}
function renderDraft(){
 $('draftPanel').hidden=!run.drafts.length;if(!run.drafts.length)return;
 if(viewVersion===null||viewVersion>=run.drafts.length)viewVersion=run.drafts.length-1;
 $('versionSelect').innerHTML=run.drafts.map((d,i)=>`<option value="${i}" ${i===viewVersion?'selected':''}>版本 ${i+1}${run.accepted_ref===d.ref?' · 已确认':''}</option>`).join('');
 const i=viewVersion,d=run.drafts[i],prev=run.drafts[i-1];
 const changes=prev?['selected_title','body','cta','tags'].filter(k=>JSON.stringify(prev.content[k])!==JSON.stringify(d.content[k])).map(k=>({selected_title:'标题',body:'正文',cta:'互动引导',tags:'标签'})[k]):[];
 $('draftView').innerHTML=(prev?'<p class="change-summary">与上一版相比：'+(changes.length?'修改了 '+changes.join('、'):'文字内容未变化')+'。左侧旧稿，右侧当前所选稿。</p><div class="draft-columns">'+draftHTML(prev,i-1)+draftHTML(d,i,true)+'</div>':draftHTML(d,i));
 const candidates=run.artifacts.find(a=>a.stage==='title')?.value;
 if(candidates&&run.allowed_actions.includes('edit')&&!editing)$('draftView').insertAdjacentHTML('beforeend','<details><summary>比较候选标题 / 选择后重新审核</summary>'+candidates.candidates.map((t,n)=>`<div class="candidate-row"><div><b>${esc(t)}</b><p class="muted">${esc(candidates.reasons?.[n]||'历史版本未记录理由')}</p></div><button data-title-choice="${n}" ${t===run.drafts.at(-1).content.selected_title?'disabled':''}>选用并复审</button></div>`).join('')+'</details>');
}
$('draftView').onclick=async e=>{const b=e.target.closest('[data-title-choice]');if(!b||busy||editing)return;const title=run.artifacts.find(a=>a.stage==='title')?.value.candidates[Number(b.dataset.titleChoice)];if(title&&title!==run.drafts.at(-1).content.selected_title&&await act('edit',{...run.drafts.at(-1).content,selected_title:title})){viewVersion=null;render();toast('标题另存为新版本，请重新审核正文是否匹配');}};
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
 if(action==='next'&&websiteSession?.auth_required)return backgroundCommand('start');
 if(busy||!run)return false;busy=true;clearError();if(action==='next'&&run.mode==='live')run.in_flight=true;render();
 try{run=await api(`/api/runs/${run.run_id}/actions`,'POST',{action,version:run.status_version,key:crypto.randomUUID(),payload});clearError();viewVersion=null;selected=currentAgent();detailStage=null;if(action==='edit'){ops=await api('/api/operations');syncAccounts();}await history();return true;}
 catch(e){auto=false;error(e);try{run=await api('/api/runs/'+run.run_id);}catch(_){}return false;}
 finally{busy=false;render();}
}
async function backgroundCommand(action){
 if(busy||!run)return false;
 busy=true;clearError();render();
 try{run=await api(`/api/runs/${run.run_id}/background`,'POST',{action,version:run.status_version,key:crypto.randomUUID()});await history();return true;}
 catch(e){error(e);try{run=await api('/api/runs/'+run.run_id);}catch(_){}return false;}
 finally{busy=false;render();}
}
async function autoRun(){
 if(websiteSession?.auth_required)return backgroundCommand(run.in_flight?'pause':'start');
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
 try{run=await api('/api/runs','POST',{...(websiteSession?.auth_required?{knowledge:{enabled:$('useKnowledge').checked}}:{}),mode:$('mode').value,workflow:$('workflow').value,topic:$('topic').value,audience:$('audience').value,tone:$('tone').value,material:$('material').value,scenario:$('scenario').value,allow_hypothesis:$('hypothesis').checked,operations:{platform:$('targetPlatform').value,account_id:currentAccount()?.id,account:$('accountName').value,trend_id:chosenTrend?.id||null,...experimentCreationFields(),promotion_brief_id:chosenPromotion?.id||null}});selected=currentAgent();detailStage=null;viewVersion=null;editing=false;$('editor').hidden=true;render();await history();}
 catch(err){error(err);}finally{busy=false;e.submitter.disabled=false;if(run&&!$('workbench').hidden)render();}});
$('history').addEventListener('click',async e=>{const b=e.target.closest('[data-run]');if(!b||busy||!dirtyGuard())return;auto=false;editing=false;$('editor').hidden=true;clearError();showPage('studio');try{run=await api('/api/runs/'+b.dataset.run);viewVersion=null;detailStage=null;selected=currentAgent();render();await history();}catch(err){error(err);}});
$('newRun').onclick=()=>{if(busy||!dirtyGuard())return;if(chosenExperiment){chosenExperiment=null;$('selectedTrend').hidden=true;$('clearTrend').hidden=true;}showPage('studio');auto=false;editing=false;$('editor').hidden=true;$('workbench').hidden=true;document.querySelector('.entry-paths').hidden=false;$('welcome').hidden=false;renderMode($('mode').value);fillAccountBrief();clearError();};
$('flow').onclick=e=>{const chip=e.target.closest('[data-stage]');const b=e.target.closest('[data-agent]');if(chip){selected='content';detailStage=chip.dataset.stage;render();}else if(b){selected=b.dataset.agent;detailStage=null;render();}};
$('recover').onclick=()=>act('recover');
$('next').onclick=()=>act('next');$('auto').onclick=autoRun;
$('cancel').onclick=async()=>{
 if(!window.confirm('取消当前任务？已有版本会保留。已发送给模型的请求可能仍产生费用。'))return;
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
$('editor').onsubmit=async e=>{e.preventDefault();const data={selected_title:$('editTitle').value,body:$('editBody').value,cta:$('editCta').value,tags:$('editTags').value.split(/[,，]/).map(x=>x.trim()).filter(Boolean)};if(await act('edit',data)){editing=false;$('editor').hidden=true;render();toast('新版本已保存。请启动后台运行，重新审核。');}};
$('accept').onclick=async()=>{if(await act('accept',{draft_ref:run.drafts.at(-1).ref,review_ref:run.review.ref}))toast('已确认当前版本，可以下载。');};
$('supplyForm').onsubmit=async e=>{e.preventDefault();if(await act('supplement',{material:$('supply').value,allow_hypothesis:$('supplyHypothesis').checked}))toast('补充已保存，请启动运行重新分析。');};
$('versionSelect').onchange=e=>{viewVersion=Number(e.target.value);renderDraft();};
window.addEventListener('beforeunload',e=>{if(editing){e.preventDefault();e.returnValue='';}});
document.addEventListener('DOMContentLoaded',async()=>{try{const session=await api('/api/session');csrf=session.csrf;if(session.auth_required&&!session.user){showLogin(session);return;}showWebsiteUser(session);provider=session.provider;$('configMessage').textContent=provider.message+' · 同一步最多3次（含首次）；接口错误立即停；整单最多16次 / 40000 Token';$('liveOption').disabled=!provider.ready;$('liveOption').textContent=provider.ready?'真实 AI · DeepSeek（消耗接口额度）':'真实 AI · DeepSeek（先填写 .env）';$('connectionStatus').textContent='DeepSeek：'+(provider.ready?'已配置':'未配置');$('mode').value='simulation';$('scenario').disabled=$('mode').value==='live';renderMode($('mode').value);const rows=await history();if(rows.length){run=rows[0];selected=currentAgent();render();await history();}await initOperations();}catch(e){error(e);}});

$('mode').onchange=()=>{renderMode($('mode').value);$('scenario').disabled=$('mode').value==='live';};
$('workflow').onchange=()=>renderMode($('mode').value);
setInterval(async()=>{
 if(!run?.in_flight||polling)return;
 polling=true;
 try{const latest=await api('/api/runs/'+run.run_id);if(run?.run_id===latest.run_id){const changed=run.status_version!==latest.status_version;run=latest;if(changed)clearError();render();if(changed)await history();}}
 catch(_){}finally{polling=false;}
},1500);
