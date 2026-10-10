'use strict';
pageInfo.connections=['DATA / CONNECTION','让账号数据有来源、可追溯。','查看实际接入能力和已有记录，未连接的数据保持明确。'];
let connectionLoad=0,connectionMutation=false;
function connectionLink(url,label){try{const u=new URL(url);if(u.protocol!=='https:')return esc(label);return `<a href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(label)} ↗</a>`;}catch(_){return esc(label);}}
async function connectionAction(action){
 if(connectionMutation)return false;connectionMutation=true;
 document.querySelectorAll('#operationsContent button').forEach(b=>b.disabled=true);
 try{await action();clearError();return true;}catch(e){error(e);return false;}
 finally{connectionMutation=false;document.querySelectorAll('#operationsContent button').forEach(b=>b.disabled=false);}
}
function connectionOverview(data){
 const records=data.local_records||{},latest=records.latest_metric;
 return `<section class="panel"><h2>${esc(data.account_name)} · ${data.connection_status==='not_connected'?'尚未连接平台':esc(data.connection_status)}</h2><p>${esc(data.reason)}</p><p class="helper">最近自动同步：${data.last_sync_at?esc(dateText(data.last_sync_at)):'尚未发生'} · 实时能力：${data.realtime_verified?'已验证':'未验证'}</p><p>${esc(data.goal)}</p></section><section class="panel"><h2>本账号已有数据</h2><p>人工归档作品 ${esc(records.publication_count??0)} 条 · 人工指标快照 ${esc(records.metric_snapshot_count??0)} 份</p><p class="helper">${esc(records.limitation)}</p>${latest?`<h3>最近一份人工指标</h3><p class="helper">${esc(dateText(latest.observed_at))} · ${esc(latest.window)} · 平台尚未核实，非账号合计</p><div class="table-scroll"><table class="metric-table"><thead><tr><th>指标</th><th>记录值</th></tr></thead><tbody>${data.fields.map(f=>`<tr><td>${esc(f.label)}</td><td>${latest.values[f.key]===null||latest.values[f.key]===undefined?'未记录':esc(latest.values[f.key])}</td></tr>`).join('')}</tbody></table></div>`:'<p>尚无人工指标快照，可以在“数据复盘”录入已有数据。</p>'}</section><section class="panel"><h2>连接依据与下一步</h2><p>获取适用个人账号的授权渠道并完成实测后，才启用自动同步。当前没有收集密码或 Cookie 的连接入口。</p><ul>${(data.admission_requirements||[]).map(t=>`<li>${esc(t)}</li>`).join('')}</ul>${(data.sources||[]).map(s=>`<p>${connectionLink(s.url,s.title)}<br><span class="helper">${esc(s.finding)} · 核对日期 ${esc(s.reviewed_on)}</span></p>`).join('')}</section>`;
}
async function renderConnections(){
 const token=++connectionLoad,identity=activeAccountId;$('operationsContent').innerHTML='<section class="panel"><p>正在读取账号数据状态…</p></section>';
 try{const [data,sync]=await Promise.all([api('/api/social/connection?account_id='+encodeURIComponent(identity)),api('/api/social/sync?account_id='+encodeURIComponent(identity))]);if(token!==connectionLoad||currentPage!=='connections'||identity!==activeAccountId)return;const notes=[];if(token!==connectionLoad||currentPage!=='connections'||identity!==activeAccountId)return;$('operationsContent').innerHTML=sync.bound?syncOverview(sync,notes):connectionOverview(data);document.querySelectorAll('[data-note-comments]').forEach(b=>b.onclick=()=>loadSyncComments(identity,b.dataset.noteComments,b,token));document.querySelectorAll('[data-import-note]').forEach(b=>b.onclick=()=>importSyncCase(identity,b.dataset.importNote));document.querySelectorAll('[data-sync-action]').forEach(b=>b.onclick=()=>connectionAction(async()=>{await api('/api/social/sync/control','POST',{account_id:identity,action:b.dataset.syncAction});await renderConnections();}));if($('reconnectSync'))$('reconnectSync').onclick=()=>reconnectSync(identity,token);if($('refreshSyncStatus'))$('refreshSyncStatus').onclick=()=>renderConnections();}
 catch(e){if(token===connectionLoad&&currentPage==='connections'&&identity===activeAccountId){$('operationsContent').innerHTML='<section class="panel"><p>账号数据状态读取失败，请重试。</p></section>';error(e);}}
}

function creatorMetricsOverview(source,previous){
 if(source&&['failed','error','unavailable','needs_attention'].includes(source.status)&&previous){source={...previous,status:'stale',error:source.error,failed_attempt_at:source.observed_at};}
 if(!source)return '<section class="panel"><h2>创作中心流量</h2><p>尚无创作中心浏览器观测。单篇曝光和阅读保持未知。</p></section>';
 const metrics={},notes=(source.notes||[]).filter(note=>note.visibility==='public');
 const hasData=Object.values(metrics).some(v=>v!==null&&v!==undefined)||notes.length>0;
 const stale=source.status==='stale'||(hasData&&['failed','error','unavailable','needs_attention'].includes(source.status));
 const status=stale?'旧数据 · 本轮读取失败':({ok:'本轮读取成功',synced:'本轮读取成功',succeeded:'本轮读取成功',partial:'部分读取成功',failed:'本轮读取失败',error:'本轮读取失败',unavailable:'当前不可读取'}[source.status]||source.status||'尚未读取');
 const stamp=value=>value===null||value===undefined?'未知':esc(dateText(typeof value==='number'?new Date(value*1000).toISOString():value));
 const value=(item,key,displays={})=>item[key]===null||item[key]===undefined?(displays[key]?`${esc(displays[key])}（页面显示，精确值未知）`:'未知'):esc(item[key])+(['cover_ctr','video_completion_rate'].includes(key)&&typeof item[key]==='number'?'%':'');
 return `<section class="panel"><h2>创作中心流量 · ${esc(status)}</h2><p>独立来源：${source.source_method==='creator_browser_dom'?'创作中心浏览器页面观测':esc(source.source_method||'来源未知')}。观测时间：${stamp(source.observed_at)} · 平台数据更新时间：${stamp(source.source_updated_at)}${source.failed_attempt_at?` · 本轮失败尝试：${stamp(source.failed_attempt_at)}`:""}</p>${stale?'<p class="issue">以下保留上次观测数据，尚未重新确认；不代表当前流量。</p>':''}${source.error?`<p class="issue">${esc(source.error)}</p>`:''}<h3>公开笔记逐篇流量</h3><p class="helper">每行对应一篇公开笔记，私密笔记不显示。未提供的指标保持未知。</p>${notes.length?`<div class="table-scroll"><table class="metric-table"><thead><tr><th>笔记</th><th>阅读 / 观看</th><th>点赞</th><th>收藏</th><th>评论</th><th>分享</th></tr></thead><tbody>${notes.map(note=>`<tr><td>${connectionLink(note.source_url,note.title||note.id||'未命名笔记')}<p class="helper">笔记 ID：${esc(note.id||'未知')}</p></td>${['views','likes','favorites','comments','shares'].map(key=>`<td>${value(note.metrics||{},key,note.metric_displays)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:'<p>尚无可对应到单篇笔记的创作中心指标。</p>'}</section>`;
}

function syncOverview(s,storedNotes){
 const names={ready:'等待同步',syncing:'正在读取',synced:'最近一轮读取成功',partial:'部分读取成功',paused:'已暂停',retrying:'断线退避中',needs_attention:'需要重新登录或检查'};
 const latest=s.latest_round?.summary||{},notes=storedNotes??s.latest_round?.notes??[],creator=s.creator_metrics??s.latest_round?.creator_metrics;
 const stamp=t=>t?esc(dateText(new Date(t*1000).toISOString())):'尚无';
 return `<section class="panel"><h2>小红书 · ${esc(names[s.status]||s.status)}</h2><p>本机 MCP 只读连接 · 每 ${Math.round(s.interval_s/60)} 分钟自动读取</p><p>最近成功：${stamp(s.last_at)} · 下次读取：${stamp(s.next_at)}</p><p class="helper">${esc(s.limitation)} 这是浏览器观测数据，不是官方 API 或实时推送；电脑和服务需保持在线。</p>${s.error?`<p class="issue">${esc(s.error)}</p>`:''}<div class="buttons"><button id="reconnectSync" class="secondary">扫码重新登录</button><button id="refreshSyncStatus" class="quiet">刷新状态</button><button class="secondary" data-sync-action="${s.enabled?'pause':'resume'}">${s.enabled?'暂停自动同步':'恢复自动同步'}</button><button class="quiet" data-sync-action="refresh" ${s.status==='syncing'?'disabled':''}>立即核对一次</button></div><div id="syncLoginQRCode"></div></section>${creatorMetricsOverview(creator,s.creator_last_success)}`;
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

async function importSyncCase(account,note){
 if(!window.confirm('将这篇本人笔记的已保存文字加入案例研究与资料库，供后续创作作表达参考。不会导入评论，也不会重新访问平台；浏览器观测指标仍未获官方核验。确认你有权保存并使用？'))return;
 await connectionAction(async()=>{
  const result=await api('/api/social/sync/import-case','POST',{account_id:account,note_id:note,permission_confirmed:true});
  toast(result.reused?'相同正文已在案例库，复用已有版本':'已保存为表达参考案例，可在案例研究和资料库查看');
 });
}

async function reconnectSync(account,token){
 await connectionAction(async()=>{
  const data=await api('/api/social/sync/login','POST',{account_id:account});
  if(token!==connectionLoad||currentPage!=='connections'||account!==activeAccountId)return;
  await renderConnections();
  if(currentPage!=='connections'||account!==activeAccountId)return;
  const target=$('syncLoginQRCode');
  if(data.is_logged_in){target.innerHTML='<p>本机连接器已登录。点击“恢复自动同步”后将重新核对绑定账号身份；不同账号不会写入。</p>';return;}
  if(typeof data.img!=='string'||!data.img.startsWith('data:image/png;base64,')||data.img.length>750000)throw new Error('二维码图片格式无效');
  target.innerHTML=`<p>自动同步已暂停，请用原绑定的小红书账号扫码。有效期：${esc(data.timeout)}。扫码完成后点击“恢复自动同步”，系统会再次核对账号。</p><img src="${esc(data.img)}" alt="小红书重新登录二维码" width="240">`;
 });
}
