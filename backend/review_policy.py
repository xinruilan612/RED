"""Apply existing non-blocking severity policy without changing model evidence."""
from copy import deepcopy

from backend.contracts import CONTRACT
from backend.review_grounding import located
from backend.workflow import validate_review


def reconcile_optional_review(report, draft, gates, previous=None):
    """Return an audited copy; a minor preference alone cannot demand a rewrite.

    This uses the existing approval gates, including disclosed unknown
    originality risk; it does not lower the approval threshold. It never
    infers resolution from natural-language suggestions or changes issue states.
    Callers retain the original model response and enforce permissions/versions.
    """
    validate_review(report, draft, gates, previous)
    result = deepcopy(report)
    if report['decision'] != 'revision_required':
        return result
    if report.get('human_questions') or report.get('unlocated_issues'):
        return result
    policy = CONTRACT['review_policy']
    checks = {c['name']: c['result'] for c in report['checks']}
    if any(checks[name] != 'pass' for name in policy['required_pass']):
        return result
    if checks['originality_risk'] != 'pass' and not (checks['originality_risk'] == 'unknown'
            and isinstance(report.get('limitations'), list)
            and any(isinstance(item, str) and item.strip() for item in report['limitations'])):
        return result
    blocking = policy['blocking_severities']
    if any(i['state'] == 'open' and (i['severity'] in blocking or not located(i, draft['content']))
           for i in report['issues']):
        return result
    important = {i['issue_id'] for i in (previous or {}).get('issues', []) if i['severity'] in blocking}
    if any(i['result'] != 'resolved' for i in report.get('previous_issue_results', []) if i['issue_id'] in important):
        return result
    result.update(decision='approved', next_action='await_user_confirmation')
    result['decision_adjustment'] = {
        'policy': 'optional-minor-review@1',
        'original_decision': report['decision'],
        'original_next_action': report['next_action'],
        'reason': '必需审核检查通过，且无未解决的重要问题或补料问题；轻微建议保留为可选优化，不强制返修。原创性未知时仍保留其限制说明。',
        'optional_issue_ids': [i['issue_id'] for i in report['issues'] if i['state'] == 'open'],
    }
    validate_review(result, draft, gates, previous)
    return result
