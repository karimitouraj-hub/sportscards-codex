"""Evidence-preserving purchase suggestions and bounded cost allocations."""
import re


def match_purchase(identity, purchases):
    fields = [identity.get(k, '').lower().strip() for k in ('player', 'year', 'set', 'number')]
    matches = []
    for line in purchases:
        if line.get('status') in ('cancelled', 'refunded'):
            continue
        title = line['title'].lower()
        score = sum(bool(v) and bool(re.search(r'(?<!\w)' + re.escape(v) + r'(?!\w)', title)) for v in fields)
        if score >= 2:
            matches.append({'purchase_id': line['id'], 'title': line['title'], 'score': score,
                            'status': 'suggested', 'uncertainty': ['Confirm the exact variant and physical copy.']})
    return sorted(matches, key=lambda row: row['score'], reverse=True)


def available(line, allocations, excluding=None):
    used = [a for a in allocations if a['purchase_id'] == line['id'] and a['card_id'] != excluding]
    return {'quantity': line['quantity'] - sum(a['quantity'] for a in used),
            'cents': line['total_cents'] - line['refund_cents'] - sum(a['cost_cents'] for a in used)}
