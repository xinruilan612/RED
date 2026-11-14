"""Lossless source-ID and quote-span repair against the current evidence snapshot.

The model is told to quote verbatim, but with dense pages (spec tables, official
product pages) it regularly:
  * copies a span with different whitespace/newlines or full-width punctuation,
  * changes one or two non-numeric characters while "quoting" (家中 / 家里),
  * concatenates several non-adjacent fragments into one quote,
  * or produces a phrase that is not in the source at all.

None of those should kill the run. This module repairs the first three *without
changing the wording*: it locates the real source span and stores the source's
own characters, and records why. Number and Latin model/unit tokens must match
exactly, so a rewritten figure can never be repaired into a citation. The last
case is reported; with ``drop_unmatched=True`` the caller drops just that item
and records a visible gap instead of failing the whole stage. It never infers a
source from meaning and never turns a review into an approval.
"""
import copy
import re
import unicodedata
from difflib import SequenceMatcher

_WHITESPACE = re.compile(r'\s+')
# Only line breaks. Sentence/punctuation boundaries overlap with the audience
# ellipsis expansion and with legitimate multi-clause quotes, so they are not
# split points; page-derived concatenations are line based in practice.
_BREAKS = re.compile(r'[\n\r]+')
_ZERO_WIDTH = dict.fromkeys(map(ord, '\u200b\u200c\u200d\ufeff'), None)
_QUOTES = str.maketrans({'“': '"', '”': '"', '‘': "'", '’': "'",
                         '「': '"', '」': '"', '『': '"', '』': '"'})
_DIGITS = re.compile(r'\d+')
_WORDS = re.compile(r'[A-Za-z][A-Za-z0-9]*')


def _fold(text):
    """NFKC + quote/space-free skeleton, with each kept char's source index."""
    out = []
    index = []
    for position, char in enumerate(text):
        if char.isspace():
            continue
        char = char.translate(_QUOTES).translate(_ZERO_WIDTH)
        if not char:
            continue
        for folded in unicodedata.normalize('NFKC', char):
            out.append(folded)
            index.append(position)
    return ''.join(out), index


def _squash(text):
    """Whitespace-free text (kept for callers of the original helper)."""
    return _fold(text)


def _signature(text):
    """Numbers and Latin words that must survive any repair unchanged."""
    return _DIGITS.findall(text), [word.lower() for word in _WORDS.findall(text)]


def locate(quote, source):
    """Return the exact source substring matching ``quote``, or None.

    First tries a literal match, then a whitespace/width/quotation-mark
    insensitive one. The returned value is always sliced from ``source`` itself,
    so stored quotes stay verbatim.
    """
    if not isinstance(quote, str) or not isinstance(source, str):
        return None
    if quote and quote in source:
        return quote
    stripped = quote.strip()
    if stripped and stripped in source:
        return stripped
    folded_source, index = _fold(source)
    folded_quote, _ = _fold(quote)
    if not folded_quote:
        return None
    position = folded_source.find(folded_quote)
    if position < 0:
        return None
    start = index[position]
    end = index[position + len(folded_quote) - 1]
    return source[start:end + 1]


def locate_near(quote, source, threshold=0.92):
    """Locate a span the model copied with a few non-numeric character changes.

    Numbers and Latin model/unit names in the quote must match the located span
    exactly; the remaining characters must still be similar enough for the span
    to be the obvious original. Returns ``(source_span, similarity)`` or None.
    """
    if not isinstance(quote, str) or not isinstance(source, str):
        return None
    folded_source, index = _fold(source)
    folded_quote, _ = _fold(quote)
    if len(folded_quote) < 12 or len(folded_source) < len(folded_quote):
        return None
    match = SequenceMatcher(None, folded_source, folded_quote,
                            autojunk=False).find_longest_match(
        0, len(folded_source), 0, len(folded_quote))
    if match.size < max(6, int(0.4 * len(folded_quote))):
        return None
    start = min(max(match.a - match.b, 0), len(folded_source) - len(folded_quote))
    window = folded_source[start:start + len(folded_quote)]
    if _signature(window) != _signature(folded_quote):
        return None
    similarity = SequenceMatcher(None, window, folded_quote, autojunk=False).ratio()
    if similarity < threshold:
        return None
    first, last = index[start], index[start + len(folded_quote) - 1]
    return source[first:last + 1], similarity


def fragments(quote):
    """Split a model-concatenated quote into candidate contiguous fragments."""
    parts = [part.strip() for part in _BREAKS.split(str(quote))]
    return [part for part in parts if part]


def repair(stage, value, sources, split=None, drop_unmatched=False):
    field = {'audience': 'observations', 'research': 'facts', 'review': 'claim_map'}.get(stage)
    if not field or not isinstance(value, dict) or not isinstance(value.get(field), list):
        return value, []
    # Splitting a concatenated quote must only happen where the caller has already
    # finished its own joining logic (audience expands ellipses first; research does
    # not). Default: research only.
    allow_split = (stage == 'research') if split is None else bool(split)
    result = copy.deepcopy(value)
    repairs = []
    known = {s['source_id']: s['text'] for s in sources}
    kept = []
    for item in result[field]:
        if not isinstance(item, dict):
            kept.append(item)
            continue
        source, quote = item.get('source_id'), item.get('quote')
        if not isinstance(source, str) or not isinstance(quote, str) or not quote.strip():
            kept.append(item)
            continue
        if source not in known:
            # UUID hyphens are occasionally misplaced by the model. All other
            # characters (including the source namespace) must remain identical.
            if stage != 'review':
                matches = [s for s in sources if
                           s['source_id'].replace('-', '') == source.replace('-', '')
                           and locate(quote, s['text'])]
                if len(matches) == 1:
                    target = matches[0]['source_id']
                    item['source_id'] = target
                    item['quote'] = locate(quote, matches[0]['text'])
                    repairs.append({'from': source, 'to': target, 'quote': item['quote'],
                                    'reason': 'source_id_hyphen_format'})
                    kept.append(item)
                    continue
            if drop_unmatched and stage != 'review':
                repairs.append({'source_id': source, 'reason': 'quote_source_unknown_dropped',
                                'from': quote[:160]})
                continue
            kept.append(item)
            continue
        body = known[source]
        if quote in body:
            kept.append(item)
            continue
        # Outer whitespace is formatting, not wording: trim it for every stage.
        if quote.strip() in body:
            item['quote'] = quote.strip()
            repairs.append({'source_id': source, 'reason': 'quote_outer_whitespace',
                            'from': quote[:120], 'to': item['quote'][:120]})
            kept.append(item)
            continue
        span = locate(quote, body)
        if stage == 'review':
            # Review keeps the model's wording literally; only layout (spaces,
            # line breaks, full-width forms, quotation marks) may be normalized
            # to the source's own span. Wording or number changes stay rejected.
            if span:
                item['quote'] = span
                repairs.append({'source_id': source, 'reason': 'quote_layout_normalized',
                                'from': quote[:120], 'to': span[:120]})
            else:
                near = locate_near(quote, body)
                if near:
                    item['quote'] = near[0]
                    repairs.append({'source_id': source, 'reason': 'quote_near_match',
                                    'similarity': round(near[1], 3),
                                    'from': quote[:120], 'to': near[0][:120]})
                elif drop_unmatched:
                    repairs.append({'source_id': source, 'reason': 'quote_unverifiable_dropped',
                                    'from': quote[:160]})
                    continue
            kept.append(item)
            continue
        if span:
            item['quote'] = span
            reason = 'quote_outer_whitespace' if quote.strip() in body else 'quote_whitespace_normalized'
            repairs.append({'source_id': source, 'reason': reason,
                            'from': quote[:120], 'to': span[:120]})
            kept.append(item)
            continue
        # Near copy: the model changed a few non-numeric characters while
        # "quoting". The stored quote becomes the source's own characters, and
        # numbers/Latin tokens must already match, so a wrong figure can never
        # pass through here.
        near = locate_near(quote, body)
        if near:
            span, similarity = near
            item['quote'] = span
            repairs.append({'source_id': source, 'reason': 'quote_near_match',
                            'similarity': round(similarity, 3),
                            'from': quote[:120], 'to': span[:120]})
            kept.append(item)
            continue
        # Reordered table rows: every line is verbatim, only the order changed.
        # Each line becomes its own verified item; never reorder the source itself.
        parts=re.split(r'\r?\n|[｜|]',quote)
        parts=[part.strip() for part in parts if part.strip()]
        lines=set(body.splitlines())
        if len(parts)>1 and all(len(part)>=4 and part in lines for part in parts):
            for part in parts:kept.append({**item,'quote':part})
            repairs.append({'source_id':source,'reason':'quote_lines_reordered_split',
                            'lines':len(parts),'from':quote[:120]})
            continue
        if not allow_split:
            if drop_unmatched:
                repairs.append({'source_id': source, 'reason': 'quote_unverifiable_dropped',
                                'from': quote[:160]})
                continue
            kept.append(item)
            continue
        parts = fragments(quote)
        spans = [(part, locate(part, body)) for part in parts]
        spans = [(part, span) for part, span in spans if span]
        if len(spans) > 1:
            # One concatenated quote becomes one item per verified contiguous span.
            for part, span in spans:
                # Carry every other field (e.g. audience interpretation) onto each
                # verified fragment, so splitting never loses the analysis.
                kept.append({**item, 'quote': span})
            repairs.append({'source_id': source, 'reason': 'quote_split_into_fragments',
                            'fragments': len(spans), 'unmatched': len(parts) - len(spans),
                            'from': quote[:120]})
            continue
        if len(spans) == 1:
            item['quote'] = spans[0][1]
            repairs.append({'source_id': source, 'reason': 'quote_reduced_to_matching_fragment',
                            'from': quote[:120], 'to': spans[0][1][:120]})
            kept.append(item)
            continue
        if drop_unmatched:
            repairs.append({'source_id': source, 'reason': 'quote_unverifiable_dropped',
                            'from': quote[:160]})
            continue
        # Cannot be repaired losslessly. Keep the model's text untouched so the
        # strict verifier still rejects it; removing it would let unverifiable
        # evidence pass silently, and rewriting it would invent a citation.
        kept.append(item)
    result[field] = kept
    return result, repairs
