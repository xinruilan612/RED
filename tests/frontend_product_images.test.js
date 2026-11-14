'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const elements=new Map(),calls=[];
 const get=id=>{if(!elements.has(id))elements.set(id,{value:'',innerHTML:'',hidden:false,checked:false,files:[],options:[],selectedOptions:[],insertAdjacentHTML(){}});return elements.get(id);};
 const sandbox={Map,URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL(){}},crypto:{randomUUID:()=> 'request-key'},activeAccountId:'account',currentPage:'library',libraryLoad:1,$:get,esc:s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),api:async(path,method,data)=>{calls.push({path,method,data});if(path==='/api/models')return {connections:[]};if(path.endsWith('/preview'))return {id:'preview',engine:'local',title:'产品',text:'产品资料',result:{uncertainties:[]}};return {id:'saved',title:'产品'};},readDocumentFile:async()=> 'encoded-image',showPage:p=>{sandbox.currentPage=p;},toast(){}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/product_images.js','utf8'),sandbox);
 const run=s=>vm.runInContext(s,sandbox);
 const mount=()=>run('mountProductImages("account",1)');
 const choose=()=>{get('productImageFile').files=[{name:'p.png',type:'image/png',size:50}];get('productImageFile').onchange();};
 const submit=()=>get('productImageForm').onsubmit({preventDefault(){}});
 return {get,calls,sandbox,run,mount,choose,submit};
}
test('upload only previews until user explicitly confirms reviewed content',async()=>{
 const s=setup();await s.mount();s.choose();await s.submit();
 assert.equal(s.calls.filter(c=>c.path.endsWith('/preview')).length,1);
 await s.get('productImageSave').onclick();assert.equal(s.calls.filter(c=>c.path.endsWith('/confirm')).length,0);
 s.get('productImageTitle').value='已核对产品';s.get('productImageText').value='已核对50mL';s.get('productImageReviewed').checked=true;s.get('productImageReviewed').onchange();
 await s.get('productImageSave').onclick();
 assert.equal(s.calls.at(-1).data.text,'已核对50mL');assert.equal(s.calls.at(-1).data.account_id,'account');
});
test('vision is blocked without a configured connection and without cost acknowledgement',async()=>{
 const s=setup();await s.mount();s.choose();s.get('productImageMode').value='vision';s.get('productImageMode').onchange();await s.submit();
 assert.match(s.get('productImageStatus').textContent,/尚未配置/);assert.equal(s.calls.length,1);
 s.get('productImageConnection').value='vision-id';s.get('productImageConnection').onchange();await s.submit();
 assert.match(s.get('productImageStatus').textContent,/费用/);assert.equal(s.calls.length,1);
 s.get('productImageCost').checked=true;s.choose();assert.equal(s.get('productImageCost').checked,false);
});
test('switching accounts while recognition runs cannot render or fill another account',async()=>{
 const s=setup();await s.mount();s.choose();let resolve;s.sandbox.api=()=>new Promise(r=>resolve=r);const pending=s.submit();await new Promise(setImmediate);
 s.sandbox.activeAccountId='other';resolve({id:'preview',engine:'local',title:'产品',text:'资料',result:{uncertainties:[]}});await pending;
 assert.equal(s.get('productImageReview').innerHTML,'');assert.equal(s.get('material').value,'');
});
test('failed request keeps the idempotency key for a safe retry',async()=>{
 const s=setup();await s.mount();s.choose();const ids=[];s.sandbox.api=async(path,method,data)=>{ids.push(data.request_id);throw new Error('连接中断');};
 await s.submit();await s.submit();assert.deepEqual(ids,['request-key','request-key']);assert.match(s.get('productImageStatus').textContent,/原图保留/);
});
test('oversized images never leave browser and previews escape markup',async()=>{
 const s=setup();await s.mount();s.get('productImageFile').files=[{name:'p.png',type:'image/png',size:3000001}];s.get('productImageFile').onchange();await s.submit();assert.equal(s.calls.length,1);
 s.sandbox.preview={id:'p',engine:'<script>',title:'</textarea>',text:'<script>x</script>',result:{uncertainties:['<img>']}};
 assert.ok(!s.run('productImageReviewMarkup(preview)').includes('<script>'));
});
test('confirmed image material can be brought into a new creation without starting a model call',async()=>{
 const s=setup();await s.mount();s.choose();await s.submit();s.get('productImageTitle').value='测'.repeat(150);s.get('productImageText').value='净含量50mL';s.get('productImageReviewed').checked=true;s.get('productImageReviewed').onchange();
 await s.get('productImageUse').onclick();assert.equal(s.sandbox.currentPage,'studio');assert.equal(s.get('material').value,'净含量50mL');assert.equal(s.get('welcome').hidden,false);
 assert.equal(s.calls.some(c=>c.path==='/api/runs'),false);assert.equal(s.get('topic').value.length,100);
});
test('thumbnail uses allowed local data images and clear removes the pending file',async()=>{
 const s=setup();await s.mount();s.choose();await new Promise(setImmediate);
 assert.equal(s.get('productImageThumbnail').src,'data:image/png;base64,encoded-image');
 s.get('productImageClear').onclick();await s.submit();
 assert.match(s.get('productImageStatus').textContent,/先选择/);assert.equal(s.calls.length,1);
});
