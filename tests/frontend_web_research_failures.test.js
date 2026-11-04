'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function render(web,extra={},hostOverrides={}){
 const elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',hidden:false,insertAdjacentHTML(_where,html){this.innerHTML+=html;}});return elements.get(id);};
 Object.assign(element('webResearchReport'),hostOverrides);
 const sandbox={element,web,extra,...(extra.document?{document:extra.document}:{})};vm.createContext(sandbox);
 const source=fs.readFileSync('frontend/app.js','utf8');
 const implementation=source.slice(source.indexOf('function renderWebResearch(){'),source.indexOf('function renderMaterialUploads(){'));
 vm.runInContext(`const $=element;const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let run={context:{web_research:web,material:extra.material||''},current_stage:'research',...extra};${implementation};renderWebResearch();`,sandbox);
 return element('webResearchReport').innerHTML;
}
const failed=[{url:'https://example.com/blocked',status:'failed',error:'来源站点返回 HTTP 403，未读取正文；请更换链接或手动粘贴'},
 {url:'https://example.com/unrelated',status:'failed',error:'正文的主题或型号不匹配，未作为证据'}];
const source={url:'https://example.com/read',title:'实际读取的产品资料',text:'型号资料正文',fetched_at:'2026-11-04T00:00:00Z'};

test('usable sources fold rejected candidates with a visible accurate count and original details',()=>{
 const html=render({enabled:true,status:'complete',sources:[source],reads:[{status:'read',url:source.url},...failed]});
 assert.match(html,/<details class="research-failures" data-research-key="failures"><summary>另有 2 条候选未采用（访问受限或不匹配）<\/summary>/);
 assert.match(html,/已读取公开来源/);assert.match(html,/型号资料正文/);
 for(const row of failed){assert.ok(html.includes(row.error));assert.ok(html.includes(`href="${row.url}"`));}
 assert.doesNotMatch(html,/<details class="research-failures" open/);
});

test('zero usable sources keep all failure details expanded and retain insufficient status',()=>{
 const html=render({enabled:true,status:'insufficient',sources:[],reads:failed});
 assert.match(html,/<details class="research-failures" data-research-key="failures" open><summary>本次 2 条候选未采用/);
 assert.match(html,/没有足够的相关正文，未调用模型/);
 assert.doesNotMatch(html,/已读取公开来源/);
 for(const row of failed)assert.ok(html.includes(row.error));
});

test('failed records lacking error text remain represented and error text is escaped',()=>{
 const html=render({enabled:true,status:'insufficient',reads:[{status:'failed',url:'https://example.com/one'},{status:'failed',url:'https://example.com/two',error:'<script>bad()</script>'}]});
 assert.match(html,/本次 2 条候选未采用/);assert.match(html,/未取得可用正文/);
 assert.match(html,/&lt;script&gt;bad\(\)&lt;\/script&gt;/);assert.doesNotMatch(html,/<script>/);
});

test('no failures does not manufacture rejected candidates',()=>{
 const html=render({enabled:true,status:'complete',sources:[source],reads:[{status:'read',url:source.url}]});
 assert.doesNotMatch(html,/research-failures|条候选未采用/);
});

test('a pristine linked task can explicitly refresh references without model execution',()=>{
 const html=render({enabled:true,status:'complete',sources:[source],reads:[]},
  {material:'来源：https://example.com/products/',current_stage:'brief'});
 assert.match(html,/重新读取参考链接或调整搜索/);
 assert.match(html,/更新本次调查（不调用模型）/);
 assert.match(html,/优先读取本次参考资料中的公开链接/);
 assert.match(html,/id="retryReferencesOnly" type="checkbox" checked/);
 assert.match(html,/仅重新读取参考链接（不搜索、不调用模型）/);
});

test('paid search retries disclose cost and offer reference-only recovery',()=>{
 const html=render({enabled:true,status:'complete',provider:'baidu',sources:[source]},
  {material:'https://example.com/products/',current_stage:'brief'});
 assert.match(html,/百度服务，可能计费/);
 assert.match(html,/id="retryReferencesOnly"/);
});

test('completed research cannot be replaced after analysis or when no link was supplied',()=>{
 const web={enabled:true,status:'complete',sources:[source],reads:[]};
 for(const extra of [{current_stage:'brief'},
  {current_stage:'brief',material:'https://example.com/products/',node_runs:[{stage:'audience'}]},
  {current_stage:'brief',material:'https://example.com/products/',artifacts:[{stage:'research'}]},
  {current_stage:'brief',material:'https://example.com/products/',in_flight:true}]){
  assert.doesNotMatch(render(web,extra),/id="retryWebResearch"/);
 }
});

test('polling preserves opened evidence and refresh controls',()=>{
 const old=[{dataset:{researchKey:'source:read'},open:true},{dataset:{researchKey:'refresh'},open:true}];
 const fresh=old.map(d=>({dataset:d.dataset,open:false}));let calls=0;
 render({enabled:true,status:'complete',sources:[source]},
  {material:'https://example.com/products/',current_stage:'brief'},
  {querySelectorAll(){return calls++===0?old:fresh;}});
 assert.ok(fresh.every(d=>d.open));
});

test('polling leaves a focused retry form and edited query intact',()=>{
 const input={id:'retryQuery1'};
 const html=render({enabled:true,status:'complete',sources:[source]},
  {material:'https://example.com/products/',current_stage:'brief',document:{activeElement:input}},
  {innerHTML:'existing edited query',querySelector(){return {contains:node=>node===input};}});
 assert.equal(html,'existing edited query');
});

test('skipped blocked-site links explain recovery without claiming success',()=>{
 const html=render({enabled:true,status:'insufficient',sources:[],reads:[{url:'https://example.com/skip',status:'skipped',error:'同站点已拒绝'}]});
 assert.match(html,/保留读取名额查找其他来源/);
 assert.match(html,/403 表示网站拒绝程序访问/);
 assert.match(html,/没有足够的相关正文，未调用模型/);
 assert.doesNotMatch(html,/已读取公开来源/);
});
