'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function fixture(blocked = false) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {hidden:false, value:'old', addEventListener(){}});
    return elements.get(id);
  };
  const context = vm.createContext({
    localStorage: {getItem:()=>'old', setItem(){}},
    $:element, document:{querySelector:element}, window:{addEventListener(){}},
    busy:blocked, opsBusy:false, dirtyGuard:()=>true, auto:true,
    chosenTrend:{id:'old-trend'}, chosenExperiment:{id:'old-experiment'},
    chosenPromotion:{id:'old-promotion'}, run:{run_id:'old-run'}, editing:true,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/account.js'),'utf8'), context);
  vm.runInContext('syncAccounts=()=>{}; renderOperations=()=>{}; history=async()=>{};', context);
  return {context, element};
}

test('changing account clears every account-bound selection and current run', async () => {
  const {context, element} = fixture();
  await element('activeAccount').onchange({target:{value:'new'}});
  for (const name of ['chosenTrend','chosenExperiment','chosenPromotion','run']) {
    assert.equal(context[name], null, name);
  }
  assert.equal(vm.runInContext('activeAccountId',context),'new');
  assert.equal(element('selectedTrend').hidden,true);
  assert.equal(element('workbench').hidden,true);
});

test('busy account switch preserves the current promotion and account', async () => {
  const {context, element} = fixture(true);
  const target={value:'new'};
  await element('activeAccount').onchange({target});
  assert.equal(target.value,'old');
  assert.equal(context.chosenPromotion.id,'old-promotion');
  assert.equal(vm.runInContext('activeAccountId',context),'old');
});

test('declining the dirty-state guard preserves all selections', async () => {
  const {context, element}=fixture();
  context.dirtyGuard=()=>false;
  await element('activeAccount').onchange({target:{value:'new'}});
  assert.equal(context.chosenPromotion.id,'old-promotion');
  assert.equal(context.run.run_id,'old-run');
});
