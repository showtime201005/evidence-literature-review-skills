"""Host-addressed minimum text spans, never a semantic atomicity claim.

Splitting only at 。；; matches the small source-first experiment without
copying that reports script into runtime. English/compound sentences can stay
whole: reviewers must inspect every factual relationship and qualifier inside
each span, and the complete actual claim remains delivered.
"""


def minimum_claim_units(claims):
    units, seen = [], set()
    for claim in claims:
        cid = claim.get('local_id', claim.get('claim_id'))
        text = claim.get('text')
        if not isinstance(cid, str) or not cid.strip() or cid in seen:
            raise ValueError('Unique nonempty actual claim IDs required')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Actual complete claim text required')
        seen.add(cid)
        start, spans = 0, []
        for end, char in enumerate(text, 1):
            if char in '。；;':
                spans.append((start, end))
                start = end
        if start < len(text):
            if text[start:].strip() or not spans:
                spans.append((start, len(text)))
            else:
                spans[-1] = (spans[-1][0], len(text))
        for begin, end in spans:
            units.append({'minimum_unit_id': 'm' + str(len(units) + 1),
                          'claim_id': cid, 'start_char': begin, 'end_char': end,
                          'text': text[begin:end]})
        if ''.join(u['text'] for u in units if u['claim_id'] == cid) != text:
            raise ValueError('Host minimum-unit spans lost original claim text')
    if not units:
        raise ValueError('At least one actual claim required')
    return units
