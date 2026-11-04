'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const source=fs.readFileSync('frontend/windtunnel.js','utf8');

test('patch panel names the real action and says when there is nothing to fix',()=>{
 assert.match(source,/PATCH \/ 没有待改项/);
 assert.match(source,/这一版没有需要改的问题/);
 assert.match(source,/手工保存一个新版本/);
 assert.match(source,/按勾选的问题生成修改提案/);
 assert.match(source,/data-tab="input">去改正文/);
});

test('identical per-condition scenes collapse into one line instead of repeating',()=>{
 assert.match(source,/适用场景：与整体场景相同/);
 const cards=source.slice(source.indexOf('function wtCard('),source.indexOf('function wtReuseView('));
 assert.match(cards,/sameScene\?/);
 assert.match(cards,/`<label for="wtScope\$\{i\}">适用场景<\/label>/);
});
