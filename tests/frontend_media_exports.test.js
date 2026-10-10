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
 return {host,calls,downloads,context,Element,download:(run,button,status)=>context.downloadCompleteBundle(run,button,status),mount:(run)=>context.mountArchivedStudio(run,host)};
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

test('public Studio mounts only the poster workspace without legacy canvas or chat requests',async()=>{const s=setup();let mounted;s.context.mountPosterStudio=async(run,host)=>{mounted={run,host};host.replaceChildren(new s.Element('poster'));};const run={workflow_type:'creation',run_status:'SUCCEEDED',accepted_ref:'v1',run_id:'r'};await s.context.mountMediaExports(run,s.host);assert.equal(mounted.run,run);assert.equal(mounted.host,s.host);assert.equal(s.host.children.length,1);assert.equal(s.host.children[0].tag,'poster');assert.equal(s.calls.length,0);});
test('public Studio clears previous content and rejects unconfirmed manuscripts',async()=>{const s=setup();s.host._posterKey='previous';s.host.append(new s.Element('old'));s.context.mountPosterStudio=()=>assert.fail('must not mount');await s.context.mountMediaExports({workflow_type:'creation',run_status:'RUNNING'},s.host);assert.equal(s.host.children.length,0);assert.equal(s.host._posterKey,null);});
test('missing poster script does not restore the deleted old editor',async()=>{const s=setup();await s.context.mountMediaExports({workflow_type:'creation',run_status:'SUCCEEDED',accepted_ref:'v1'},s.host);assert.equal(s.calls.length,0);assert.match(s.host.children[0].textContent,/刷新/);});

test('full text export mounts beside poster without restoring old canvas or calling AI',async()=>{const s=setup();s.context.mountPosterStudio=async(run,host)=>{if(host._posterKey===s.context.mediaKey(run))return;host._posterKey=s.context.mediaKey(run);host.replaceChildren(new s.Element('poster'));};const run={workflow_type:'creation',run_status:'SUCCEEDED',accepted_ref:'v1',run_id:'r',drafts:[{ref:'v1',content_hash:'hash'}]};await s.context.mountMediaExports(run,s.host);assert.equal(s.host.children.length,2);assert.equal(s.host.children[0].tag,'poster');assert.equal(s.host.children[1].children[0].textContent,'全文分张导出');assert.equal(s.calls.length,0);await s.context.mountMediaExports(run,s.host);assert.equal(s.host.children.length,2);});
test('full text export binds preview and download to complete accepted draft and classic pagination',async()=>{const s=setup(),run={workflow_type:'creation',run_status:'SUCCEEDED',accepted_ref:'v1',run_id:'r',drafts:[{ref:'v1',content_hash:'hash'}]},button=new s.Element('button'),status=new s.Element('p');const key=s.context.mediaKey(run);s.host._fullTextKey=key;let count=0;s.context.fetch=async(url,opts)=>{s.calls.push(url);const body=JSON.parse(opts.body);assert.equal(body.template,'classic');assert.equal(body.draft_ref,'v1');assert.equal(body.content_hash,'hash');assert.equal(opts.credentials,'same-origin');if(count++===0)return {ok:true,json:async()=>({draft_ref:'v1',content_hash:'hash',design_hash:'design',pages:[{}, {}, {}]})};assert.equal(body.design_hash,'design');assert.equal(body.kind,'images');return {ok:true,blob:async()=>({})};};assert.equal(await s.context.downloadFullTextBundle(run,s.host,key,'images',button,status),true);assert.equal(s.calls.length,2);assert.match(status.textContent,/全文 3 张/);assert.equal(s.downloads[0],'youji-fulltext-images-r.zip');});
test('full text rejects mismatched preview before requesting download',async()=>{const s=setup(),run={workflow_type:'creation',run_status:'SUCCEEDED',accepted_ref:'v1',run_id:'r',drafts:[{ref:'v1',content_hash:'hash'}]},button=new s.Element('button'),status=new s.Element('p'),key=s.context.mediaKey(run);s.host._fullTextKey=key;s.context.fetch=async()=>{s.calls.push('preview');return {ok:true,json:async()=>({draft_ref:'v2',content_hash:'hash',design_hash:'design',pages:[{}]})};};assert.equal(await s.context.downloadFullTextBundle(run,s.host,key,'images',button,status),false);assert.equal(s.calls.length,1);assert.equal(s.downloads.length,0);assert.equal(button.disabled,false);assert.match(status.textContent,/版本已变化/);});
test('full text ignores a preview completed after switching manuscript',async()=>{const s=setup(),run={workflow_type:'creation',run_status:'SUCCEEDED',accepted_ref:'v1',run_id:'r',drafts:[{ref:'v1',content_hash:'hash'}]},button=new s.Element('button'),status=new s.Element('p'),key=s.context.mediaKey(run);s.host._fullTextKey=key;s.context.fetch=async()=>{s.calls.push('preview');s.host._fullTextKey='new';return {ok:true,json:async()=>({draft_ref:'v1',content_hash:'hash',design_hash:'design',pages:[{}]})};};assert.equal(await s.context.downloadFullTextBundle(run,s.host,key,'images',button,status),false);assert.equal(s.calls.length,1);assert.equal(s.downloads.length,0);});
