'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const elements=new Map(),element=id=>{if(!elements.has(id))elements.set(id,{hidden:false,disabled:false,value:'',checked:false,textContent:'',innerHTML:'',selectedOptions:[],addEventListener(){},scrollIntoView(){},insertAdjacentHTML(_where,text){this.innerHTML+=text;}});return elements.get(id);};
 const sandbox={document:{getElementById:element,addEventListener(){},querySelector:element,querySelectorAll(){return [];}},window:{addEventListener(){},confirm(){return true;}},setInterval(){},setTimeout(){},clearTimeout(){},crypto:{randomUUID:()=> 'key'},websiteSession:{auth_required:true}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/app.js','utf8'),sandbox);
 vm.runInContext(`run={run_id:'r1',mode:'simulation',snapshot_id:'s1',status_version:3,workflow_type:'creation',run_status:'WAITING_USER',wait_reason:'missing_material',context:{algorithm_state:{snapshot_id:'s1',planning:{selected_modules:[{id:'m1',title:'比较参数',length:80,covers:['预算问题'],source_ids:['f1']}],weighted_coverage:0.8},gap_ranking:{questions:[{id:'q1',question:'价格是多少？',reason:'决定预算结论'}]},structure:{slots:[{role:'intro',function:'引出问题',needs:['产品资料']}],adaptations:['缺少实测，改为选购建议']}}},allowed_actions:['supplement','skip_questions','cancel'],drafts:[],calls:[],events:[],artifacts:[],node_runs:[],usage:{}};actualRenderHuman=renderHuman;render=()=>{};history=async()=>[];calls=[];api=async(path,method,body)=>{calls.push(body);return run;};`,sandbox);
 return {element,eval:code=>vm.runInContext(code,sandbox)};
}
test('creation options keep questions opt-in and disable them with main switch',()=>{
 const s=setup();s.element('useCreationAlgorithms').checked=true;assert.equal(s.eval('algorithmOptionsRequest().enabled'),true);assert.equal(s.eval('algorithmOptionsRequest().ask_questions'),false);
 s.element('askMaterialQuestions').checked=true;assert.equal(s.eval('algorithmOptionsRequest().ask_questions'),true);
 s.element('useCreationAlgorithms').checked=false;s.element('useCreationAlgorithms').onchange();assert.equal(s.element('askMaterialQuestions').disabled,true);assert.equal(s.eval('algorithmOptionsRequest().ask_questions'),false);
 const html=fs.readFileSync('frontend/index.html','utf8');assert.match(html,/<input id="useCreationAlgorithms"[^>]*checked/);assert.doesNotMatch(html,/<input id="askMaterialQuestions"[^>]*checked/);
});
test('plan distinguishes projected coverage and simulation, with escaped reference data',()=>{
 const s=setup(),html=s.eval('algorithmPlanHTML(run)');assert.match(html,/计划不等于正文已覆盖/);assert.match(html,/模拟运行/);assert.match(html,/80.0%（规划指标）/);assert.match(html,/缺少实测/);
 s.eval("run.context.algorithm_state.planning.selected_modules[0].title='<img src=x onerror=alert(1)>';run.context.algorithm_state.structure.slots[0].function='<script>oops</script>'");const safe=s.eval('algorithmPlanHTML(run)');assert.doesNotMatch(safe,/<img|<script>/);assert.match(safe,/&lt;img/);assert.match(safe,/&lt;script/);
});
test('old tasks and stale snapshots have no active algorithm questions',()=>{
 const s=setup();assert.equal(s.eval('algorithmQuestions(run).length'),1);assert.equal(s.eval('availableMaterialContinuation(run)'),false);
 s.eval("run.context.algorithm_state.snapshot_id='old'");assert.equal(s.eval('algorithmQuestions(run).length'),0);assert.match(s.eval('algorithmPlanHTML(run)'),/旧输入/);assert.equal(s.eval('availableMaterialContinuation(run)'),true);
 s.eval('delete run.context.algorithm_state');assert.equal(s.eval('algorithmPlanHTML(run)'),'');assert.equal(s.eval('algorithmQuestions(run).length'),0);assert.equal(s.eval('availableMaterialContinuation(run)'),true);
});
test('question card appears only at current missing-material pause and escapes questions',()=>{
 const s=setup();s.eval("run.context.algorithm_state.gap_ranking.questions[0].question='<b>价格？</b>';actualRenderHuman()");assert.equal(s.element('supplyForm').hidden,false);assert.equal(s.element('algorithmQuestions').hidden,false);assert.equal(s.element('skipAlgorithmQuestions').hidden,false);assert.match(s.element('algorithmQuestions').innerHTML,/&lt;b&gt;/);assert.equal(s.element('confirmationPending').hidden,true);
 for(const change of ["run.wait_reason='final_confirmation'","run.wait_reason='missing_material';run.run_status='SUCCEEDED'","run.run_status='WAITING_USER';run.workflow_type='windtunnel'"]){s.eval(change+';actualRenderHuman()');assert.equal(s.element('supplyForm').hidden,true);assert.equal(s.element('algorithmQuestions').hidden,true);}
});
test('skip uses existing versioned action without hypothesis permission',async()=>{
 const s=setup();await s.element('skipAlgorithmQuestions').onclick();assert.equal(s.eval('calls.length'),1);assert.equal(s.eval('calls[0].action'),'skip_questions');assert.equal(s.eval('calls[0].version'),3);assert.equal(s.eval('JSON.stringify(calls[0].payload)'),'{}');
});
test('answers use supplement without authorizing invented experience',async()=>{
 const s=setup();s.element('supply').value='预算500元，没有实测';s.element('supplyHypothesis').checked=true;await s.element('supplyForm').onsubmit({preventDefault(){}});assert.equal(s.eval('calls[0].action'),'supplement');assert.equal(s.eval('calls[0].payload.material'),'预算500元，没有实测');assert.equal(s.eval('calls[0].payload.allow_hypothesis'),false);
});

test('unknown coverage stays unknown and context simulation mode retains correct label',()=>{
 const s=setup();s.eval("run.context.algorithm_state.planning.weighted_coverage=null;delete run.mode;run.context.mode='simulation'");const html=s.eval('algorithmPlanHTML(run)');assert.doesNotMatch(html,/0.0%|计划加权覆盖度/);assert.match(html,/模拟运行/);assert.doesNotMatch(html,/正文由选定模型生成/);
});

test('plan translates requirement IDs and structure gaps into readable user language',()=>{
 const s=setup();s.eval("run.context.algorithm_state.planning.requirements=[{id:'r1',question:'预算够不够？'}];run.context.algorithm_state.planning.selected_modules[0].covers=['r1'];run.context.algorithm_state.structure.slots[0].needs=['firsthand_record'];run.context.algorithm_state.structure.adaptations=[{slot_id:'secret-slot',original_role:'experience',missing_fields:['firsthand_record','use_steps','comparison_specs'],action:'replace_with_checklist',reason:'改成购买前检查。'}]");
 const html=s.eval('algorithmPlanHTML(run)'),visible=html.split('<details>')[0];assert.match(visible,/计划回答：预算够不够？/);assert.match(visible,/预计 80 字/);assert.match(visible,/有 1 份资料依据/);assert.match(visible,/缺少亲测记录、使用步骤、对比参数。改成购买前检查。/);assert.doesNotMatch(visible,/r1|f1|secret-slot|replace_with_checklist|firsthand_record|slot_id/);assert.match(html,/secret-slot/);
});

test('disabled modules do not present diagnostic plans as active decisions',()=>{
 const s=setup();s.eval("run.context.algorithm_state.active_modules={coverage:false,structure:false}");const html=s.eval('algorithmPlanHTML(run)'),visible=html.split('<details>')[0];assert.match(visible,/未启用需求覆盖优化/);assert.match(visible,/未启用篇章结构迁移/);assert.doesNotMatch(visible,/比较参数|计划加权覆盖度|引出问题|根据现有资料调整/);assert.match(html,/比较参数/);
 s.eval('delete run.context.algorithm_state.active_modules');const legacy=s.eval('algorithmPlanHTML(run)');assert.match(legacy,/比较参数/);assert.match(legacy,/引出问题/);
});
