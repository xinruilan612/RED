"use strict";
// Local renderer only: no image or copy leaves this project's server.
window.posterGenerate=async function(e,payload){
 if(!payload.source_image)throw new Error('请先添加产品原图。已确认文案会自动读取。');
 if(!posterAlive(e)||e.busy)return false;
 e.busy=true;posterSync(e);e.status.textContent='正在本机制作海报，保留已确认文案…';
 try{
  const response=await fetch(`/api/runs/${encodeURIComponent(e.run.run_id)}/poster/generate`,{method:'POST',credentials:'same-origin',headers:mediaHeaders(),body:JSON.stringify({...posterBase(e),...payload})});
  const data=await response.json();if(!response.ok)throw new Error(posterError(data));
  if(!posterAlive(e))return false;posterApply(e,data);e.status.textContent='新版本已完成。检查画面后采用，也可以撤销。';return true;
 }catch(error){if(posterAlive(e))e.status.textContent=error.message;return false;}
 finally{e.busy=false;posterSync(e);}
};
window.dispatchEvent(new Event('poster-provider-ready'));
