const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(){
 const elements={};const e=id=>elements[id]||(elements[id]={innerHTML:'',value:''});let n=0;
 const s={URL,pageInfo:{},activeAccountId:'a',currentPage:'topics',crypto:{randomUUID:()=>`c${++n}`},$:e,esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),currentAccount:()=>({name:'测试账号'}),setTimeout,noticeSeverity:()=> 'info',api:async()=>data(),toast:()=>{},startCreation:()=>true};
 vm.createContext(s);vm.runInContext(fs.readFileSync('frontend/topics.js','utf8'),s);
 return {s,e,eval:code=>vm.runInContext(code,s)};
}
function data(extra={}){return {version:1,account_revision:2,encoder_ready:true,config:{positioning:'摄影',audience:'初学者',window:'72h',metric:'views',text_weight:.55,image_weight:.25,profile_weight:.2,neighbors:5},history:[],...extra};}
test('free text positioning is editable with no hard-coded niche; unavailable encoder gives calm instructions',async()=>{
 const x=setup();x.s.api=async()=>data({encoder_ready:false,config:{...data().config,positioning:'天文观测',audience:'喜欢星空的人'}});await x.s.renderTopics();
 const html=x.e('operationsContent').innerHTML;assert.match(html,/天文观测/);assert.match(html,/喜欢星空的人/);assert.match(html,/保存会同步当前账号档案/);assert.match(html,/图文编码模型尚未准备好/);assert.match(html,/type="submit" class="primary" disabled/);assert.doesNotMatch(html,/class="error/);
});
test('result distinguishes numeric predictions from matching suggestions and escapes source content',()=>{
 const {s}=setup();const html=s.topicsResultHTML({method:'<script>bad</script>',candidates:[{id:'one',title:'<img src=x>',fit_score:.6,estimated_value:null,reason:'<b>why</b>',references:[{title:'<script>bad</script>',similarity:.7}]}]},data().config);
 assert.match(html,/先看匹配建议/);assert.match(html,/不是爆款概率/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<script>|<img src=x>|参考值/);
 const withNumber=s.topicsResultHTML({candidates:[{title:'标题',estimated_value:21,fit_score:.6,references:[]}]},data().config);assert.match(withNumber,/21.0/);assert.match(withNumber,/72h/);
});
test('switching account clears candidates and ignores late previous-account reads',async()=>{
 const x=setup();let finish;x.s.api=()=>new Promise(r=>finish=r);const pending=x.s.renderTopics();x.s.activeAccountId='b';x.s.resetTopics();x.e('operationsContent').innerHTML='账号B';finish(data());await pending;assert.equal(x.e('operationsContent').innerHTML,'账号B');assert.equal(x.eval('topicsState.candidates.length'),0);
});
test('leaving the page ignores late initial read',async()=>{const x=setup();let finish;x.s.api=()=>new Promise(r=>finish=r);const pending=x.s.renderTopics();x.s.currentPage='studio';x.e('operationsContent').innerHTML='创作';finish(data());await pending;assert.equal(x.e('operationsContent').innerHTML,'创作');});
test('evaluation first saves custom profile then uses returned new version',async()=>{
 const x=setup();await x.s.renderTopics();x.eval("topicsState.config.positioning='做饭';topicsState.candidates=[{id:'c',title:' 饭盒 ',body:' 新手 ',image:''}]");const calls=[];
 x.s.api=async(path,method,payload)=>{calls.push({path,method,payload});return path.endsWith('config')?data({version:7}):{status:'insufficient',version:8,candidates:[]};};
 await x.s.topicsAction('evaluate');assert.equal(calls.length,2);assert.equal(calls[0].payload.config.positioning,'做饭');assert.equal(calls[1].payload.version,7);assert.equal(calls[1].payload.candidates[0].title,'饭盒');assert.equal(x.eval('topicsState.busy'),false);assert.equal(x.eval('topicsState.data.version'),8);
});
test('account switch during save prevents evaluation of a different account',async()=>{
 const x=setup();await x.s.renderTopics();x.eval("topicsState.candidates=[{id:'c',title:'标题',body:'内容',image:''}]");let finish;let calls=0;x.s.api=()=>{calls++;return new Promise(r=>finish=r);};const pending=x.s.topicsAction('evaluate');x.s.activeAccountId='b';x.s.resetTopics();finish(data({version:2}));await pending;assert.equal(calls,1);assert.equal(x.eval('topicsState.result'),null);assert.equal(x.eval('topicsState.busy'),false);
});
test('blank titles do not save configuration or spend model work',async()=>{const x=setup();await x.s.renderTopics();let calls=0;x.s.api=async()=>calls++;await x.s.topicsAction('evaluate');assert.equal(calls,0);assert.match(x.e('operationsContent').innerHTML,/需要一个标题/);});
test('conflict preserves drafts and offers quiet refresh instead of repeating work',async()=>{
 const x=setup();await x.s.renderTopics();x.eval("topicsState.candidates=[{id:'c',title:'已有草稿',body:'内容',image:''}]");x.s.api=async()=>{const e=new Error('conflict');e.status=409;e.code='VERSION_CONFLICT';throw e;};await x.s.topicsAction('evaluate');assert.equal(x.eval('topicsState.candidates[0].title'),'已有草稿');assert.match(x.e('operationsContent').innerHTML,/刷新历史/);assert.doesNotMatch(x.e('operationsContent').innerHTML,/class="error/);
});
test('image input rejects unsupported type and oversized file without reading it',async()=>{const {s}=setup();await assert.rejects(()=>s.topicsReadImage({type:'text/html',size:1}),/JPG/);await assert.rejects(()=>s.topicsReadImage({type:'image/png',size:3*1024*1024+1}),/3 MB/);});
test('editing profile or candidate invalidates old result immediately',async()=>{
 const x=setup();await x.s.renderTopics();x.eval("topicsState.result={candidates:[]}");x.e('operationsContent').oninput({target:{dataset:{topicsConfig:'positioning'},value:'植物养护'}});assert.equal(x.eval('topicsState.result'),null);assert.equal(x.e('topicsResults').innerHTML,'');assert.equal(x.eval('topicsState.config.positioning'),'植物养护');
});
test('adopt starts existing creation form with title audience and body rather than publishing',async()=>{const x=setup();await x.s.renderTopics();x.eval("topicsState.result={candidates:[]};topicsState.candidates=[{id:'one',title:'夜景摄影',body:'如何选机位',image:''}]");x.s.topicsAdopt('one');assert.equal(x.e('topic').value,'夜景摄影');assert.equal(x.e('audience').value,'初学者');assert.equal(x.e('material').value,'如何选机位');});

test('crossmodal results describe actual image-text use, without claiming paired covers',()=>{
 const {s}=setup();const html=s.topicsResultHTML({candidates:[{id:'one',title:'选题',image_mode:'crossmodal',fit_score:45,estimated_value:null,references:[{title:'参考',image_mode:'crossmodal',similarity:.4,contribution:.2}]}]},data().config);
 assert.match(html,/图文跨模态匹配/);assert.match(html,/回测帮助值/);assert.doesNotMatch(html,/本次按文字比较|参考权重/);
});
test('uploading historical cover preserves unsaved positioning while advancing version',async()=>{
 const x=setup();await x.s.renderTopics();x.eval("topicsState.config.positioning='自己新写的方向'");mockImageTools(x.s);x.s.api=async()=>data({version:2});await x.s.topicsAction('history','p',{type:'image/png',size:1});assert.equal(x.eval('topicsState.config.positioning'),'自己新写的方向');assert.equal(x.eval('topicsState.data.version'),2);
});
test('model unavailable conflict keeps the model explanation rather than claiming settings changed',async()=>{
 const x=setup();await x.s.renderTopics();x.eval("topicsState.candidates=[{id:'c',title:'已有草稿',body:'内容',image:''}]");
 x.s.api=async()=>{const e=new Error('正在分析另一批图文，请稍后再试。');e.status=409;e.code='TOPIC_MODEL_UNAVAILABLE';throw e;};
 await x.s.topicsAction('evaluate');assert.match(x.eval('topicsState.message'),/正在分析另一批图文/);assert.doesNotMatch(x.eval('topicsState.message'),/设置或历史刚刚发生了变化/);
});

function mockImageTools(s,{width=4000,height=2000,encoded='data:image/jpeg;base64,eA=='}={}){
 const record={closed:false,draws:[],fills:[],formats:[]};
 s.createImageBitmap=async()=>({width,height,close(){record.closed=true;}});
 const canvas={width:0,height:0,getContext:()=>({fillStyle:'',fillRect(...args){record.fills.push(args);},drawImage(...args){record.draws.push(args.slice(1));}}),toDataURL(...args){record.formats.push(args);return typeof encoded==='function'?encoded(args):encoded;}};
 s.document={createElement:kind=>{assert.equal(kind,'canvas');return canvas;}};record.canvas=canvas;return record;
}
test('large cover becomes bounded proportional JPEG analysis input and releases decoded pixels',async()=>{
 const {s}=setup(),record=mockImageTools(s);const file={type:'image/png',size:3*1024*1024,name:'original.png'};const result=await s.topicsReadImage(file);
 assert.match(result,/^data:image\/jpeg;base64,/);assert.equal(record.canvas.width,1024);assert.equal(record.canvas.height,512);assert.deepEqual(record.draws,[[0,0,1024,512]]);assert.equal(record.fills.length,1);assert.deepEqual(record.formats[0],['image/jpeg',.85]);assert.equal(record.closed,true);assert.equal(file.name,'original.png');assert.equal(file.type,'image/png');
});
test('small image is not enlarged and oversized pixel dimensions fail gently',async()=>{
 const {s}=setup();const small=mockImageTools(s,{width:320,height:240});await s.topicsReadImage({type:'image/jpeg',size:100});assert.equal(small.canvas.width,320);assert.equal(small.canvas.height,240);
 const huge=mockImageTools(s,{width:5000,height:4000});await assert.rejects(()=>s.topicsReadImage({type:'image/jpeg',size:100}),/1600 万像素/);assert.equal(huge.closed,true);assert.equal(huge.draws.length,0);
});
test('five transformed images fit total request limit and excess image output is rejected',async()=>{
 const {s}=setup();const record=mockImageTools(s,{encoded:([format,quality])=>'data:image/jpeg;base64,'+'a'.repeat(quality>.7?1100000:900000)});
 const image=await s.topicsReadImage({type:'image/jpeg',size:3000000});assert.equal(record.formats.length,2);
 const payload=JSON.stringify({candidates:Array.from({length:5},()=>({image,title:'图文选题',body:'内容'.repeat(3000)}))});assert.ok(Buffer.byteLength(payload)<8*1024*1024);
 mockImageTools(s,{encoded:'data:image/jpeg;base64,'+'a'.repeat(1100000)});await assert.rejects(()=>s.topicsReadImage({type:'image/jpeg',size:3000000}),/压缩后仍较大/);
});

test('public samples keep public counts separate and reject unsafe source links',()=>{
 const {s}=setup();const html=s.topicsPublicRows([{title:'<script>test</script>',url:'javascript:alert(1)',likes:0,saves:null,comments:3,collected_at:'2026-10-07'},{title:'来源',url:'https://www.xiaohongshu.com/explore/abc',likes:20}]);
 assert.doesNotMatch(html,/javascript:|<script>/);assert.match(html,/点赞 0/);assert.match(html,/收藏 未提供/);assert.match(html,/2026-10-07/);assert.match(html,/rel="noopener noreferrer"/);
});
test('reading public library never starts an external search',async()=>{
 const x=setup(),calls=[];x.s.api=async path=>{calls.push(path);return path.includes('/public?')?{version:3,samples:[],connection:{message:'等待连接'}}:data();};await x.s.renderTopics();
 assert.equal(calls.length,2);assert.match(calls[1],/\/public\?/);assert.equal(x.eval('topicsState.data.version'),3);assert.match(x.e('operationsContent').innerHTML,/等待连接/);
});
test('explicit public search keeps drafts and configuration, invalidates stale report and advances version',async()=>{
 const x=setup();await x.s.renderTopics();x.eval("topicsState.keyword=' 夜景 ';topicsState.config.positioning='新方向';topicsState.candidates[0].title='保留草稿';topicsState.result={candidates:[]}");let sent;
 x.s.api=async(path,method,payload)=>{if(path.endsWith('/config'))return data({version:4,config:payload.config});sent={path,payload};return {version:5,samples:[{title:'参考',url:'https://example.com',likes:2}],connection:{ready:true}};};await x.s.topicsSearchPublic();
 assert.equal(sent.path,'/api/topics/public/search');assert.equal(sent.payload.keyword,'夜景');assert.equal(x.eval('topicsState.data.version'),5);assert.equal(x.eval('topicsState.config.positioning'),'新方向');assert.equal(x.eval('topicsState.candidates[0].title'),'保留草稿');assert.equal(x.eval('topicsState.result'),null);
});
test('account switch rejects a late public search response',async()=>{
 const x=setup();await x.s.renderTopics();x.eval("topicsState.keyword='摄影'");let finish;x.s.api=()=>new Promise(r=>finish=r);const pending=x.s.topicsSearchPublic();x.s.activeAccountId='b';x.s.resetTopics();finish({version:9,samples:[{title:'A账号记录'}]});await pending;assert.equal(x.eval('topicsState.publicData'),null);assert.equal(x.eval('topicsState.busy'),false);
});
test('no keyword makes no external request and connection errors are calm',async()=>{
 const x=setup();await x.s.renderTopics();x.eval("topicsState.config.positioning=''");let called=0;x.s.api=async()=>{called++;throw new Error('搜索服务未连接');};await x.s.topicsSearchPublic();assert.equal(called,0);x.eval("topicsState.keyword='摄影'");await x.s.topicsSearchPublic();assert.equal(called,1);assert.match(x.e('operationsContent').innerHTML,/搜索服务未连接/);assert.doesNotMatch(x.e('operationsContent').innerHTML,/class="error/);
});
test('backend public count snapshots render observed time and preserve unknown values',()=>{const {s}=setup();const html=s.topicsPublicRows([{title:'真实参考',counts:{likes:4,saves:0,comments:null},observed_at:'2026-10-07T12:00:00Z'}]);assert.match(html,/点赞 4/);assert.match(html,/收藏 0/);assert.match(html,/评论 未提供/);assert.match(html,/2026-10-07/);});
test('QR connection is explicit, local image only and successful login clears it',async()=>{const x=setup();await x.s.renderTopics();let calls=[];x.s.api=async(path,method,payload)=>{calls.push({path,payload});return payload.mode==='qrcode'?{data:{img:'data:image/png;base64,'+'a'.repeat(120)}}:{is_logged_in:true};};await x.s.topicsConnect('qrcode');assert.match(x.eval('topicsState.publicQR'),/^data:image\/png/);assert.equal(calls[0].payload.mode,'qrcode');await x.s.topicsConnect('status');assert.equal(x.eval('topicsState.publicQR'),'');assert.match(x.eval('topicsState.message'),/已登录/);});
test('remote or malicious QR images are not embedded',async()=>{const x=setup();await x.s.renderTopics();x.s.api=async()=>({img:'https://attacker.example/track.png'});await x.s.topicsConnect('qrcode');assert.equal(x.eval('topicsState.publicQR'),'');assert.doesNotMatch(x.e('operationsContent').innerHTML,/attacker/);});
test('full render with real public schema includes content boundaries and working action controls',async()=>{const x=setup();x.s.api=async path=>path.includes('/public?')?{version:2,connection:'not_checked',samples:[{id:'p',url:'https://example.com',title:'公开笔记',content_status:'search_summary',counts:{likes:0},observed_at:'2026-10-07'}]}:data();await x.s.renderTopics();const html=x.e('operationsContent').innerHTML;assert.match(html,/尚未读取正文/);assert.match(html,/data-topics-public-refresh="p"/);assert.match(html,/data-topics-public-remove="p"/);assert.match(html,/data-topics="public-import"/);assert.equal(typeof x.e('topicsForm').onsubmit,'function');assert.equal(typeof x.e('operationsContent').onclick,'function');});
test('manual import preserves unknown counts and zero, clears form only after success',async()=>{const x=setup();await x.s.renderTopics();x.eval("topicsState.manual={url:'https://example.com/note',title:' 参考 ',body:'正文',likes:'0',saves:'',comments:'2'}");let payload;x.s.api=async(path,method,p)=>{assert.equal(path,'/api/topics/public/import');payload=p;return {version:4,samples:[]};};await x.s.topicsManagePublic('import');assert.equal(payload.samples[0].counts.likes,0);assert.equal(payload.samples[0].counts.saves,null);assert.equal(payload.samples[0].counts.comments,2);assert.equal(x.eval('topicsState.data.version'),4);assert.equal(x.eval('Object.keys(topicsState.manual).length'),0);});
test('invalid manual counters do not send and failed saves retain user input',async()=>{const x=setup();await x.s.renderTopics();x.eval("topicsState.manual={url:'https://example.com',title:'参考',likes:'-1'}");let n=0;x.s.api=async()=>{n++;throw new Error('暂时无法保存');};await x.s.topicsManagePublic('import');assert.equal(n,0);x.eval("topicsState.manual.likes='3'");await x.s.topicsManagePublic('import');assert.equal(n,1);assert.equal(x.eval('topicsState.manual.title'),'参考');});
test('refresh and remove use current account/version and direct removal needs no confirmation',async()=>{const x=setup();await x.s.renderTopics();const calls=[];x.s.api=async(path,method,payload)=>{calls.push({path,payload});return {version:7,samples:[]};};await x.s.topicsManagePublic('refresh','sample');await x.s.topicsManagePublic('remove','sample');assert.equal(calls[0].path,'/api/topics/public/refresh');assert.equal(calls[1].path,'/api/topics/public/remove');assert.equal(calls[1].payload.version,7);assert.equal(calls[1].payload.account_id,'a');assert.equal(calls[1].payload.sample_id,'sample');});

test('public result discloses unavailable cover analysis and escapes image notes',()=>{const {s}=setup();const html=s.topicsPublicRows([{title:'参考1',image_missing:true,image_note:'尚未编码公开参考封面 <script>'},{title:'参考2',image_missing:true}]);assert.match(html,/尚未编码公开参考封面 &lt;script&gt;/);assert.match(html,/未分析参考封面，本条参考按文字匹配/);assert.doesNotMatch(html,/<script>/);});

test('simple flow keeps search and candidate action prominent while advanced panels stay collapsed',async()=>{
 const x=setup();await x.s.renderTopics();const html=x.e('operationsContent').innerHTML;
 assert.match(html,/aria-label="使用步骤"/);assert.match(html,/01 \/ 找参考/);assert.match(html,/02 \/ 比较选题/);
 assert.match(html,/class="primary" data-topics="public-search"/);
 assert.match(html,/<details class="panel topics-profile" ><summary>当前方向：摄影/);
 assert.match(html,/<details class="panel topics-details"><summary>补充自己的历史作品/);
 assert.doesNotMatch(html,/尚未访问小红书|先补充真实历史/);
 const result=x.s.topicsResultHTML({candidates:[{id:'a',title:'标题'}]},data().config);
 assert.match(result,/03 \/ 选一个开始创作/);assert.match(result,/class="primary" data-topics-adopt/);
});
test('verified login stays visible and supersedes stale connection text',async()=>{
 const x=setup();await x.s.renderTopics();x.eval("topicsState.publicData={connection:'not_checked',samples:[]}");x.s.api=async()=>({is_logged_in:true});await x.s.topicsConnect('status');
 const html=x.e('operationsContent').innerHTML;assert.match(html,/小红书已连接/);assert.doesNotMatch(html,/尚未访问小红书/);assert.match(html,/<div class="topics-connection" role="group"/);assert.doesNotMatch(html,/<details class="topics-connection"/);
});
test('missing profile and logged out connection open only the needed setup',async()=>{
 const x=setup();await x.s.renderTopics();x.eval("topicsState.config.positioning='';topicsState.publicConnected=false");const html=x.s.topicsHTML();
 assert.match(html,/<details class="panel topics-profile" open>/);assert.match(html,/class="primary" data-topics="public-qrcode"/);assert.match(html,/<div class="topics-connection" role="group"/);
});

test('profile search uses saved dynamic positioning and never sends external status implicitly',async()=>{
 const x=setup(),calls=[];await x.s.renderTopics();x.eval("topicsState.config.positioning='摄影 / 夜景';topicsState.keyword=''");
 x.s.api=async(path,method,payload)=>{calls.push({path,payload});return path.endsWith('/config')?data({version:2,config:payload.config}):{version:3,samples:[],positioning:'摄影 / 夜景'};};
 await x.s.topicsSearchPublic();assert.equal(calls.length,2);assert.equal(calls[0].path,'/api/topics/config');assert.equal(calls[1].payload.keyword,'摄影 / 夜景');assert.equal(calls[1].payload.version,2);assert.equal(x.eval('topicsState.config.positioning'),'摄影 / 夜景');
});
test('candidate helper and reference library make provenance and role understandable',async()=>{
 const x=setup();await x.s.renderTopics();x.eval("topicsState.publicData={samples:[],archived_count:2,unclassified_count:1}");const html=x.s.topicsHTML();
 assert.match(html,/准备写的想法，不是已发布作品或平台数据/);assert.match(html,/产品事实仍以资料库中的原文为准/);assert.match(html,/其他定位的 2 条参考已保留，本次不参与比较/);
 const rows=x.s.topicsPublicRows([{title:'手录',source:'manual_public',observed_at:'2026-10-07T12:00:00Z'},{title:'搜索',source:'public_search',observed_at:'2026-10-07T12:00:00Z'}]);assert.match(rows,/手动录入/);assert.match(rows,/小红书公开检索/);assert.match(rows,/2026-10-07/);assert.doesNotMatch(rows,/T12:00:00Z/);
});

test('explicit logged-out status overrides an old successful search connection',async()=>{const x=setup();await x.s.renderTopics();x.eval("topicsState.publicData={samples:[],connection:{ready:true}};topicsState.publicConnected=false");const html=x.s.topicsPublicHTML();assert.match(html,/先连接小红书/);assert.doesNotMatch(html,/小红书已连接/);});
