'use strict';
// Right-side guidance uses current account state; sidebar routes stay independent.
pageInfo.studio=['CREATE / 创作','把想法写成一份可用稿件。','写清主题和素材，检查问题，再由你确认。'];
pageInfo.trends=['TOPICS / 选题与来源','先找到一个值得写的问题。','公开搜索提供线索；保存的原文可回到资料库复用，不是实时平台热榜。'];
function renderPageTools(page){
 const groups=[[['studio','写内容'],['trends','选题与来源']], [['publish','作品归档'],['metrics','数据复盘']]];
 const links=groups.find(group=>group.some(([id])=>id===page))||[],host=$('pageTools');
 if(!host)return;host.hidden=!links.length;
 host.innerHTML=links.map(([id,label])=>`<button class="${id===page?'active':'quiet'}" data-go-page="${id}" aria-current="${id===page?'page':'false'}">${label}</button>`).join('');
}
function onboardingState(account,documents=[],runs=[]){
 const profile=account?.profile||{};
 return {profile:!!(profile.positioning?.trim()&&profile.audience?.trim()&&profile.goal?.trim()),
  material:!!account?.id&&documents.some(d=>d.account_id===account.id),
  creation:!!account?.id&&runs.some(r=>r.workflow_type!=='windtunnel'&&r.context?.operations?.account_id===account.id&&r.run_status==='SUCCEEDED'&&r.accepted_ref&&r.drafts?.some(d=>d.ref===r.accepted_ref))};
}
function creationStatusText(value){
 if(value.run_status==='WAITING_USER')return value.wait_reason==='final_confirmation'?'成稿待你确认':value.wait_reason==='review_blocked'?'需要补充资料或处理审核问题':'等待你处理';
 return ({QUEUED:'已排队，等待创作',RUNNING:'正在创作',SUCCEEDED:'已确认成稿',FAILED:'执行未完成，可查看原因',CANCELLED:'已取消',EXPIRED:'任务已过期'})[value.run_status]||'查看任务详情';
}
function gettingStartedHTML(account,runs=[]){
 const state=onboardingState(account,materialDocsCache,runs);
 const step=(done,title,body,button)=>`<li class="${done?'done':''}"><span class="guide-check">${done?'✓':'○'}</span><div><b>${title}</b><p>${body}</p>${button}</div></li>`;
 const cards=step(state.profile,'设置你的账号','填清方向、读者和当前目标，之后创作会沿用它。','<button class="quiet" data-go-page="accounts">'+(state.profile?'调整档案':'完善账号档案')+' →</button>')+
  step(state.material,'备好一份素材（可选）','常用原文存进资料库；只做一次也可在创作时直接粘贴。',websiteSession?.auth_required?'<button class="quiet" data-go-page="library">'+(state.material?'查看已有素材':'添加一份真实资料')+' →</button>':'')+
  step(state.creation,'完成第一份稿件','保存需求 → 连续运行或逐步查看 → 处理问题 → 确认下载。','<button class="secondary" data-start-creation>开始一份创作 →</button>');
 const content=`<div class="detail-heading"><div><span class="eyebrow">开始使用</span><h2 id="gettingStartedTitle">${state.creation?'下一次继续积累':'第一次来，按这三步就够了'}</h2></div></div><ol class="guide-steps">${cards}</ol><p class="helper">资料和周计划都不是强制前置步骤。模拟不调用模型；真实 AI 需要你明确选择和确认费用。</p>`;
 return state.profile&&state.creation?`<details id="gettingStarted" class="panel getting-started"><summary>使用指引（基础步骤已完成，按需查看）</summary>${content}</details>`:`<section id="gettingStarted" class="panel getting-started" aria-labelledby="gettingStartedTitle">${content}</section>`;
}
document.addEventListener('click',e=>{
 const button=e.target.closest('[data-go-page], [data-start-creation]');
 if(!button||button.disabled||busy||opsBusy)return;
 if(button.hasAttribute('data-start-creation')){
  // newRun owns the dirty guard and clears the current creation safely.
  $('newRun').click();
 }else if(dirtyGuard()){auto=false;showPage(button.dataset.goPage);}
});
