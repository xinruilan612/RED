'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function setup(){
 const elements=new Map(),calls=[],errors=[],timers=[];let serial=0;
 const element=id=>{if(!elements.has(id))elements.set(id,{value:'',innerHTML:'',disabled:false,hidden:false});return elements.get(id);};
 const sandbox={pageInfo:{},activeAccountId:'a',currentPage:'library',crypto:{randomUUID:()=> 'key-'+(++serial)},URL,Set,Map,
  esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  api:async(...a)=>{calls.push(a);return a[0].includes('/jobs?')?[]:{};},error:e=>errors.push(e),toast(){},$:element,
  document:{querySelectorAll:()=>[]},setTimeout:fn=>{timers.push(fn);return fn;},clearTimeout:fn=>{const i=timers.indexOf(fn);if(i>=0)timers.splice(i,1);}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/knowledge.js','utf8'),sandbox);
 return {sandbox,calls,errors,timers,element,run:s=>vm.runInContext(s,sandbox)};
}
function fill(s,provider='xhs_local'){
 for(const [k,v]of Object.entries({ragProvider:provider,ragQuery:'美妆',ragLikes:'100',ragFavorites:'50',ragSort:'favorites'}))s.element(k).value=v;
}
const candidate={id:'c1',packet:{title:'参考',text:'公开取得的完整笔记正文供预览使用',source_url:'https://example.com/post',platform:'xiaohongshu',metrics:{likes:0,favorites:null}}};

test('theme search requests candidates for confirmation and never posts confirm automatically',async()=>{
 const s=setup();fill(s);s.run("bindRagSearch('a',0)");await s.element('ragSearchForm').onsubmit({preventDefault(){},submitter:{disabled:false}});
 const body=s.calls.find(c=>c[1]==='POST')[2];assert.equal(body.provider,'xhs_local');assert.equal(body.evidence_role,'expression_reference');assert.equal(body.style_filters.min_favorites,50);assert.equal(body.style_filters.sort_by,'favorites');assert.equal(body.confirmation_required,true);
 assert.equal(s.calls.filter(c=>c[0].includes('/confirm')).length,0);
});
test('web sources omit platform thresholds and hide their advanced controls',async()=>{
 const s=setup();fill(s,'bing');s.run("bindRagSearch('a',0)");assert.equal(s.element('ragAdvanced').hidden,true);assert.equal(s.element('ragLikes').disabled,true);
 await s.element('ragSearchForm').onsubmit({preventDefault(){},submitter:{disabled:false}});
 const body=s.calls.find(c=>c[1]==='POST')[2];assert.equal(body.provider,'bing');assert.equal(body.targets[0],'web');assert.equal(body.confirmation_required,true);assert.equal('style_filters' in body,false);
});
test('main search is simple, advanced criteria are folded, and candidates are not promised automatic saving',()=>{
 const s=setup(),html=s.run('ragSearchPanel()');assert.match(html,/主题/);assert.match(html,/资料来源/);assert.match(html,/<details id="ragAdvanced">/);assert.match(html,/>搜索资料</);assert.doesNotMatch(html,/搜索并加入|正文直接进入/);
 const script=fs.readFileSync('frontend/knowledge.js','utf8');assert.match(script,/<summary>补充自己的资料/);assert.match(script,/<summary[^>]*>已有资料/);
});
test('candidate previews escape text, reject unsafe links and start unchecked',()=>{
 const s=setup();s.sandbox.job={id:'j',candidates:[{id:'c',packet:{title:'<img>',text:'<script>PRIVATE</script>',source_url:'javascript:alert(1)',platform:'xiaohongshu',metrics:{likes:0}}}]};
 const html=s.run("ragCandidatePanel(job,'a')");assert.match(html,/&lt;img&gt;/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>|javascript:| checked/);assert.match(html,/点赞 0/);assert.match(html,/收藏 未知/);assert.match(html,/尚未加入资料库/);assert.match(html,/type="submit" disabled/);
});
test('awaiting confirmation renders review controls without exporting or auto-confirming',async()=>{
 const s=setup();s.sandbox.api=async(...args)=>{s.calls.push(args);return [{id:'j',queries:['主题'],status:'awaiting_confirmation',documents:[],candidates:[candidate]}];};
 await s.run("refreshRagJobs('a',0)");const html=s.element('ragJobResult').innerHTML;assert.match(html,/待你确认/);assert.match(html,/data-rag-confirm="j"/);assert.match(html,/完整候选正文/);assert.doesNotMatch(html,/\/export/);assert.equal(s.timers.length,0);assert.equal(s.calls.some(c=>c[1]==='POST'),false);
});
test('only selected known candidate IDs are submitted with a stable idempotency key',async()=>{
 const s=setup();s.sandbox.job={id:'j/a',candidates:[candidate,{id:'c2',packet:{}}]};s.sandbox.form={querySelectorAll:()=>[]};s.sandbox.refreshRagJobs=async()=>{};s.sandbox.refreshRagDocuments=async()=>{};
 await s.run("confirmRagSelection('a',0,job,['c1','unknown','c1'],form)");assert.equal(s.calls[0][0],'/api/research/jobs/j%2Fa/confirm');assert.deepEqual(Array.from(s.calls[0][2].candidate_ids),['c1']);assert.match(s.calls[0][2].key,/key-/);
});
test('no selection or a stale account cannot submit confirmation',async()=>{
 const s=setup();s.sandbox.job={id:'j',candidates:[candidate]};s.sandbox.form={querySelectorAll:()=>[]};
 await s.run("confirmRagSelection('a',0,job,[],form)");s.sandbox.activeAccountId='other';await s.run("confirmRagSelection('a',0,job,['c1'],form)");assert.equal(s.calls.length,0);
});
test('uncertain confirmation can retry the same selection with the same key',async()=>{
 const s=setup();s.sandbox.job={id:'j',candidates:[candidate]};s.sandbox.form={querySelectorAll:()=>[]};s.sandbox.refreshRagJobs=async()=>{};s.sandbox.refreshRagDocuments=async()=>{};
 s.sandbox.api=async(...args)=>{s.calls.push(args);if(s.calls.length===1)throw new Error('connection lost');return {};};
 await s.run("confirmRagSelection('a',0,job,['c1'],form)");await s.run("confirmRagSelection('a',0,job,['c1'],form)");assert.equal(s.calls.length,2);assert.equal(s.calls[0][2].key,s.calls[1][2].key);
});
test('an old jobs response cannot overwrite another account page',async()=>{
 const s=setup();let resolve;s.sandbox.api=()=>new Promise(r=>resolve=r);const pending=s.run("refreshRagJobs('a',0)");s.sandbox.activeAccountId='other';resolve([{id:'j',queries:['OLD'],status:'awaiting_confirmation',candidates:[candidate]}]);await pending;assert.equal(s.element('ragJobResult').innerHTML,'');
});
test('search errors stay actionable without treating timeout as logged out',()=>{
 const s=setup();assert.match(s.run("ragErrorText('XHS_SEARCH_HTTP_500')"),/本机 MCP 搜索接口返回 HTTP 500/);assert.match(s.run("ragErrorText('XHS_SEARCH_TIMEOUT')"),/超时/);assert.doesNotMatch(s.run("ragErrorText('XHS_SEARCH_TIMEOUT')"),/已失效|XHS_/);
});

test('XHS hides irrelevant web scope and only user links target a new tab',()=>{
 const s=setup();fill(s);s.run("bindRagSearch('a',0)");assert.equal(s.element('ragWebScope').hidden,true);
 s.sandbox.job={id:'j',candidates:[{...candidate,preview:{content_type:'video',cover_url:'https://sns-webpic-qc.xhscdn.com/cover.jpg'}}]};
 const html=s.run("ragCandidatePanel(job,'a')");assert.match(html,/查看小红书原文/);assert.match(html,/target="_blank"/);assert.match(html,/封面/);assert.match(html,/未读取音轨或转写/);assert.match(html,/评论 未知/);
 assert.doesNotMatch(fs.readFileSync('frontend/knowledge.js','utf8'),/window\.open\(|location\.(?:assign|replace)\(/);
});
test('link-only candidates cannot be selected or submitted as usable knowledge',async()=>{
 const s=setup();s.sandbox.job={id:'j',candidates:[{id:'link',packet:{title:'线索',source_url:'https://example.com',text:''}}]};s.sandbox.form={querySelectorAll:()=>[]};
 const html=s.run("ragCandidatePanel(job,'a')");assert.match(html,/暂不能作为创作资料/);assert.match(html,/data-rag-candidate[^>]+disabled/);
 await s.run("confirmRagSelection('a',0,job,['link'],form)");assert.equal(s.calls.length,0);
});
test('cancelled tasks retain usable candidates and saved rows preserve actual import status',async()=>{
 const s=setup();s.sandbox.api=async()=>[{id:'j',status:'cancelled',queries:['主题'],candidates:[candidate],items:[],documents:[]}];
 await s.run("refreshRagJobs('a',0)");assert.match(s.element('ragJobResult').innerHTML,/已取消/);assert.match(s.element('ragJobResult').innerHTML,/公开取得的完整笔记/);assert.doesNotMatch(s.element('ragJobResult').innerHTML,/已加入 0/);
 s.sandbox.job={id:'j',status:'done',candidates:[candidate],items:[{candidate_id:'c1',status:'saved'}]};
 const html=s.run("ragCandidatePanel(job,'a')");assert.match(html,/已入库/);assert.match(html,/已加入 1/);assert.match(html,/data-rag-candidate[^>]+disabled/);
});
test('late response for the same account cannot replace newer keyword results',async()=>{
 const s=setup(),resolvers=[];s.sandbox.api=()=>new Promise(r=>resolvers.push(r));
 const old=s.run("refreshRagJobs('a',0)"),fresh=s.run("refreshRagJobs('a',0)");
 resolvers[1]([{id:'fresh',queries:['新主题'],status:'failed'}]);await fresh;
 resolvers[0]([{id:'old',queries:['旧主题'],status:'failed'}]);await old;
 assert.match(s.element('ragJobResult').innerHTML,/新主题/);assert.doesNotMatch(s.element('ragJobResult').innerHTML,/旧主题/);
});
test('running job exposes cancellation and duplicate submissions are guarded',async()=>{
 const s=setup();fill(s,'bing');s.sandbox.api=async(...args)=>{s.calls.push(args);return args[0].includes('/jobs?')?[{id:'j',provider:'bing',queries:['美妆'],style_filters:{min_likes:100,min_favorites:50,sort_by:'favorites'},status:'running'}]:args[0].includes('/settings')?{providers:[{id:'bing',can_attempt:true}]}:{bound:true};};
 s.run("bindRagSearch('a',0)");await s.run("refreshRagJobs('a',0)");
 assert.match(s.element('ragJobResult').innerHTML,/data-rag-cancel="j"/);fill(s,'bing');
 await s.element('ragSearchForm').onsubmit({preventDefault(){},submitter:{}});assert.equal(s.calls.filter(c=>c[1]==='POST').length,0);
});
test('query and selection state survive a page rebind without opening a source',()=>{
 const s=setup();fill(s);s.run("ragSelections.set('a/j',new Set(['c1']));saveRagView('a')");s.element('ragQuery').value='';
 s.run("restoreRagView('a')");assert.equal(s.element('ragQuery').value,'美妆');assert.equal(s.run("ragSelections.get('a/j').has('c1')"),true);
});


test('covers only load from trusted platform CDNs without inline CSP violations',()=>{
 const s=setup();s.sandbox.job={id:'j',candidates:[{...candidate,preview:{cover_url:'https://sns-webpic-qc.xhscdn.com/cover.jpg'}}]};
 const html=s.run("ragCandidatePanel(job,'a')");assert.match(html,/class="rag-candidate-cover" data-rag-cover/);assert.doesNotMatch(html,/style=|onerror=/);
 for(const url of ['https://evil.example/image','https://xhscdn.com.evil.example/image','ftp://sns.xhscdn.com/image','https://user@a.xhscdn.com/image']){
  s.sandbox.url=url;assert.equal(s.run("ragCoverUrl(url,'xiaohongshu')"),'');
 }
 assert.equal(s.run("ragCoverUrl('https://sns.xhscdn.com/image','web')"),'');
 assert.equal(s.run("ragCoverUrl('http://sns-webpic-qc.xhscdn.com/image','xiaohongshu')"),'http://sns-webpic-qc.xhscdn.com/image');
});
test('cover failures hide the broken image and show readable fallback',()=>{
 const s=setup(),fallback={hidden:true},img={complete:false,naturalWidth:0,hidden:false,nextElementSibling:fallback};
 s.sandbox.form={querySelectorAll:()=>[img]};s.run('bindRagCovers(form)');img.onerror();assert.equal(img.hidden,true);assert.equal(fallback.hidden,false);
 img.onload();assert.equal(img.hidden,false);assert.equal(fallback.hidden,true);
});


test('empty successful search never claims that import completed',async()=>{
 const s=setup();s.sandbox.api=async()=>[{id:'j',queries:['主题'],status:'done',documents:[],candidates:[]}];
 await s.run("refreshRagJobs('a',0)");assert.match(s.element('ragJobResult').innerHTML,/搜索完成/);assert.doesNotMatch(s.element('ragJobResult').innerHTML,/导入已完成/);
});
test('per-note failure remains visible alongside successful staged candidates',async()=>{
 const s=setup();s.sandbox.api=async()=>[{id:'j',queries:['主题'],status:'awaiting_confirmation',documents:[],candidates:[candidate],attempts:[{status:'failed',error:'XHS_TIMEOUT'}]}];
 await s.run("refreshRagJobs('a',0)");const html=s.element('ragJobResult').innerHTML;assert.match(html,/部分读取未完成/);assert.match(html,/读取超时/);assert.match(html,/公开取得的完整笔记/);
});


test('platform abbreviated metrics stay original strings without becoming exact counts',()=>{
 const s=setup();s.sandbox.job={id:'j',candidates:[{...candidate,packet:{...candidate.packet,metrics:{likes:null,favorites:0,comments:null}},preview:{metric_display:{likes:'1.2万',favorites:'8万'}}}]};
 const html=s.run("ragCandidatePanel(job,'a')");assert.match(html,/点赞 1.2万（平台原值）/);assert.match(html,/收藏 0/);assert.match(html,/评论 未知/);assert.doesNotMatch(html,/12000|8万|暂无真实互动依据| · 达到所选互动阈值/);
 assert.match(html,/未确认达到所选互动阈值/);
});


test('retrying active confirmation preserves its original selection and key',async()=>{
 const s=setup();s.sandbox.job={id:'j',status:'confirming',candidates:[candidate,{...candidate,id:'c2'},{...candidate,id:'c3'}],items:[{candidate_id:'c1',status:'saved'}],confirmation:{candidate_ids:['c1','c2'],key:'prior-key'}};
 s.sandbox.form={querySelectorAll:()=>[]};s.sandbox.refreshRagJobs=async()=>{};s.sandbox.refreshRagDocuments=async()=>{};
 const html=s.run("ragCandidatePanel(job,'a')");assert.match(html,/value="c2" checked/);assert.match(html,/value="c3"[^>]*disabled/);
 await s.run("confirmRagSelection('a',0,job,['c2'],form)");assert.deepEqual(Array.from(s.calls[0][2].candidate_ids),['c1','c2']);assert.equal(s.calls[0][2].key,'prior-key');
});


test('confirmation refreshes library counts and rows without replacing drafts or candidates',async()=>{
 const s=setup();s.sandbox.currentAccount=()=>({name:'当前账号'});s.sandbox.api=async()=>[{id:'doc1',title:'新资料',version:1,source_type:'research_case',updated_at:0}];
 s.element('documentText').value='尚未保存的用户正文';s.element('documentTitle').value='用户标题';s.element('ragQuery').value='衬衣领子发黄';s.element('ragJobResult').innerHTML='候选及选择状态';s.element('operationsContent').innerHTML='整个页面';
 await s.run("refreshRagDocuments('a',0)");assert.equal(s.element('ragLibraryCount').textContent,'当前账号 · 1 份已有资料');assert.equal(s.element('ragExistingSummary').textContent,'已有资料（1 份）');assert.match(s.element('ragExistingDocuments').innerHTML,/新资料/);
 assert.equal(s.element('documentText').value,'尚未保存的用户正文');assert.equal(s.element('documentTitle').value,'用户标题');assert.equal(s.element('ragQuery').value,'衬衣领子发黄');assert.equal(s.element('ragJobResult').innerHTML,'候选及选择状态');assert.equal(s.element('operationsContent').innerHTML,'整个页面');
});


test('in-progress search does not label unfinished attempt tracking as zero searches',async()=>{
 const s=setup();s.sandbox.api=async()=>[{id:'j',queries:['主题'],status:'running',documents:[],candidates:[candidate],searches:[],reads:[{status:'awaiting_confirmation'}]}];
 await s.run("refreshRagJobs('a',0)");const html=s.element('ragJobResult').innerHTML;assert.match(html,/正在搜索 \/ 读取，已有 1 条读取记录/);assert.doesNotMatch(html,/已执行 0 次搜索/);
 const panel=s.run('ragSearchPanel()');assert.match(panel,/本次平台返回的候选按可得互动排序/);assert.match(panel,/不代表全站最高/);
});


test('scope identity includes source, range and filters while folding query whitespace',()=>{
 const s=setup();s.sandbox.p={account_id:'a',queries:['  大衣   护理  '],provider:'xhs_local',targets:['xiaohongshu'],style_filters:{min_likes:100,min_favorites:50,sort_by:'likes'}};
 const original=s.run('ragScope(p)');s.sandbox.p.queries=['大衣 护理'];assert.equal(s.run('ragScope(p)'),original);
 s.sandbox.p.style_filters.sort_by='favorites';assert.notEqual(s.run('ragScope(p)'),original);
 s.sandbox.p.provider='bing';assert.notEqual(s.run('ragScope(p)'),original);
 s.sandbox.p.targets=['jd'];const jd=s.run('ragScope(p)');s.sandbox.p.targets=['web'];assert.notEqual(s.run('ragScope(p)'),jd);
});
test('current search and other themes are separated into a collapsed history section',()=>{
 const s=setup();s.sandbox.jobs=[{id:'old',queries:['旧主题'],provider:'bing',status:'running'},{id:'new',queries:['新主题'],provider:'bing',status:'done'}];
 s.run("ragViewState.set('a',{jobId:'new',scope:ragScope(jobs[1])});renderRagJobList('a',0,jobs)");
 const html=s.element('ragJobResult').innerHTML,current=html.split('<details data-rag-history>')[0];assert.match(current,/新主题/);assert.doesNotMatch(current,/旧主题/);assert.match(html,/<details data-rag-history><summary>历史研究/);
});
test('polling failure is explicit, retains candidates and retries status at most twice',async()=>{
 const s=setup();s.sandbox.jobs=[{id:'j',queries:['主题'],status:'running',candidates:[candidate]}];s.run("ragJobsCache.set('a',jobs)");s.sandbox.api=async()=>{throw new Error('network down');};
 await s.run("refreshRagJobs('a',0)");await s.run("refreshRagJobs('a',0,true)");await s.run("refreshRagJobs('a',0,true)");
 assert.equal(s.timers.length,2);const html=s.element('ragJobResult').innerHTML;assert.match(html,/状态刷新中断/);assert.match(html,/公开取得的完整笔记正文/);assert.doesNotMatch(html,/正在后台搜索与读取/);
});
test('a hung status request gets a bounded failure instead of infinite running',async()=>{
 const s=setup();s.sandbox.api=()=>new Promise(()=>{});const pending=s.run("refreshRagJobs('a',0)");s.timers.shift()();await pending;assert.match(s.element('ragJobResult').innerHTML,/状态刷新中断/);
});
test('editing the scope while POST is pending prevents its late response from taking over',async()=>{
 const s=setup();fill(s,'bing');let resolve;s.sandbox.api=async(path,method)=>{if(method==='POST')return new Promise(r=>resolve=r);if(path.includes('/jobs?'))return [];if(path.includes('/settings'))return {providers:[{id:'bing',can_attempt:true}]};return {bound:false};};
 s.run("bindRagSearch('a',0)");await s.run("refreshRagJobs('a',0)");const pending=s.element('ragSearchForm').onsubmit({preventDefault(){},submitter:{}});
 s.element('ragQuery').value='不同的新主题';s.element('ragQuery').oninput();resolve({id:'old',queries:['美妆'],provider:'bing',status:'queued'});await pending;
 assert.equal(s.run("ragViewState.get('a').jobId"),null);assert.equal(s.element('ragQuery').value,'不同的新主题');assert.doesNotMatch(s.element('ragJobResult').innerHTML,/data-rag-cancel="old"/);
});
test('terminal outcomes distinguish real empty results, parse failure and all-detail failure',()=>{
 const s=setup();for(const [outcome,label]of [['empty_results','平台未返回候选'],['invalid_results','无法解析'],['filtered_all','均不符合'],['detail_failed','全部读取失败'],['search_failed','搜索失败'],['queue_timeout','排队超时']]){
  s.sandbox.job={status:'done',outcome,candidates:[],documents:[]};assert.match(s.run('ragJobStatus(job)'),new RegExp(label));
 }
 s.sandbox.job={status:'cancelled',outcome:'empty_results'};assert.equal(s.run('ragJobStatus(job)'),'已取消');
});
test('job details show canonical query and local MCP errors without claiming upstream HTTP',()=>{
 const s=setup();s.sandbox.job={queries:['主题 研究'],raw_queries:[' 主题   研究 '],phase:'complete',counts:{raw_count:4,detail_failed_count:2},reuse:{kind:'active_task',cache_hit:false},error_origin:'local_mcp',mcp_http_status:500};
 const html=s.run('ragJobTrace(job)');assert.match(html,/实际查询：主题 研究/);assert.match(html,/输入原文/);assert.match(html,/复用同范围运行中任务/);assert.match(html,/未使用结果缓存/);assert.match(html,/本机 MCP HTTP 500/);assert.match(html,/不能据此推断平台上游/);
});
test('read-only retry trace states no new Baidu search and suppresses cache miss wording',()=>{
 const s=setup();s.sandbox.job={queries:['主题 研究'],read_only_retry:true,reuse:{cache_hit:false}};
 const html=s.run('ragJobTrace(job)');assert.match(html,/仅重读已保存链接，无新增百度搜索/);assert.doesNotMatch(html,/未使用结果缓存/);
});
test('unrelated pending history does not keep current completed search polling',async()=>{
 const s=setup();s.sandbox.jobs=[{id:'new',queries:['新主题'],status:'done'},{id:'old',queries:['旧主题'],status:'running'}];s.run("ragViewState.set('a',{jobId:'new'})");s.sandbox.api=async()=>s.sandbox.jobs;
 await s.run("refreshRagJobs('a',0)");assert.equal(s.timers.length,0);
});

function withSearchLeadHelpers(s){vm.runInContext(fs.readFileSync('frontend/research.js','utf8'),s.sandbox);}
test('library distinguishes eight search leads from zero readable candidates and offers only rereading',()=>{
 const s=setup();withSearchLeadHelpers(s);s.sandbox.job={id:'j',status:'failed',search_result_count:8,search_result_retention:'legacy_partial',search_results:Array.from({length:5},(_,i)=>({url:'https://example.com/'+i,title:'线索'+i,body_read:false})),candidates:[]};
 const html=s.run("ragJobPanel(job,'a')");assert.match(html,/搜索已有结果，正文读取未完成/);assert.match(html,/搜索返回 8 条结果/);assert.match(html,/旧任务仅保留 5 条链接/);assert.match(html,/可预览正文 0 条/);assert.match(html,/data-rag-retry-reads="j"/);assert.doesNotMatch(html,/data-rag-candidate|搜索到 0/);
 for(const status of ['running','queued','confirming','done']){s.sandbox.job.status=status;assert.doesNotMatch(s.run("ragJobPanel(job,'a')"),/data-rag-retry-reads/);}
 s.sandbox.job.status='partial';s.sandbox.job.confirmation={candidate_ids:['c']};assert.doesNotMatch(s.run("ragJobPanel(job,'a')"),/data-rag-retry-reads/);
});
test('reread posts the saved job only, does not search or confirm, and prevents double clicks',async()=>{
 const s=setup();withSearchLeadHelpers(s);s.sandbox.job={id:'a/b',status:'failed',search_results:[{url:'https://example.com',body_read:false}]};s.sandbox.button={disabled:false};let finish;
 s.sandbox.api=async(...args)=>{s.calls.push(args);return new Promise(resolve=>finish=resolve);};s.run('refreshRagJobs=async()=>{}');
 const pending=s.run("retryRagReads(job,'a',0,button)");await s.run("retryRagReads(job,'a',0,button)");assert.equal(s.calls.length,1);assert.equal(s.calls[0][0],'/api/research/jobs/a%2Fb/retry-reads');assert.equal(s.calls[0][1],'POST');assert.deepEqual(JSON.parse(JSON.stringify(s.calls[0][2])),{});finish({});await pending;assert.equal(s.sandbox.button.disabled,false);
 s.sandbox.activeAccountId='other';await s.run("retryRagReads(job,'a',0,button)");assert.equal(s.calls.length,1);
});
test('failed reread keeps the original leads and unlocks retry',async()=>{
 const s=setup();withSearchLeadHelpers(s);s.sandbox.job={id:'j',status:'failed',search_results:[{url:'https://example.com',body_read:false}]};s.sandbox.button={disabled:false};s.sandbox.api=async()=>{throw Error('链接读取未启动，请重试');};
 await s.run("retryRagReads(job,'a',0,button)");assert.equal(s.sandbox.button.disabled,false);assert.equal(s.sandbox.job.search_results.length,1);assert.match(s.errors[0].message,/请重试/);
});

test('library source HTTP failures explain page restrictions without blaming credentials',()=>{
 const s=setup();for(const [code,label] of [['SOURCE_HTTP_403','读取被拒绝（403）'],['SOURCE_HTTP_404','页面不存在（404）'],['SOURCE_HTTP_429','限流（429）'],['SOURCE_HTTP_ERROR','上游 HTTP 错误']]){
  s.sandbox.code=code;const text=s.run('ragErrorText(code)');assert.ok(text.includes(label));assert.doesNotMatch(text,/密钥|Key|重新登录/);
 }
});

test('usable bodies precede folded unread leads with one selection per candidate',()=>{
 const s=setup();withSearchLeadHelpers(s);s.sandbox.job={id:'j',status:'awaiting_confirmation',candidates:[candidate],search_results:[{url:candidate.packet.source_url,body_read:true},{url:'https://example.com/unread',body_read:false,read_error:'SOURCE_HTTP_403'}]};
 const html=s.run("ragJobPanel(job,'a')");assert.ok(html.indexOf('data-rag-confirm')<html.indexOf('research-search-leads'));assert.equal((html.match(/data-rag-candidate value/g)||[]).length,1);assert.match(html,/rag-selectable-card/);assert.match(html,/data-rag-link-candidate="c1"/);assert.match(html,/data-rag-save-lead="https:\/\/example.com\/unread"/);assert.match(html,/<details><summary>程序未读到 1 条/);assert.match(html,/不代表浏览器无法打开/);assert.match(html,/一键加入全部可用正文/);assert.match(html,/加入所选资料/);assert.match(html,/写作材料 \/ 待核验事实/);assert.match(html,/写法参考/);
});
test('lead save submits only known unread unsaved URLs, separately from bodies',async()=>{
 const s=setup();s.sandbox.job={id:'j',candidates:[candidate],search_results:[{url:'https://example.com/unread'},{url:'https://example.com/saved',lead_saved:true},{url:candidate.packet.source_url,body_read:true}]};s.sandbox.form={querySelectorAll:()=>[]};s.sandbox.refreshRagJobs=async()=>{};s.sandbox.refreshRagDocuments=async()=>{};
 await s.run("confirmRagSelection('a',0,job,[],form,['https://example.com/unread','https://example.com/unread','https://example.com/saved','https://example.com/post','https://unknown.test'])");
 assert.deepEqual(Array.from(s.calls[0][2].candidate_ids),[]);assert.deepEqual(Array.from(s.calls[0][2].lead_urls),['https://example.com/unread']);assert.equal(s.calls[0][2].purpose,'product_fact');
});
test('selected purpose is submitted and changes confirmation attempt identity',async()=>{
 const s=setup();let purpose='product_fact';s.sandbox.job={id:'j',candidates:[candidate]};s.sandbox.form={querySelectorAll:()=>[],querySelector:q=>q==='[data-rag-purpose]'?{value:purpose}:null};s.sandbox.refreshRagJobs=async()=>{};s.sandbox.refreshRagDocuments=async()=>{};
 await s.run("confirmRagSelection('a',0,job,['c1'],form)");purpose='expression_reference';await s.run("confirmRagSelection('a',0,job,['c1'],form)");assert.equal(s.calls[0][2].purpose,'product_fact');assert.equal(s.calls[1][2].purpose,'expression_reference');assert.notEqual(s.calls[0][2].key,s.calls[1][2].key);
});
test('add all uses only usable unsaved body candidates and excludes leads',async()=>{
 const s=setup();s.sandbox.jobs=[{id:'j',candidates:[candidate,{...candidate,id:'saved'},{id:'empty',packet:{text:''}}],items:[{candidate_id:'saved',status:'saved'}],search_results:[{url:'https://example.com/unread'}]}];const all={},form={dataset:{ragConfirm:'j'},querySelectorAll:()=>[],querySelector:q=>q==='[data-rag-add-all]'?all:null};s.sandbox.document.querySelectorAll=q=>q==='[data-rag-confirm]'?[form]:[];s.sandbox.refreshRagJobs=async()=>{};s.sandbox.refreshRagDocuments=async()=>{};
 s.run("bindRagCandidates(jobs,'a',0)");await all.onclick();assert.deepEqual(Array.from(s.calls[0][2].candidate_ids),['c1']);assert.deepEqual(Array.from(s.calls[0][2].lead_urls),[]);
});
test('search body shortcut selects the existing checkbox and does not submit',()=>{
 const s=setup();let changes=0,scrolls=0;const input={value:'c1',checked:false,onchange:()=>changes++,closest:()=>({scrollIntoView:()=>scrolls++})},form={dataset:{ragConfirm:'j'},querySelectorAll:()=>[input]},button={dataset:{job:'j',ragLinkCandidate:'c1'}};
 s.sandbox.document.querySelectorAll=q=>q==='[data-rag-link-candidate]'?[button]:q==='[data-rag-confirm]'?[form]:[];s.run("bindRagSearchResults([],'a',0)");button.onclick();assert.equal(input.checked,true);assert.equal(changes,1);assert.equal(scrolls,1);assert.equal(s.calls.length,0);
});

test('completed confirmation history does not lock another unsaved body or a lead',async()=>{
 const s=setup();withSearchLeadHelpers(s);s.sandbox.job={id:'j',status:'done',candidates:[candidate,{...candidate,id:'c2'}],items:[{candidate_id:'c1',status:'saved'}],confirmation:{candidate_ids:['c1'],key:'old-key'},search_results:[{url:'https://example.com/unread'}]};s.sandbox.form={querySelectorAll:()=>[]};s.sandbox.refreshRagJobs=async()=>{};s.sandbox.refreshRagDocuments=async()=>{};
 const html=s.run("ragCandidatePanel(job,'a')");assert.doesNotMatch(html,/value="c2"[^>]*disabled/);
 await s.run("confirmRagSelection('a',0,job,['c2'],form)");assert.deepEqual(Array.from(s.calls[0][2].candidate_ids),['c2']);assert.notEqual(s.calls[0][2].key,'old-key');
 await s.run("confirmRagSelection('a',0,job,[],form,['https://example.com/unread'])");assert.deepEqual(Array.from(s.calls[1][2].lead_urls),['https://example.com/unread']);
});

test('historical reference metadata labels report date, original displayed counts and analysis scope',()=>{
 const s=setup();s.sandbox.doc={source_url:'https://example.com/note',metadata:{research_case:{evidence_role:'expression_reference',metrics:{likes:768300,favorites:672900},provenance:{metrics_basis:'historical_report',report_published_date:'2022-07-07',metrics_display:{likes:'76.83万',favorites:'67.29万'},content_scope:'short_excerpt_and_structure_analysis',evidence_url:'https://example.com/report'}}}};
 const html=s.run('ragDocumentMeta(doc)');assert.match(html,/写法参考 · 历史报道指标（2022-07-07） · 点赞 76.83万 · 收藏 67.29万/);assert.match(html,/短摘录与原创结构拆解/);assert.match(html,/href="https:\/\/example.com\/report"/);assert.match(html,/案例出处/);assert.doesNotMatch(html,/原文来源|href="https:\/\/example.com\/note"/);
});
test('primary snapshot labels observation date and preserves original source link',()=>{
 const s=setup();s.sandbox.doc={source_url:'https://example.com/note',metadata:{research_case:{evidence_role:'expression_reference',metrics:{likes:100,favorites:null},provenance:{metrics_basis:'public_page_snapshot',metrics_observed_date:'2026-10-13'}}}};
 const html=s.run('ragDocumentMeta(doc)');assert.match(html,/公开页面快照指标（2026-10-13）/);assert.match(html,/点赞 100 · 收藏 未知/);assert.match(html,/原文来源/);assert.doesNotMatch(html,/历史报道|案例出处|短摘录/);
});
test('provenance labels escape external values and unsupported metadata adds no fabricated claims',()=>{
 const s=setup();s.sandbox.doc={source_url:'javascript:alert(1)',metadata:{research_case:{metrics:{likes:0},provenance:{metrics_basis:'historical_report',report_published_date:'<img>',metrics_display:{likes:'<script>'},evidence_url:'javascript:alert(1)'}}}};
 let html=s.run('ragDocumentMeta(doc)');assert.match(html,/&lt;img&gt;/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<img>|<script>|javascript:|写法参考/);
 s.sandbox.doc={metadata:{research_case:{metrics:{likes:0,favorites:2}}}};assert.equal(s.run('ragDocumentMeta(doc)'),'<p class="helper">点赞 0 · 收藏 2</p>');s.sandbox.doc={};assert.equal(s.run('ragDocumentMeta(doc)'),'');
});
