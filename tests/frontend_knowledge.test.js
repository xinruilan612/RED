'use strict';
// Small DOM/API test doubles exercise actual handlers and response ordering.
// They are not a browser E2E or a production-network verification.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve=yes; reject=no;});
  return {promise, resolve, reject};
}
const docs = ['a','b'].map(id => ({id,title:'文档 '+id,version:2,source_type:'text',updated_at:1}));
const pack = {id:'starter',title:'原创指南',version:1,count:3,available:true,note:'项目指南',fingerprint:'pack-hash',
  documents:[{title:'来源指南',text:'<script>bad()</script>',author:'项目自编',license:'仅项目使用',
    published_at:'2026-09-22',fingerprint:'text-hash'}]};
function documentVersion(id, version=2) {
  return {id,title:'文档 '+id+' 版本 '+version,version,current_version:2,read_only:version!==2,
    filename:'材料.txt',fingerprint:'hash-'+version,source_url:'https://example.com/v'+version,
    source_recorded:true,stored_at:1,metadata:{title:'文档 '+id,published_at:'2026-01-0'+version},
    versions:[2,1].map(v=>({version:v,metadata:{title:'文档 '+id}})),
    chunks:[{page:version,offset:0,text:'原文 '+id+' v'+version}]};
}

function fixture() {
  const elements = new Map(), errors=[], toasts=[], calls=[], groups = new Map();
  const makeElement = id => {
    const node={value:'',disabled:false,files:[],dataset:{},_html:'',_text:''};
    Object.defineProperties(node, {
      innerHTML:{get:()=>node._html,set:html=>{
        node._html=html; node._text='';
        for (const match of html.matchAll(/\bid="([^"]+)"/g)) elements.set(match[1],makeElement(match[1]));
        for (const attribute of ['document','delete-document','preview-pack','read-source']) {
          const found=[...html.matchAll(new RegExp('data-'+attribute+'="([^"]+)"','g'))];
          if (id==='operationsContent'||found.length) {
            const field=attribute.replace(/-([a-z])/g,(_m,c)=>c.toUpperCase());
            groups.set('[data-'+attribute+']',found.map(match=>({disabled:false,dataset:{[field]:match[1]}})));
          }
        }
      }},
      textContent:{get:()=>node._text,set:text=>{node._text=text;node._html='';}}
    });
    node.insertAdjacentHTML=(_where,html)=>{node.innerHTML=html+node.innerHTML;};
    return node;
  };
  const element = id => {if(!elements.has(id))elements.set(id,makeElement(id));return elements.get(id);};
  let handler=()=>undefined;
  const context = vm.createContext({
    URL, pageInfo:{},activeAccountId:'owner-a',currentPage:'library',
    websiteSession:{auth_required:true},ops:{accounts:[]},
    $:element,document:{querySelectorAll:selector=>groups.get(selector)||[]},
    currentAccount:()=>({name:context.activeAccountId}),
    esc:value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
    badge:()=>'',window:{confirm:()=>true},error:e=>errors.push(e),toast:text=>toasts.push(text),
    api:(url,method='GET',data)=>{
      calls.push({url,method,data});
      const result=handler(url,method,data);
      if(result!==undefined)return Promise.resolve(result);
      if(url.startsWith('/api/knowledge?'))return Promise.resolve(docs);
      if(url.startsWith('/api/knowledge/packs?'))return Promise.resolve([pack]);
      if(url.startsWith('/api/knowledge/packs/starter?'))return Promise.resolve(pack);
      const match=url.match(/^\/api\/knowledge\/([ab])\?/);
      if(match)return Promise.resolve(documentVersion(match[1]));
      throw new Error('Unexpected request '+url);
    }
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/knowledge.js'),'utf8'),context);
  return {context,element,calls,errors,toasts,groups,setHandler:fn=>{handler=fn;}};
}

test('preview is opt-in, read-only and escapes original text and metadata',async()=>{
  const f=fixture();await f.context.renderLibrary();
  assert.equal(f.calls.length,2);
  assert.ok(!f.calls.some(c=>c.method==='POST'));
  await f.groups.get('[data-preview-pack]')[0].onclick();
  const html=f.element('packPreview').innerHTML;
  assert.ok(html.includes('&lt;script&gt;bad()&lt;/script&gt;'));
  assert.ok(html.includes('pack-hash')&&html.includes('text-hash')&&html.includes('仅项目使用'));
  assert.ok(!html.includes('<script>'));
  assert.ok(!f.calls.some(c=>c.method==='POST'));
});

test('double import submits once and reports created/skipped/conflict accurately',async()=>{
  const f=fixture(),pending=deferred();
  f.setHandler((url,method)=>method==='POST'?pending.promise:undefined);
  await f.context.renderLibrary();await f.groups.get('[data-preview-pack]')[0].onclick();
  const button=f.element('importKnowledgePack');
  const first=button.onclick({currentTarget:button});
  await button.onclick({currentTarget:button});
  assert.equal(f.calls.filter(c=>c.method==='POST').length,1);
  const sent=f.calls.find(c=>c.method==='POST');
  assert.equal(sent.data.account_id,'owner-a');
  assert.equal(sent.data.version,1);assert.equal(sent.data.fingerprint,'pack-hash');
  pending.resolve({created:1,skipped:1,conflict:1,documents:[{title:'有冲突',reason:'未覆盖用户修改'}]});
  await first;
  const receipt=f.element('packImportResult').innerHTML;
  assert.ok(receipt.includes('新增 1')&&receipt.includes('跳过 1')&&receipt.includes('未改动 1'));
  assert.ok(receipt.includes('未覆盖用户修改'));
});

test('late import response cannot refresh or toast into another account',async()=>{
  const f=fixture(),pending=deferred();
  f.setHandler((_url,method)=>method==='POST'?pending.promise:undefined);
  await f.context.renderLibrary();await f.groups.get('[data-preview-pack]')[0].onclick();
  const button=f.element('importKnowledgePack'),action=button.onclick({currentTarget:button});
  f.context.activeAccountId='owner-b';await f.context.renderLibrary();
  const afterSwitch=f.calls.length;
  pending.resolve({created:3,skipped:0,conflict:0,documents:[]});await action;
  assert.equal(f.calls.length,afterSwitch);
  assert.equal(f.element('packImportResult').innerHTML,'');assert.deepEqual(f.toasts,[]);
});

test('out-of-order document clicks show only the last selected document',async()=>{
  const f=fixture(),a=deferred(),b=deferred();
  f.setHandler(url=>url.startsWith('/api/knowledge/a?')?a.promise:url.startsWith('/api/knowledge/b?')?b.promise:undefined);
  await f.context.renderLibrary();
  const buttons=f.groups.get('[data-document]'),first=buttons[0].onclick(),second=buttons[1].onclick();
  b.resolve(documentVersion('b'));await second;
  a.resolve(documentVersion('a'));await first;
  assert.ok(f.element('documentDetail').innerHTML.includes('原文 b v2'));
  assert.ok(!f.element('documentDetail').innerHTML.includes('原文 a v2'));
});

test('historical version selector requests exact version and safely renders old source',async()=>{
  const f=fixture();await f.context.renderLibrary();await f.groups.get('[data-document]')[0].onclick();
  f.setHandler(url=>url.includes('version=1')?{...documentVersion('a',1),source_url:'javascript:alert(1)',
    chunks:[{page:2,offset:17,text:'<img src=x onerror=bad()>'}]}:undefined);
  await f.element('documentVersion').onchange({target:{value:'1'}});
  assert.ok(f.calls.some(c=>c.url==='/api/knowledge/a?account_id=owner-a&version=1'));
  const html=f.element('documentDetail').innerHTML;
  assert.ok(html.includes('历史只读版本')&&html.includes('hash-1')&&html.includes('2026-01-01'));
  assert.ok(html.includes('第 2 页')&&html.includes('位置 17'));
  assert.ok(!html.includes('javascript:')&&!html.includes('<img'));
});

test('returning to same page/account invalidates older details and error responses',async()=>{
  const f=fixture(),pending=deferred();
  f.setHandler(url=>url.startsWith('/api/knowledge/a?')?pending.promise:undefined);
  await f.context.renderLibrary();const action=f.groups.get('[data-document]')[0].onclick();
  f.context.currentPage='overview';f.context.currentPage='library';await f.context.renderLibrary();
  pending.reject(new Error('stale error'));await action;
  assert.equal(f.element('documentDetail').innerHTML,'');assert.deepEqual(f.errors,[]);
});

test('stale preview cannot appear after account switching and revisiting',async()=>{
  const f=fixture(),pending=deferred();
  f.setHandler(url=>url.startsWith('/api/knowledge/packs/starter?')?pending.promise:undefined);
  await f.context.renderLibrary();const action=f.groups.get('[data-preview-pack]')[0].onclick();
  f.context.activeAccountId='owner-b';await f.context.renderLibrary();
  f.context.activeAccountId='owner-a';await f.context.renderLibrary();
  pending.resolve(pack);await action;
  assert.equal(f.element('packPreview').innerHTML,'');
});

test('only latest retrieval response may change the results',async()=>{
  const f=fixture(),first=deferred(),second=deferred();
  f.setHandler((url,_method,data)=>url==='/api/knowledge/retrieve'?(data.query==='first'?first.promise:second.promise):undefined);
  await f.context.renderLibrary();
  const submit=f.element('retrieveForm').onsubmit,button={disabled:false};
  f.element('retrieveQuery').value='first';const one=submit({preventDefault(){},submitter:button});
  f.element('retrieveQuery').value='second';const two=submit({preventDefault(){},submitter:button});
  const result=title=>({sources:[{title,text:title,version:1,page:1,offset:0,score:1,verification:'fixture',fingerprint:'hash'}]});
  second.resolve(result('second result'));await two;first.resolve(result('first result'));await one;
  assert.ok(f.element('retrievalResult').innerHTML.includes('second result'));
  assert.ok(!f.element('retrievalResult').innerHTML.includes('first result'));
  assert.equal(button.disabled,false);
});

test('switching accounts while file is being read prevents a later upload',async()=>{
  const f=fixture();let reader;
  f.context.FileReader=class {constructor(){reader=this;}readAsDataURL(){}};
  await f.context.renderLibrary();f.element('documentFile').files=[{name:'source.txt',size:10}];
  const submit=f.element('documentForm').onsubmit({preventDefault(){},submitter:{disabled:false}});
  f.context.activeAccountId='owner-b';await f.context.renderLibrary();
  reader.result='data:text/plain;base64,ZmFrZQ==';reader.onload();await submit;
  assert.ok(!f.calls.some(c=>c.method==='POST'));assert.deepEqual(f.errors,[]);
});

test('source links allow only credential-free HTTP(S), metadata is HTML escaped',()=>{
  const f=fixture();
  for(const url of ['javascript:alert(1)','data:text/html,x','file:///secret','https://u:p@example.com'])
    assert.equal(f.context.knowledgeSourceLink(url),'');
  assert.ok(f.context.knowledgeSourceLink('https://example.com/?a="').includes('https://example.com/'));
  assert.ok(f.context.knowledgeProvenance({author:'<script>x</script>'}).includes('&lt;script&gt;'));
});

test('remounting source search suppresses old results and errors',async()=>{
  const f=fixture(),pending=deferred();f.context.currentPage='trends';
  f.setHandler(url=>url==='/api/sources/search'?pending.promise:undefined);
  f.context.mountSourceSearch();f.element('sourceQuery').value='old query';
  const action=f.element('sourceSearchForm').onsubmit({preventDefault(){},submitter:{disabled:false}});
  f.context.mountSourceSearch();pending.reject(new Error('old request'));await action;
  assert.equal(f.element('sourceSearchResult').innerHTML,'');assert.deepEqual(f.errors,[]);
});

test('manual URL form can import two successive different URLs after success',async()=>{
  const f=fixture();f.context.currentPage='trends';
  f.setHandler(url=>url==='/api/sources/import'?{title:'已读取的网页'}:undefined);
  f.context.mountSourceSearch();
  const button={disabled:false,textContent:'读取正文并保存'},submit=f.element('sourceUrlForm').onsubmit;
  for(const url of ['https://example.com/first','https://example.com/second']){
    f.element('sourceUrl').value=url;
    await submit({preventDefault(){},submitter:button});
    assert.equal(button.disabled,false);
    assert.equal(button.textContent,'读取正文并保存');
  }
  const imports=f.calls.filter(c=>c.url==='/api/sources/import');
  assert.deepEqual(imports.map(c=>c.data.url),['https://example.com/first','https://example.com/second']);
  assert.equal(f.toasts.length,2);
});

test('successfully imported search-result card stays saved and cannot double-submit',async()=>{
  const f=fixture();f.context.currentPage='trends';
  f.setHandler(url=>url==='/api/sources/import'?{title:'已读取的网页'}:url==='/api/sources/search'
    ?{provider:'fixture',note:'test',results:[{title:'来源',snippet:'摘要',url:'https://example.com/article',fetched_at:'2026-09-22'}]}:undefined);
  f.context.mountSourceSearch();
  await f.element('sourceSearchForm').onsubmit({preventDefault(){},submitter:{disabled:false}});
  const button=f.groups.get('[data-read-source]')[0];
  await button.onclick();
  assert.equal(button.disabled,true);assert.equal(button.textContent,'已保存正文');
  await button.onclick();
  assert.equal(f.calls.filter(c=>c.url==='/api/sources/import').length,1);
});
