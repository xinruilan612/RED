"""Keep unsupported review quotations out of copy-edit instructions."""
import copy


def located(issue, content):
    field=content.get(issue.get('location'))
    excerpt=issue.get('excerpt')
    if isinstance(field,list):
        return isinstance(excerpt,str) and bool(excerpt.strip()) and any(excerpt in tag for tag in field)
    return isinstance(field,str) and isinstance(excerpt,str) and bool(excerpt.strip()) and excerpt in field


def project_previous(report, content, stage):
    if not report:return None
    # content is the draft this report reviewed, not the newly revised draft.
    # Missing legacy version references cannot establish a location failure.
    result={k:copy.deepcopy(v) for k,v in report.items() if k in ('decision','issues','limitations','human_questions')}
    if 'limitations' in result:
        # System-added disclaimers accumulate on recovery; one exact copy
        # retains every constraint without repeating the same paragraph.
        result['limitations']=list(dict.fromkeys(result['limitations']))
    quarantined={i['issue_id']:i for i in report.get('unlocated_issues',[])}
    # Older reports did not validate excerpt locations. Do not silently assume
    # missing locations in those stored reports describe the current copy.
    unlocated=[copy.deepcopy(quarantined.get(i.get('issue_id'),i)) for i in result.get('issues',[]) if i.get('issue_id') in quarantined or
               (content is not None and 'location' in i and 'excerpt' in i and not located(i,content))]
    if unlocated:
        ids={i['issue_id'] for i in unlocated}
        result['issues']=[i for i in result['issues'] if i['issue_id'] not in ids]
        result['issues_requiring_recheck']=[{
            'issue_id':i['issue_id'],'reason':i.get('reason',''),
            'previous_excerpt':i.get('excerpt',''),'previous_location':i.get('location',''),
            'status':'原审核引文未定位到被审核版本；不是已证实的稿件问题，需审核者重新核对。'
        } for i in unlocated]
        if stage=='revise':
            # The writer must not invent a missing sentence just to "fix" it.
            result['issues_requiring_recheck']=[{'issue_id':i['issue_id'],'status':i['status']}
                                                for i in result['issues_requiring_recheck']]
    return result


def annotate(report, content):
    missing=[copy.deepcopy(i) for i in report['issues'] if i.get('state')=='open' and not located(i,content)]
    if not missing:return report
    result=copy.deepcopy(report)
    result['unlocated_issues']=missing
    ids={i['issue_id'] for i in missing}
    for issue in result['issues']:
        if issue['issue_id'] in ids:
            issue.update(location='body',excerpt=content['body'][:80],severity='major',state='open',
                reason='审核意见的引文未在指定稿件位置找到，不能据此认定文案有错。',
                suggestion='请审核者针对当前稿件重新核对该问题；不要要求作者修改不存在的句子，也不能自动认定问题已解决。')
    for check in result['checks']:
        if check.get('name')=='evidence_integrity':
            check.update(result='fail',basis='审核问题的引文未能定位到当前稿件，须重新核对。')
    if result.get('decision')!='needs_human':
        result.update(decision='revision_required',next_action='revise')
    result['limitations'].append('未定位的审核意见已隔离并保留原始响应；未据此改稿、认定解决或判定通过。')
    return result
