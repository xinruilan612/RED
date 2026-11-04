'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
test('typography grows 15 percent while component geometry and relative hierarchy remain stable',()=>{
 const css=fs.readFileSync('frontend/style.css','utf8');
 assert.match(css,/html\{font-size:18\.4px\}/);assert.match(css,/body\{[^}]*font-size:16\.1px/);assert.match(css,/h1\{font-size:33\.35px/);assert.match(css,/h2\{font-size:20\.7px/);assert.match(css,/\.helper\{font-size:11\.5px/);
 assert.match(css,/grid-template-columns:44px minmax\(0,1fr\);gap:16px/);assert.match(css,/width:26px;height:26px;min-width:26px/);assert.match(css,/\.panel\{[^}]*padding:24px/);
 for(const path of ['frontend/style.css','frontend/trials.css','frontend/windtunnel.css']){const sheet=fs.readFileSync(path,'utf8');assert.doesNotMatch(sheet,/\bzoom\s*:|transform\s*:\s*scale/);assert.doesNotMatch(sheet,/(?:padding|margin|gap)\s*:[^;{}]*\d(?:rem|em)\b/);}
 assert.match(fs.readFileSync('frontend/trials.css','utf8'),/font:600 19\.55px/);assert.match(fs.readFileSync('frontend/windtunnel.css','utf8'),/font:600 12\.65px/);
});
