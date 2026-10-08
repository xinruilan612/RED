'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 class Element{
  constructor(tag){this.tag=tag;this.children=[];this.events={};this.disabled=false;}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  setAttribute(){}remove(){}
  addEventListener(event,fn){this.events[event]=fn;}
  querySelectorAll(tag){return this.children.filter(c=>c.tag===tag);}
  click(){return this.events.click?.();}
 }
 const host=new Element('host'),calls=[],downloads=[];
 const context={document:{createElement:tag=>{const e=new Element(tag);if(tag==='a')e.click=()=>downloads.push(e.download);return e;},body:new Element('body')},
  URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},setTimeout(){},
  fetch:async url=>{calls.push(url);return url.includes('capabilities')?{ok:true,json:async()=>({complete_available:true,images_available:true,video_available:true,storyboard_available:true,video_message:'无声视频'})}:{ok:true,blob:async()=>({})};}};
 vm.createContext(context);vm.runInContext(fs.readFileSync('frontend/media_exports.js','utf8'),context);
 return {host,calls,downloads,context,Element,download:(run,button,status)=>context.downloadCompleteBundle(run,button,status),mount:(run)=>context.mountMediaExports(run,host)};
}
test('confirmed draft gets a full bundle button using the authenticated endpoint',async()=>{
 const s=setup();await s.mount({workflow_type:'creation',run_status:'SUCCEEDED',accepted_ref:'v5',run_id:'run-1'});
 const section=s.host.children[0],buttons=section.children[2];
 assert.equal(buttons.children[0].textContent,'下载全部成品包');
 assert.equal(buttons.children[0].className,'primary media-export-primary');
 assert.equal(buttons.children.length,1);
 await buttons.children[0].click();
 assert.deepEqual(s.calls,['/api/runs/run-1/media/capabilities','/api/runs/run-1/media-export?kind=complete']);
 assert.deepEqual(s.downloads,['youji-complete-run-1.zip']);
 assert.match(section.children[3].textContent,/使用说明.txt/);
});
test('unconfirmed creation does not expose full bundle or fetch',async()=>{
 const s=setup();await s.mount({workflow_type:'creation',run_status:'RUNNING',run_id:'run-1'});
 assert.equal(s.host.children.length,0);assert.equal(s.calls.length,0);
});

test("confirmed export bundle follows manuscript and editor and usage details are collapsed",()=>{const html=fs.readFileSync("frontend/index.html","utf8");assert.ok(html.indexOf('id="humanPanel"')<html.indexOf('id="draftPanel"'));assert.ok(html.indexOf('id="confirmedPanel"')>html.indexOf('id="editor"'));assert.ok(html.indexOf('id="mediaExports"')>html.indexOf('id="confirmedPanel"'));assert.equal((html.match(/id="mediaExports"/g)||[]).length,1);assert.match(html,/<details id="usageDetails" class="usage-details" hidden>/);assert.doesNotMatch(html,/<details id="usageDetails"[^>]*\sopen/);});

test('prominent bundle action refuses unconfirmed drafts without requesting or downloading',async()=>{
 const s=setup(),button=new s.Element('button'),status=new s.Element('p');
 for(const run of [{workflow_type:'creation',run_status:'RUNNING',accepted_ref:'v4',run_id:'r'}, {workflow_type:'creation',run_status:'SUCCEEDED',run_id:'r'}]){
  assert.equal(await s.download(run,button,status),false);
 }
 assert.equal(s.calls.length,0);assert.equal(s.downloads.length,0);assert.match(status.textContent,/先确认/);assert.equal(button.disabled,false);
});
test('prominent bundle action uses authenticated export and surfaces server rejection',async()=>{
 const s=setup(),button=new s.Element('button'),status=new s.Element('p');
 s.context.fetch=async(url,options)=>{s.calls.push(url);assert.equal(options.credentials,'same-origin');assert.equal(button.disabled,true);return {ok:false,json:async()=>({error:{message:'当前稿件尚未确认'}})};};
 assert.equal(await s.download({workflow_type:'creation',run_status:'SUCCEEDED',accepted_ref:'v4',run_id:'run-1'},button,status),false);
 assert.deepEqual(s.calls,['/api/runs/run-1/media-export?kind=complete']);assert.equal(s.downloads.length,0);assert.equal(status.textContent,'当前稿件尚未确认');assert.equal(button.disabled,false);
});
test('prominent bundle action suppresses duplicate clicks and restores button after successful download',async()=>{
 const s=setup(),button=new s.Element('button'),status=new s.Element('p');
 let resolveFetch;
 s.context.fetch=async(url)=>{s.calls.push(url);return new Promise(resolve=>{resolveFetch=resolve;});};
 const run={workflow_type:'creation',run_status:'SUCCEEDED',accepted_ref:'v4',run_id:'run-1'};
 const first=s.download(run,button,status);
 assert.equal(button.disabled,true);assert.equal(await s.download(run,button,status),false);assert.equal(s.calls.length,1);
 resolveFetch({ok:true,blob:async()=>({})});assert.equal(await first,true);
 assert.deepEqual(s.downloads,['youji-complete-run-1.zip']);assert.equal(button.disabled,false);assert.match(status.textContent,/已下载/);
});
