'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const html=fs.readFileSync('frontend/index.html','utf8');
const theme=fs.readFileSync('frontend/theme.css','utf8');

test('theme stylesheet loads after the base and wind tunnel styles',()=>{
 const styles=[...html.matchAll(/<link rel="stylesheet" href="([^"]+)">/g)].map(m=>m[1]);
 assert.deepEqual(styles,['/style.css','/windtunnel.css','/theme.css']);
});

test('promova theme uses pastel blocks, a black action and a larger bold hierarchy',()=>{
 for(const token of ['--bg:#fffcf3','--pink:#f6d9ea','--yellow:#fbf6c8','--blue:#dcebff','--lime:#dff247','--action:#111111','--radius:20px'])assert.ok(theme.includes(token),token);
 assert.match(theme,/\.topbar\{[^}]*border-bottom:1px solid var\(--line\)/);
 assert.match(theme,/\.sidebar\{[^}]*background:var\(--sidebar\)/);
 assert.match(theme,/\.page\{[^}]*max-width:1240px/);
 assert.match(theme,/\.page-header h1\{[^}]*font-size:40px;line-height:1\.12;font-weight:800/);
 assert.match(theme,/\.primary,\.button\.primary\{[^}]*background:var\(--action\)/);
 assert.match(theme,/\.stats>div:nth-child\(4n\+1\)\{[^}]*background:var\(--pink\)/);
 assert.match(theme,/\.panel\{[^}]*border-radius:var\(--radius\)/);
});

test('top bar, section sidebar and welcome guide share the console structure',()=>{
 assert.match(html,/<header class="topbar">/);
 assert.match(html,/<aside class="sidebar">/);
 assert.match(html,/<div class="nav-section-label">工作空间<\/div>/);
 assert.match(html,/<div class="nav-section-label">运营与复盘<\/div>/);
 assert.match(html,/<div class="topbar-actions">/);
 assert.match(html,/<div class="get-started"[^>]*>/);
 assert.match(html,/<div class="login-brand">/);
 assert.match(theme,/\.topnav\{/);
 assert.match(theme,/\.nav-section-label\{/);
 assert.match(theme,/\.gs-step\.is-active\{/);
});

test('playful mascot layer stays available without replacing the console layout',()=>{
 assert.match(html,/mascot-space\.png/);
 assert.match(html,/shape-hemisphere\.png/);
 assert.match(html,/shape-torus\.png/);
 assert.match(html,/id="dog-face"/);
 assert.match(html,/id="bootLoader"/);
 assert.match(html,/class="login-art"/);
 const operations=fs.readFileSync('frontend/operations.js','utf8');
 assert.match(operations,/empty=\(title,body\)=>.*?mascot-dog\.png/s);
 assert.match(theme,/\.boot-loader\{/);
 assert.match(theme,/\.login-art\{/);
 assert.match(theme,/\.empty-art\{/);
});

test('theme adds no transforms or rem-based geometry',()=>{
 assert.doesNotMatch(theme,/\bzoom\s*:/);
 assert.doesNotMatch(theme,/transform\s*:\s*scale/);
 assert.doesNotMatch(theme,/(?:padding|margin|gap)\s*:[^;{}]*\d(?:rem|em)\b/);
});
