'use strict';

pageInfo.windtunnel=['READER CHECK / 读者理解检查','发布前，把关键问题讲清楚。','这是可选的深入检查：带入稿件版本，确认读者问题，再检查并复查。'];

const wt={account:'',runs:[],creationRuns:[],checklists:[],run:null,tab:'input',newDraft:true,loading:0,busy:false,polling:false,message:'',failure:'',batch:'',form:null};
const wtOutcome={pass:['讲清楚了','pass'],unclear:['未讲清楚','fail'],unsupported:['材料不支持','conflict'],insufficient:['证据不足','insufficient']};
const wtOriginLabels={author:'作者设定',feedback:'有来源的问题',historical_feedback:'历史读者反馈',pilot_feedback:'本次预试读反馈',user_hypothesis:'作者设定',manual:'作者设定',demo:'虚构演示',simulation:'虚构演示'};

function wtFreshForm(){return {mode:'live',title:'',text:'',scene:'第一次使用这项工具、希望独立完成操作的读者',material:'',materialTitle:'操作说明与事实材料',feedback:'',feedbackOrigin:'作者手动提供',origin:'user_hypothesis',permission:false,inputMode:'paste',importRun:'',importRef:'',importMaterials:[],bridge:null,checklist:''};}
let wtReaderRequest=0;
function wtReaderSignature(source,draftRef){
 const draft=source?.drafts?.find(d=>d.ref===draftRef);
 return draft?JSON.stringify({id:source.run_id,account:source.context?.operations?.account_id,snapshot:source.snapshot_id,version:source.status_version,refs:source.drafts.map(d=>d.ref),draft}):null;
}
function wtReaderMaterials(source){
 const context=source.context||{},materials=[];
 const append=(text,title,origin)=>{
  if(typeof text!=='string'||!text.trim())return;
  const characters=Array.from(text);
  for(let offset=0;offset<characters.length;offset+=6000){
   const completeOrigin=String(origin)+(characters.length>6000?` · 原文字符 ${offset}–${Math.min(offset+6000,characters.length)}`:'');
   if(Array.from(completeOrigin).length>500)throw new Error('材料链接或定位信息超过本次检查的来源字段容量，无法完整带入。请在读者理解检查中手动选择材料；未截断来源或创建任务。');
   materials.push({text:characters.slice(offset,offset+6000).join(''),title:String(title||'创作资料快照').slice(0,500),origin:completeOrigin});
  }
 };
 append(context.material,'创作时手工材料','作者提供 · 创作输入快照，未独立核实');
 for(const evidence of context.evidence||[]){
  const locator=[evidence.document_id?`资料 ${evidence.document_id}`:'',evidence.version!=null?`v${evidence.version}`:'',evidence.page!=null?`页 ${evidence.page}`:'',evidence.offset!=null?`位置 ${evidence.offset}`:'',evidence.source_id,evidence.url||evidence.source_url].filter(Boolean).join(' · ');
  append(evidence.text,evidence.title||'创作检索片段',`创作检索快照 · 原文未独立核实${locator?' · '+locator:''}`);
 }
 if(materials.length>20||materials.reduce((sum,item)=>sum+Array.from(item.text).length,0)>24000)throw new Error('创作材料超过本次检查的容量，请在读者理解检查中手动选择材料；没有自动截断或创建任务。');
 return materials;
}
async function openDraftReaderCheck(sourceRun,draftRef){
 const account=activeAccountId,page=currentPage,request=++wtReaderRequest;
 const signature=wtReaderSignature(sourceRun,draftRef);
 if(!account||sourceRun?.context?.operations?.account_id!==account||!['creation',undefined].includes(sourceRun?.workflow_type)||!signature){error(new Error('请选择当前账号可访问的准确稿件版本。'));return false;}
 if(wt.busy||!dirtyGuard())return false;
 const viewed=typeof run!=='undefined'&&run?.run_id===sourceRun.run_id;
 const selectedVersion=typeof viewVersion!=='undefined'?viewVersion:null;
 try{
  const latest=await api('/api/runs/'+encodeURIComponent(sourceRun.run_id));
  if(request!==wtReaderRequest||account!==activeAccountId||page!==currentPage)return false;
  if(!['creation',undefined].includes(latest?.workflow_type)||wtReaderSignature(sourceRun,draftRef)!==signature||wtReaderSignature(latest,draftRef)!==signature||(viewed&&(run?.run_id!==sourceRun.run_id||wtReaderSignature(run,draftRef)!==signature))||(viewed&&typeof viewVersion!=='undefined'&&viewVersion!==selectedVersion)){error(new Error('稿件或所选版本已变化，请回到创作页重新选择后检查。'));return false;}
  const draft=latest.drafts.find(d=>d.ref===draftRef),content=draft.content;
  const form={...wtFreshForm(),inputMode:'import',importRun:latest.run_id,importRef:draftRef,title:content.selected_title,text:[content.body,content.cta,(content.tags||[]).join(' ')].filter(Boolean).join('\n\n'),scene:(latest.context.audience||currentAccount()?.profile?.audience||'这篇内容的目标读者').slice(0,500),importMaterials:wtReaderMaterials(latest),bridge:{runId:latest.run_id,ref:draftRef,signature}};
  wt.loading++;wt.account=account;wt.run=null;wt.runs=[];wt.creationRuns=[latest];wt.newDraft=true;wt.tab='input';wt.batch='';wt.form=form;wt.failure='';
  wt.message=`已带入版本 ${latest.drafts.indexOf(draft)+1} 和创作资料快照。先确认适用读者与问题，再主动保存；不会自动启动检查。`;
  window.activeTrialHypothesisId=null;
  showPage('windtunnel');return true;
 }catch(err){if(request===wtReaderRequest&&account===activeAccountId&&page===currentPage)error(err);return false;}
}
function wtAllowed(action){return (!wt.run?.in_flight||['cancel','export'].includes(action))&&(wt.run?.allowed_actions||[]).includes(action);}
function wtData(){return wt.run?.windtunnel||{};}
function wtDraft(){return (wtData().drafts||[]).at(-1)||{};}
function wtSet(){const d=wtData();return (d.condition_sets||[]).find(s=>s.id===d.current_set_id)||(d.condition_sets||[]).at(-1)||{};}
function wtCards(){return wtSet().conditions||wtSet().cards||[];}
function wtReports(){return wtData().reports||[];}
function wtReport(){return wtReports().find(r=>(r.id||r.batch_id)===wt.batch)||wtReports().at(-1);}
function wtState(status){return wtOutcome[status]?`<span class="wt-state ${wtOutcome[status][1]}">${wtOutcome[status][0]}</span>`:`<span class="wt-state">${esc(status==='blocked'?'执行受阻，未得出结论':status||'待检查')}</span>`;}
function wtTitle(r){return r?.windtunnel?.drafts?.at(-1)?.title||r?.context?.topic||'未命名教程';}
function wtTime(value){return value?new Date(typeof value==='number'?value*1000:value).toLocaleString('zh-CN',{hour12:false}):'已保存';}
function wtEmpty(title,text){return `<div class="wt-empty"><span aria-hidden="true">◈</span><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;}
function wtBelongs(r,account){return (r.windtunnel?.account_id||r.context?.operations?.account_id||r.context?.account_id)===account;}
function wtNotice(){const h=(ops?.hypotheses||[]).find(x=>x.id===window.activeTrialHypothesisId),live=(wt.run?.context?.mode||wt.form?.mode||'live')==='live';return `<div class="wt-notice" role="note"><span aria-hidden="true">◈</span><div><strong>${live?'真实 AI 检查 · 主动启动后调用已配置模型并计费':'开发模拟 · 不调用模型，不计真实试读'}</strong><p>${live?'稿件和所选材料会交给模型检查，调用与费用保留记录。AI 的阅读检查不能代替真实读者反馈，也不能预测平台流量。':'仅供检查操作流程；结果不用于证明读者理解或增长效果。'}</p></div></div>`+(h?`<div class="notice"><strong>关联改进：</strong>${esc(h.statement)}</div>`:'');}


async function renderWindtunnel(){
 const account=activeAccountId,request=++wt.loading;
 if(!account){$('operationsContent').innerHTML=wtEmpty('先建立一个运营账号','在账号与历史中创建账号，再保存这次内容检查。');return;}
 if(wt.account!==account){wt.account=account;wt.run=null;wt.runs=[];wt.newDraft=true;wt.tab='input';wt.batch='';wt.form=wtFreshForm();wt.message='';wt.failure='';}
 $('operationsContent').innerHTML='<div class="wt-workspace">'+wtNotice()+'<div class="panel wt-loading" role="status">正在读取当前账号的风洞记录…</div></div>';
 try{
  const result=await Promise.all([api('/api/runs'),api('/api/windtunnel/checklists?account_id='+encodeURIComponent(account))]);
  if(request!==wt.loading||account!==activeAccountId||currentPage!=='windtunnel')return;
  wt.runs=result[0].filter(r=>r.workflow_type==='windtunnel'&&wtBelongs(r,account));
  wt.creationRuns=result[0].filter(r=>r.workflow_type!=='windtunnel'&&wtBelongs(r,account)&&(r.drafts||[]).length);
  wt.checklists=Array.isArray(result[1])?result[1]:result[1].checklists||[];
  if(wt.form?.bridge){const bridge=wt.form.bridge,source=wt.creationRuns.find(r=>r.run_id===bridge.runId);if(wtReaderSignature(source,bridge.ref)!==bridge.signature){wt.form=wtFreshForm();wt.message='';wt.failure='源稿件已变化，没有导入旧选择。请回到创作页重新选择版本。';}}
  if(wt.run)wt.run=wt.runs.find(r=>r.run_id===wt.run.run_id)||null;
  wtPaint();
 }catch(err){if(request!==wt.loading||account!==activeAccountId||currentPage!=='windtunnel')return;wt.failure=err.message;wtPaint();}
}

function wtPaint(){
 if(currentPage!=='windtunnel'||wt.account!==activeAccountId)return;
 wt.form=wt.form||wtFreshForm();
 const selected=wt.run&&!wt.newDraft;
 $('operationsContent').innerHTML=`<div class="wt-workspace">${wtNotice()}<div class="wt-topbar"><div><h2>读者理解检查</h2><p class="helper">${esc(currentAccount()?.name||'当前账号')} · 可选检查，不是创作和导出的必经步骤</p></div><button class="primary" data-wt="new" ${wt.busy?'disabled':''}>＋ 新建检查</button></div>${wt.failure?`<div class="wt-error" role="alert"><strong>这一步没有完成</strong><p>${esc(wt.failure)}</p><button class="quiet wt-muted-button" data-wt="refresh">重新读取记录</button></div>`:''}${wt.message?`<p class="wt-inline-message" role="status">${esc(wt.message)}</p>`:''}<div class="wt-layout"><aside class="wt-sidebar"><h3>我的检查 <span class="wt-count">${wt.runs.length} 次</span></h3><div class="wt-projects">${wt.runs.map(r=>`<button class="wt-project" data-wt="open" data-id="${esc(r.run_id)}" aria-current="${selected&&wt.run.run_id===r.run_id}"><strong>${esc(wtTitle(r))}</strong><small>${esc(states[r.run_status]||r.run_status)} · ${(r.windtunnel?.drafts||[]).length} 个稿件版本</small></button>`).join('')||'<p class="wt-empty-note">每篇稿件单独保留问题、来源和修改记录，刷新后可以继续。</p>'}</div></aside><div class="wt-main">${selected?wtWorkspace():wtCreateForm()}</div></div></div>`;
 if(!selected&&wt.form.importMaterials?.length)$('wtCreateForm')?.insertAdjacentHTML('afterbegin',wtImportMaterialsPreview());
 wtBind();
}

function wtImportMaterialsPreview(){return `<details class="wt-reuse"><summary>已带入 ${wt.form.importMaterials.length} 段创作资料快照 · 查看出处</summary><p class="helper">这是创作时保存的材料，不代表已经核实。下方可以另外补充材料；切换导入稿件或版本会清除这些快照。</p>${wt.form.importMaterials.map(s=>`<article class="wt-source"><h3>${esc(s.title)}</h3><p class="helper">${esc(s.origin)}</p><pre>${esc(s.text)}</pre></article>`).join('')}</details>`;}

function wtCreateForm(){
 const active=wt.runs.find(r=>!['SUCCEEDED','FAILED','CANCELLED','EXPIRED'].includes(r.run_status));
 if(active)return `<section class="panel"><h2>继续上次检查</h2><p>「${esc(wtTitle(active))}」还没结束。已保存的稿件和进度都在，先继续或在其中取消，再新建检查。</p><button class="primary" data-wt="open" data-id="${esc(active.run_id)}">打开这次检查 →</button></section>`;
 const f=wt.form,sourceRun=wt.creationRuns.find(r=>r.run_id===f.importRun),drafts=sourceRun?.drafts||[];
 return `<section class="panel"><div class="wt-heading"><div><span class="wt-kicker">01 / 准备一篇教程</span><h2>读者要完成什么？</h2><p>先放入稿件，再分别提供事实材料与读者问题。</p></div><span class="pill neutral">资料只属于当前账号</span></div><form id="wtCreateForm"><label>检查方式</label><select data-wt-field="mode"><option value="live" ${f.mode!=='simulation'?'selected':''}>真实 AI 检查（使用已配置模型，启动后计费）</option><option value="simulation" ${f.mode==='simulation'?'selected':''}>开发模拟（不作为真实验证）</option></select><label for="wtTitle">教程标题</label><input id="wtTitle" name="title" data-wt-field="title" maxlength="200" ${f.inputMode==='paste'?'required':'disabled'} value="${esc(f.title)}" placeholder="例如：第一次把任务表导出为 CSV"><div class="wt-input-tabs" role="group" aria-label="稿件导入方式"><button type="button" data-wt="input-mode" data-value="paste" aria-pressed="${f.inputMode==='paste'}">粘贴稿件</button><button type="button" data-wt="input-mode" data-value="import" aria-pressed="${f.inputMode==='import'}">导入已有版本</button></div>${f.inputMode==='paste'?`<label for="wtText">待检查正文</label><textarea id="wtText" name="text" data-wt-field="text" rows="8" maxlength="16000" required placeholder="粘贴你真实准备发布的工具教程。">${esc(f.text)}</textarea>`:`<label for="wtImportRun">当前账号的创作记录</label><select id="wtImportRun" data-wt-field="importRun" required><option value="">选择一篇已有稿件</option>${wt.creationRuns.map(r=>`<option value="${esc(r.run_id)}" ${r.run_id===f.importRun?'selected':''}>${esc(r.context?.topic||r.run_id)}</option>`).join('')}</select><label for="wtImportRef">准确稿件版本</label><select id="wtImportRef" data-wt-field="importRef" required><option value="">选择一个固定版本</option>${drafts.map((d,i)=>`<option value="${esc(d.ref)}" ${d.ref===f.importRef?'selected':''}>版本 ${i+1} · ${esc(d.content?.selected_title||'稿件')}</option>`).join('')}</select><p class="helper">导入保存这一版的快照，原创作后续改稿不会自动覆盖它。</p>`}<label for="wtScene">适用读者与使用场景</label><textarea id="wtScene" data-wt-field="scene" rows="2" maxlength="500" required>${esc(f.scene)}</textarea><div class="wt-source-grid"><div><label for="wtMaterials">支持材料</label><textarea id="wtMaterials" data-wt-field="material" rows="5" maxlength="6000" placeholder="粘贴操作说明、工具版本、限制条件等可核实材料。没有就留空。">${esc(f.material)}</textarea><p class="helper">材料用于核实答案，不会给阅读检查步骤直接看答案。</p></div><div><label for="wtFeedback">读者反馈或作者预设的问题</label><textarea id="wtFeedback" data-wt-field="feedback" rows="5" maxlength="2000" placeholder="例如：在哪里选择 UTF-8？找不到导出按钮怎么办？">${esc(f.feedback)}</textarea><label for="wtOrigin">这段问题来自哪里？</label><select id="wtOrigin" data-wt-field="origin"><option value="user_hypothesis" ${f.origin==='user_hypothesis'?'selected':''}>作者设定 · 不是读者反馈</option><option value="pilot_feedback" ${f.origin==='pilot_feedback'?'selected':''}>本次真实预试读反馈</option><option value="historical_feedback" ${f.origin==='historical_feedback'?'selected':''}>有权使用的历史读者反馈</option><option value="demo" ${f.origin==='demo'?'selected':''}>虚构演示 · 不计真实样本</option></select><label for="wtFeedbackOrigin">来源说明（采集方式、时间或原始位置）</label><input id="wtFeedbackOrigin" data-wt-field="feedbackOrigin" maxlength="400" value="${esc(f.feedbackOrigin)}" required></div></div>${wt.checklists.length?`<label for="wtNewChecklist">复用当前账号的已保存条件（可选）</label><select id="wtNewChecklist" data-wt-field="checklist"><option value="">先生成新的候选条件</option>${wt.checklists.map(c=>`<option value="${esc(c.id+':'+c.version)}" ${f.checklist===c.id+':'+c.version?'selected':''}>${esc(c.title)} · v${c.version}</option>`).join('')}</select><p class="helper">来源快照一并带入，你仍需确认适用范围。</p>`:''}<label class="checkbox"><input id="wtPermission" type="checkbox" data-wt-field="permission" ${f.permission?'checked':''} required><span>我有权使用这些稿件、材料及反馈，已移除不必要的个人信息。</span></label><div class="wt-action-bar"><button class="primary" type="submit" ${wt.busy?'disabled':''}>保存稿件，准备问题卡 →</button><button class="quiet" type="button" data-wt="example">填入虚构示例</button><p class="helper">先保存，再由你主动启动检查。示例内容不会计入真实样本。</p></div></form></section>`;
}

function wtWorkspace(){
 return `<div class="wt-heading"><div><span class="wt-kicker">发布前检查</span><h2>${esc(wtTitle(wt.run))}</h2><p>稿件 ${wtDraft().version||wtData().drafts?.length||1} · ${esc(states[wt.run.run_status]||wt.run.run_status)}</p></div>${wtAllowed('export')?`<a class="button secondary" href="/api/runs/${encodeURIComponent(wt.run.run_id)}/export">导出当前版本报告 ↗</a>`:''}</div><ol class="wt-steps" role="tablist" aria-label="内容检查步骤">${[['input','稿件与材料'],['cards','确认问题卡'],['report','检查与修改']].map(([id,label],i)=>`<li role="presentation"><button id="wt-tab-${id}" role="tab" aria-selected="${wt.tab===id}" aria-controls="wtPanel" data-wt="tab" data-tab="${id}"><b>0${i+1}</b>${label}</button></li>`).join('')}</ol><section id="wtPanel" role="tabpanel" aria-labelledby="wt-tab-${wt.tab}">${wt.tab==='input'?wtInputView():wt.tab==='cards'?wtCardsView():wtReportView()}</section>`;
}

function wtInputView(){
 const d=wtDraft(),sources=wtData().sources||[],materials=sources.filter(s=>s.kind==='material'||s.type==='material'),feedback=sources.filter(s=>s.kind!=='material'&&s.type!=='material');
 return `<section class="panel"><div class="wt-heading"><div><span class="wt-kicker">DRAFT / 当前稿件快照</span><h2>${esc(d.title||wtTitle(wt.run))}</h2><p>${esc(wtData().scene||wt.run.context?.audience||'工具使用教程')}</p></div><span class="pill neutral">版本 ${esc(d.version||wtData().drafts?.length||1)}</span></div><div class="wt-reading">${esc(d.text||d.body||'')}</div>${wtAllowed('edit_draft')&&!wt.run.in_flight?`<details><summary>手工保存一个新稿件版本</summary><form id="wtEditDraft"><label for="wtEditText">修改后的正文</label><textarea id="wtEditText" rows="8" maxlength="16000" required>${esc(d.text||d.body||'')}</textarea><p class="helper">保存新版本会要求重新检查；旧稿和旧报告继续留作记录。</p><button class="secondary">保存为新版本</button></form></details>`:''}<div class="buttons"><button class="primary" data-wt="tab" data-tab="cards">查看问题卡 →</button></div></section><section class="panel"><div class="wt-heading"><div><span class="wt-kicker">SOURCES / 原始输入</span><h2>事实材料与读者问题</h2><p>读者提问说明存在疑问，不代表评论本身正确。</p></div></div><div class="wt-source-grid"><div><h3>用于核实的材料</h3>${materials.map(wtSource).join('')||'<p class="helper">暂时没有支持材料。可以先检查正文有没有回答问题，补充资料后再核实答案。</p>'}</div><div><h3>反馈与作者设定</h3>${feedback.map(wtSource).join('')||'<p class="helper">没有历史反馈。当前场景由作者设定。</p>'}</div></div>${wtMaterialsEditor(materials)}</section>`;
}
function wtSource(s){return `<article class="wt-source"><span class="pill neutral">${esc(s.kind==='material'||s.type==='material'?'作者提供的支持材料':wtOriginLabels[s.provenance]||wtOriginLabels[s.origin]||s.origin||'来源待确认')}</span><p>${esc(s.title||'')}</p><p class="helper">${esc(s.origin||'')}</p><pre>${esc(s.text||'')}</pre><small>来源 ${esc((s.id||s.source_id||'').slice(0,12))}${s.collected_at?' · '+esc(wtTime(s.collected_at)):''}</small></article>`;}

function wtCardsView(){
 const cards=wtCards();
 return `<section class="panel"><div class="wt-heading"><div><span class="wt-kicker">02 / 把问题固定下来</span><h2>确认这篇教程需要回答什么</h2><p>候选条件由你调整和确认；没有真实来源的条件会标为作者设定。</p></div><span class="pill neutral">${cards.length} 条条件</span></div>${wtExecution()}${cards.length?`<form id="wtConditions">${cards.map((c,i)=>wtCard(c,i)).join('')}${wtAllowed('edit_conditions')?'<button class="quiet" type="button" data-wt="add-condition">＋ 添加作者设定的条件</button>':''}<div class="wt-action-bar">${wtAllowed('edit_conditions')?'<button class="secondary" type="submit" name="intent" value="edit">保存条件修改</button>':''}${wtAllowed('confirm_conditions')?'<button class="primary" type="submit" name="intent" value="confirm">确认这些条件，固定检查范围 →</button>':''}${wtSet().confirmed?'<p class="helper">条件已确认。同条件复查将复用这一版本；改变条件需要建立新批次。</p>':''}</div></form>`:wtAllowed('set_initial_conditions')?wtInitialConditionsForm():wtEmpty('先生成候选问题','保存稿件后，启动一次后台检查。没有反馈时，候选条件会明确标为作者设定。')}${wtReuseView()}</section>`;
}
function wtInitialConditionsForm(){return `<form id="wtInitialConditions" class="wt-question"><h3>也可以自己写一个检查问题</h3><p>不必重建稿件，也不需要再次调用 AI 来生成问题卡。这里记录的是你设定的问题，之后仍由你确认。</p><label for="wtInitialQuestion">希望读者看完后能回答什么？</label><textarea id="wtInitialQuestion" rows="2" maxlength="500" required placeholder="例如：读完后，新手能说清早间洗脸后先做什么吗？"></textarea><label for="wtInitialScene">这篇写给谁，在什么情况下使用？</label><input id="wtInitialScene" maxlength="500" value="${esc(wtData().scene||'')}" placeholder="例如：第一次了解早间护肤顺序的新手"><button class="primary">保存我的问题（不调用 AI）</button><p class="helper">来源：作者设定。保存后可继续添加问题，再确认检查范围。</p></form>`;}

function wtCard(c,i){
 const locked=wt.run.in_flight||(!wtAllowed('edit_conditions')&&!wtAllowed('confirm_conditions'));
 const sources=(wtData().sources||[]).filter(s=>(c.source_ids||[]).includes(s.id));
 return `<article class="wt-question ${wtSet().confirmed?'confirmed':'candidate'}"><div class="wt-card-head"><span class="wt-card-number">QUESTION ${String(i+1).padStart(2,'0')}</span><span class="pill ${wtSet().confirmed?'':'amber'}">${wtSet().confirmed?'已固定':'待确认'}</span></div><fieldset ${locked?'disabled':''} data-wt-condition="${esc(c.id||'')}"><label for="wtQuestion${i}">读者的问题</label><textarea id="wtQuestion${i}" name="question" rows="2" required maxlength="500">${esc(c.question||c.text||'')}</textarea><label for="wtScope${i}">适用场景</label><input id="wtScope${i}" name="scene" maxlength="500" value="${esc(c.scene||wtData().scene||'')}"></fieldset><p class="wt-origin">来源：<b>${esc(sources.length?sources.map(s=>wtOriginLabels[s.origin]||s.origin).join('；'):'作者设定 · 无读者反馈')}</b></p>${sources.map(s=>`<details><summary>查看原始问题与来源</summary><p class="helper">${esc(s.text)}</p><small>${esc(s.origin)} · ${esc(s.id.slice(0,12))}</small></details>`).join('')}${!locked&&wtCards().length>1?`<div class="wt-card-actions"><button type="button" class="quiet" data-wt="remove-condition" data-id="${esc(c.id)}">移除此候选条件</button></div>`:''}</article>`;
}
function wtReuseView(){return `<details class="wt-reuse"><summary>保存当前账号的检查条件</summary><p class="helper">已保存的条件可在新建检查时复用；来源快照会一并保存，适用范围仍需重新确认。</p>${wtSet().confirmed?'<form id="wtSaveChecklist"><label for="wtChecklistName">这组条件的名称</label><input id="wtChecklistName" maxlength="120" required placeholder="例如：新手工具教程检查"><div class="buttons"><button class="secondary">保存到当前账号</button></div></form>':'<p class="helper">先确认当前条件，才能保存为可复用清单。</p>'}</details>`;}

function wtExecution(){
 const r=wt.run,b=r.background||{};
 const unknownUsage=Boolean(r.usage?.unknown_calls||(r.calls||[]).some(c=>c.tokens==null));
 const canStart=!unknownUsage&&!r.in_flight&&['QUEUED','RUNNING'].includes(r.run_status)&&['idle','blocked','paused','waiting',undefined].includes(b.status);
 let description='准备好后，主动启动后台检查。',title='等待开始';
 if(r.in_flight){title=b.status==='queued'?'已排队':'后台正在执行';description=b.worker_online===false?'任务已保存，等待后台 Worker 启动。可以稍后回来继续查看。':'你可以切换页面。任务进度会保存，回到这里可以继续查看。';}
 else if(r.run_status==='FAILED'||b.status==='blocked'){title='执行未完成';description=b.error||r.wait_reason||'请查看失败原因，再决定是否重试。失败不计为检查通过。';}
 else if(r.run_status==='CANCELLED'){title='本次检查已取消';description='已有稿件和报告继续保留；没有产生新的检查结论。';}
 else if(r.run_status==='SUCCEEDED'){title='本次流程已结束';description='报告已保存。AI 检查不代表真人试读或平台效果；请按建议核实并修改。';}
 else if(r.run_status==='WAITING_USER'){title='需要你确认';description=r.wait_reason==='wt_recheck'?'稿件或支持材料已有变化，请使用已确认的原条件重新检查。':wtReports().length?'检查结果已保存。可查看依据、提出局部修改，再用原条件复查。':'请检查候选问题的来源与适用范围，然后确认检查条件。';}
 return `<div class="wt-report-banner ${r.run_status==='FAILED'||b.status==='blocked'?'failed':''}" role="status"><h3>${esc(title)}</h3><p>${esc(description)}</p>${b.status==='blocked'&&unknownUsage?'<p>这次调用的用量记录不完整，暂时不能重试。可以取消本次检查，已有内容仍会保留；不会自动重复调用。</p>':''}<div class="wt-action-bar">${canStart?`<button class="primary" data-wt="start">${b.status==='blocked'?'重试当前步骤':b.status==='paused'?'继续后台检查':'启动后台检查'}</button>`:''}${r.in_flight&&b.status!=='pausing'?'<button class="secondary" data-wt="pause">暂停后台检查</button>':''}${wtAllowed('cancel')?'<button class="quiet wt-cancel" data-wt="cancel">取消本次检查</button>':''}<button class="quiet" data-wt="refresh-run">刷新状态</button></div></div>`;
}

function wtReportView(){
 const report=wtReport(),results=report?.results||report?.checks||[],patches=wtData().patches||[];
 return `<section class="panel"><div class="wt-heading"><div><span class="wt-kicker">03 / 检查、修改、再检查</span><h2>读者能从稿件找到答案吗？</h2><p>先看稿件有没有回答问题，再看答案有没有材料支持。</p></div></div>${wtExecution()}${report?`${wtReportIsCurrent(report)?'<p class="wt-inline-message">这是当前稿件与条件对应的检查记录。</p>':'<p class="wt-inline-message wt-inline-error">正在查看历史报告。稿件、材料或检查批次已有变化，当前版本需要重新检查。</p>'}${wtReportIsCurrent(report)?wtNextAdvice(results):'<p class="helper">以下结论只对应旧版本；请先复查当前稿件，再决定下一步。</p>'}<details class="wt-reuse"><summary>查看版本与检查记录编号</summary><p class="wt-status-line">任务 ${esc(wt.run.run_id)}<br>稿件 ${esc(report.draft_id||report.draft_ref||report.draft_version||'')} · 问题组 ${esc(report.condition_set_id||report.set_id||'')} · ${esc(wtTime(report.created_at))}</p></details>${results.map(wtResult).join('')||'<p class="helper">这份报告尚未产生逐项结果。</p>'}${wtNewIssues(report)}`:wtEmpty('报告还没有生成','先确认问题卡，再启动检查。失败或等待中的任务不会显示为通过。')}${wtAllowed('recheck')?'<div class="wt-action-bar"><button class="primary" data-wt="recheck">使用原条件复查当前稿件</button><p class="helper">保留原条件与支持材料快照，不会删除困难条件以提高通过率。</p></div>':''}${wtAllowed('finish')?'<div class="buttons"><button class="secondary" data-wt="finish">结束本次流程并保存报告</button></div>':''}</section>${wtAllowed('propose_patch')&&!wt.run.in_flight?wtPatchForm():''}${patches.length?`<section class="panel"><div class="wt-heading"><div><span class="wt-kicker">PATCH / 局部修改</span><h2>查看修改与补充建议</h2><p>有材料依据的修改可以预览并采用；缺材料的提醒只留给你，不会写入正文。</p></div></div>${patches.map(wtPatch).join('')}</section>`:''}${wtReports().length?wtHistoryView():''}`;
}
function wtNextAdvice(results){
 const unclear=results.filter(r=>r.reading?.status==='unclear').length;
 const missing=results.filter(r=>r.status==='insufficient'&&r.reading?.status==='pass').length;
 const conflicts=results.filter(r=>r.status==='unsupported').length;
 let advice='先阅读下面的答案和依据，再决定是否修改正文。';
 if(conflicts)advice='有答案与材料不一致，先按材料核对并修改正文。';
 else if(unclear)advice='有问题还没讲清楚，先修改对应正文，再重新检查。';
 else if(missing)advice='稿件已经回答了问题。下一步补充能支持答案的资料；不用为了缺材料反复改正文。';
 else if(results.length&&results.every(r=>r.status==='pass'))advice='这次问题已讲清楚，也有材料支持。你可以结束检查，回到创作页确认和导出。';
 return `<div class="wt-next-advice" role="note"><h3>接下来做什么</h3><p>${esc(advice)}</p>${missing?'<button class="quiet" data-wt="tab" data-tab="input">去补充支持材料 →</button>':''}</div>`;
}
function wtResult(result,i){
 const set=(wtData().condition_sets||[]).find(c=>c.id===wtReport()?.condition_set_id)||wtSet();
 const card=(set.conditions||[]).find(c=>c.id===result.condition_id),reading=result.reading||{};
 const readingLabel=reading.status==='pass'?'稿件已回答':reading.status==='unclear'?'还没讲清楚':'尚无阅读结论';
 const verificationLabel={pass:'有材料支持',insufficient:'还需要支持材料',unsupported:'与材料不一致',unclear:'先把正文讲清楚'}[result.status]||'尚未核实';
 return `<article class="wt-result"><h3>${String(i+1).padStart(2,'0')} · ${esc(card?.question||'检查问题')}</h3><div class="wt-answer"><strong>稿件给出的答案</strong><p>${esc(reading.answer||'这次没有找到明确答案。')}</p></div><div class="wt-check-parts"><section><h4>有没有讲清楚？</h4><p class="wt-check-label">${esc(readingLabel)}</p>${reading.status==='unclear'&&reading.reason?`<p>${esc(reading.reason)}</p>`:''}${reading.excerpt?`<details><summary>查看正文原句</summary><blockquote>${esc(reading.excerpt)}</blockquote></details>`:''}</section><section><h4>答案有没有依据？</h4><p class="wt-check-label">${esc(verificationLabel)}</p><p>${esc(result.reason||'')}</p>${result.citations?.length?`<details><summary>查看支持材料</summary>${result.citations.map(c=>`<blockquote>${esc(c.quote)}</blockquote><small>材料 ${esc(c.source_id)}</small>`).join('')}</details>`:result.status==='insufficient'?'<p class="helper">缺材料不等于正文没讲清楚，也不表示答案一定错误。</p>':''}</section></div></article>`;
}
function wtPatchForm(){
 const results=(wtReports().at(-1)?.results||[]).filter(r=>r.status!=='pass');
 return `<section class="panel"><div class="wt-heading"><div><span class="wt-kicker">PATCH / 选择要处理的问题</span><h2>需要帮你处理哪些问题？</h2><p>有依据时生成正文修改，缺材料时给出补充建议。你查看后再决定下一步。</p></div></div><form id="wtPatchForm">${results.map(r=>{const c=wtCards().find(c=>c.id===r.condition_id);return `<label class="checkbox"><input type="checkbox" name="condition_id" value="${esc(r.condition_id)}"><span>${esc(c?.question||'检查问题')} ${wtState(r.status)}</span></label>`;}).join('')}<div class="buttons"><button class="secondary" ${results.length?'':'disabled'}>生成修改提案</button></div><p class="helper">缺材料时只给作者补充建议，不会把“待核实”写进成品正文。</p></form></section>`;
}
function wtPatch(p){
 const applicable=wtAllowed('apply_patch')&&p.base_hash===wtDraft().hash&&!wt.run.in_flight;
 const editable=(p.items||[]).filter(item=>item.citations?.length&&!item.accepted);
 return `<article class="wt-patch" data-patch-group="${esc(p.id)}"><div class="wt-row"><h3>${editable.length?'局部修改预览':'给作者的补充建议'}</h3><span class="pill neutral">${applicable&&editable.length?'可选择采用':editable.length?'历史提案':'不写入正文'}</span></div>${(p.items||[]).map(item=>{
  if(!item.citations?.length)return `<div class="wt-author-advice"><h4>给作者的补充建议</h4><p>${esc(item.reason)}</p><p>${esc(item.replacement)}</p><p class="helper">这条提醒用于补充资料，不是成品正文。${item.accepted?'旧版本曾采用此提醒，历史记录保留；可手工修改原稿。':'补充材料后再检查，不必把提醒插入稿件。'}</p><button class="quiet" data-wt="tab" data-tab="input">去补充支持材料 →</button></div>`;
  return `<div><label class="checkbox"><input type="checkbox" value="${esc(item.id)}" ${applicable&&!item.accepted?'':'disabled'}><span>${esc(item.reason)} ${item.accepted?'<b>· 已采用</b>':''}</span></label><div class="wt-diff"><div><h4>修改前 · 正文位置 ${item.start}–${item.end}</h4><pre>${esc(item.original||'（在这里插入）')}</pre></div><div><h4>修改后</h4><pre>${esc(item.replacement)}</pre></div></div><details><summary>修改的材料依据</summary>${item.citations.map(c=>`<p class="helper">${esc(c.quote)}</p>`).join('')}</details></div>`;
 }).join('')}<details class="wt-reuse"><summary>提案生成时间</summary><p class="helper">${esc(wtTime(p.created_at))}</p></details>${applicable&&editable.length?`<button class="primary" data-wt="apply-patch" data-id="${esc(p.id)}">采用勾选项，保存新版本</button>`:''}</article>`;
}

function wtHistoryView(){return `<details class="panel wt-batches"><summary>查看历史检查与版本详情</summary><div class="wt-heading"><div><span class="wt-kicker">HISTORY / 检查记录</span><h2>每次检查都有对应版本</h2><p>旧报告仅代表当时版本，不冒充当前检查结果。</p></div></div>${wtReports().map((r,i)=>`<article class="wt-batch"><div class="wt-row"><div><p>第 ${i+1} 次检查 · ${esc(r.draft_id||r.draft_ref||r.draft_version||'稿件快照')}</p><small>条件 ${esc(r.condition_set_id||r.set_id||'')} · ${esc(wtTime(r.created_at))}</small></div><button class="quiet" data-wt="report" data-id="${esc(r.id||r.batch_id||'')}">查看这次检查</button></div></article>`).join('')}</details>`;}

async function wtMutation(action,payload={},background=false){
 if(wt.busy||!wt.run)return false;
 const account=wt.account,id=wt.run.run_id;wt.busy=true;wt.failure='';
 document.querySelectorAll('.wt-workspace button').forEach(b=>b.disabled=true);
 try{
  const result=await api(`/api/runs/${encodeURIComponent(id)}/${background?'background':'actions'}`,'POST',{action,version:wt.run.status_version,key:crypto.randomUUID(),...(background?{}:{payload})});
  if(account!==activeAccountId||wt.account!==account)return false;
  wt.run=result;wt.runs=wt.runs.map(r=>r.run_id===id?result:r);wt.message='已保存。';return true;
 }catch(err){if(account===activeAccountId)wt.failure=err.message;return false;}
 finally{wt.busy=false;wtPaint();}
}

async function wtRefreshRun(){
 if(!wt.run||wt.polling||wt.busy)return;
 const account=wt.account,id=wt.run.run_id;wt.polling=true;
 try{const latest=await api('/api/runs/'+encodeURIComponent(id));if(account!==activeAccountId||wt.run?.run_id!==id||currentPage!=='windtunnel')return;const changed=Boolean(wt.failure)||latest.status_version!==wt.run.status_version||JSON.stringify(latest.background)!==JSON.stringify(wt.run.background);wt.failure='';wt.run=latest;wt.runs=wt.runs.map(r=>r.run_id===id?latest:r);if(changed)wtPaint();}
 catch(err){if(currentPage==='windtunnel'&&account===activeAccountId){wt.failure=err.message;wtPaint();}}
 finally{wt.polling=false;}
}

function wtBind(){
 const root=document.querySelector('.wt-workspace');if(!root)return;
 root.addEventListener('input',e=>{if(e.target.dataset.wtField){const key=e.target.dataset.wtField;wt.form[key]=e.target.type==='checkbox'?e.target.checked:e.target.value;}});
 root.addEventListener('change',e=>{if(e.target.dataset.wtField){const key=e.target.dataset.wtField;wt.form[key]=e.target.type==='checkbox'?e.target.checked:e.target.value;if(key==='mode'){wtPaint();}if(key==='importRun'||key==='importRef'){if(key==='importRun')wt.form.importRef='';wt.form.importMaterials=[];wt.form.bridge=null;wt.message='';wtPaint();}}});
 root.addEventListener('click',wtClick);
 if($('wtCreateForm'))$('wtCreateForm').onsubmit=wtCreate;
 if($('wtConditions'))$('wtConditions').onsubmit=wtSaveConditions;
 if($('wtInitialConditions'))$('wtInitialConditions').onsubmit=async e=>{e.preventDefault();const question=$('wtInitialQuestion').value.trim(),scene=$('wtInitialScene').value.trim();if(await wtMutation('set_initial_conditions',{conditions:[{question,scene,source_ids:[],origin:'author'}]})){wt.message='已保存你的问题，没有调用 AI。确认问题后即可继续检查正文。';wtPaint();}};
 if($('wtPatchForm'))$('wtPatchForm').onsubmit=async e=>{e.preventDefault();const ids=[...e.target.querySelectorAll('[name="condition_id"]:checked')].map(x=>x.value);if(!ids.length){wt.failure='请至少选择一个未通过的问题。';wtPaint();return;}if(await wtMutation('propose_patch',{condition_ids:ids}))await wtMutation('start',{},true);};
 if($('wtEditDraft'))$('wtEditDraft').onsubmit=async e=>{e.preventDefault();await wtMutation('edit_draft',{title:wtDraft().title,text:$('wtEditText').value,base_hash:wtDraft().hash});};
 if($('wtSaveChecklist'))$('wtSaveChecklist').onsubmit=wtSaveChecklist;
 if($('wtMaterialsForm'))$('wtMaterialsForm').onsubmit=async e=>{e.preventDefault();const materials=[...e.target.querySelectorAll('[data-material-edit]')].map(x=>({title:x.querySelector('[name="title"]').value,text:x.querySelector('[name="text"]').value,origin:x.querySelector('[name="origin"]').value}));await wtMutation('update_materials',{base_material_hash:wtData().material_hash,materials});};
 if($('wtSupplementForm'))$('wtSupplementForm').onsubmit=async e=>{e.preventDefault();await wtMutation('supplement_material',{title:$('wtSupplementTitle').value,text:$('wtSupplementText').value,origin:$('wtSupplementOrigin').value});};
}

async function wtClick(e){
 const b=e.target.closest('[data-wt]');if(!b||b.disabled||wt.busy)return;
 const action=b.dataset.wt;
 if(action==='new'){wt.run=null;wt.newDraft=true;wt.tab='input';wt.batch='';wt.form=wtFreshForm();wt.failure='';wt.message='';wtPaint();}
 if(action==='refresh')await renderWindtunnel();
 if(action==='open'){wt.run=wt.runs.find(r=>r.run_id===b.dataset.id);wt.newDraft=false;wt.tab=wtReports().length?'report':wtCards().length?'cards':'input';wt.batch='';wt.message='';wt.failure='';wtPaint();}
 if(action==='tab'){wt.tab=b.dataset.tab;wtPaint();}
 if(action==='input-mode'){wt.form.inputMode=b.dataset.value;if(b.dataset.value==='paste'){wt.form.bridge=null;wt.message='已改为手工输入。带入的资料快照仍保留出处；请确认它们适用于当前正文。';}wtPaint();}
 if(action==='example'){wt.form={...wtFreshForm(),mode:'simulation',title:'虚构示例：第一次导出任务表',text:'打开任务表，在菜单中选择导出，将文件保存到电脑。之后可以使用表格工具查看。',material:'以下仅为虚构演示材料：这个示例工具的导出菜单位于右上角“更多”内，导出格式选择 CSV，编码选择 UTF-8。',feedback:'找不到导出入口怎么办？应该选什么文件格式和编码？',origin:'demo',scene:'第一次使用虚构示例工具、需要导出中文任务表的读者'};wtPaint();}
 if(action==='start'){if(await wtMutation('start',{},true)){wt.tab=wtCards().length?'report':'cards';wtPaint();}}
 if(action==='cancel')await wtMutation('cancel');
 if(action==='pause')await wtMutation('pause',{},true);
 if(action==='refresh-run')await wtRefreshRun();
 if(action==='recheck'){if(await wtMutation('recheck',{condition_set_id:wtSet().id})){wt.batch='';await wtMutation('start',{},true);}}
 if(action==='finish')await wtMutation('finish');
 if(action==='add-condition'){const conditions=wtReadConditions();if(conditions.length>=12){wt.failure='每组最多 12 条条件。';wtPaint();return;}conditions.push({id:crypto.randomUUID(),question:'请填写读者需要回答的新问题',scene:wtData().scene,source_ids:[],origin:'author'});await wtMutation('edit_conditions',{conditions});}
 if(action==='remove-condition')await wtMutation('edit_conditions',{conditions:wtReadConditions().filter(c=>c.id!==b.dataset.id)});
 if(action==='apply-patch'){const patch=wtData().patches.find(p=>p.id===b.dataset.id);const selected=[...rootQuery('[data-patch-group="'+b.dataset.id+'"] input:checked')].map(x=>x.value);if(!selected.length){wt.failure='请先勾选要采用的修改。';wtPaint();return;}await wtMutation('apply_patch',{patch_id:patch.id,item_ids:selected,base_hash:patch.base_hash});}
 if(action==='report'){wt.batch=b.dataset.id;wt.tab='report';wtPaint();}
}

async function wtCreate(e){
 e.preventDefault();if(wt.busy)return;
 const f=wt.form,account=wt.account;
 if(!account||account!==activeAccountId)return;
 if(!f.permission){wt.failure='请先确认稿件、材料与反馈的使用权。';wtPaint();return;}
 const body={workflow_type:'windtunnel',account_id:account,title:f.title,scene:f.scene,mode:f.mode||'live',hypothesis_id:window.activeTrialHypothesisId||null,materials:[...(f.importMaterials||[]),...(f.material.trim()?[{text:f.material,title:f.materialTitle}]:[])],feedback:f.feedback.trim()?[{text:f.feedback,origin:wtOriginLabels[f.origin]+' · '+f.feedbackOrigin,provenance:f.origin==='user_hypothesis'?'author':f.origin,permission:f.permission}]:[]};
 if(f.inputMode==='import'){delete body.title;body.import={run_id:f.importRun,draft_ref:f.importRef};}else body.text=f.text;
 if(f.checklist){const [id,version]=f.checklist.split(':');body.checklist={id,version:Number(version)};}
 wt.busy=true;e.submitter.disabled=true;wt.failure='';
 try{const created=await api('/api/runs','POST',body);if(account!==activeAccountId)return;window.activeTrialHypothesisId=null;wt.run=created;wt.runs.unshift(created);wt.newDraft=false;wt.tab='cards';wt.message='稿件和来源已保存。请主动启动检查，生成候选问题。';wt.form=wtFreshForm();}
 catch(err){if(account===activeAccountId)wt.failure=err.message;}
 finally{wt.busy=false;wtPaint();}
}

async function wtSaveConditions(e){
 e.preventDefault();const original=wtCards(),conditions=wtReadConditions();
 const confirm=e.submitter?.value==='confirm';
 if(JSON.stringify(conditions)!==JSON.stringify(original)&&!await wtMutation('edit_conditions',{conditions}))return;
 if(confirm&&await wtMutation('confirm_conditions',{condition_set_id:wtSet().id,condition_hash:wtSet().hash})){wt.tab='report';wt.message='条件已确认。启动后台检查，阅读与核实会分别执行。';wtPaint();}
 else if(!confirm){wt.message='条件已保存，请确认后再开始检查。';wtPaint();}
}

async function wtSaveChecklist(e){
 e.preventDefault();if(wt.busy)return;const account=wt.account;wt.busy=true;e.submitter.disabled=true;
 try{await api('/api/windtunnel/checklists','POST',{title:$('wtChecklistName').value,run_id:wt.run.run_id,condition_set_id:wtSet().id,version:wt.run.status_version,key:crypto.randomUUID()});if(account===activeAccountId){wt.message='已保存到当前账号，可用于同类教程。';await renderWindtunnel();}}
 catch(err){if(account===activeAccountId)wt.failure=err.message;}
 finally{wt.busy=false;wtPaint();}
}

function wtReadConditions(){return [...document.querySelectorAll('[data-wt-condition]')].map((fieldset,i)=>({...wtCards()[i],question:fieldset.querySelector('[name="question"]').value,scene:fieldset.querySelector('[name="scene"]').value}));}
function wtReportIsCurrent(report){return report.draft_hash===wtDraft().hash&&report.condition_set_id===wtSet().id&&report.material_hash===wtData().material_hash&&report.batch_id===wtData().batch_id;}
function wtNewIssues(report){return `<details class="wt-reuse"><summary>本次新增问题 · ${(report.new_issues||[]).length} 项记录</summary><p class="helper">新增问题单独保留，不替换原检查条件。模拟模式没有记录不表示已经验证无新错误。</p>${(report.new_issues||[]).map(r=>`<article class="wt-result">${wtState(r.status)}<blockquote>${esc(r.excerpt)}</blockquote><p>${esc(r.reason)}</p>${(r.citations||[]).map(c=>`<p class="helper">依据：${esc(c.quote)}</p>`).join('')}</article>`).join('')}</details>`;}
function wtMaterialsEditor(materials){
 if(!wtAllowed('supplement_material'))return '';
 return `<details class="wt-reuse"><summary>补充事实材料</summary><form id="wtSupplementForm"><label for="wtSupplementTitle">材料标题</label><input id="wtSupplementTitle" value="补充操作说明" maxlength="200" required><label for="wtSupplementOrigin">材料来源与适用版本</label><input id="wtSupplementOrigin" placeholder="例如：作者实际操作记录 / 工具版本与日期" maxlength="500" required><label for="wtSupplementText">材料原文</label><textarea id="wtSupplementText" rows="5" maxlength="6000" required></textarea><div class="buttons"><button class="secondary">保存材料，等待复查</button></div><p class="helper">补材料会让旧报告过期，不会直接把检查状态改成通过。</p></form></details>${materials.length&&wtAllowed('update_materials')?`<details class="wt-reuse"><summary>修正已有材料</summary><form id="wtMaterialsForm">${materials.map(m=>`<div class="wt-source" data-material-edit><label>材料标题<input name="title" value="${esc(m.title||'支持材料')}" maxlength="200" required></label><label>材料来源<input name="origin" value="${esc(m.origin||'作者提供')}" maxlength="500" required></label><label>修正后的原文<textarea name="text" rows="4" maxlength="6000" required>${esc(m.text)}</textarea></label></div>`).join('')}<div class="buttons"><button class="secondary">保存材料新版本</button></div><p class="helper">此前材料及报告保留审计；必须重新检查当前版本。</p></form></details>`:''}`;
}
function rootQuery(selector){return document.querySelectorAll('.wt-workspace '+selector);}

setInterval(()=>{if(currentPage==='windtunnel'&&wt.run?.in_flight&&!wt.busy)wtRefreshRun();},1800);
