/** PPT diagram assets only; all labels follow the implemented creation path. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {C,polygon,text,box,arrow,panel,start,svg} from './build_ppt_architecture.mjs';
const require=createRequire(import.meta.url),sharp=require('sharp');
const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const out=path.resolve(process.argv[2]||path.join(app,'../output/有迹-PPT分项流程-20261103'));
function decision(cx,cy,w,h,label){
  polygon([[cx,cy-h/2],[cx+w/2,cy],[cx,cy+h/2],[cx-w/2,cy]]);
  text(cx,cy+10,label,{size:31,maxWidth:w-48});
}
function overview(){
  start('分项流程','资料检索、创作决策与审核采用分别展开');
  for(const [y,s] of [[260,'产品资料'],[350,'创作方法'],[440,'表达样例']])box(72,y,180,60,s,{size:30,fill:C.pale});
  arrow('M254 290 H276 V384 H298');arrow('M254 380 H298');arrow('M254 470 H276 V384 H298');
  box(306,334,218,100,['账号与领域过滤','方法/样例匹配'],{size:27});
  arrow('M530 384 H568');box(578,334,286,100,['组内排序','向量 / BM25降级'],{size:28});
  arrow('M721 442 V478');box(578,486,286,66,'来源与版本快照',{size:29,fill:C.pale});
  text(468,620,'图1 资料分组检索流程',{size:30});
  box(1010,260,260,70,'受众分析',{size:31,fill:C.pale});box(1420,260,310,70,'资料研究',{size:31,fill:C.pale});
  arrow('M1140 336 V360 H1350 V381');arrow('M1575 336 V360 H1350 V381');
  box(1110,390,290,70,'内容策划与创作',{size:29});arrow('M1406 425 H1476');box(1488,390,310,70,'主编审核',{size:31});
  arrow('M1643 466 V495');box(1488,506,310,64,'人工采用与导出',{size:29,fill:C.pale});
  arrow('M1480 538 H1255 V466');text(1368,520,'改稿后复审',{size:26,color:C.muted});
  text(1428,620,'图2 四角色协作与采用流程',{size:30});
  for(const [x,lines] of [[72,['读者问题与候选内容','证据准入与篇幅约束','加权覆盖优化']],[700,['事实缺口与影响范围','价值排序与去重','最多一轮两问，可跳过']],[1328,['同类样例与本次证据','提取段落功能并适配','结构建议，不迁移原事实']]]){
    box(x,704,520,60,lines[0],{size:30,fill:C.pale});arrow(`M${x+260} 772 V804`,{color:C.orange});
    box(x,816,520,60,lines[1],{size:30,stroke:C.orange,fill:C.amber});arrow(`M${x+260} 884 V916`,{color:C.orange});
    box(x,928,520,60,lines[2],{size:29,stroke:C.orange});
  }
  text(960,1050,'图3 三算法创作决策流程',{size:30});return svg();
}
function retrieval(){
  start('资料分组检索','先限定资料范围，再做组内排序，保留本次引用依据');
  box(72,250,320,94,['主题与产品资料','已有资料库'],{size:31,fill:C.pale});arrow('M402 297 H446');
  box(460,250,410,94,['任务分类','领域、渠道与内容形式'],{size:30});arrow('M880 297 H924');
  box(938,250,410,94,['账号与领域过滤','方法、样例匹配形式'],{size:30});arrow('M1358 297 H1402');
  box(1416,250,432,94,['创作方法 / 表达样例','本次产品事实'],{size:30,fill:C.pale});
  arrow('M1632 352 V410 H960 V447');
  decision(960,520,300,140,'向量可用？');
  arrow('M804 520 H525 V606');text(680,499,'可用',{size:28,color:C.muted});
  arrow('M1116 520 H1395 V606');text(1232,499,'不可用',{size:28,color:C.muted});
  box(300,620,450,104,['本地向量排序','余弦相似度 + 主题覆盖'],{size:29,fill:C.pale});
  box(1170,620,450,104,['BM25关键词排序','按组降级，不扩大范围'],{size:29,fill:C.pale});
  arrow('M525 732 V775 H960 V803');arrow('M1395 732 V775 H960 V803');
  box(530,815,860,80,'同文档去重 · 分组配额 · 上下文长度限制',{size:32});arrow('M960 903 V929');
  box(530,942,860,70,'冻结原文、来源、位置和版本',{size:33,stroke:C.orange,fill:C.amber});
  text(960,1060,'范围始终受账号授权约束；没有匹配结果时，不借用无关领域样例',{size:28,color:C.muted});
  return svg();
}
function algorithms(){
  start('三算法决策流程','围绕篇幅、资料缺口和段落证据，形成可回查的创作计划');
  panel(72,232,520,752,'需求覆盖优化',C.orange);
  box(96,330,472,90,['读者问题与权重','候选内容与预计字数'],{size:30,fill:C.pale});arrow('M332 428 V456');
  box(96,464,472,64,'引用定位与覆盖准入',{size:31});arrow('M332 536 V554');
  // Downward connector ends at the decision's top; kept separate from branches.
  decision(332,620,400,120,'合法候选≤12？');
  arrow('M132 620 H116 V694');arrow('M532 620 H548 V694');text(164,672,'是',{size:26,color:C.muted});text(500,672,'否',{size:26,color:C.muted});
  box(96,706,220,68,'枚举子集',{size:31,fill:C.pale});box(348,706,220,68,'贪心选择',{size:31,fill:C.pale});
  arrow('M206 782 V812 H332 V830');arrow('M458 782 V812 H332 V830');
  box(96,842,472,90,['选中内容与未覆盖问题','保留取舍记录'],{size:29,fill:C.amber,stroke:C.orange});
  text(332,970,'目标：加权覆盖，减少重复',{size:26,color:C.muted,maxWidth:500});
  panel(700,232,520,752,'关键缺口提问排序',C.orange);
  box(724,330,472,90,['事实缺口','受影响的问题与优先级'],{size:30,fill:C.pale});arrow('M960 428 V456');
  box(724,468,472,110,['按重要程度、影响范围','可补充程度与成本评分'],{size:29});arrow('M960 586 V616');
  box(724,628,472,102,['选高分问题，扣除重复影响','每选一问后重新排序'],{size:28});arrow('M960 738 V768');
  box(724,780,472,80,['最多一轮两问','用户可回答或跳过'],{size:29,fill:C.amber,stroke:C.orange});
  text(960,919,['回答：换快照后重新研究','跳过：保留缺口继续'],{size:28,color:C.muted,maxWidth:490,lh:39});
  panel(1328,232,520,752,'证据约束结构迁移',C.orange);
  for(const [y,lines] of [[330,['同领域表达样例','本次可用证据']],[480,['规则提取段落功能']],[620,['检查槽位证据依赖']],[760,['适配缺证据槽位']]]){
    box(1352,y,472,80,lines,{size:30,fill:y===330?C.pale:C.white});if(y!==760)arrow(`M1588 ${y+88} V${y+126}`);
  }
  arrow('M1588 848 V862');box(1352,874,472,58,'输出段落功能建议',{size:31,fill:C.amber,stroke:C.orange});
  text(1588,966,'写作可合并、省略，不继承亲历',{size:25,color:C.muted,maxWidth:495});
  text(960,1054,'规划结果用于辅助写作，不代表文章全局最优或事实核验通过',{size:29,color:C.muted});
  return svg();
}
function collaboration(){
  start('四角色与改稿复审','前置分析并行，内容分阶段执行，采用决定绑定稿件版本');
  box(72,310,240,92,['冻结本次','任务快照'],{size:32,fill:C.pale});
  arrow('M320 356 H360 V279 H388');arrow('M360 356 V445 H388');
  box(400,240,260,78,'受众分析',{size:33});box(400,406,260,78,'资料研究',{size:33});
  arrow('M668 279 H718 V356 H748');arrow('M668 445 H718 V356 H748');
  box(760,310,260,92,['汇合结果','计算初步计划'],{size:30,fill:C.amber,stroke:C.orange});arrow('M1028 356 H1098');
  box(1110,310,738,112,['内容角色：策略与候选模块','更新计划后：提纲→开头→标题→正文'],{size:29,fill:C.pale});
  arrow('M1479 430 V510 H960 V548');box(720,560,480,82,'主编审核与程序检查',{size:32});arrow('M960 650 V680');
  decision(960,760,300,136,'审核结果');
  arrow('M804 760 H624');text(704,737,'修改',{size:27,color:C.muted});
  box(180,718,430,84,['用户修改或申请改稿','生成新版本后重新审核'],{size:29});arrow('M395 710 V601 H708');
  text(395,853,'旧版本审核失效',{size:29,color:C.muted});
  arrow('M960 836 V902');text(1006,880,'通过',{size:27,color:C.muted,anchor:'start'});
  box(720,914,480,72,'人工确认当前版本',{size:32});arrow('M1208 950 H1308');
  arrow('M1116 760 H1308');text(1216,737,'人工处理',{size:26,color:C.muted});
  box(1320,700,528,122,['查看问题后明确知情采用','单独记录采用决定'],{size:29,fill:C.pale});arrow('M1584 830 V902');
  box(1320,914,528,72,'复制文案 / Word导出',{size:31,fill:C.amber,stroke:C.orange});
  text(960,1050,'人工采用不等于审核通过；所有决定绑定当前稿件版本',{size:29,color:C.muted});
  return svg();
}
await fs.mkdir(out,{recursive:true});
for(const [name,build] of [['00-分项流程总览',overview],['01-资料分组检索流程',retrieval],['02-三算法决策流程',algorithms],['03-四角色与改稿复审流程',collaboration]]){
  const source=build();await fs.writeFile(path.join(out,name+'.svg'),source);
  await sharp(Buffer.from(source)).resize(3840,2160).png().toFile(path.join(out,name+'.png'));
  console.log(name,'SVG geometry checks and 4K rendering complete');
}
await fs.copyFile(path.join(app,'docs/design/PPT_SUBFLOWS_20261103.md'),path.join(out,'分项流程说明与讲稿.md'));
