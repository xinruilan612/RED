const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(){
 const elements={};const e=id=>elements[id]||(elements[id]={innerHTML:'',value:''});let n=0;
 const s={pageInfo:{},activeAccountId:'a',currentPage:'topics',crypto:{randomUUID:()=>`c${++n}`},$:e,esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),currentAccount:()=>({name:'测试账号'}),setTimeout,noticeSeverity:()=> 'info',api:async()=>data(),toast:()=>{},startCreation:()=>true};
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
 const x=setup();await x.s.renderTopics();x.eval("topicsState.candidates=[{id:'c',title:'已有草稿',body:'内容',image:''}]");x.s.api=async()=>{const e=new Error('conflict');e.status=409;throw e;};await x.s.topicsAction('evaluate');assert.equal(x.eval('topicsState.candidates[0].title'),'已有草稿');assert.match(x.e('operationsContent').innerHTML,/刷新历史/);assert.doesNotMatch(x.e('operationsContent').innerHTML,/class="error/);
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
 const x=setup();await x.s.renderTopics();x.eval("topicsState.config.positioning='自己新写的方向'");x.s.FileReader=class{readAsDataURL(){this.result='data:image/png;base64,eA==';this.onload();}};x.s.api=async()=>data({version:2});await x.s.topicsAction('history','p',{type:'image/png',size:1});assert.equal(x.eval('topicsState.config.positioning'),'自己新写的方向');assert.equal(x.eval('topicsState.data.version'),2);
});
