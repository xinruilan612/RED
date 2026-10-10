'use strict';
pageInfo.models=['MODEL / SETTINGS','选择模型，管理自己的连接。','默认使用平台 DeepSeek，也可配置自己的模型与费用上限。'];
pageInfo.connections=['DATA / CONNECTION','让账号数据有来源、可追溯。','查看实际接入能力和已有记录，未连接的数据保持明确。'];
let settingsLoad=0,connectionLoad=0,connectionMutation=false;
function connectionLink(url,label){try{const u=new URL(url);if(u.protocol!=='https:')return esc(label);return `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;}catch(_){return esc(label);}}
async function connectionAction(action){
 if(connectionMutation)return false;connectionMutation=true;
 document.querySelectorAll('#operationsContent button').forEach(b=>b.disabled=true);
 try{await action();clearError();return true;}catch(e){error(e);return false;}
 finally{connectionMutation=false;document.querySelectorAll('#operationsContent button').forEach(b=>b.disabled=false);}
}
function modelConnectionForm(catalog,item={}){
 const provider=item.provider||catalog[0]?.id||'',entry=catalog.find(p=>p.id===provider)||{};
 return `<form id="modelConnectionForm" class="panel"><h2>${item.id?'编辑模型连接':'添加自己的模型'}</h2><input name="id" type="hidden" value="${esc(item.id||'')}"><input name="version" type="hidden" value="${esc(item.version??'')}"><div class="two-col"><label>厂商<select name="provider">${catalog.map(p=>`<option value="${esc(p.id)}" ${p.id===provider?'selected':''}>${esc(p.name)}</option>`).join('')}</select></label><label>连接名称<input name="label" maxlength="80" value="${esc(item.label||'')}" required></label><label>模型 ID<input name="model" maxlength="160" value="${esc(item.model||'')}" required placeholder="填写厂商控制台中的模型 ID"></label><label>连接地址<input name="base_url" type="url" value="${esc(item.base_url||entry.base_url||'')}" required></label></div><p id="modelProviderDocs" class="helper">${connectionLink(entry.docs,'查看厂商接入文档')}</p><label>API Key<input name="api_key" type="password" autocomplete="new-password" ${item.id?'':'required'} placeholder="${item.id?'留空保留已保存的密钥':'只保存在服务端，不会回显'}"></label><div class="two-col"><label>保守费率上限（美元 / 百万 Token）<input name="rate_usd_per_million" type="number" min="0.000001" step="any" value="${esc(item.rate_usd_per_million??'')}" required></label><label>每次任务预算（美元）<input name="run_budget_usd" type="number" min="0.000001" step="any" value="${esc(item.run_budget_usd??'')}" required></label><label>每日预算（美元）<input name="day_budget_usd" type="number" min="0.000001" step="any" value="${esc(item.day_budget_usd??'')}" required></label></div><p class="helper">费率用于保守预算预留，不是厂商账单。请按所选模型的输入、输出及其他计费项填写足够的上限。保存不会调用模型；连接测试需另行确认小额费用。</p><button class="primary" type="submit">保存连接</button>${item.id?'<button id="cancelModelEdit" type="button" class="quiet">取消编辑</button>':''}</form>`;
}
function bindModelForm(catalog){
 const form=$('modelConnectionForm');
 form.elements.provider.onchange=()=>{const p=catalog.find(x=>x.id===form.elements.provider.value)||{};form.elements.base_url.value=p.base_url||'';$('modelProviderDocs').innerHTML=connectionLink(p.docs,'查看厂商接入文档');};
 form.onsubmit=async e=>{e.preventDefault();const f=form.elements,payload={};for(const key of ['provider','label','model','base_url'])payload[key]=f[key].value.trim();for(const key of ['rate_usd_per_million','run_budget_usd','day_budget_usd'])payload[key]=Number(f[key].value);if(f.id.value){payload.id=f.id.value;payload.version=Number(f.version.value);}if(f.api_key.value)payload.api_key=f.api_key.value;await connectionAction(async()=>{await api('/api/models/connections','POST',payload);f.api_key.value='';await refreshModelStatus();if(currentPage==='models')await renderModelSettings();toast('模型连接已保存');});};
 if($('cancelModelEdit'))$('cancelModelEdit').onclick=()=>renderModelSettings();
}
async function testModelConnection(item){
 if(!window.confirm(`将使用「${item.label}」的密钥发送一次短请求，会产生小额模型费用（受该连接预算约束）。确认测试？`))return;
 await connectionAction(async()=>{await api('/api/models/connections/'+encodeURIComponent(item.id)+'/test','POST',{version:item.version,acknowledge_cost:true});await refreshModelStatus();if(currentPage==='models')await renderModelSettings();toast('连接测试已完成，请查看状态');});
}
function searchSettingsForm(settings){
 const s=settings.baidu||{};
 return `<form id="searchSettingsForm" class="panel"><h2>百度联网搜索</h2><p>用于全网或限定京东、淘宝等站点的网页检索；限定站点不等于完整的站内搜索接口。</p><p class="helper">${connectionLink(s.docs,'百度搜索接口文档')} · 当前${s.configured?'已保存密钥':'未配置密钥'} · 今日已用 ${esc(s.requests_today??0)} 次（UTC 日）</p><label><input name="enabled" type="checkbox" ${s.enabled?'checked':''}> 启用百度搜索</label><label>每日请求上限（UTC 日）<input name="day_limit" type="number" min="1" step="1" value="${esc(s.day_limit??100)}" required></label><label>百度 API Key<input name="api_key" type="password" autocomplete="new-password" placeholder="${s.configured?'留空保留已保存的密钥':'输入自己的百度搜索密钥'}"></label><p class="helper">搜索请求可能计费；次数限制不是金额保证。保存设置本身不执行搜索。</p><button class="secondary">保存搜索设置</button></form>`;
}
async function renderModelSettings(){
 const token=++settingsLoad;$('operationsContent').innerHTML='<section class="panel"><p>正在读取模型与搜索配置…</p></section>';
 try{const [data,search]=await Promise.all([api('/api/models'),api('/api/search/settings')]);if(token!==settingsLoad||currentPage!=='models')return;
 const catalog=data.catalog||[],items=data.connections||[];
 $('operationsContent').innerHTML=`<section class="panel"><h2>默认模型</h2><p>平台 DeepSeek 由平台提供密钥；自带连接使用你自己的密钥和预算。切换默认模型用于后续任务。</p><label>当前选择<select id="defaultModelConnection"><option value="" ${!data.default_connection_id?'selected':''}>平台 DeepSeek</option>${items.map(c=>`<option value="${esc(c.id)}" ${data.default_connection_id===c.id?'selected':''}>${esc(c.label)} · ${esc(c.model)}</option>`).join('')}</select></label><p class="helper">${data.ready?'当前默认连接可用；实际调用仍受额度和模型能力约束。':'当前默认连接尚不可用，请检查配置。'}</p></section><section class="panel"><h2>我的模型连接</h2>${items.map(c=>`<article class="detail-block"><h3>${esc(c.label)} · ${esc(c.model)}</h3><p class="helper">${esc(c.provider)} · ${esc(c.base_url)} · 测试状态：${esc(c.test_status||'未测试')} · ${c.last_tested?esc(dateText(c.last_tested)):'尚无测试时间'}</p><div class="buttons"><button data-edit-model="${esc(c.id)}" class="quiet">编辑</button><button data-test-model="${esc(c.id)}" class="secondary">测试连接（可能计费）</button><button data-delete-model="${esc(c.id)}" class="quiet">删除连接</button></div></article>`).join('')||'<p class="helper">还没有自带密钥的连接。</p>'}</section><div id="modelConnectionEditor">${modelConnectionForm(catalog)}</div>${searchSettingsForm(search)}`;
 bindModelForm(catalog);
 $('defaultModelConnection').onchange=async e=>{const next=e.target.value||null;const ok=await connectionAction(async()=>{await api('/api/models/default','POST',{connection_id:next});await refreshModelStatus();if(currentPage==='models')await renderModelSettings();});if(!ok)e.target.value=data.default_connection_id||'';};
 document.querySelectorAll('[data-edit-model]').forEach(b=>b.onclick=()=>{const item=items.find(c=>c.id===b.dataset.editModel);$('modelConnectionEditor').innerHTML=modelConnectionForm(catalog,item);bindModelForm(catalog);});
 document.querySelectorAll('[data-test-model]').forEach(b=>b.onclick=()=>testModelConnection(items.find(c=>c.id===b.dataset.testModel)));
 document.querySelectorAll('[data-delete-model]').forEach(b=>b.onclick=async()=>{const item=items.find(c=>c.id===b.dataset.deleteModel);if(!window.confirm(`删除「${item.label}」的保存连接？以后需重新填写密钥。`))return;await connectionAction(async()=>{await api('/api/models/connections/'+encodeURIComponent(item.id)+'/delete','POST',{version:item.version});await refreshModelStatus();if(currentPage==='models')await renderModelSettings();});});
 $('searchSettingsForm').onsubmit=async e=>{e.preventDefault();const f=e.target.elements,enabled=f.enabled.checked;if(enabled&&!window.confirm('启用后，你发起或授权的百度搜索可能产生费用，按所设 UTC 日次数上限执行。确认启用？'))return;const payload={enabled,day_limit:Number(f.day_limit.value),version:search.baidu.version,acknowledge_cost:true};if(f.api_key.value)payload.api_key=f.api_key.value;await connectionAction(async()=>{await api('/api/search/settings','POST',payload);f.api_key.value='';if(currentPage==='models')await renderModelSettings();toast('搜索配置已保存');});};
 }catch(e){if(token===settingsLoad&&currentPage==='models'){$('operationsContent').innerHTML='<section class="panel"><p>配置读取失败，请重新打开此页重试。</p></section>';error(e);}}
}
function connectionOverview(data){
 const records=data.local_records||{},latest=records.latest_metric;
 return `<section class="panel"><h2>${esc(data.account_name)} · ${data.connection_status==='not_connected'?'尚未连接平台':esc(data.connection_status)}</h2><p>${esc(data.reason)}</p><p class="helper">最近自动同步：${data.last_sync_at?esc(dateText(data.last_sync_at)):'尚未发生'} · 实时能力：${data.realtime_verified?'已验证':'未验证'}</p><p>${esc(data.goal)}</p></section><section class="panel"><h2>本账号已有数据</h2><p>人工归档作品 ${esc(records.publication_count??0)} 条 · 人工指标快照 ${esc(records.metric_snapshot_count??0)} 份</p><p class="helper">${esc(records.limitation)}</p>${latest?`<h3>最近一份人工指标</h3><p class="helper">${esc(dateText(latest.observed_at))} · ${esc(latest.window)} · 平台尚未核实，非账号合计</p><div class="table-scroll"><table class="metric-table"><thead><tr><th>指标</th><th>记录值</th></tr></thead><tbody>${data.fields.map(f=>`<tr><td>${esc(f.label)}</td><td>${latest.values[f.key]===null||latest.values[f.key]===undefined?'未记录':esc(latest.values[f.key])}</td></tr>`).join('')}</tbody></table></div>`:'<p>尚无人工指标快照，可以在“数据复盘”录入已有数据。</p>'}</section><section class="panel"><h2>连接依据与下一步</h2><p>获取适用个人账号的授权渠道并完成实测后，才启用自动同步。当前没有收集密码或 Cookie 的连接入口。</p><ul>${(data.admission_requirements||[]).map(t=>`<li>${esc(t)}</li>`).join('')}</ul>${(data.sources||[]).map(s=>`<p>${connectionLink(s.url,s.title)}<br><span class="helper">${esc(s.finding)} · 核对日期 ${esc(s.reviewed_on)}</span></p>`).join('')}</section>`;
}
async function renderConnections(){
 const token=++connectionLoad,identity=activeAccountId;$('operationsContent').innerHTML='<section class="panel"><p>正在读取账号数据状态…</p></section>';
 try{const [data,sync]=await Promise.all([api('/api/social/connection?account_id='+encodeURIComponent(identity)),api('/api/social/sync?account_id='+encodeURIComponent(identity))]);if(token!==connectionLoad||currentPage!=='connections'||identity!==activeAccountId)return;const notes=sync.bound?await api('/api/social/sync/notes?account_id='+encodeURIComponent(identity)):[];if(token!==connectionLoad||currentPage!=='connections'||identity!==activeAccountId)return;$('operationsContent').innerHTML=sync.bound?syncOverview(sync,notes):connectionOverview(data);document.querySelectorAll('[data-note-comments]').forEach(b=>b.onclick=()=>loadSyncComments(identity,b.dataset.noteComments,b,token));document.querySelectorAll('[data-sync-action]').forEach(b=>b.onclick=()=>connectionAction(async()=>{await api('/api/social/sync/control','POST',{account_id:identity,action:b.dataset.syncAction});await renderConnections();}));if($('refreshSyncStatus'))$('refreshSyncStatus').onclick=()=>renderConnections();}
 catch(e){if(token===connectionLoad&&currentPage==='connections'&&identity===activeAccountId){$('operationsContent').innerHTML='<section class="panel"><p>账号数据状态读取失败，请重试。</p></section>';error(e);}}
}

function syncOverview(s,storedNotes){
 const names={ready:'等待同步',syncing:'正在读取',synced:'最近一轮读取成功',partial:'部分读取成功',paused:'已暂停',retrying:'断线退避中',needs_attention:'需要重新登录或检查'};
 const latest=s.latest_round?.summary||{},notes=storedNotes??s.latest_round?.notes??[];
 const stamp=t=>t?esc(dateText(new Date(t*1000).toISOString())):'尚无';
 return `<section class="panel"><h2>小红书 · ${esc(names[s.status]||s.status)}</h2><p>本机 MCP 只读连接 · 每 ${Math.round(s.interval_s/60)} 分钟自动读取</p><p>最近成功：${stamp(s.last_at)} · 下次读取：${stamp(s.next_at)}</p><p class="helper">${esc(s.limitation)} 这是浏览器观测数据，不是官方 API 或实时推送；电脑和服务需保持在线。</p>${s.error?`<p class="issue">${esc(s.error)}</p>`:''}<div class="buttons"><button id="refreshSyncStatus" class="quiet">刷新状态</button><button class="secondary" data-sync-action="${s.enabled?'pause':'resume'}">${s.enabled?'暂停自动同步':'恢复自动同步'}</button><button class="quiet" data-sync-action="refresh" ${s.status==='syncing'?'disabled':''}>立即核对一次</button></div></section><section class="panel"><h2>已同步笔记与评论</h2><p>唯一笔记 ${esc(s.counts.note)} 篇 · 唯一评论 ${esc(s.counts.comment)} 条</p><p class="helper">最近一轮新增笔记 ${esc(latest.new_notes??0)}，变化笔记 ${esc(latest.changed_notes??0)}，新增评论 ${esc(latest.new_comments??0)}；未读到的历史记录不会当作删除。下方展示最近观测的最多 30 篇已保存笔记。</p>${notes.map(n=>`<article class="detail-block"><h3>${connectionLink(n.url,n.title||'未命名笔记')}</h3><p>${esc(n.text.slice(0,300))}</p><p>点赞 ${n.metrics.likes??'未知'} · 收藏 ${n.metrics.favorites??'未知'} · 评论数 ${n.metrics.comments??'未知'} · 分享 ${n.metrics.shares??'未知'} · 曝光 / 阅读：暂无数据</p><div><button class="quiet" data-note-comments="${esc(n.id)}">查看已保存评论（非全量）</button><div class="saved-comments"></div></div></article>`).join('')||'<p>首轮读取完成后显示本人笔记。</p>'}</section>`;
}

async function loadSyncComments(account,note,button,token,offset=0){
 button.disabled=true;
 try{
  const data=await api('/api/social/sync/comments?account_id='+encodeURIComponent(account)+'&note_id='+encodeURIComponent(note)+'&offset='+offset);
  if(token!==connectionLoad||currentPage!=='connections'||account!==activeAccountId)return;
  const target=button.nextElementSibling;
  const html=data.items.map(c=>`<blockquote><p>${esc(c.content)}</p><span class="helper">首次观测：${esc(dateText(new Date(c.first_seen*1000).toISOString()))} · 最近观测：${esc(dateText(new Date(c.last_seen*1000).toISOString()))}</span></blockquote>`).join('');
  if(offset===0)target.innerHTML=html||'<p>尚无已保存评论正文；不代表平台没有评论。</p>';else target.insertAdjacentHTML('beforeend',html);
  button.textContent=data.next_offset===null?'已展示全部已保存评论（非全量）':'继续加载已保存评论';
  button.disabled=data.next_offset===null;
  if(data.next_offset!==null)button.onclick=()=>loadSyncComments(account,note,button,token,data.next_offset);
 }catch(e){if(token===connectionLoad&&currentPage==='connections'&&account===activeAccountId){button.disabled=false;error(e);}}
}
