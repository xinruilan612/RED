"""Lossless removal of identical repeated results for a known prior issue."""
from copy import deepcopy
import json


def repair(value, previous):
    """Keep raw output intact; conflicting, missing and unknown results stay invalid.

    No judgment is inferred: decisions, checks, issues, severity and result values
    are untouched. The caller still runs the complete review validator.
    """
    if not isinstance(value, dict) or not isinstance(value.get('previous_issue_results'), list):
        return value, []
    known = {i.get('issue_id') for i in (previous or {}).get('issues', [])
             if isinstance(i, dict) and isinstance(i.get('issue_id'), str)}
    rows = value['previous_issue_results']
    signatures = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get('issue_id'), str) and row['issue_id'] in known:
            signatures.setdefault(row['issue_id'], set()).add(json.dumps(row, sort_keys=True, ensure_ascii=False))
    seen, kept, repairs = set(), [], []
    for index, row in enumerate(rows):
        issue_id = row.get('issue_id') if isinstance(row, dict) else None
        safe = isinstance(issue_id, str) and issue_id in known and len(signatures[issue_id]) == 1
        if safe and issue_id in seen:
            repairs.append({'rule': 'identical-prior-result@1', 'issue_id': issue_id,
                            'removed_index': index, 'reason': 'identical_duplicate_result'})
            continue
        if safe:
            seen.add(issue_id)
        kept.append(row)
    if not repairs:
        return value, []
    result = deepcopy(value)
    result['previous_issue_results'] = deepcopy(kept)
    return result, repairs
