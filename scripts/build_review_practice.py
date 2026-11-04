"""Package existing real-model fictional drafts as a clearly limited practice.

No model calls; no invented ratings. The reviewer folder excludes group keys.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from scripts.sprint_evaluation import blind_package

RUBRIC = '''<details open><summary>先看评分标准：每项1-5分，无法判断留空</summary>
<p>先看任务与事实，再读文章。2分介于1和3，4分介于3和5。低分请指出具体原句；不要因为文笔流畅忽略事实问题。开发者自己的评分只能单列自评。</p>
<table border="1" cellpadding="8" style="border-collapse:collapse;font-size:16px"><tr><th>维度</th><th>1分</th><th>3分</th><th>5分</th></tr>
<tr><td>完整性</td><td>遗漏多数核心问题</td><td>回答主要问题，仍漏重要条件</td><td>重要问题基本回答，限制保留</td></tr>
<tr><td>事实</td><td>核心参数冲突或虚构亲历</td><td>主要有依据，仍有个别缺依据推断</td><td>可核查主张有支持，未知表达恰当</td></tr>
<tr><td>逻辑</td><td>前后矛盾、顺序难理解</td><td>能理解，仍有跳跃或重复</td><td>标题与正文一致，论据支持结论</td></tr>
<tr><td>表达</td><td>大量套话、重复或难读</td><td>通顺，仍有模板腔或冗长</td><td>自然清楚，符合目标读者</td></tr>
<tr><td>可用性</td><td>需推翻重写</td><td>修改后可用，仍有明显修改点</td><td>判断只需轻微修改即可使用</td></tr></table>
<p>虚构任务只核对给定资料，不证明现实商品真实性。可用性是判断，不是已实际采用或发布。缺依据与事实冲突分别在评语说明。</p></details>'''

FORM = r'''
<style>
section.scorecard{background:#f4f6f8;border-radius:8px;padding:20px;margin:12px 0 32px}label{display:block;margin:14px 0}select,textarea,button{font:inherit;padding:8px}textarea{width:95%;min-height:90px}button{background:#164b44;color:white;border:0;border-radius:6px;cursor:pointer}small{display:block;color:#4b5563}.sticky{position:sticky;bottom:0;padding:14px;background:#fff;border-top:1px solid #ccc}#saveNotice{font-size:16px;color:#374151}
</style>
<script>
const metrics=[['completeness','内容完整性'],['factuality','事实准确性'],['coherence','逻辑连贯性'],['naturalness','表达自然度'],['usefulness','可用性判断']];
const reviewerId=__REVIEWER__;
const records=[];
document.querySelectorAll('article').forEach(article=>{
 const id=article.querySelector('h2').textContent.trim();
 const box=document.createElement('section');box.className='scorecard';
 const heading=document.createElement('h3');heading.textContent='为 '+id+' 评分';box.append(heading);
 const scores={};
 for(const [key,title] of metrics){const label=document.createElement('label');label.textContent=title+'：';const select=document.createElement('select');select.setAttribute('aria-label',id+' '+title);for(const [value,text] of [['','未评价/无法判断'],['1','1 很差'],['2','2 较差'],['3','3 基本可用'],['4','4 较好'],['5','5 很好']]){const option=document.createElement('option');option.value=value;option.textContent=text;select.append(option)}label.append(select);box.append(label);scores[key]=select;}
 const label=document.createElement('label');label.textContent='请指出具体原句、问题和理由（低分尤其需要）：';const notes=document.createElement('textarea');notes.placeholder='例如：Pxxxx中“……”没有资料支持；或漏掉“包装不含电池”。';label.append(notes);box.append(label);
 const hint=document.createElement('small');hint.textContent='未评价请留空。虚构亲历、把未知当已证实、错参数都应指出原句；不要因为语气流畅就忽略事实。';box.append(hint);
 article.after(box);records.push({id,scores,notes});
});
const footer=document.createElement('div');footer.className='sticky';const button=document.createElement('button');button.textContent='下载我的评分CSV';footer.append(button);const notice=document.createElement('div');notice.id='saveNotice';notice.textContent='本页离线评分，不上传服务器、不调用AI；关闭或刷新前请下载。下载文件后发给实验组织者。';footer.append(notice);document.body.append(footer);
function csvCell(value){const text=String(value);const safe=/^[=+\-@\t\r]/.test(text)?"'"+text:text;return '"'+safe.replaceAll('"','""')+'"'}
button.onclick=()=>{const fields=['reviewer_id','article_id',...metrics.map(x=>x[0]),'notes'];const rows=records.map(r=>[reviewerId,r.id,...metrics.map(([key])=>r.scores[key].value),r.notes.value]);const csv='\uFEFF'+[fields,...rows].map(row=>row.map(csvCell).join(',')).join('\r\n');const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));link.download=reviewerId+'-scores.csv';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),5000);notice.textContent='已请求下载。请确认文件已保存；未填项保持空白，不自动补分。';};
</script>
'''


def build(data, output, reviewers=3):
    result=blind_package(data,output,reviewers=reviewers,groups=('A','B','C','D'))
    output=Path(output)
    for folder in sorted((output/'reviewers').iterdir()):
        page=folder/'articles.html'
        html=page.read_text()
        html=html.replace('<h1>文章评价</h1>', '<h1>文章评审练习</h1><p><strong>这是同一虚构任务的四份真实模型稿，不是完整五组实验。仅用于熟悉评分；不要据此推断获奖分数或算法质量提升。</strong></p>')
        html=html.replace('<article>',RUBRIC+'<article>',1)
        html+=FORM.replace('__REVIEWER__',json.dumps(folder.name))
        page.write_text(html)
        target=output/(folder.name+'-仅评审文件.zip')
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.iterdir()):
                if path.is_file():archive.write(path,arcname=path.name)
        with zipfile.ZipFile(target) as archive:
            assert archive.testzip() is None
            assert not any('mapping' in name or 'private' in name for name in archive.namelist())
    result['scope']='四组不完整批次，仅用于评分练习；开发者自评分开；无真人分数'
    (output/'PRACTICE_STATUS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(build(json.loads(args.input.read_text()),args.output),ensure_ascii=False))


if __name__=='__main__':main()
