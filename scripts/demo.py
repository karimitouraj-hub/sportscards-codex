"""Create an offline synthetic walkthrough in a new, separate data directory."""
import argparse
from contextlib import chdir
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEMO_CONDITION = 'Synthetic example only. No physical condition is claimed.'
CARDS = (
    dict(player='Demo Player One', year='2026', set='Demo Collection', number='DEMO-01',
         variant='Emerald', serial_number='01/99', grade='Raw', condition=DEMO_CONDITION),
    dict(player='Demo Player Two', year='2026', set='Demo Collection', number='DEMO-02',
         variant='Base', serial_number='', grade='Raw', condition=DEMO_CONDITION),
)


def validate_destination(destination):
    """Reject existing storage and paths within the project or a real collection."""
    if destination is None or not str(destination).strip():
        raise ValueError('Specify a new directory with --destination.')
    raw = Path(destination).expanduser()
    target = raw.resolve()
    if raw.exists() or raw.is_symlink() or target.exists():
        raise ValueError('The destination already exists. Select a new directory.')
    protected = [ROOT.resolve(), (Path.home() / '.sportscards').resolve()]
    if os.environ.get('SPORTSCARDS_DATA'):
        protected.append(Path(os.environ['SPORTSCARDS_DATA']).expanduser().resolve())
    if any(target == path or target.is_relative_to(path) for path in protected):
        raise ValueError('Keep demo data outside the repository and real collection directories.')
    if any((parent / 'collection.sqlite3').exists() for parent in target.parents):
        raise ValueError('Do not create demo data inside an existing collection.')
    return target


def demo_image(card, side):
    """Draw fictional card artwork. Do not use external fonts, photos, or logos."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new('RGB', (900, 1200), '#eef2ea')
    draw = ImageDraw.Draw(image)
    large = ImageFont.load_default(size=64)
    medium = ImageFont.load_default(size=40)
    small = ImageFont.load_default(size=30)
    color = '#244c3f' if card['number'] == 'DEMO-01' else '#49466b'
    draw.rounded_rectangle((35, 35, 865, 1165), radius=34, fill=color)
    draw.text((85, 85), 'SYNTHETIC DEMO', font=large, fill='white')
    draw.text((85, 170), 'NOT A REAL CARD', font=medium, fill='#dde6d5')
    draw.text((85, 260), card['player'], font=medium, fill='white')
    draw.text((85, 320), f"{card['year']} / {card['number']}", font=medium, fill='white')
    if side == 'front':
        draw.ellipse((250, 430, 650, 830), fill='#d8b16d')
        draw.polygon(((450, 470), (605, 740), (295, 740)), fill=color)
        draw.text((85, 890), card['variant'], font=medium, fill='white')
        draw.text((85, 950), card['serial_number'] or 'No serial number', font=medium, fill='white')
    else:
        for y, line in zip((460, 525, 590, 700, 765), (
                'Fictitious player and card.', 'Generated on this computer.',
                'No marketplace transaction.', 'Practice the review workflow.',
                'Do not publish this example.')):
            draw.text((85, y), line, font=small, fill='white')
    draw.text((85, 1060), f'{side.upper()} / SYNTHETIC DEMO', font=medium, fill='white')
    output = io.BytesIO()
    image.save(output, 'PNG')
    return output.getvalue()


def request_json(client, method, path, expected=200, **kwargs):
    response = client.open(path, method=method, **kwargs)
    if response.status_code != expected:
        raise RuntimeError(f'{method} {path} failed: {response.status_code} {response.get_json()}')
    return response.get_json()


def seed_photo(app, client, card, side):
    """Use the upload, crop, and review routes with known synthetic geometry."""
    from server.app import process_one

    # The application's decoder subprocess imports server.decoder from the project.
    with chdir(ROOT):
        result = request_json(client, 'POST', '/api/photos', 201, data=demo_image(card, side),
                              headers={'X-Filename': f"synthetic-{card['number']}-{side}.png",
                                       'Content-Type': 'application/octet-stream'})
    photo = result['photo']
    process_one(app.store)
    state = request_json(client, 'GET', '/api/state')
    job = next(item for item in state['jobs'] if item['photo_id'] == photo['id'])
    if job['state'] != 'done':
        raise RuntimeError('The synthetic photo did not finish local processing.')
    proposals = [item for item in state['observations'] if item['photo_id'] == photo['id']]
    # Ignore detector rectangles. The generator knows the full fictional card boundary.
    for proposal in proposals:
        request_json(client, 'PATCH', '/api/observations/' + proposal['id'],
                     json={'status': 'ignored', 'review_note': 'Synthetic fixture: use the complete generated image.'})
    observation = request_json(client, 'POST', '/api/observations', 201,
                               json={'photo_id': photo['id'], 'bbox': [0, 0, 1, 1], 'rotation': 0})
    return photo, observation


def generate(destination):
    """Return a verified demo summary. Never overwrite an existing destination."""
    target = validate_destination(destination)
    from server.app import create_app
    from server.analysis import DEFAULT_COSTS, break_even, proceeds
    from server.mcp_drafts import save_draft

    target.mkdir(parents=True, exist_ok=False, mode=0o700)
    (target / 'SYNTHETIC-DEMO.txt').write_text(
        'SYNTHETIC DEMO ONLY\nAll cards, images, purchases, prices, and evidence are fictitious.\n'
        'Do not publish these listing drafts. No network request was made.\n', encoding='utf-8')
    app = create_app(target)
    client = app.test_client()
    client.environ_base['HTTP_X_SPORTSCARDS_TOKEN'] = client.get('/api/state').json['token']
    created = []
    selected_photos = {}
    for identity in CARDS:
        front_photo, front = seed_photo(app, client, identity, 'front')
        card = request_json(client, 'POST', '/api/cards', 201,
                            json={**identity, 'observation_id': front['id'], 'side': 'front',
                                  'notes': 'SYNTHETIC DEMO. Fictitious identity, artwork, and amounts.',
                                  'evidence_state': 'user_confirmed'})
        back_photo, back = seed_photo(app, client, identity, 'back')
        request_json(client, 'POST', f"/api/cards/{card['id']}/link",
                     json={'observation_id': back['id'], 'side': 'back'})
        for photo in (front_photo, back_photo):
            request_json(client, 'POST', f"/api/photos/{photo['id']}/review")
        created.append(card)
        selected_photos[card['id']] = [front['id'], back['id']]

    priced, unknown = created
    purchase = request_json(client, 'POST', '/api/purchases', 201, json={
        'title': 'SYNTHETIC DEMO purchase: Demo Player One', 'source_ref': 'SYNTHETIC-DEMO-ORDER-001',
        'account': 'SYNTHETIC DEMO', 'quantity': 1, 'total_cents': 1600,
        'cost_basis': 'Fictitious single-card purchase for the local walkthrough.'})
    request_json(client, 'POST', f"/api/cards/{priced['id']}/allocation", json={
        'purchase_id': purchase['id'], 'cost_cents': 1600,
        'basis': 'SYNTHETIC DEMO. Allocate the complete fictitious single-card purchase.'})
    today = dt.datetime.now(dt.timezone.utc).date()
    for index, price in enumerate((2500, 2700, 2900), 1):
        request_json(client, 'POST', f"/api/cards/{priced['id']}/comparables", 201, json={
            **CARDS[0], 'status': 'sold', 'match_reviewed': True, 'price_status': 'known',
            'price_cents': price, 'shipping_cents': 500, 'shipping_known': True, 'currency': 'USD',
            'sold_date': (today - dt.timedelta(days=index)).isoformat(),
            'source_url': f'https://example.com/synthetic-demo/sale-{index}',
            'source_title': f'SYNTHETIC DEMO sold example {index}',
            'match_note': 'Fictitious exact-match evidence. No sale or network lookup occurred.'})
    request_json(client, 'POST', f"/api/cards/{priced['id']}/listings", 201, json={
        'revision': priced['revision'], 'match_reviewed': True, 'ask_cents': 4500,
        'shipping_cents': 500, 'shipping_known': True, 'currency': 'USD', 'status': 'active',
        'source_url': 'https://example.com/synthetic-demo/active-ask',
        'source_title': 'SYNTHETIC DEMO asking example', 'seller': 'SYNTHETIC DEMO SELLER',
        'physical_copy_key': 'SYNTHETIC-DEMO-ASK-002', 'buying_format': 'fixed_price',
        'evidence_state': 'user_entered', 'notes': 'Fictitious asking evidence. This is not a completed sale.'})
    request_json(client, 'PUT', f"/api/cards/{unknown['id']}/listing-research", json={
        'revision': unknown['revision'], 'query': 'SYNTHETIC DEMO: missing evidence example',
        'url': 'https://example.com/synthetic-demo/unknown',
        'limitations': 'No price or purchase cost is supplied for this fictitious card. Unknown does not mean zero.'})
    run = request_json(client, 'POST', '/api/pricing-engine/simulate', 201,
                       json={'seed': 42, 'trials': 10000, 'horizon_days': 90, 'strategy': 'individual'})
    costs = dict(DEFAULT_COSTS)
    net = proceeds(3900, costs)
    draft = save_draft(app.store, priced['id'], {
        'card_revision': priced['revision'], 'title': 'SYNTHETIC DEMO - Demo Player One Emerald 01/99',
        'description': 'SYNTHETIC DEMO ONLY. This fictitious card demonstrates a local listing draft. '
                       'The artwork and prices are generated examples. Do not publish this draft.',
        'condition': DEMO_CONDITION, 'condition_confirmed': True,
        'condition_source': 'Synthetic fixture author. This is not an owner statement about a real card.',
        'terms_confirmed': True, 'photos_reviewed': True,
        'specifics': {'Player': 'Demo Player One', 'Set': 'Demo Collection', 'Card Number': 'DEMO-01'},
        'listing_format': 'fixed_price', 'duration_days': None, 'price_cents': 3400,
        'shipping_cents': 500, 'minimum_offer_cents': 2500, 'reserve_price_cents': None,
        'buy_it_now_price_cents': None, 'photo_observation_ids': selected_photos[priced['id']],
        'status': 'ready', 'pricing_note': 'Synthetic asking price. This is not a market recommendation.',
        'review_notes': ['SYNTHETIC DEMO. Do not publish. No real condition or marketplace claim.'],
        'seller_analysis': {'purchase_cost_cents': 1600, 'modeled_net_at_bin_cents': net,
                            'modeled_profit_at_bin_cents': net - 1600,
                            'cost_recovery_item_cents': max(0, break_even(1600, costs) - 500)},
    }, None)
    if draft['summary']['ready'] != 1:
        raise RuntimeError('The synthetic listing draft did not pass validation.')
    state = request_json(client, 'GET', '/api/state')
    report = request_json(client, 'GET', '/api/pricing-engine')
    summary = {
        'synthetic': True, 'destination': str(target),
        'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'counts': {key: len(state[key]) for key in ('photos', 'observations', 'cards', 'purchases',
                                                    'allocations', 'comparables', 'listings')},
        'confirmed_observations': sum(item['status'] == 'confirmed' for item in state['observations']),
        'card_ids': {card['player']: card['id'] for card in created},
        'draft_card_id': priced['id'], 'simulation_run_id': run['id'],
        'pricing_summary': report['summary'], 'listing_summary': draft['summary'],
        'notes': ['All identities, images, prices, and evidence are fictitious.',
                  'Sold evidence stays separate from active asks. The second card remains unpriced.',
                  'The simulation is an uncalibrated scenario. No network request or publication occurred.',
                  'Detector proposals can vary by platform. Four manual full-image crops are confirmed.'],
    }
    (target / 'demo-summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True,
                        help='New directory outside the repository and your real collection.')
    args = parser.parse_args(argv)
    try:
        summary = generate(args.destination)
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(1, f'Demo generation failed: {error}\n')
    print(json.dumps(summary, indent=2))
    print('\nStart the synthetic dashboard from the project directory:')
    print(f'python scripts/start.py --data-dir "{summary["destination"]}" --port 8099')
    print('Open http://127.0.0.1:8099. Do not publish the synthetic draft.')
    return summary


if __name__ == '__main__':
    main()
