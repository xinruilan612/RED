'use strict';

// Product guidance is derived from saved account state, not a browser-only wizard.
pageInfo.studio=['CREATE / 创作','把想法写成一份可用稿件。','写清主题和素材，检查问题，再由你确认。'];
pageInfo.trends=['TOPICS / 选题与来源','先找到一个值得写的问题。','公开搜索提供线索；保存的原文可回到资料库复用，不是实时平台热榜。'];
pageInfo.examples=['EXAMPLES / 体验示例','先体验，不混入真实运营。','示例账号、模拟发布和演练数据均有标记，不代表真实平台结果。'];

function renderPageTools(page){
 const groups={studio:[['studio','写内容'],['trends','选题与来源']],publish:[['publish','作品归档'],['metrics','数据复盘']]};
 const group=navigationGroup(page),links=groups[group]||[];
 if(group==='studio'&&websiteSession?.auth_required)links.push(['windtunnel','读者理解检查（可选）']);
 const host=$('pageTools');host.hidden=!links.length;
 host.innerHTML=links.map(([id,label])=>`<button class="${id===page?'active':'quiet'}" data-go-page="${id}" aria-current="${id===page?'page':'false'}">${label}</button>`).join('');
}

function onboardingState(account,documents=[],runs=[]){
 const profile=account?.profile||{};
 return {profile:!!(profile.positioning?.trim()&&profile.audience?.trim()&&profile.goal?.trim()),
  material:documents.some(d=>d.account_id===account?.id),
  creation:runs.some(r=>r.workflow_type!=='windtunnel'&&r.context?.operations?.account_id===account?.id&&r.run_status==='SUCCEEDED'&&r.accepted_ref&&r.drafts?.some(d=>d.ref===r.accepted_ref))};
}

function gettingStartedHTML(account,runs=[]){
 const state=onboardingState(account,materialDocsCache,runs);
 const step=(done,title,body,button)=>`<li class="${done?'done':''}"><span class="guide-check">${done?'✓':'○'}</span><div><b>${title}</b><p>${body}</p>${button}</div></li>`;
 const cards=step(state.profile,'设置你的账号','填清方向、读者和当前目标，之后创作会沿用它。','<button class="quiet" data-go-page="accounts">'+(state.profile?'调整档案':'完善账号档案')+' →</button>')+
  step(state.material,'备好一份素材（可选）','常用原文存进资料库；只做一次也可在创作时直接粘贴。',websiteSession?.auth_required?'<button class="quiet" data-go-page="library">'+(state.material?'查看已有素材':'添加一份真实资料')+' →</button>':'')+
  step(state.creation,'完成第一份稿件','保存需求 → 连续运行或逐步查看 → 处理问题 → 确认下载。','<button class="secondary" data-start-creation>开始一份创作 →</button>');
 const content=`<div class="detail-heading"><div><span class="eyebrow">开始使用</span><h2 id="gettingStartedTitle">${state.creation?'下一次继续积累':'第一次来，按这三步就够了'}</h2></div></div><ol class="guide-steps">${cards}</ol><p class="helper">资料、实验和周计划都不是强制前置步骤。默认模拟免费，真实 AI 需要你明确选择和确认费用。</p>`;
 return state.profile&&state.creation?`<details id="gettingStarted" class="panel getting-started"><summary>使用指引（基础步骤已完成，按需查看）</summary>${content}</details>`:`<section id="gettingStarted" class="panel getting-started" aria-labelledby="gettingStartedTitle">${content}</section>`;
}

let exampleReturnAccountId=null;
async function loadExampleAccount(){
 if(busy||opsBusy||!dirtyGuard())return;
 if(currentAccount()&&!currentAccount().demo_sample)exampleReturnAccountId=activeAccountId;
 let sample=ops.accounts.find(a=>a.demo_sample);
 if(!sample){if(!await operate('load_sample',{}))return;sample=ops.accounts.find(a=>a.demo_sample);}
 if(!sample)return;
 activeAccountId=sample.id;run=null;editing=false;chosenTrend=null;chosenHypothesis=null;window.activeTrialHypothesisId=null;
 $('editor').hidden=true;$('workbench').hidden=true;$('welcome').hidden=false;
 syncAccounts();showPage('examples');await history();toast('已切换到示例账号；可按下方步骤体验，再返回自己的账号。');
}

function renderExamples(){
 $('operationsContent').innerHTML=`<section class="panel"><h2>了解完整闭环，不需要填造真实数据</h2><p>穿搭示例包含虚构作品和演练指标，可看周计划、复盘和经验如何连接。示例在独立账号中保留，不替代你自己的业务记录。</p><div class="buttons"><button id="sampleAccount" class="secondary">体验穿搭示例账号</button><button class="quiet" data-go-page="trends">查看选题来源 →</button></div><p class="helper">自己的稿件也可使用免费模拟模式。模拟发布不会发送到小红书或抖音，模拟检查不能证明真实读者理解。</p></section>`;
 $('sampleAccount').onclick=loadExampleAccount;
 if(currentAccount()?.demo_sample){
  $('operationsContent').insertAdjacentHTML('beforeend',`<section class="panel"><h2>示例已准备好，按顺序体验</h2><p>① 看虚构作品 → ② 看演练数据与复盘 → ③ 接受或撤销示例经验 → ④ 免费模拟创作。</p><div class="buttons"><button data-go-page="publish">1. 看示例作品</button><button data-go-page="metrics">2. 看示例复盘</button><button data-go-page="memory">3. 看示例经验</button><button id="exampleCreate">4. 免费模拟创作</button><button id="exampleReturn" class="secondary">返回自己的账号</button></div></section>`);
  $('exampleCreate').onclick=()=>{if(startCreation()){$('topic').value='上课前怎样搭配一套方便活动的穿搭';$('material').value='这是虚构穿搭示例，只用于免费模拟流程，不是真实商品或效果证据。';$('mode').value='simulation';$('mode').onchange();}};
  $('exampleReturn').onclick=async()=>{if(busy||opsBusy||!dirtyGuard())return;const account=ops.accounts.find(a=>a.id===exampleReturnAccountId&&!a.demo_sample)||ops.accounts.find(a=>!a.demo_sample);if(!account){showPage('accounts');return;}activeAccountId=account.id;run=null;editing=false;chosenTrend=null;chosenHypothesis=null;window.activeTrialHypothesisId=null;syncAccounts();showPage('overview');await history();};
 }

}

document.addEventListener('click',e=>{
 const button=e.target.closest('[data-go-page], [data-start-creation]');
 if(!button||button.disabled||busy||opsBusy)return;
 auto=false;
 if(button.hasAttribute('data-start-creation'))$('newRun').click();
 else if(dirtyGuard())showPage(button.dataset.goPage);
});
