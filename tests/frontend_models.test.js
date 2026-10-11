'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup(){
 const elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{innerHTML:'',elements:{},value:'',disabled:false});return elements.get(id);};
 const calls=[];
 const sandbox={pageInfo:{},URL,currentPage:'connections',activeAccountId:'mine',$:element,
  esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  document:{querySelectorAll:()=>[]},window:{confirm:()=>false},dateText:v=>v,toast(){},error(){},clearError(){},refreshModelStatus:async()=>{},
  api:async(...args)=>{calls.push(args);return {id:'saved',version:4};}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/connections.js','utf8'),sandbox);vm.runInContext(fs.readFileSync('frontend/models.js','utf8'),sandbox);
 return {sandbox,element,calls,eval:code=>vm.runInContext(code,sandbox)};
}
test('model form never echoes credentials returned by a server',()=>{
 const s=setup();const html=s.eval("modelConnectionForm([{id:'vendor',name:'厂商',base_url:'https://example.com',docs:'https://example.com'}],{api_key:'LEAK',label:'<script>'})");
 assert.doesNotMatch(html,/LEAK|<script>/);assert.match(html,/type="password"/);assert.match(html,/https:\/\/example.com/);
});
test('cancelled paid test sends no request',async()=>{
 const s=setup();await s.eval("testModelConnection({id:'id',label:'test',version:2})");assert.equal(s.calls.length,0);
});
test('confirmed paid test binds version and cost acknowledgement',async()=>{
 const s=setup();s.sandbox.window.confirm=()=>true;await s.eval("testModelConnection({id:'a/b',label:'test',version:2})");
 assert.equal(s.calls[0][0],'/api/models/connections/a%2Fb/test');assert.equal(s.calls[0][2].version,2);assert.equal(s.calls[0][2].acknowledge_cost,true);
});
test('saving an existing model omits blank key and retains optimistic version',async()=>{
 const s=setup(),fields={id:'saved',version:'3',provider:'vendor',label:'name',model:'model',base_url:'https://example.com',api_key:'',rate_usd_per_million:'2',run_budget_usd:'1',day_budget_usd:'5'};
 const form=s.element('modelConnectionForm');form.elements=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,{value:v}]));
 s.eval('bindModelForm([])');await form.onsubmit({preventDefault(){}});
 assert.equal(s.calls[0][0],'/api/models/connections');assert.equal(s.calls[0][2].version,3);assert.equal(s.calls[0][2].rate_usd_per_million,2);assert.equal('api_key' in s.calls[0][2],false);
});
test('successful save clears key input',async()=>{
 const s=setup(),fields={id:'',version:'',provider:'vendor',label:'name',model:'model',base_url:'https://example.com',api_key:'PRIVATE',rate_usd_per_million:'2',run_budget_usd:'1',day_budget_usd:'5'};
 const form=s.element('modelConnectionForm');form.elements=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,{value:v}]));s.eval('bindModelForm([])');await form.onsubmit({preventDefault(){}});assert.equal(form.elements.api_key.value,'');
});

test('main form keeps credentials and endpoint visible while budgets stay collapsed',()=>{
 const s=setup();const html=s.eval("modelConnectionForm([{id:'custom',name:'自定义',base_url:''}])");
 const [main,advanced]=html.split('<details>');
 for(const name of ['provider','model','api_key','base_url'])assert.match(main,new RegExp('name="'+name+'"'));
 assert.doesNotMatch(main,/name="rate_usd_per_million"|name="run_budget_usd"/);
 assert.match(advanced,/name="run_budget_usd"[^>]*value="1"/);
 assert.match(advanced,/name="protocol"/);assert.match(advanced,/name="json_mode"/);
 assert.doesNotMatch(html,/<details open/);assert.match(html,/保存和切换模型均不发起模型调用/);
});
test('switching provider clears key and model and resets advanced protocol',()=>{
 const s=setup(),form=s.element('modelConnectionForm');
 form.elements=Object.fromEntries(Object.entries({provider:'qwen',base_url:'old',model:'old-model',api_key:'PRIVATE',protocol:'responses'}).map(([k,v])=>[k,{value:v}]));form.elements.json_mode={checked:true};
 s.eval("bindModelForm([{id:'qwen',base_url:'https://dashscope.aliyuncs.com/compatible-mode/v1',docs:'https://example.com'}])");form.elements.provider.onchange();
 assert.equal(form.elements.api_key.value,'');assert.equal(form.elements.api_key.required,true);assert.equal(form.elements.model.value,'');assert.equal(form.elements.protocol.value,'');assert.equal(form.elements.json_mode.checked,false);
});
test('save sends only selected protocol and opted-in JSON mode without probing',async()=>{
 const s=setup(),fields={id:'',version:'',provider:'custom',label:'',model:'gateway-model',base_url:'https://example.com/v1/responses',api_key:' KEY ',rate_usd_per_million:'',run_budget_usd:'',day_budget_usd:'',protocol:'responses'};
 const form=s.element('modelConnectionForm');form.elements=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,{value:v}]));form.elements.json_mode={checked:false};s.eval('bindModelForm([])');await form.onsubmit({preventDefault(){}});
 assert.equal(s.calls.length,2);assert.equal(s.calls[1][0],'/api/models/default');assert.equal(s.calls[1][2].connection_id,'saved');assert.equal(s.calls[0][0],'/api/models/connections');assert.equal(s.calls[0][2].api_key,'KEY');assert.equal(s.calls[0][2].protocol,'responses');assert.equal(s.calls[0][2].json_mode,false);assert.equal('run_budget_usd' in s.calls[0][2],false);
});

 test('model candidates are editable and escape remote catalog values',()=>{
 const s=setup();
 const html=s.eval("modelConnectionForm([{id:'qwen',name:'Qwen',models:['qwen-plus','<unsafe>']}])");
 assert.match(html,/list="modelSuggestions"/);assert.match(html,/<option value="qwen-plus">/);
 assert.ok(!html.includes('<unsafe>'));assert.match(html,/自由填写其他模型 ID/);
 });

test('top selector includes every provider before any connection is saved',async()=>{
 const s=setup();s.sandbox.currentPage='models';
 const catalog=[{id:'qwen',name:'通义千问',models:['qwen-plus'],base_url:'https://example.com/v1'},{id:'anthropic',name:'Claude',models:['claude-example']}];
 s.sandbox.api=async path=>path==='/api/models'?{catalog,connections:[],default_connection_id:null}:{baidu:{version:1}};
 await s.eval('renderModelSettings()');
 const html=s.element('operationsContent').innerHTML;
 assert.match(html,/value="platform"/);assert.match(html,/value="preset:qwen"/);assert.match(html,/value="preset:anthropic"/);
 assert.ok(html.indexOf('id="defaultModelConnection"')<html.indexOf('id="modelConnectionEditor"'));
 s.element('modelConnectionForm').elements={provider:{value:'qwen'}};
 const calls=[];s.sandbox.api=async(...args)=>{calls.push(args);return {};};
 await s.element('defaultModelConnection').onchange({target:{value:'preset:qwen'}});
 assert.equal(calls.length,0);
 const editor=s.element('modelConnectionEditor').innerHTML;
 assert.match(editor,/value="qwen-plus"/);assert.match(editor,/name="api_key"/);assert.match(editor,/value="https:\/\/example.com\/v1"/);assert.match(editor,/保存并用于新任务/);
});

test('saved connection and platform selections update routing without a model call',async()=>{
 for(const [choice,expected] of [['connection:saved','saved'],['platform',null]]){
  const s=setup();s.sandbox.currentPage='models';
  s.sandbox.api=async path=>path==='/api/models'?{catalog:[],connections:[],default_connection_id:null}:{baidu:{version:1}};
  await s.eval('renderModelSettings()');s.sandbox.currentPage='connections';
  s.sandbox.api=async(...args)=>{s.calls.push(args);return {};};
  await s.element('defaultModelConnection').onchange({target:{value:choice}});
  assert.equal(s.calls.length,1);assert.equal(s.calls[0][0],'/api/models/default');assert.equal(s.calls[0][2].connection_id,expected);
 }
});

test('activation failure retains saved identity for retry and never reports success',async()=>{
 const s=setup(),fields={id:'',version:'',provider:'qwen',label:'name',model:'qwen-plus',base_url:'https://example.com',api_key:'PRIVATE'};
 const form=s.element('modelConnectionForm');form.elements=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,{value:v}]));
 const errors=[],toasts=[];s.sandbox.error=e=>errors.push(e.message);s.sandbox.toast=message=>toasts.push(message);
 s.sandbox.api=async(path,method,payload)=>{s.calls.push([path,method,payload]);if(path==='/api/models/default')throw new Error('暂时不可用');return {id:'new-id',version:1};};
 s.eval('bindModelForm([])');await form.onsubmit({preventDefault(){}});
 assert.equal(form.elements.id.value,'new-id');assert.equal(form.elements.version.value,'1');assert.equal(form.elements.api_key.value,'');assert.equal(form.elements.api_key.required,false);
 assert.equal(toasts.length,0);assert.match(errors[0],/连接已保存，但切换失败/);
 await form.onsubmit({preventDefault(){}});assert.equal(s.calls[2][2].id,'new-id');assert.equal(s.calls[2][2].version,1);assert.equal('api_key' in s.calls[2][2],false);
});

test('revoked default stays unavailable until an explicit user selection',async()=>{
 const s=setup();s.sandbox.currentPage='models';
 s.sandbox.api=async path=>path==='/api/models'?{catalog:[],connections:[],default_connection_id:'revoked',ready:false,platform:{ready:true}}:{baidu:{version:1}};
 await s.eval('renderModelSettings()');const html=s.element('operationsContent').innerHTML;
 assert.match(html,/原默认连接已撤销或不可用/);assert.doesNotMatch(html,/当前用于新任务：平台 DeepSeek/);
 assert.match(html,/value="connection:revoked" selected disabled/);
 assert.match(s.element('modelConnectionEditor').innerHTML,/未自动切换或消耗平台额度/);
});
test('failed probe refreshes actual status without losing unsaved configuration or retrying',async()=>{
 const s=setup(),errors=[];s.sandbox.currentPage='models';s.sandbox.window.confirm=()=>true;
 s.element('modelConnectionEditor').innerHTML='保留未提交编辑';let refreshes=0;
 s.sandbox.refreshModelStatus=async()=>{refreshes++;};s.sandbox.error=e=>errors.push(e.message);
 s.sandbox.api=async(path,...args)=>{s.calls.push([path,...args]);if(path.endsWith('/test'))throw new Error('密钥无效，请编辑连接');return {connections:[{id:'id',version:2,test_status:'failed',last_tested:'刚刚'}]};};
 await s.eval("testModelConnection({id:'id',label:'test',version:2})");
 assert.equal(refreshes,1);assert.match(s.element('modelTestStatus-id').textContent,/上次测试失败/);
 assert.equal(s.element('modelConnectionEditor').innerHTML,'保留未提交编辑');assert.match(errors[0],/密钥无效/);
 assert.equal(s.calls.filter(c=>c[0].endsWith('/test')).length,1);
});
test('settings read failure offers an in-page non-billing retry',async()=>{
 const s=setup(),globalErrors=[];s.sandbox.error=e=>globalErrors.push(e);s.sandbox.currentPage='models';s.sandbox.api=async()=>{throw new Error('网络暂时不可用');};
 await s.eval('renderModelSettings()');assert.match(s.element('operationsContent').innerHTML,/重新读取配置（不调用模型）/);assert.match(s.element('operationsContent').innerHTML,/网络暂时不可用/);
 s.sandbox.api=async path=>{s.calls.push([path]);return path==='/api/models'?{connections:[],catalog:[],platform:{ready:false}}:{baidu:{version:1}};};
 await s.element('retryModelSettings').onclick();assert.match(s.element('operationsContent').innerHTML,/平台 DeepSeek 尚未配置/);
 assert.doesNotMatch(s.element('operationsContent').innerHTML,/网络暂时不可用|配置读取失败/);assert.equal(globalErrors.length,0);
 assert.ok(s.calls.every(c=>!c[0].includes('/test')));
});
