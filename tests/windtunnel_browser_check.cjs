/* Optional real-browser acceptance. Start an isolated API + Worker first.
   Requires playwright on NODE_PATH and installed Chrome. No model calls. */
const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
const crypto=require('crypto');
(async()=>{
 const origin=process.env.WINDTUNNEL_TEST_ORIGIN||'http://127.0.0.1:8777';
 if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(origin))throw new Error('Only isolated loopback acceptance is supported');
 const out=path.resolve(process.env.WINDTUNNEL_TEST_OUTPUT||'runtime/windtunnel-browser-evidence');
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true,recordVideo:{dir:out,size:{width:1440,height:1000}}});
 const session=await (await context.request.get(origin+'/api/session')).json();
 const registered=await context.request.post(origin+'/api/auth/register',{headers:{Origin:origin,'X-CSRF-Token':session.csrf},data:{username:'winddemo_'+Date.now(),password:'Wind'+crypto.randomBytes(6).toString('hex')+'Z'}});
 if(!registered.ok())throw new Error('Cannot create isolated browser account');
 // No credentials, cookies or recovery code are written to evidence.
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const started=Date.now(),checks=[];
 async function step(label,action){await action();checks.push(label);console.log('PASS '+label);}
 async function pause(){await page.waitForTimeout(Number(process.env.WINDTUNNEL_VIDEO_PAUSE_MS||1000));}
 try{
  await page.goto(origin+'/#windtunnel');
  await page.locator('[data-page="windtunnel"]').click();
  await step('workbench visible',async()=>{await page.locator('#wtCreateForm').waitFor();});
  await page.locator('[data-wt="example"]').click();
  await page.locator('#wtPermission').check();
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'01-input.png'),fullPage:true});await pause();
  await page.getByRole('button',{name:'保存稿件，准备问题卡 →'}).click();
  await page.locator('[data-wt="start"]').click();
  await step('worker generates candidate conditions',async()=>{await page.locator('#wtConditions').waitFor({timeout:30000});});
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'02-conditions.png'),fullPage:true});await pause();
  await page.getByRole('button',{name:'确认这些条件，固定检查范围 →'}).click();
  await page.locator('[data-wt="start"]').click();
  await step('first report from independent worker',async()=>{await page.locator('#wtPatchForm').waitFor({timeout:30000});});
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'03-report.png'),fullPage:true});await pause();
  await page.locator('#wtPatchForm input[name="condition_id"]').first().check();
  await page.locator('#wtPatchForm button').click();
  await step('patch preview ready',async()=>{await page.locator('[data-wt="apply-patch"]').waitFor({timeout:30000});});
  await page.locator('[data-patch-group] input[type="checkbox"]').first().check();await pause();
  await page.locator('[data-wt="apply-patch"]').click();
  await step('accepted patch creates a new immutable draft',async()=>{
   await page.waitForFunction(()=>wt.run?.windtunnel?.drafts.length===2);
  });
  await page.locator('[data-wt="recheck"]').click();
  await step('same-condition recheck produces second report',async()=>{
   await page.waitForFunction(()=>wt.run?.windtunnel?.reports.length===2&&!wt.run.in_flight,{},{timeout:30000});
  });
  const two=await page.evaluate(()=>({first:wt.run.windtunnel.reports[0],second:wt.run.windtunnel.reports[1],run_id:wt.run.run_id}));
  if(two.first.condition_hash!==two.second.condition_hash||two.first.draft_hash===two.second.draft_hash)throw new Error('Recheck invariants broken');
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'04-recheck.png'),fullPage:true});await pause();
  const download=page.waitForEvent('download');
  await page.getByRole('link',{name:'导出当前版本报告 ↗'}).click();
  const file=await download;const landed=path.join(out,'downloaded-report.md');await file.saveAs(landed);
  if(!fs.readFileSync(landed,'utf8').includes('模拟流程'))throw new Error('Export not labelled simulation');checks.push('browser download landed');
  await page.locator('[data-wt="tab"][data-tab="cards"]').click();
  await page.getByText('保存当前账号的检查条件',{exact:true}).click();
  await page.locator('#wtChecklistName').fill('演示教程检查条件');
  await page.getByRole('button',{name:'保存到当前账号',exact:true}).click();
  await step('reusable checklist saved',async()=>{await page.waitForFunction(()=>wt.checklists.length===1&&!wt.busy);});
  await page.locator('[data-wt="tab"][data-tab="report"]').click();
  await page.locator('[data-wt="finish"]').click();
  await page.waitForFunction(()=>wt.run?.run_status==='SUCCEEDED');
  if(process.env.WINDTUNNEL_RESTART_MARKER){
   const marker=process.env.WINDTUNNEL_RESTART_MARKER;
   fs.writeFileSync(marker+'.ready','ready');
   const deadline=Date.now()+60000;
   while(!fs.existsSync(marker+'.done')){if(Date.now()>deadline)throw new Error('Restart evidence timeout');await page.waitForTimeout(250);}
   checks.push('API and Worker externally restarted');
  }
  await page.reload();await page.locator('[data-page="windtunnel"]').click();
  await page.locator('[data-wt="open"]').first().click();
  await step('refresh restores completed drafts and reports',async()=>{await page.waitForFunction(()=>wt.run?.windtunnel?.reports.length===2&&wt.run.run_status==='SUCCEEDED');});
  await page.locator('[data-wt="new"]').click();await page.locator('[data-wt="example"]').click();
  await page.locator('#wtTitle').fill('虚构示例：复用已确认的问题');
  await page.locator('#wtNewChecklist').selectOption({label:'演示教程检查条件 · v1'});await page.locator('#wtPermission').check();
  await page.getByRole('button',{name:'保存稿件，准备问题卡 →'}).click();
  await step('checklist reuse requires new confirmation',async()=>{await page.waitForFunction(()=>wt.run?.wait_reason==='wt_confirm_conditions'&&!wt.run.windtunnel.condition_sets.at(-1).confirmed);});
  await page.locator('[data-wt="cancel"]').click();await page.waitForFunction(()=>wt.run?.run_status==='CANCELLED');checks.push('cancel persisted');
  await page.setViewportSize({width:390,height:844});
  await page.locator('[data-wt="new"]').click();
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'05-mobile.png'),fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
  if(overflow)throw new Error('Mobile horizontal overflow');checks.push('mobile has no horizontal overflow');
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('[data-wt="open"]').filter({hasText:'虚构示例：第一次导出任务表'}).first().click();
  await page.locator('[data-wt="tab"][data-tab="report"]').click();
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'06-completed.png'),fullPage:true});
  const remaining=Number(process.env.WINDTUNNEL_VIDEO_MIN_MS||0)-(Date.now()-started);
  if(remaining>0)await page.waitForTimeout(remaining);
  if(errors.length)throw new Error('Browser errors: '+errors.join('; '));
  fs.writeFileSync(path.join(out,'browser-evidence.json'),JSON.stringify({mode:'simulation',paid_model_calls:0,checks,js_errors:errors,first_run_id:two.run_id,reports:2,condition_hash:two.first.condition_hash,download_bytes:fs.statSync(landed).size,source:'unpacked delivery with fresh virtual environment and empty PostgreSQL database'},null,2));
 }catch(e){await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});console.error(e.message);process.exitCode=1;}
 finally{const video=page.video();await context.close();if(video){await video.saveAs(path.join(out,'windtunnel-demo.webm'));console.log('Video saved');}await browser.close();}
})();
