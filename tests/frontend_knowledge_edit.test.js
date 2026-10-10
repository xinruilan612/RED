'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
test('generic document update choices exclude research cases without hiding normal documents',()=>{
 const sandbox={pageInfo:{}};vm.createContext(sandbox);vm.runInContext(fs.readFileSync('frontend/knowledge.js','utf8'),sandbox);
 sandbox.docs=[{id:'case',source_type:'research_case'},{id:'web',source_type:'web'},{id:'text',source_type:'text'},{id:'file',source_type:'upload'}];
 assert.deepEqual(Array.from(vm.runInContext('editableKnowledgeDocuments(docs).map(d=>d.id)',sandbox)),['web','text','file']);
 assert.equal(sandbox.docs.length,4);
});
