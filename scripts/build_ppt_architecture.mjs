/** Editable SVG diagrams for the provincial defense. No model/network calls.
 * Run with Node and sharp available (NODE_PATH may locate the bundled runtime).
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url), sharp=require('sharp');
const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const out=path.resolve(process.argv[2] || path.join(app,'../output/有迹-PPT架构图与设计方案-20261103'));
const C={blue:'#0754A3',orange:'#ED9600',ink:'#172435',muted:'#5C6D7D',line:'#D5DFE8',pale:'#F3F7FB',amber:'#FFF8EC',white:'#FFFFFF'};
let parts=[],texts=[],bounds=[];
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
function rect(x,y,w,h,{stroke=C.blue,fill=C.white,width=2}={}){
  bounds.push({x,y,w,h});parts.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}" stroke="${stroke}" stroke-width="${width}"/>`);
}
function polygon(points,{stroke=C.blue,fill=C.pale}={}){
  if(points.some(([x,y])=>x<0||y<0||x>1920||y>1080))throw Error('Polygon outside canvas');
  parts.push(`<polygon points="${points.map(p=>p.join(',')).join(' ')}" fill="${fill}" stroke="${stroke}" stroke-width="2"/>`);
}
function text(x,y,lines,{size=32,color=C.ink,weight=400,anchor='middle',lh=size*1.35,maxWidth=1800}={}){
  if(!Array.isArray(lines))lines=[lines];
  for(const [i,line] of lines.entries()){
    const estimated=[...line].reduce((a,c)=>a+(/[\u0000-\u007f]/.test(c)?.56:1),0)*size;
    if(estimated>maxWidth)throw Error(`Text exceeds assigned width: ${line} (${estimated}>${maxWidth})`);
    const yy=y+i*lh;texts.push({x,y:yy,line,size,maxWidth});
    parts.push(`<text x="${x}" y="${yy}" font-size="${size}" font-weight="${weight}" fill="${color}" text-anchor="${anchor}">${esc(line)}</text>`);
  }
}
function box(x,y,w,h,lines,opts={}){
  rect(x,y,w,h,opts);const size=opts.size||32,arr=Array.isArray(lines)?lines:[lines],lh=opts.lh||size*1.35;
  text(x+w/2,y+h/2-(arr.length-1)*lh/2+size*.35,arr,{...opts,size,lh,maxWidth:w-26});
}
function arrow(points,{color=C.blue,dashed=false,both=false}={}){
  const marker=color===C.orange?'orange':color===C.line?'gray':'blue';
  parts.push(`<path d="${points}" fill="none" stroke="${color}" stroke-width="3" ${dashed?'stroke-dasharray="9 7"':''} ${both?`marker-start="url(#${marker}Start)"`:''} marker-end="url(#${marker})"/>`);
}
function panel(x,y,w,h,title,accent=C.blue){
  rect(x,y,w,h,{stroke:accent});rect(x,y,w,66,{stroke:accent,fill:accent});
  text(x+w/2,y+45,title,{size:35,color:C.white,weight:700,maxWidth:w-24});
}
function start(title,subtitle){
  parts=[];texts=[];bounds=[];
  parts.push(`<rect width="1920" height="1080" fill="white"/>`);
  rect(72,46,690,94,{fill:C.blue,stroke:C.blue});rect(72,46,10,94,{fill:C.orange,stroke:C.orange});
  text(116,110,title,{size:54,color:C.white,weight:700,anchor:'start',maxWidth:620});
  text(72,184,subtitle,{size:30,color:C.muted,anchor:'start',maxWidth:1776});
}
function svg(){
  for(const b of bounds)if(b.x<0||b.y<0||b.x+b.w>1920||b.y+b.h>1080)throw Error('Shape outside canvas');
  for(const t of texts)if(t.y-t.size<0||t.y>1080)throw Error('Text outside canvas');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080" role="img"><title>有迹技术图</title><defs>${[['blue',C.blue],['orange',C.orange],['gray',C.line]].map(([id,c])=>`<marker id="${id}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 Z" fill="${c}"/></marker><marker id="${id}Start" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 Z" fill="${c}"/></marker>`).join('')}</defs><g font-family="Hiragino Sans GB, Microsoft YaHei, Noto Sans CJK SC, sans-serif">${parts.join('')}</g></svg>`;
}
function architecture(){
  start('系统总体架构','有迹｜小红书商品与服务文稿创作');
  rect(72,222,1776,112);box(72,222,202,112,'交互层',{fill:C.blue,color:C.white,weight:700,size:36});
  for(const [x,label] of [[300,'主题与产品资料'],[690,'创作工作台'],[1080,'改稿与人工确认'],[1470,'复制 / Word导出']])
    text(x+175,289,label,{size:32,maxWidth:350});
  arrow('M960 342 V374');
  rect(72,382,1776,116);box(72,382,202,116,['接口与','任务编排'],{fill:C.blue,color:C.white,weight:700,size:34});
  box(300,405,410,70,'FastAPI 接口服务',{fill:C.pale});
  arrow('M722 440 H750');
  box(762,405,470,70,'持久任务队列 / Worker',{fill:C.pale,size:31});
  arrow('M1242 440 H1272');
  box(1284,405,536,70,'LangGraph 工作流',{fill:C.pale});
  arrow('M960 507 V534');
  panel(72,544,520,320,'分组检索与证据');
  for(const [x,label] of [[94,'创作方法'],[260,'表达样例'],[426,'产品事实']])box(x,634,144,64,label,{size:29,fill:C.pale});
  text(332,745,'账号与领域过滤',{size:32});
  text(332,792,'向量排序 / BM25降级',{size:30,maxWidth:470});
  text(332,840,'原文、位置与版本快照',{size:30});
  arrow('M601 709 H628');
  panel(638,544,678,320,'四角色协作');
  box(660,628,296,62,'受众分析',{fill:C.pale,size:34});
  box(998,628,296,62,'资料研究',{fill:C.pale,size:34});
  arrow('M808 692 V706 H977 V717');arrow('M1146 692 V706 H977 V717');
  box(660,722,634,62,'内容策划与创作',{size:34});
  arrow('M977 788 V803');
  box(660,807,634,42,'主编审核',{size:30});
  panel(1352,544,496,320,'创作决策模块',C.orange);
  box(1374,628,452,58,'需求覆盖优化',{stroke:C.orange,fill:C.amber,size:34});
  box(1374,710,452,58,'关键缺口提问排序',{stroke:C.orange,fill:C.amber,size:34});
  box(1374,792,452,58,'证据约束结构迁移',{stroke:C.orange,fill:C.amber,size:34});
  arrow('M1345 753 H1322',{color:C.orange,dashed:true});
  arrow('M960 904 V875',{color:C.line});
  rect(72,916,1776,92);box(72,916,202,92,'基础支撑',{fill:C.blue,color:C.white,size:34,weight:700});
  text(534,956,'统一模型路由',{size:32});text(534,992,'平台模型 / 用户配置',{size:27,color:C.muted});
  text(1040,956,'PostgreSQL / SQLite',{size:30,maxWidth:500});text(1040,992,'按部署配置选择数据库',{size:27,color:C.muted});
  text(1552,956,'证据、版本与运行记录',{size:30});text(1552,992,'持久检查点 · 调用台账',{size:27,color:C.muted});
  text(960,1054,'贯穿全程：账号隔离｜预算控制｜引用校验｜版本复审｜人工确认',{size:29,color:C.muted});
  return svg();
}
function route(){
  start('总体技术路线','前端交互、后端服务、模型编排与数据存储的技术选型');
  const columns=[[72,'前端开发',C.blue],[524,'后端服务',C.blue],[976,'Agent 编排',C.orange],[1428,'模型接入',C.blue]];
  for(const [x,title,color] of columns)panel(x,240,420,402,title,color);
  box(96,344,372,94,['HTML5 · CSS3','原生 JavaScript'],{size:31,fill:C.pale});
  box(96,492,372,74,'Fetch API + 轮询',{size:30});
  text(282,618,'页面交互与任务状态更新',{size:26,color:C.muted,maxWidth:396});
  box(548,344,372,94,['Python + FastAPI','Uvicorn'],{size:31,fill:C.pale});
  box(548,492,372,74,'Pydantic',{size:32});
  text(734,618,'接口服务与参数校验',{size:27,color:C.muted,maxWidth:396});
  box(1000,344,372,94,'LangGraph',{size:35,fill:C.amber,stroke:C.orange});
  box(1000,492,372,74,'Worker + SQL队列',{size:30,stroke:C.orange});
  text(1186,618,'四角色 · 检查点 · 暂停恢复',{size:25,color:C.muted,maxWidth:396});
  box(1452,344,372,94,'DeepSeek / Qwen',{size:31,fill:C.pale});
  box(1452,492,372,74,'OpenAI兼容 HTTP',{size:30});
  text(1638,618,'统一路由与调用计费记录',{size:26,color:C.muted,maxWidth:396});
  for(const x of [500,952,1404])arrow(`M${x} 464 H${x+16}`,{color:C.line});
  panel(72,714,560,270,'检索与知识库');
  text(352,818,'自实现 BM25',{size:34,maxWidth:512});
  text(352,865,'Sentence-Transformers（可选）',{size:27,maxWidth:512});
  text(352,912,'本地 BGE 向量 / 余弦排序',{size:28,maxWidth:512});
  text(352,965,'向量不可用时使用BM25',{size:26,color:C.muted,maxWidth:512});
  panel(680,714,560,270,'数据库与状态');
  text(960,818,'PostgreSQL · psycopg',{size:32,maxWidth:512});
  text(960,865,'SQLite · sqlite3',{size:32,maxWidth:512});
  text(960,912,'LangGraph Checkpoint',{size:30,maxWidth:512});
  text(960,965,'按部署配置选择数据库',{size:26,color:C.muted,maxWidth:512});
  panel(1288,714,560,270,'算法与文档处理',C.orange);
  text(1568,818,'Python：枚举 / 贪心 / 规则排序',{size:28,maxWidth:512});
  text(1568,865,'pypdf · XML / ZIP',{size:32,maxWidth:512});
  text(1568,912,'DOCX / OOXML 导出',{size:30,maxWidth:512});
  text(1568,965,'覆盖优化 · 缺口排序 · 结构适配',{size:26,color:C.muted,maxWidth:536});
  text(960,1052,'安全：PBKDF2密码散列 · CSRF校验 · Fernet密钥加密',{size:29,color:C.muted});
  return svg();
}
export {C,rect,polygon,text,box,arrow,panel,start,svg};
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  await fs.mkdir(out,{recursive:true});
  for(const [name,build] of [['01-系统总体架构',architecture],['02-总体技术路线',route]]){
    const source=build();await fs.writeFile(path.join(out,name+'.svg'),source);
    await sharp(Buffer.from(source)).resize(3840,2160).png().toFile(path.join(out,name+'.png'));
    console.log(name, '1920×1080 SVG; 3840×2160 PNG;',texts.length,'text lines; bounds OK');
  }
  await fs.copyFile(path.join(app,'docs/design/PPT_ARCHITECTURE_20261103.md'),path.join(out,'设计方案与讲稿.md'));
}
