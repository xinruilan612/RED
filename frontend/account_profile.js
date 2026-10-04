'use strict';
(function(root,factory){
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 if(root)root.accountProfile=api;
})(typeof window!=='undefined'?window:globalThis,function(){
 const positions=['摄影 / 摄影服务','服饰 / 穿搭','美妆 / 护肤','餐饮 / 美食','知识 / 教育','工具 / 软件','本地生活 / 活动','生活方式 / 其他'];
 const basePillars={
  '摄影 / 摄影服务':{
   xiaohongshu:['摄影作品展示','拍摄技巧教程','修图前后对比','拍摄幕后花絮','器材与参数分享','约拍案例 / 摄影服务介绍'],
   douyin:['摄影作品展示','拍摄过程短视频','镜头前讲拍摄方法','修图前后对比','拍摄幕后花絮','约拍案例 / 摄影服务介绍']},
  '服饰 / 穿搭':{
   xiaohongshu:['穿搭展示','单品细节 / 真实测评','搭配教程','不同场景穿搭','试穿上身效果','尺码 / 选购答疑','上新 / 活动介绍'],
   douyin:['穿搭变装视频','上身试穿展示','面料细节 / 对比','搭配技巧讲解','日常穿搭场景','直播 / 上新预告','尺码 / 选购答疑']},
  '美妆 / 护肤':{
   xiaohongshu:['产品成分 / 使用说明','化妆步骤教程','上脸效果记录','不同肤质选购建议','使用前后对比（注明条件）','产品答疑 / 活动信息'],
   douyin:['快速化妆教程','上脸实测过程','产品使用演示','妆容前后对比','成分与使用答疑','直播 / 上新预告']},
  '餐饮 / 美食':{
   xiaohongshu:['菜品展示','制作过程','探店记录','菜单 / 价格说明','食材与后厨幕后','顾客常见问题'],
   douyin:['菜品制作短视频','门店探访','出餐过程','招牌菜介绍','菜单 / 活动说明','顾客常见问题']},
  '知识 / 教育':{
   xiaohongshu:['入门知识清单','步骤教程','常见错误解析','案例拆解','问题答疑','学习 / 活动信息'],
   douyin:['一分钟知识讲解','步骤演示','常见错误纠正','案例口播拆解','评论区答疑','直播 / 课程预告']},
  '工具 / 软件':{
   xiaohongshu:['新手入门教程','功能实操演示','工作流 / 效率技巧','真实使用体验','常见问题答疑','版本 / 活动信息'],
   douyin:['屏幕操作教程','功能演示短视频','效率技巧口播','使用问题解答','真实场景案例','直播 / 活动预告']},
  '本地生活 / 活动':{
   xiaohongshu:['地点 / 活动介绍','路线与参与指南','现场记录','费用 / 时间说明','参与者体验','报名问题答疑'],
   douyin:['现场短视频','活动亮点介绍','路线 / 参与方法','活动时间与费用','报名入口说明','现场问答']},
  '生活方式 / 其他':{
   xiaohongshu:['日常记录','经验分享','步骤教程','清单 / 选购建议','幕后故事','问题答疑'],
   douyin:['日常短视频','经验口播','步骤演示','清单 / 选购建议','幕后记录','评论区答疑']}
 };
 const goals={
  '摄影 / 摄影服务':['吸引摄影兴趣用户关注','获取约拍咨询','展示作品并建立专业形象','提升收藏与互动','验证内容方向'],
  '服饰 / 穿搭':['提升商品浏览与成交','引导进店或查看商品','积累穿搭兴趣关注','促进上新 / 活动参与','提升收藏与互动'],
  '美妆 / 护肤':['提升商品浏览与成交','引导进店或查看商品','积累美妆兴趣关注','解答选购疑问','验证内容方向'],
  '餐饮 / 美食':['增加到店咨询与到店消费','引导查看菜单 / 预约','扩大本地关注','介绍新品 / 活动','提升收藏与互动'],
  '知识 / 教育':['吸引目标学习者关注','获取课程 / 咨询线索','引导报名 / 注册','提升内容收藏','验证内容方向'],
  '工具 / 软件':['吸引目标用户关注','引导试用 / 注册','获取有效线索','提升教程收藏','验证内容方向'],
  '本地生活 / 活动':['获取活动报名','引导预约 / 到店','扩大本地关注','推广活动信息','验证内容方向'],
  '生活方式 / 其他':['吸引目标受众关注','提升收藏与互动','建立个人品牌','推广商品 / 服务','验证内容方向']
 };
 const commonBanned=['必爆','全网第一','百分之百有效','保证涨粉','保证收益','立刻见效','亲测有效'];
 const nicheBanned={
  '摄影 / 摄影服务':['保证出片','零基础一定拍好','修图前后效果保证'],
  '服饰 / 穿搭':['全网最低价','所有人都适合','显瘦十斤'],
  '美妆 / 护肤':['保证祛痘','保证美白','所有肤质都适用'],
  '餐饮 / 美食':['全城最好吃','保证减脂','绝对新鲜'],
  '知识 / 教育':['保证提分','包过','百分百录取'],
  '工具 / 软件':['保证提高效率','永久免费（未经确认）','百分百安全'],
  '本地生活 / 活动':['名额永久充足','保证中奖','绝对不排队'],
  '生活方式 / 其他':[]
 };
 const resourceGroups={
  time:['每周少于 2 小时','每周 2–4 小时','每周 5 小时以上','可投入时间不固定'],
  equipment:{
   '摄影 / 摄影服务':['主要用手机拍摄','有相机 / 镜头','有灯光 / 反光板','可安排拍摄对象'],
   '服饰 / 穿搭':['主要用手机拍摄','已有商品样品','可安排试穿 / 模特','有店铺 / 仓库场景'],
   '美妆 / 护肤':['主要用手机拍摄','已有产品样品','有基础补光设备','可安排上脸演示'],
   '餐饮 / 美食':['主要用手机拍摄','可进入门店 / 后厨','可拍摄制作过程','可安排菜品试吃'],
   '知识 / 教育':['主要用手机拍摄','可录制屏幕 / 课件','可安排出镜讲解','有现成课程素材'],
   '工具 / 软件':['主要用手机拍摄','可录制屏幕操作','有产品试用账号','可演示真实工作流'],
   '本地生活 / 活动':['主要用手机拍摄','可进入活动现场','已有活动照片 / 视频','可安排参与者采访'],
   '生活方式 / 其他':['主要用手机拍摄','有相机 / 灯光等设备','可安排出镜拍摄']
  },
  materials:{
   '摄影 / 摄影服务':['已有可用照片或视频素材','需要重新拍摄','可以安排人物拍摄'],
   '服饰 / 穿搭':['已有可用照片或视频素材','需要重新拍摄商品','有现成商品介绍素材'],
   '美妆 / 护肤':['已有可用照片或视频素材','需要重新拍摄','有产品说明 / 成分资料'],
   '餐饮 / 美食':['已有可用照片或视频素材','需要重新拍摄菜品','有菜单 / 价格资料'],
   '知识 / 教育':['已有课件 / 教学素材','需要重新录制','有可公开案例 / 资料'],
   '工具 / 软件':['已有操作录屏 / 截图','需要重新录制','有官方说明 / 产品资料'],
   '本地生活 / 活动':['已有活动照片或视频','需要重新拍摄现场','有时间 / 地点 / 报名资料'],
   '生活方式 / 其他':['已有可用照片或视频素材','需要重新拍摄','有可引用的资料']
  }
 };
 const aliases={
  '摄影 / 摄影服务':['摄影','约拍','人像','写真','摄影师','摄像'],
  '服饰 / 穿搭':['服饰','穿搭','服装','女装','男装','衣服','鞋包'],
  '美妆 / 护肤':['美妆','护肤','化妆','彩妆','美甲'],
  '餐饮 / 美食':['餐饮','美食','探店','菜品','烘焙'],
  '知识 / 教育':['知识','教育','课程','培训','学习'],
  '工具 / 软件':['工具','软件','App','应用','剪辑'],
  '本地生活 / 活动':['本地','活动','门店','旅游','探店','展会'],
  '生活方式 / 其他':['生活','日常']
 };
 function categoryOf(value){
  const text=(value||'').split('｜')[0].toLowerCase();
  if(positions.includes(value))return value;
  return positions.find(category=>aliases[category].some(alias=>text.includes(alias.toLowerCase())))||'生活方式 / 其他';
 }
 function options(positioning,platform){
  const category=categoryOf(positioning),site=platform==='douyin'?'douyin':'xiaohongshu';
  return {category,pillars:basePillars[category][site],goals:goals[category],banned:[...commonBanned,...nicheBanned[category]],resources:{time:resourceGroups.time,equipment:resourceGroups.equipment[category],materials:resourceGroups.materials[category]}};
 }
 function splitList(value){return (Array.isArray(value)?value:(value||'').split(/[，、,\n]/)).map(v=>v.trim()).filter(Boolean);}
 function positionValue(category,detail){return category==='__custom__'?detail.trim():`${category}${detail.trim()?`｜${detail.trim()}`:''}`;}
 function positioningParts(value){
  if(!value)return {category:'',detail:''};
  if(positions.includes(value))return {category:value,detail:''};
  const text=value||'';
  const saved=positions.find(category=>text.startsWith(category+'｜'));
  if(saved)return {category:saved,detail:text.slice(saved.length+1)};
  const category=categoryOf(value);
  if(text&&category!=='生活方式 / 其他'&&category!==text){
   const rest=text.replace(new RegExp(aliases[category].join('|'),'gi'),'').replace(/[\s/｜|,，-]/g,'').trim();
   return {category,detail:rest};
  }
  if(text.startsWith(category+'｜'))return {category,detail:text.slice(category.length+1)};
  return {category:'__custom__',detail:text};
 }
 function valuesFor(key,values,oldPosition,oldPlatform,newPosition,newPlatform){
  const before=options(oldPosition,oldPlatform),after=options(newPosition,newPlatform);
  const oldSet=new Set([...before.pillars,...before.goals,...before.banned,...before.resources.time,...before.resources.equipment,...before.resources.materials]);
  const newSet=new Set([...after.pillars,...after.goals,...after.banned,...after.resources.time,...after.resources.equipment,...after.resources.materials]);
  return splitList(values).filter(value=>!oldSet.has(value)||newSet.has(value));
 }
 function saveTarget(current,accounts,name,platform){
  if(!current||current.platform===platform)return current?.id||'';
  return accounts.find(a=>a.id!==current.id&&a.platform===platform&&(a.name===name||(a.aliases||[]).includes(name)))?.id||'';
 }
 return {positions,options,splitList,positionValue,positioningParts,saveTarget,valuesFor,commonBanned};
});
