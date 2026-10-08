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
 return {host,calls,downloads,mount:(run)=>context.mountMediaExports(run,host)};
}
test('confirmed draft gets a full bundle button using the authenticated endpoint',async()=>{
 const s=setup();await s.mount({workflow_type:'creation',run_status:'SUCCEEDED',accepted_ref:'v5',run_id:'run-1'});
 const section=s.host.children[0],buttons=section.children[2];
 assert.equal(buttons.children[0].textContent,'下载全部成品包');
 assert.equal(buttons.children[0].className,'primary media-export-primary');
 assert.equal(buttons.children[1].className,'secondary');
 await buttons.children[0].click();
 assert.deepEqual(s.calls,['/api/runs/run-1/media/capabilities','/api/runs/run-1/media-export?kind=complete']);
 assert.deepEqual(s.downloads,['youji-complete-run-1.zip']);
 assert.match(section.children[3].textContent,/使用说明.txt/);
});
test('unconfirmed creation does not expose full bundle or fetch',async()=>{
 const s=setup();await s.mount({workflow_type:'creation',run_status:'RUNNING',run_id:'run-1'});
 assert.equal(s.host.children.length,0);assert.equal(s.calls.length,0);
});

test("export bundle sits beside confirmation and usage details are collapsed",()=>{const html=fs.readFileSync("frontend/index.html","utf8");assert.ok(html.indexOf('id="mediaExports"')<html.indexOf('id="draftPanel"'));assert.match(html,/<details id="usageDetails" class="usage-details" hidden>/);assert.doesNotMatch(html,/<details id="usageDetails"[^>]*\sopen/);});
