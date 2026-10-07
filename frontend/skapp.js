 'use strict';
pageInfo.skapp=['SKAPP / 实验','看看模型在公开数据上的预测表现。','复现 SKAPP 的研究方法；这里展示离线测试结果，不给你的稿件打爆款概率。'];
let skappRenderSequence=0;
function skappNumber(value){return typeof value==='number'&&Number.isFinite(value)?value.toFixed(4):'—';}
function skappReportHTML(report){
 const intro='<section class="panel"><h2>先理解这个实验</h2><p>SKAPP 作者当前参考实现利用相似历史内容与多模态特征预测热度。当前实现采用 soft RRCP 门控注意力，不代表论文全部双图网络均已复现。此页读取本机训练后保存的公开数据集评估，不会在点击时重新训练或推理，也不会调用收费模型。</p><p class="helper">公开数据上的热度分数不是阅读量，也不是爆款概率。尚未验证小红书新稿效果；不能把论文或公开测试成绩当作你账号的增长保证。</p></section>';
 if(report.status!=='ready')return intro+'<section class="panel"><h2>实验结果待准备</h2><p>'+esc(report.message||'实验报告暂不可用，请稍后重试。')+'</p><button id="skappRefresh" class="secondary">刷新实验结果</button></section>';
 const m=report.metrics,b=report.baseline;
 const rows=[['MSE（误差平方均值，越低越好）','MSE'],['MAE（平均绝对误差，越低越好）','MAE'],['Spearman（排序相关性，越高越好）','SRC']];
 return intro+`<section class="panel"><div class="detail-heading"><div><h2>已保存的真实评估</h2><p>${esc(report.dataset)} · ${esc(m.samples)} 个测试样本</p></div><a class="button primary" href="/api/skapp/report/download" download>下载实验报告（JSON）</a></div><p class="helper">以下数值仅适用于本次数据、划分与训练设置；这是开源复现，非本项目原创模型。</p><div class="table-scroll"><table><thead><tr><th>指标</th><th>SKAPP</th><th>${esc(b?.name||'对照模型')}</th></tr></thead><tbody>${rows.map(([title,key])=>`<tr><td>${title}</td><td>${skappNumber(m[key])}</td><td>${skappNumber(b?.[key])}</td></tr>`).join('')}</tbody></table></div>${b?'':'<p class="helper">尚无可比对照结果，暂不宣称效果提升。</p>'}<details><summary>训练设置与来源</summary><p>作者仓库版本：${esc(report.upstream_commit)}</p><pre>${esc(JSON.stringify(report.training,null,2))}</pre><a href="https://github.com/YifanZhang-git/SKAPP" target="_blank" rel="noopener noreferrer">查看 SKAPP 作者代码 →</a></details></section><section class="panel"><h2>查看测试样本</h2><p>选择一条已离线评估的样本，对照预测分数和真实标签。这里不读取你的账号或创作记录。</p>${report.predictions.length?`<label for="skappSample">公开数据样本</label><select id="skappSample">${report.predictions.slice(0,20).map((row,i)=>`<option value="${i}">${esc(row.id)}</option>`).join('')}</select><div class="buttons"><button id="skappPrevious" class="quiet" disabled>上一页</button><span id="skappPageLabel">第 1 页 · 共 ${esc(report.predictions.length)} 条预测</span><button id="skappNext" class="quiet" ${report.predictions.length<=20?'disabled':''}>下一页</button></div><div id="skappSampleResult" aria-live="polite"></div>`:'<p class="helper">此报告未附逐条预测，可先查看整体指标。</p>'}<button id="skappRefresh" class="secondary">刷新实验结果</button></section>`;
}
async function renderSkapp(){
 const sequence=++skappRenderSequence;
 $('operationsContent').innerHTML='<section class="panel"><p>正在读取本机实验报告…</p></section>';
 let report;
 try{report=await api('/api/skapp/report');}catch(_){report={status:'unavailable',message:'暂时无法读取实验报告，请检查登录状态后重试。'};}
 if(currentPage!=='skapp'||sequence!==skappRenderSequence)return;
 $('operationsContent').innerHTML=skappReportHTML(report);
 $('skappRefresh').onclick=renderSkapp;
 if(report.status==='ready'&&report.predictions.length){
  const show=()=>{const row=report.predictions[Number($('skappSample').value)||0];$('skappSampleResult').innerHTML=`<div class="stats ops-stats">${stat('真实热度标签',skappNumber(row.actual),'公开数据的标签尺度')}${stat('模型预测',skappNumber(row.predicted),'保存的离线推理结果')}${stat('绝对误差',skappNumber(Math.abs(row.predicted-row.actual)),'单条样本不代表整体准确率')}</div>`;};
  let samplePage=0;
  const turn=delta=>{samplePage+=delta;const start=samplePage*20,end=Math.min(start+20,report.predictions.length);$('skappSample').innerHTML=report.predictions.slice(start,end).map((row,i)=>`<option value="${start+i}">${esc(row.id)}</option>`).join('');$('skappSample').value=String(start);$('skappPrevious').disabled=samplePage===0;$('skappNext').disabled=end===report.predictions.length;$('skappPageLabel').textContent=`第 ${samplePage+1} 页 · 共 ${report.predictions.length} 条预测`;show();};
  $('skappPrevious').onclick=()=>{if(samplePage>0)turn(-1);};
  $('skappNext').onclick=()=>{if((samplePage+1)*20<report.predictions.length)turn(1);};
  $('skappSample').onchange=show;show();
 }
}
