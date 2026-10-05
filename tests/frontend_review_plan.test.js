const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const source=fs.readFileSync('frontend/account.js','utf8');
 const a={id:'review',metric_id:'m',publication_id:'p',status:'insufficient',window_quality:'late',comparisons:{},ai_review:{summary:'证明复用价值',change:'再加步骤和提问',execution:{model:'old',model_calls:1},snapshot_hash:'abc',limitation:'旧记录'},flags:[],metric_refs:[]};
 const s={ops:{metrics:[{id:'m',observed_at:'2026-10-04T21:00:00Z',window:'72h',values:{views:19,saves:5,likes:2,comments:0}}],publications:[{id:'p',published_at:'2026-10-01T00:00:00Z',content:{selected_title:'入门教程',body:'① 操作一\n② 操作二\n参考公开资料。你怎么做？'}}]},esc:x=>String(x??''),badge:x=>x,dateText:x=>x,provider:{ready:true}};
 vm.createContext(s);vm.runInContext(source.slice(source.indexOf('function plainReview(a)'),source.indexOf('function renderMetrics(')),s);return {s,a};
}
test('review uses actual observation time and does not invent missing exposure/followers',()=>{const {s,a}=setup(),r=s.plainReview(a);assert.match(r.timing,/93.0 小时/);assert.match(r.missing.join(''),/没有曝光/);assert.match(r.missing.join(''),/未记录.*关注/);assert.equal(r.counts.length,4);assert.match(r.keep,/已有的编号步骤/);assert.match(r.keep,/现有结尾提问/);assert.match(r.change,/具体日常场景/);});
test('legacy AI claim remains auditable but main advice is explicitly rules based',()=>{const {s,a}=setup(),html=s.analysisHTML(a);assert.match(html,/免费规则建议/);assert.match(html,/此前 AI 建议/);assert.doesNotMatch(s.reviewAdvice(a).summary,/证明复用价值/);assert.match(html,/现在还不能判断什么/);});
test('next creation carries source, one change and measurement plan',()=>{const {s,a}=setup(),r=s.nextReviewBrief(a);assert.ok(r.topic.length<=100);for(const term of ['复盘记录：review','保留什么','只改一点','之后记录','24 小时','72 小时','不是产品事实或医学证据'])assert.ok(r.material.includes(term),term);});
test('versioned new AI advice is used without replacing its output',()=>{const {s,a}=setup();a.ai_review={review_version:2,summary:'谨慎建议',keep:'保留',change:'一项',next_topic:'新主题',check_next:'记录'};assert.equal(s.reviewAdvice(a),a.ai_review);assert.equal(s.nextReviewBrief(a).topic,'新主题');});
