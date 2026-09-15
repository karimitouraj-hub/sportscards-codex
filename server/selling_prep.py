"""Read-only listing drafts and a package of reviewed, linked card photos."""
import io
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import zipfile

from flask import jsonify, send_file
from PIL import Image

from .analysis import signature

MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_DRAFTS = 100
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
ID = re.compile(r'[a-f0-9]{32}')
SHA256 = re.compile(r'[a-f0-9]{64}')
DEFAULT_PHOTO_GALLERY_URL = None
LOCAL_GALLERY_PATH = re.compile(r'/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?')
SELLER_FIELDS = ('purchase_cost_cents', 'modeled_net_at_bin_cents', 'modeled_profit_at_bin_cents',
                 'modeled_net_at_minimum_offer_cents', 'modeled_profit_at_minimum_offer_cents',
                 'modeled_net_at_starting_bid_cents', 'modeled_profit_at_starting_bid_cents', 'cost_recovery_item_cents')


def _plain(value, limit=20000):
    return value.strip() if isinstance(value, str) and len(value) <= limit else ''


def _notes(value):
    if isinstance(value, str):
        return [_plain(value)] if _plain(value) else []
    return [_plain(item) for item in value if _plain(item)] if isinstance(value, list) else []


def _price(value):
    return value if type(value) is int and 0 <= value <= 100000000 else None


def _photo_gallery_url(value):
    """Keep the gallery on this host, without encoded or traversing paths."""
    value = _plain(value, 512)
    return value if LOCAL_GALLERY_PATH.fullmatch(value) else DEFAULT_PHOTO_GALLERY_URL


def _crop_file(store, observation):
    """Resolve only a stored observation crop within the private crop directory."""
    value = observation.get('crop')
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None
    directory = (store.root / 'crops').resolve()
    path = (store.root / value).resolve()
    if not directory.is_relative_to(store.root.resolve()) or not path.is_relative_to(directory) or path.suffix.lower() not in ('.jpg', '.jpeg', '.png') or not path.is_file():
        return None
    return path


def _digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def _slug(draft):
    title = unicodedata.normalize('NFKD', draft['title']).encode('ascii', 'ignore').decode()
    return re.sub(r'[^A-Za-z0-9]+', '-', title).strip('-')[:90].rstrip('-') or draft['card_id']


def _photo_requirements(path):
    try:
        with Image.open(path) as image:
            if max(image.size) < 500:
                return 'A listing photo must be at least 500 pixels on its longest side.'
        if path.stat().st_size > 12_000_000:
            return 'A listing photo exceeds the 12 MB picture limit.'
    except (OSError, ValueError):
        return 'A listing photo cannot be decoded.'
    return None


def prep_report(store):
    """Return a current validation of a private manifest. Never modify it."""
    path = store.root / 'listing-prep' / 'current.json'
    empty = dict(batch_id=None, created_at=None, drafts=[], summary=dict(drafts=0, ready=0, needs_review=0),
                 package_url='/api/listing-prep/package', photo_gallery_url=DEFAULT_PHOTO_GALLERY_URL, status='empty')
    if not path.exists():
        return empty
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError('The listing draft file is too large.')
    try:
        manifest = json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, OSError) as exc:
        raise ValueError('The listing draft file is unreadable.') from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get('drafts'), list) or len(manifest['drafts']) > MAX_DRAFTS:
        raise ValueError('The listing draft file has an invalid structure.')
    drafts = []
    seen = set()
    with store.connect() as db:
        db.execute('BEGIN')
        for item in manifest['drafts']:
            if not isinstance(item, dict):
                raise ValueError('Each listing draft must be an object.')
            card_id = _plain(item.get('card_id'), 32)
            card = store.get('card', card_id, db) if ID.fullmatch(card_id) else None
            blockers = _notes(item.get('blockers'))
            if not card:
                blockers.append('The collection card is unavailable.')
            if card_id in seen:
                blockers.append('This card appears more than once in this batch.')
            seen.add(card_id)
            title, description, condition = (_plain(item.get(key)) for key in ('title', 'description', 'condition'))
            if not 1 <= len(title) <= 80 or any(ord(character) < 32 for character in title):
                blockers.append('Use a listing title with 1 to 80 characters.')
            if not description:
                blockers.append('The listing description is missing.')
            if not condition:
                blockers.append('The condition description is missing.')
            price, shipping = _price(item.get('price_cents')), _price(item.get('shipping_cents'))
            minimum = _price(item.get('minimum_offer_cents'))
            if price is None or shipping is None:
                blockers.append('The item price and buyer shipping must be nonnegative amounts in cents.')
            if item.get('minimum_offer_cents') is not None and minimum is None:
                blockers.append('The offer guide must be a nonnegative amount in cents.')
            if minimum is not None and price is not None and minimum > price:
                blockers.append('The offer guide exceeds the item price.')
            listing_format = _plain(item.get('listing_format', 'fixed_price'), 40)
            duration = item.get('duration_days')
            reserve, buy_it_now = _price(item.get('reserve_price_cents')), _price(item.get('buy_it_now_price_cents'))
            if listing_format not in ('fixed_price', 'auction'):
                blockers.append('Select fixed_price or auction as the listing format.')
            if listing_format == 'auction':
                if type(duration) is not int or duration not in (1, 3, 5, 7, 10):
                    blockers.append('Select an auction duration of 1, 3, 5, 7, or 10 days.')
                    duration = None
                if price == 0:
                    blockers.append('The auction starting bid must be greater than zero.')
                if item.get('minimum_offer_cents') is not None:
                    blockers.append('Auction drafts do not support a manual offer guide. Set it to null.')
                if item.get('reserve_price_cents') is not None:
                    blockers.append('Auction drafts do not support a reserve price. Set it to null.')
                if item.get('buy_it_now_price_cents') is not None:
                    blockers.append('Auction drafts do not support Buy It Now. Set it to null.')
            else:
                duration = None
            expected_identity = item.get('identity_signature')
            stale = bool(not isinstance(expected_identity, str) or not SHA256.fullmatch(expected_identity) or not card or expected_identity != signature(card))
            if stale:
                blockers.append('The draft identity is missing or no longer matches the card.')
            status = _plain(item.get('status', 'draft'), 40)
            if status not in ('draft', 'ready', 'needs_review'):
                blockers.append('The draft status is invalid.')
            if status != 'ready':
                blockers.append('Mark this draft ready after its review is complete.')
            observation_ids = item.get('photo_observation_ids')
            hashes = item.get('photo_sha256') if isinstance(item.get('photo_sha256'), dict) else {}
            photos = []
            sides = set()
            if not isinstance(observation_ids, list) or len(observation_ids) != 2 or len(set(map(str, observation_ids))) != 2:
                blockers.append('Select one front crop and one back crop.')
                observation_ids = []
            for index, observation_id in enumerate(observation_ids):
                observation = store.get('observation', observation_id, db) if isinstance(observation_id, str) and ID.fullmatch(observation_id) else None
                if not observation or observation.get('card_id') != card_id:
                    blockers.append('A selected photo is not linked to this card.')
                    continue
                if observation.get('status') != 'confirmed':
                    blockers.append('A selected card photo is not confirmed.')
                side = observation.get('side')
                if side != ('front' if index == 0 else 'back'):
                    blockers.append('Photo order must be front, then back, with matching saved sides.')
                photo = store.get('photo', observation.get('photo_id'), db)
                crop = _crop_file(store, observation)
                if not photo or crop is None:
                    blockers.append('A linked photo or its crop file is unavailable.')
                    continue
                if not photo.get('review_complete'):
                    blockers.append('A parent photo still requires review.')
                photo_problem = _photo_requirements(crop)
                if photo_problem:
                    blockers.append(photo_problem)
                expected_hash = hashes.get(observation_id)
                digest = _digest(crop)
                if not isinstance(expected_hash, str) or not SHA256.fullmatch(expected_hash) or digest != expected_hash:
                    blockers.append('A selected crop changed or lacks a reviewed file hash.')
                sides.add(side)
                photos.append(dict(observation_id=observation_id, photo_id=photo['id'], side=side,
                                   sha256=digest,
                                   url=f'/media/crop/{observation_id}',
                                   download_url=f'/api/listing-prep/photos/{card_id}/{observation_id}'))
            if sides != {'front', 'back'}:
                blockers.append('Linked front and back crop files are required.')
            specifics = item.get('specifics')
            if not isinstance(specifics, dict) or len(specifics) > 60 or any(not _plain(key, 120) or not _plain(value, 1000) for key, value in specifics.items()):
                blockers.append('Item specifics must contain valid text fields.')
                specifics = {}
            blockers = list(dict.fromkeys(blockers))
            seller = item.get('seller_analysis') if isinstance(item.get('seller_analysis'), dict) else {}
            seller_analysis = {key: value for key, value in seller.items() if key in SELLER_FIELDS and type(value) is int and abs(value) <= 100000000}
            drafts.append(dict(card_id=card_id, title=title, description=description, specifics=specifics,
                               condition=condition, price_cents=price, minimum_offer_cents=minimum, shipping_cents=shipping,
                               listing_format=listing_format, duration_days=duration,
                               reserve_price_cents=reserve, buy_it_now_price_cents=buy_it_now,
                               pricing_note=_plain(item.get('pricing_note')), review_notes=_notes(item.get('review_notes')),
                               seller_analysis=seller_analysis,
                               identity_signature=expected_identity, identity_stale=stale,
                               photo_sha256={key: value for key, value in hashes.items() if key in observation_ids and isinstance(value, str)},
                               photo_observation_ids=observation_ids, photos=photos, status=status,
                               ready=not blockers, blockers=blockers))
    return dict(batch_id=_plain(manifest.get('batch_id'), 120), created_at=_plain(manifest.get('created_at'), 80),
                drafts=drafts, summary=dict(drafts=len(drafts), ready=sum(item['ready'] for item in drafts),
                                           needs_review=sum(not item['ready'] for item in drafts)),
                package_url='/api/listing-prep/package',
                photo_gallery_url=_photo_gallery_url(manifest.get('photo_gallery_url')), status='prepared')


def _listing_text(draft):
    """Export public listing fields only. Private pricing guidance stays in the app."""
    details = '\n'.join(f'{key}: {value}' for key, value in draft['specifics'].items())
    if draft['listing_format'] == 'auction':
        duration_unit = 'day' if draft['duration_days'] == 1 else 'days'
        pricing = (f"FORMAT\nAuction\n\nDURATION\n{draft['duration_days']} {duration_unit}\n\n"
                   f"STARTING BID\n${draft['price_cents']/100:.2f}\n\nNO RESERVE\n\n")
    else:
        pricing = f"ITEM PRICE\n${draft['price_cents']/100:.2f}\n\n"
    return (f"TITLE\n{draft['title']}\n\nDESCRIPTION\n{draft['description']}\n\n"
            f"CONDITION\n{draft['condition']}\n\nITEM SPECIFICS\n{details}\n\n"
            f"{pricing}BUYER SHIPPING\n${draft['shipping_cents']/100:.2f}\n")


def register_listing_prep(app, store):
    def report_or_error():
        try:
            return prep_report(store), None
        except (OSError, ValueError):
            return None, (jsonify(error='The listing draft file is unavailable. Retry after the batch is prepared.'), 503)

    @app.get('/api/listing-prep')
    def listing_prep():
        report, error = report_or_error()
        return error if error else jsonify(report)

    @app.get('/api/listing-prep/photos/<card_id>/<observation_id>')
    def listing_prep_photo(card_id, observation_id):
        report, error = report_or_error()
        if error:
            return error
        draft = next((item for item in report['drafts'] if item['card_id'] == card_id), None)
        photo = next((item for item in draft['photos'] if item['observation_id'] == observation_id), None) if draft else None
        observation = store.get('observation', observation_id) if photo else None
        path = _crop_file(store, observation) if observation and store.get('card', card_id) and observation.get('card_id') == card_id and observation.get('side') == photo['side'] else None
        if path is None:
            return jsonify(error='This linked listing photo is unavailable.'), 404
        return send_file(path, as_attachment=True, download_name=f"{_slug(draft)}-{photo['side']}{path.suffix.lower()}")

    @app.get('/api/listing-prep/package')
    def listing_prep_package():
        report, error = report_or_error()
        if error:
            return error
        ready = [draft for draft in report['drafts'] if draft['ready']]
        if not ready:
            return jsonify(error='No complete listing drafts are ready to download.'), 409
        files, total_bytes = [], 0
        for index, draft in enumerate(ready, 1):
            folder = f'{index:02d}-{_slug(draft)}'
            card = store.get('card', draft['card_id'])
            if not card or signature(card) != draft['identity_signature']:
                return jsonify(error='A card changed. Refresh the draft before you download it.'), 409
            for photo in draft['photos']:
                observation = store.get('observation', photo['observation_id'])
                parent = store.get('photo', observation.get('photo_id')) if observation else None
                path = _crop_file(store, observation) if observation and observation.get('card_id') == draft['card_id'] and observation.get('side') == photo['side'] and observation.get('status') == 'confirmed' and parent and parent.get('review_complete') else None
                if path is None:
                    return jsonify(error='A listing photo changed. Refresh the draft before you download it.'), 409
                total_bytes += path.stat().st_size
                if total_bytes > MAX_PACKAGE_BYTES:
                    return jsonify(error='The photo package exceeds 200 MB. Download the photos separately.'), 413
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != draft['photo_sha256'][photo['observation_id']]:
                    return jsonify(error='A listing photo changed. Refresh the draft before you download it.'), 409
                files.append((content, f"{folder}/{photo['side']}{path.suffix.lower()}"))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr('README.txt', 'SportsCards listing drafts\n\nEach folder contains listing text and linked front/back card photos.\nThe starting bid or item price is separate from buyer shipping. Review each draft before you publish it.\nThis package does not publish listings or configure offer rules.\nPrivate purchase costs and seller guidance are excluded.\n')
            for index, draft in enumerate(ready, 1):
                package.writestr(f'{index:02d}-{_slug(draft)}/listing.txt', _listing_text(draft))
            for content, name in files:
                package.writestr(name, content)
        stream.seek(0)
        return send_file(stream, mimetype='application/zip', as_attachment=True, download_name='sportscards-listing-drafts.zip')
