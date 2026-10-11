'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const elements=new Map(),calls=[],errors=[];
 const get=id=>{if(!elements.has(id))elements.set(id,{id,value:'',innerHTML:'',hidden:false,files:[],disabled:false,readOnly:false,events:{},focus(){},addEventListener(k,f){this.events[k]=f;},insertAdjacentHTML(){},querySelector(){return get('parseButton');}});return elements.get(id);};
 get('documentTitle').value='产品资料';get('documentText').value='原价 129.50 元';get('documentMaterialType').value='fact';
 const preview={source_sha256:'hash',warnings:['请核对'],pages:[{page:1,text:'原价 129.50 元',original_text:'原价 129.50 元'}]};
 const sandbox={pageInfo:{},activeAccountId:'account',currentPage:'library',crypto:{randomUUID:()=> '00000000-0000-4000-8000-000000000001'},$ :get,esc:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),toast(){},error:e=>errors.push(e.message),api:async(path,method,data)=>{calls.push({path,method,data});return path.endsWith('/preview')?structuredClone(preview):{id:'saved'};}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/knowledge.js','utf8'),sandbox);
 const run=source=>vm.runInContext(source,sandbox);
 run('renderLibrary=async()=>{};bindDocumentInput("account",0,[])');
 const parse=()=>get('documentForm').onsubmit({preventDefault(){},submitter:get('parseButton')});
 return {get,calls,errors,sandbox,run,parse,preview};
}
test('parsing only previews; explicit confirmation sends edited pages and original text',async()=>{
 const s=setup();await s.parse();assert.deepEqual(s.calls.map(c=>c.path),['/api/knowledge/preview']);
 s.get('reviewedDocument-0').value='校对 119.50 元';s.get('reviewedDocument-0').oninput();
 await s.get('confirmDocumentInput').onclick();const payload=s.calls[1].data;
 assert.equal(payload.text,'原价 129.50 元');assert.equal(payload.input_review.pages[0].text,'校对 119.50 元');assert.equal(payload.input_review.confirmed,true);
});
test('back or cancel does not save and preserves original input',async()=>{
 const s=setup();await s.parse();s.get('backDocumentInput').onclick();
 assert.equal(s.calls.length,1);assert.equal(s.get('documentText').value,'原价 129.50 元');assert.equal(s.get('documentInputPreview').hidden,true);
});
test('parse failure offers file or paste recovery without clearing input',async()=>{
 const s=setup();s.sandbox.api=async()=>{throw new Error('文件无法解析');};await s.parse();
 assert.equal(s.get('documentText').value,'原价 129.50 元');assert.match(s.get('documentInputStatus').textContent,/换文件.*粘贴/);assert.equal(s.get('parseButton').disabled,false);
});
test('uncertain confirmation retries the identical payload and locks reviewed text',async()=>{
 const s=setup();await s.parse();s.sandbox.api=async(path,method,data)=>{s.calls.push({path,data});throw new Error('网络超时');};
 await s.get('confirmDocumentInput').onclick();await s.get('confirmDocumentInput').onclick();
 assert.equal(s.calls[1].data,s.calls[2].data);assert.equal(s.get('reviewedDocument-0').readOnly,true);assert.match(s.get('documentReviewStatus').textContent,/不重复入库/);
});
test('old confirmation explicitly distinguishes saved version from a later edit',async()=>{
 const s=setup(),notices=[];await s.parse();s.sandbox.toast=notice=>notices.push(notice);
 s.sandbox.api=async()=>({id:'saved',version:2,input_confirmation:{confirmed_version:1,current_version:2,replayed:true}});
 await s.get('confirmDocumentInput').onclick();
 assert.equal(notices.length,1);assert.match(notices[0],/先前校对版本 v1.*当前资料已更新至 v2.*未覆盖/);
});
test('late preview cannot render in another account and cached input stays account scoped',async()=>{
 const s=setup();let resolve;s.sandbox.api=()=>new Promise(r=>resolve=r);const pending=s.parse();await Promise.resolve();
 s.sandbox.activeAccountId='other';resolve(s.preview);await pending;assert.equal(s.get('documentInputPreview').innerHTML,'');
 s.get('documentText').value='other';s.run('bindDocumentInput("other",0,[])');assert.equal(s.get('documentText').value,'other');
 s.sandbox.activeAccountId='account';s.run('bindDocumentInput("account",0,[])');assert.equal(s.get('documentText').value,'原价 129.50 元');
});
test('editing source while parsing discards the outdated response',async()=>{
 const s=setup();let resolve;s.sandbox.api=()=>new Promise(r=>resolve=r);const pending=s.parse();await Promise.resolve();
 s.get('documentText').value='新输入';s.get('documentForm').events.input();resolve(s.preview);await pending;
 assert.equal(s.get('documentInputPreview').innerHTML,'');assert.equal(s.get('documentText').value,'新输入');
});
test('preview escapes markup rather than executing document instructions',()=>{
 const s=setup();s.sandbox.packet={warnings:['<script>'],pages:[{page:1,text:'</textarea><script>x</script>',original_text:'<img onerror=x>'}]};
 const html=s.run('documentPreviewMarkup(packet)');assert.ok(!html.includes('<script>'));assert.match(html,/&lt;\/textarea&gt;/);
});
