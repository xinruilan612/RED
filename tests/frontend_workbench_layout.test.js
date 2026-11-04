'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const html=fs.readFileSync('frontend/index.html','utf8'),css=fs.readFileSync('frontend/style.css','utf8');
test('workspace navigation stays in one labelled sidebar',()=>{
 const top=html.match(/<header class="topbar">[\s\S]*?<\/header>/)[0].replace(/\r\n/g,'\n');
 const aside=html.match(/<aside class="sidebar">[\s\S]*?<\/aside>/)[0].replace(/\r\n/g,'\n');
 assert.doesNotMatch(top,/data-page=/);
 for(const page of ['library','trends','studio','windtunnel','publish','overview','accounts','metrics','memory','connections','models'])assert.match(aside,new RegExp(`data-page="${page}"`),page);
 for(const label of ['工作空间','运营与复盘','连接与设置'])assert.match(aside,new RegExp(label));
});
test('draft and human decisions precede collapsed process and runtime details',()=>{
 assert.ok(html.indexOf('id="humanPanel"')<html.indexOf('id="processDetails"'));
 assert.ok(html.indexOf('id="draftPanel"')<html.indexOf('id="processDetails"'));
 assert.match(html,/<details id="processDetails" class="process-disclosure">/);
 assert.match(html,/<details class="process-disclosure"><summary>运行记录与模型调用/);
 assert.match(html,/<label id="compareVersionsWrap"[^>]*hidden><input id="compareVersions" type="checkbox">/);
 assert.match(html,/<details id="materialFileBox" hidden>/);
 assert.match(html,/<details class="creation-options">/);
});
test('current retrieval, classification, source controls and model integrations remain available once each',()=>{
 const ids=Array.from(html.matchAll(/\bid="([^"]+)"/g),m=>m[1]);assert.equal(ids.length,new Set(ids).size);
 for(const id of ['creationDomains','creationFormat','creationGoal','creationWordCount','creationReport','automaticReferencesOption','useAutomaticReferences','webSearchProvider','webSearchTarget','webQuery1','webQuery2','webResearchReport','useKnowledge','materialDocumentSelect','modelsNav','connectionsNav'])assert.ok(ids.includes(id),id);
 for(const script of ['connections','models','research','knowledge','guidance','windtunnel'])assert.ok(html.includes(`src="/${script}.js"`),script);
 assert.match(html,/src="\/windtunnel\.js"/);
 assert.doesNotMatch(html,/id="(?:checkReaders|readerCheckHelp)"|src="\/trials\.js"|data-page="trials"/);
});
test('new dialogs provide complete hidden cancel and cost-confirmation controls',()=>{
 for(const id of ['pageTools','workbenchGuide','cancelConfirmation','confirmCancel','keepTask','liveBudgetConfirmation','liveBudgetMessage','approveLiveBudget','declineLiveBudget'])assert.ok(html.includes(`id="${id}"`),id);
 for(const id of ['cancelConfirmation','liveBudgetConfirmation'])assert.match(html,new RegExp('<section id="'+id+'"[^>]*role="dialog"[^>]*hidden>'));
 assert.match(css,/\.process-disclosure>summary/);assert.match(css,/\.nav-group>summary/);
 const added=css.split('/* Adopted right-side workbench layout; existing sidebar rules above are unchanged. */')[1];assert.ok(added);assert.doesNotMatch(added,/\.sidebar|\.workspace-nav|\.nav-group|\.history|\.brand/);
});
