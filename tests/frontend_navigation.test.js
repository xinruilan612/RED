'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync('frontend/index.html','utf8');
const operations=fs.readFileSync('frontend/operations.js','utf8');
function setup(){
 const elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{hidden:false,open:false,textContent:''});return elements.get(id);};
 const groups={overview:'navOperations',accounts:'navOperations',metrics:'navOperations',memory:'navOperations',connections:'navSettings',models:'navSettings'};
 const buttons=['library','trends','studio','publish',...Object.keys(groups)].map(page=>({dataset:{page},active:false,attributes:{},classList:{toggle(name,value){buttons.find(b=>b.dataset.page===page).active=value;}},setAttribute(name,value){this.attributes[name]=value;},closest(){return groups[page]?element(groups[page]):null;}}));
 const sandbox={$:element,esc:String,location:{hash:''},clearError(){},window:{scrollTo(){}},document:{querySelectorAll(selector){if(selector.includes('details'))return ['navOperations','navSettings','recentCreations'].map(element);return buttons;}}};
 vm.createContext(sandbox);vm.runInContext(operations.slice(0,operations.indexOf('async function initOperations(')),sandbox);
 vm.runInContext("pageInfo.library=['资料','资料','资料'];pageInfo.connections=['连接','连接','连接'];pageInfo.models=['设置','设置','设置'];",sandbox);
 return {element,buttons,sandbox,show:page=>vm.runInContext(`showPage(${JSON.stringify(page)})`,sandbox),page:()=>vm.runInContext('currentPage',sandbox)};
}
test('retired experimentation pages and their assets are absent from main entry',()=>{
 assert.doesNotMatch(html,/data-page="(?:trials|windtunnel)"|(?:src|href)="\/(?:trials|windtunnel)\.(?:js|css)"/);
 assert.doesNotMatch(operations,/renderTrials\s*\(|renderWindtunnel\s*\(/);
});
test('secondary navigation and recent creations are initially collapsed, primary creation path remains visible',()=>{
 for(const id of ['navOperations','navSettings','recentCreations']){const tag=html.match(new RegExp('<details\\b[^>]*\\bid="'+id+'"[^>]*>'));assert.ok(tag,id);assert.doesNotMatch(tag[0],/\bopen(?:\s|=|>)/);}
 for(const page of ['library','trends','studio','publish'])assert.match(html,new RegExp('data-page="'+page+'"'));
 const ops=html.match(/<details\b[^>]*id="navOperations"[^>]*>([\s\S]*?)<\/details>/)[1];
 for(const page of ['overview','accounts','metrics','memory'])assert.match(ops,new RegExp('data-page="'+page+'"'));
 const settings=html.match(/<details\b[^>]*id="navSettings"[^>]*>([\s\S]*?)<\/details>/)[1];
 for(const page of ['connections','models'])assert.match(settings,new RegExp('data-page="'+page+'"'));
 assert.match(html,/<details\b[^>]*id="recentCreations"[^>]*>[\s\S]*?id="history"[\s\S]*?<\/details>/);
});
test('retired hash routes fall back to the creation workbench',()=>{
 for(const page of ['trials','windtunnel']){const s=setup();s.show(page);assert.equal(s.page(),'studio');assert.equal(s.sandbox.location.hash,'studio');assert.equal(s.element('studioView').hidden,false);assert.equal(s.element('operationsView').hidden,true);assert.equal(s.buttons.find(b=>b.dataset.page==='studio').attributes['aria-current'],'page');}
});
test('selecting a secondary destination opens its group and highlights only the active entry',()=>{
 for(const [page,group]of [['accounts','navOperations'],['metrics','navOperations'],['connections','navSettings'],['models','navSettings']]){const s=setup();s.show(page);assert.equal(s.page(),page);assert.equal(s.element(group).open,true);assert.equal(s.element('studioView').hidden,true);assert.deepEqual(s.buttons.filter(b=>b.active).map(b=>b.dataset.page),[page]);}
});
test('primary navigation does not force open collapsed secondary groups',()=>{
 const s=setup();s.show('studio');for(const id of ['navOperations','navSettings','recentCreations'])assert.equal(s.element(id).open,false);
});

test('login boot works after retired navigation is removed',()=>{
 const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,{hidden:true,textContent:''});return nodes.get(id);};
 const sandbox={websiteSession:null,document:{getElementById:get,querySelector(){return null;}}};vm.createContext(sandbox);
 const auth=fs.readFileSync('frontend/auth.js','utf8');vm.runInContext(auth.slice(auth.indexOf('function showWebsiteUser(')),sandbox);
 sandbox.showWebsiteUser({auth_required:false});
 sandbox.showWebsiteUser({auth_required:true,user:{username:'fixture'}});
 assert.equal(get('websiteUser').hidden,false);assert.equal(get('libraryNav').hidden,false);assert.equal(get('websiteUsername').textContent,'fixture');
});
