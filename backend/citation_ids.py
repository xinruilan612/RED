"""Lossless source-ID formatting repair against the current evidence snapshot."""
import copy


def repair(stage, value, sources):
    # Never change quoted wording, infer a source from semantics, or turn a
    # review into approval. Outer whitespace is formatting, not source content.
    field = {'audience': 'observations', 'research': 'facts', 'review': 'claim_map'}.get(stage)
    if not field or not isinstance(value, dict) or not isinstance(value.get(field), list):
        return value, []
    result = copy.deepcopy(value)
    repairs = []
    known = {s['source_id']:s['text'] for s in sources}
    for item in result[field]:
        if not isinstance(item, dict):
            continue
        source, quote = item.get('source_id'), item.get('quote')
        if not isinstance(source, str) or not isinstance(quote, str) or not quote.strip():
            continue
        if source in known:
            if quote not in known[source] and quote.strip() in known[source]:
                item['quote'] = quote.strip()
                repairs.append({'from':quote,'to':quote.strip(),'source_id':source,
                                'reason':'quote_outer_whitespace'})
            continue
        if stage == 'review':
            continue
        # UUID hyphens are occasionally misplaced by the model. All other
        # characters (including the source namespace) must remain identical.
        matches = [s for s in sources if
                   s['source_id'].replace('-', '') == source.replace('-', '')
                   and quote in s['text']]
        if len(matches) == 1:
            target = matches[0]['source_id']
            item['source_id'] = target
            repairs.append({'from': source, 'to': target, 'quote': quote,
                            'reason': 'source_id_hyphen_format'})
    return result, repairs
