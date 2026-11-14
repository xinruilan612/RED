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
test('retired trials page is absent while the content wind tunnel keeps its own entry',()=>{
 assert.doesNotMatch(html,/data-page="trials"|(?:src|href)="\/trials\.(?:js|css)"/);
 assert.match(html,/data-page="windtunnel"/);
 assert.match(html,/(?:src|href)="\/windtunnel\.(?:js|css)"/);
 assert.doesNotMatch(operations,/renderTrials\s*\(/);
 assert.match(operations,/renderWindtunnel\s*\(/);
});
test('all workspace routes stay in the labelled sidebar',()=>{
 const top=html.match(/<header class="topbar">[\s\S]*?<\/header>/)[0];
 assert.doesNotMatch(top,/data-page=/);
 const aside=html.match(/<aside class="sidebar">[\s\S]*?<\/aside>/)[0];
 for(const page of ['library','trends','studio','windtunnel','publish','overview','accounts','metrics','memory','connections','models'])assert.match(aside,new RegExp('data-page="'+page+'"'),page);
 for(const label of ['工作空间','运营与复盘','连接与设置'])assert.match(aside,new RegExp(label));
 assert.match(aside,/<details\b[^>]*id="recentCreations"[^>]*>[\s\S]*?id="history"[\s\S]*?<\/details>/);
});
test('retired hash routes fall back to the creation workbench',()=>{
 for(const page of ['trials']){const s=setup();s.show(page);assert.equal(s.page(),'studio');assert.equal(s.sandbox.location.hash,'studio');assert.equal(s.element('studioView').hidden,false);assert.equal(s.element('operationsView').hidden,true);assert.equal(s.buttons.find(b=>b.dataset.page==='studio').attributes['aria-current'],'page');}
});
test('selecting a secondary destination highlights only the active entry',()=>{
 for(const page of ['accounts','metrics','connections','models']){const s=setup();s.show(page);assert.equal(s.page(),page);assert.equal(s.element('studioView').hidden,true);assert.equal(s.element('operationsView').hidden,false);assert.deepEqual(s.buttons.filter(b=>b.active).map(b=>b.dataset.page),[page]);}
});
test('primary navigation keeps the creation workbench instead of the operations surface',()=>{
 const s=setup();s.show('studio');assert.equal(s.element('studioView').hidden,false);assert.equal(s.element('operationsView').hidden,true);
});
test('top-bar and sidebar routes share one delegated navigation handler',()=>{
 assert.match(operations,/document\.addEventListener\('click',e=>\{const b=e\.target\.closest\('\[data-page\]'\)/);
 assert.doesNotMatch(operations,/querySelector\('\.workspace-nav'\)\.onclick/);
});

test('login boot works after retired navigation is removed',()=>{
 const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,{hidden:true,textContent:''});return nodes.get(id);};
 const sandbox={websiteSession:null,document:{getElementById:get,querySelector(){return null;}}};vm.createContext(sandbox);
 const auth=fs.readFileSync('frontend/auth.js','utf8');vm.runInContext(auth.slice(auth.indexOf('function showWebsiteUser(')),sandbox);
 sandbox.showWebsiteUser({auth_required:false});
 sandbox.showWebsiteUser({auth_required:true,user:{username:'fixture'}});
 assert.equal(get('websiteUser').hidden,false);assert.equal(get('libraryNav').hidden,false);assert.equal(get('websiteUsername').textContent,'fixture');
});
