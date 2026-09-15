"""SportsCards local application. Run with python -m server.app."""
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory, Response
from werkzeug.exceptions import HTTPException
from PIL import Image, ImageOps
import pillow_heif

pillow_heif.register_heif_opener()

from .store import Store, now, uid
from .recognition import detect, identify, VERSION
from .purchases import match_purchase, available
from .valuation import value_card, IDENTITY_FIELDS
from .analysis import analyse_card, portfolio, signature, DEFAULT_COSTS, CATEGORIES, normalize_costs
from .pricing_api import register_pricing_api
from .selling_prep import register_listing_prep

MAX_BYTES = 40 * 1024**2
MAX_PHOTOS_PER_BATCH = 20
MAX_OBSERVATIONS = 250


class Invalid(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def text(value, maximum=250):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise Invalid('Use valid text within the field limit.')
    return value.strip()


def integer(value, minimum=0, maximum=100_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Invalid('Use a whole number within the field limit.')
    return value


def choice(value, choices):
    if value not in choices:
        raise Invalid('Select a valid option.')
    return value


def bbox(value):
    if not isinstance(value, list) or len(value) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise Invalid('Use four finite crop coordinates.')
    x, y, w, h = value
    if min(x, y) < 0 or min(w, h) < .005 or x+w > 1.000001 or y+h > 1.000001:
        raise Invalid('Keep the crop inside the photo.')
    return [round(v, 6) for v in value]


def source_url(value):
    value = text(value, 2000)
    parsed = urlparse(value)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise Invalid('Enter a complete HTTP or HTTPS source URL.')
    return value


def identity(data):
    return {k: text(data.get(k, '')) for k in IDENTITY_FIELDS}


def make_crop(store, photo, id, box, rotation=0):
    with Image.open(store.root / photo['original']) as original:
        im = ImageOps.exif_transpose(original).convert('RGB')
        x, y, w, h = box
        crop = im.crop((int(x*im.width), int(y*im.height), round((x+w)*im.width), round((y+h)*im.height)))
        crop = crop.rotate(rotation, expand=True)
        crop.thumbnail((2000, 2000))
        crop.save(store.root / 'crops' / f'{id}.jpg', 'JPEG', quality=95)
    return f'crops/{id}.jpg'


def process_one(store):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        job = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
        if not job:
            return False
        db.execute("UPDATE jobs SET state='processing',attempts=attempts+1,error=NULL WHERE id=?", (job['id'],))
        photo = store.get('photo', job['photo_id'], db)
    started = time.monotonic()
    try:
        result = detect(store.root / photo['preview'])
        proposals = []
        for box in result['cards'][:max(0, MAX_OBSERVATIONS-len(store.all('observation')))]:
            id = uid()
            crop = make_crop(store, photo, id, box)
            proposals.append({'id': id, 'photo_id': photo['id'], 'bbox': box,
                              'crop': crop, 'side': 'unknown', 'status': 'needs_review',
                              'card_id': None, 'created_at': now(), 'method': VERSION,
                              'identity_proposal': identify(store.root / crop)})
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            total = len(store.all('observation', db))
            for observation in proposals[:max(0, MAX_OBSERVATIONS-total)]:
                store.put('observation', observation, db)
            photo.update(processed_at=now(), detection=result, review_complete=False)
            store.put('photo', photo, db)
            db.execute("UPDATE jobs SET state='done',duration_ms=? WHERE id=?", (round((time.monotonic()-started)*1000), job['id']))
    except Exception:
        with store.connect() as db:
            db.execute("UPDATE jobs SET state='failed',error=? WHERE id=?", ('Processing failed. Retry this photo.', job['id']))
    return True


def recover(store):
    with store.connect() as db:
        db.execute("UPDATE jobs SET state='queued',error=NULL WHERE state='processing'")


def create_app(root=None, worker=False):
    app = Flask(__name__, static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = MAX_BYTES
    store = Store(root or os.environ.get('SPORTSCARDS_DATA', str(Path.home() / '.sportscards')))
    app.store = store
    dist = Path(__file__).resolve().parents[1] / 'dist'
    allowed_hosts = {'127.0.0.1', 'localhost'}
    allowed_hosts.update(host.strip() for host in os.environ.get('SPORTSCARDS_ALLOWED_HOSTS', '').split(',') if host.strip())
    token_path = store.root / 'session-token'
    if not token_path.exists():
        token_path.write_text(uid()+uid())
        token_path.chmod(0o600)
    token = token_path.read_text().strip()
    upload_diagnostic_lock = threading.Lock()

    def capture_failed_upload(staged, digest, filename, diagnostic):
        """Keep at most three rejected originals during an explicit diagnostic session."""
        if os.environ.get('SPORTSCARDS_UPLOAD_DIAGNOSTICS') != '1':
            return None
        diagnostic_id = digest[:12]
        try:
            with upload_diagnostic_lock:
                directory = store.root / 'failed-uploads'
                directory.mkdir(exist_ok=True, mode=0o700)
                original = directory / (digest + '.bin')
                if not original.exists() and len(list(directory.glob('*.bin'))) >= 3:
                    app.logger.warning('Photo decode failed: %s; diagnostic sample limit reached.', diagnostic_id)
                    return diagnostic_id
                if not original.exists():
                    os.replace(staged, original)
                    original.chmod(0o600)
                report = dict(id=diagnostic_id, sha256=digest, filename=filename,
                              bytes=original.stat().st_size, captured_at=now(), **diagnostic)
                sidecar = directory / (digest + '.json')
                sidecar.write_text(json.dumps(report, indent=2))
                sidecar.chmod(0o600)
                app.logger.warning('Photo decode failed: %s; private diagnostic captured.', diagnostic_id)
        except OSError:
            app.logger.warning('Photo decode failed: %s; diagnostic capture unavailable.', diagnostic_id)
        return diagnostic_id

    @app.before_request
    def protect():
        if request.host.split(':')[0] not in allowed_hosts:
            raise Invalid('This host is not allowed.', 403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                raise Invalid('This request came from another site.', 403)
            if request.headers.get('X-SportsCards-Token') != token:
                raise Invalid('Refresh the page before you retry.', 403)

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['Cache-Control'] = 'no-store' if request.path.startswith(('/api', '/media')) else 'no-cache'
        return response

    @app.errorhandler(Invalid)
    def invalid(error):
        return jsonify(error=error.message), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error='The file exceeds 40 MB.' if error.code == 413 else error.description), error.code

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.error('Request failed: %s', type(error).__name__)
        return jsonify(error='The server could not finish this request.'), 500

    def body():
        data = request.get_json()
        if not isinstance(data, dict):
            raise Invalid('Send a JSON object.')
        return data

    def get(kind, id, db=None):
        record = store.get(kind, id, db)
        if not record:
            raise Invalid('This record is unavailable.', 404)
        return record

    @app.get('/api/health')
    def health():
        return jsonify(status='ok', version='1.0.0', recognition='Local rectangle proposals and OCR; manual identity review',
                       ebay='Read-only browser evidence import; automatic synchronization not enabled', limits={'photos_per_batch': MAX_PHOTOS_PER_BATCH, 'observations': MAX_OBSERVATIONS, 'file_bytes': MAX_BYTES})

    @app.get('/api/state')
    def state():
        with store.connect() as db:
            data = {k+'s': store.all(k, db) for k in ('photo', 'observation', 'card', 'purchase', 'comparable', 'allocation', 'listing')}
            data['jobs'] = [dict(r) for r in db.execute('SELECT * FROM jobs')]
        data['token'] = token
        return jsonify(data)

    def analysis_costs(db):
        saved = store.get('settings', 'analysis-settings', db)
        return normalize_costs(saved['costs'] if saved else DEFAULT_COSTS)

    @app.get('/api/portfolio')
    def portfolio_analysis():
        with store.connect() as db:
            return jsonify(portfolio(store.all('card', db), store.all('comparable', db),
                                     store.all('allocation', db), analysis_costs(db)))

    @app.patch('/api/analysis-settings')
    def update_analysis_settings():
        data = body()
        costs = dict(DEFAULT_COSTS)
        for key in ('percent', 'tax_percent'):
            value = data.get(key, costs[key])
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 50:
                raise Invalid('Use a percentage between 0 and 50.')
            costs[key] = value
        for key in ('shipping_cents', 'packaging_cents'):
            costs[key] = integer(data.get(key, costs[key]), 0, 100000)
        costs = normalize_costs(costs)
        with store.connect() as db:
            store.put('settings', dict(id='analysis-settings', costs=costs, updated_at=now()), db)
            store.audit(db, 'analysis_costs_changed', 'analysis-settings', costs)
        return jsonify(costs)

    @app.put('/api/cards/<id>/research')
    def save_research(id):
        data = body()
        record = {key: text(data.get(key, ''), 2000 if key in ('reason', 'limitations') else 500)
                  for key in ('reason', 'horizon', 'trigger', 'limitations', 'query', 'searched_at')}
        record['category'] = choice(data.get('category', 'needs_evidence'), CATEGORIES)
        sources = data.get('sources', [])
        if not isinstance(sources, list) or len(sources) > 20:
            raise Invalid('Use at most 20 research source links.')
        record['sources'] = [dict(url=source_url(s.get('url', '')), label=text(s.get('label', ''), 250)) for s in sources if isinstance(s, dict)]
        with store.connect() as db:
            card = get('card', id, db)
            if data.get('revision') != card['revision']:
                raise Invalid('This card changed. Refresh before you save.', 409)
            record.update(identity_signature=signature(card), reviewed_at=now(), evidence_state='assisted_review')
            card['research'] = record
            store.put('card', card, db)
            store.audit(db, 'research_reviewed', id, record)
        return jsonify(record)

    @app.post('/api/photos')
    def upload():
        name = text(request.headers.get('X-Filename', 'photo'), 500)
        if not request.content_length or request.content_length > MAX_BYTES:
            raise Invalid('Select a complete photo under 40 MB.', 413)
        id = uid()
        staged = store.root / 'staging' / id
        preview = store.root / 'previews' / f'{id}.jpg'
        sha = hashlib.sha256()
        count = 0
        try:
            with staged.open('xb') as out:
                while chunk := request.stream.read(1024*1024):
                    count += len(chunk)
                    if count > MAX_BYTES:
                        raise Invalid('The photo exceeds 40 MB.', 413)
                    sha.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if count != request.content_length:
                raise Invalid('The upload was interrupted. Select the photo again.')
            digest = sha.hexdigest()
            with store.connect() as db:
                old = db.execute('SELECT photo_id FROM hashes WHERE sha=?', (digest,)).fetchone()
                if old:
                    return jsonify(status='duplicate', photo=get('photo', old[0], db))
            run = subprocess.run([sys.executable, '-m', 'server.decoder', str(staged), str(preview)],
                                 capture_output=True, text=True, timeout=35)
            if run.returncode:
                diagnostic_id = capture_failed_upload(staged, digest, name,
                    dict(returncode=run.returncode, stdout=run.stdout[:8000], stderr=run.stderr[:8000]))
                message = 'The decoder could not read this photo.'
                if diagnostic_id:
                    message += f' Diagnostic ID: {diagnostic_id}.'
                raise Invalid(message, 422)
            metadata = json.loads(run.stdout)
            with store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT photo_id FROM hashes WHERE sha=?', (digest,)).fetchone()
                if old:
                    preview.unlink(missing_ok=True)
                    return jsonify(status='duplicate', photo=get('photo', old[0], db))
                original = f'originals/{digest}'
                os.replace(staged, store.root / original)
                photo = dict(id=id, filename=name, sha256=digest, bytes=count, original=original,
                             preview=f'previews/{id}.jpg', created_at=now(), review_complete=False, **metadata)
                store.put('photo', photo, db)
                db.execute('INSERT INTO hashes VALUES(?,?)', (digest, id))
                db.execute('INSERT INTO jobs(id,photo_id,state) VALUES(?,?,?)', (uid(), id, 'queued'))
                store.audit(db, 'photo_uploaded', id, {'sha256': digest})
            return jsonify(status='saved', photo=photo), 201
        except subprocess.TimeoutExpired:
            capture_failed_upload(staged, digest, name, dict(error_type='TimeoutExpired', timeout_seconds=35))
            raise Invalid('Photo decoding timed out. Try a smaller photo.', 422)
        finally:
            staged.unlink(missing_ok=True)
            if not store.get('photo', id):
                preview.unlink(missing_ok=True)

    @app.get('/media/<kind>/<id>')
    def media(kind, id):
        if not re.fullmatch('[a-f0-9]{32}', id):
            raise Invalid('This image is unavailable.', 404)
        if kind in ('preview', 'original'):
            record = get('photo', id)
            path = record['preview' if kind == 'preview' else 'original']
        elif kind == 'crop':
            path = get('observation', id)['crop']
        else:
            raise Invalid('This image is unavailable.', 404)
        return send_from_directory(store.root, path, as_attachment=kind == 'original',
                                   download_name=f'{id}.{record["format"].lower()}' if kind == 'original' else None)

    @app.post('/api/photos/<id>/retry')
    def retry(id):
        with store.connect() as db:
            get('photo', id, db)
            result = db.execute("UPDATE jobs SET state='queued',error=NULL WHERE photo_id=? AND state='failed'", (id,))
            if not result.rowcount:
                raise Invalid('Only failed jobs can be retried.', 409)
        return jsonify(status='queued')

    @app.post('/api/photos/<id>/review')
    def photo_review(id):
        with store.connect() as db:
            photo = get('photo', id, db)
            job = db.execute('SELECT state FROM jobs WHERE photo_id=?', (id,)).fetchone()
            if job[0] != 'done' or any(o['photo_id'] == id and o['status'] == 'needs_review' for o in store.all('observation', db)):
                raise Invalid('Review each observation before you finish this photo.', 409)
            photo['review_complete'] = True
            store.put('photo', photo, db)
            store.audit(db, 'photo_reviewed', id, {})
        return jsonify(photo)

    @app.post('/api/observations')
    def add_observation():
        data = body()
        box = bbox(data.get('bbox'))
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            photo = get('photo', data.get('photo_id'), db)
            if db.execute('SELECT state FROM jobs WHERE photo_id=?', (photo['id'],)).fetchone()[0] != 'done':
                raise Invalid('Wait for photo processing to finish.', 409)
            if len(store.all('observation', db)) >= MAX_OBSERVATIONS:
                raise Invalid(f'This batch is limited to {MAX_OBSERVATIONS} card observations.', 409)
            id = uid()
            rotation = choice(data.get('rotation', 0), (0, 90, 180, 270))
            record = dict(id=id, photo_id=photo['id'], bbox=box, rotation=rotation, crop=make_crop(store, photo, id, box, rotation),
                          side='unknown', status='needs_review', card_id=None, created_at=now(), method='manual')
            store.put('observation', record, db)
            photo['review_complete'] = False
            store.put('photo', photo, db)
        return jsonify(record), 201

    @app.patch('/api/observations/<id>')
    def edit_observation(id):
        data = body()
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = get('observation', id, db)
            photo = get('photo', record['photo_id'], db)
            new_box = bbox(data.get('bbox', record['bbox']))
            rotation = choice(data.get('rotation', record.get('rotation', 0)), (0, 90, 180, 270))
            if new_box != record['bbox'] or rotation != record.get('rotation', 0):
                record['bbox'] = new_box
                record['rotation'] = rotation
                # Version crop URLs to prevent stale browser images after corrections.
                record['crop'] = make_crop(store, photo, uid(), record['bbox'], rotation)
                record['crop_revision'] = record.get('crop_revision', 0)+1
                record['identity_proposal'] = {'status': 'unresolved', 'evidence_text': '',
                                               'uncertainty': ['The crop changed. Extract text again.']}
            if 'side' in data:
                record['side'] = choice(data['side'], ('front', 'back', 'unknown'))
            if data.get('status') == 'ignored':
                if record['card_id']:
                    raise Invalid('A linked observation cannot be ignored.', 409)
                record['status'] = 'ignored'
            if data.get('status') == 'needs_review' and not record['card_id']:
                record['status'] = 'needs_review'
            if 'review_note' in data:
                record['review_note'] = text(data['review_note'], 1000)
            store.put('observation', record, db)
            photo['review_complete'] = False
            store.put('photo', photo, db)
            store.audit(db, 'observation_corrected', id, data)
        return jsonify(record)

    @app.post('/api/observations/<id>/recognize')
    def recognize(id):
        record = get('observation', id)
        revision = record.get('crop_revision', 0)
        proposal = identify(store.root / record['crop'])
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = get('observation', id, db)
            if current.get('crop_revision', 0) != revision:
                raise Invalid('The crop changed. Extract text again.', 409)
            current['identity_proposal'] = proposal
            store.put('observation', current, db)
            store.audit(db, 'text_extracted', id, {'crop_revision': revision})
        return jsonify(current)

    @app.post('/api/cards')
    def create_card():
        data = body()
        details = identity(data)
        if not details['player']:
            raise Invalid('Enter the player name before you add this card.')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            observation = get('observation', data.get('observation_id'), db)
            if observation['card_id']:
                raise Invalid('This observation already belongs to a card.', 409)
            card = dict(id=uid(), **details, notes=text(data.get('notes', ''), 4000), revision=1,
                        evidence_state=choice(data.get('evidence_state', 'user_confirmed'), ('user_confirmed', 'photo_reviewed')),
                        primary_observation_id=observation['id'],
                        visual_description=text(data.get('visual_description', ''), 500),
                        serial_number=text(data.get('serial_number', ''), 100), created_at=now(), fees=None)
            store.put('card', card, db)
            observation.update(card_id=card['id'], status='confirmed', side=choice(data.get('side', 'unknown'), ('front', 'back', 'unknown')))
            store.put('observation', observation, db)
            store.audit(db, 'card_recorded', card['id'], {**details, 'evidence_state': card['evidence_state']})
        return jsonify(card), 201

    @app.post('/api/cards/<id>/link')
    def link(id):
        data = body()
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            get('card', id, db)
            observation = get('observation', data.get('observation_id'), db)
            if observation['card_id'] and observation['card_id'] != id:
                raise Invalid('This observation belongs to another card.', 409)
            observation.update(card_id=id, status='confirmed', side=choice(data.get('side', 'unknown'), ('front', 'back', 'unknown')))
            store.put('observation', observation, db)
            store.audit(db, 'observation_linked', id, {'observation_id': observation['id']})
        return jsonify(observation)

    @app.patch('/api/cards/<id>')
    def edit_card(id):
        data = body()
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            card = get('card', id, db)
            if data.get('revision') != card['revision']:
                raise Invalid('This card changed. Refresh before you save.', 409)
            for key in IDENTITY_FIELDS + ('notes', 'visual_description', 'serial_number', 'sport', 'manufacturer', 'condition_source', 'purchase_match_note'):
                if key in data:
                    card[key] = text(data[key], {'notes': 4000, 'visual_description': 500, 'serial_number': 100}.get(key, 250))
            for key in ('autograph', 'memorabilia'):
                if key in data:
                    if type(data[key]) is not bool:
                        raise Invalid('Use true or false for card features.')
                    card[key] = data[key]
            if 'evidence_state' in data:
                card['evidence_state'] = choice(data['evidence_state'], ('user_confirmed', 'photo_reviewed'))
            if 'primary_observation_id' in data:
                cover = get('observation', data['primary_observation_id'], db)
                if cover['card_id'] != id:
                    raise Invalid('Select an observation linked to this physical card.', 409)
                card['primary_observation_id'] = cover['id']
            if not card['player']:
                raise Invalid('Enter the player name.')
            if 'fees' in data:
                fees = data['fees']
                if not isinstance(fees, dict):
                    raise Invalid('Enter the fee assumptions.')
                percent = fees.get('percent')
                if type(percent) not in (int, float) or not math.isfinite(percent) or not 0 <= percent <= 100:
                    raise Invalid('Use a fee percentage from 0 to 100.')
                card['fees'] = {'percent': percent, 'fixed_cents': integer(fees.get('fixed_cents')), 'shipping_cents': integer(fees.get('shipping_cents'))}
            card.update(revision=card['revision']+1, updated_at=now())
            store.put('card', card, db)
            store.audit(db, 'card_corrected', id, data)
        return jsonify(card)

    @app.get('/api/cards/<id>/analysis')
    def analysis(id):
        with store.connect() as db:
            card = get('card', id, db)
            allocations = [a for a in store.all('allocation', db) if a['card_id'] == id]
            comps = [c for c in store.all('comparable', db) if c['card_id'] == id]
            cost = sum(a['cost_cents'] for a in allocations) if allocations else None
            valuation = analyse_card(card, comps, allocations, analysis_costs(db)) if card.get('research') or any(c.get('match_reviewed') for c in comps) else value_card(card, comps, card.get('fees'), cost)
            return jsonify(revision=card['revision'], purchases=match_purchase(card, store.all('purchase', db)),
                           allocations=allocations, valuation=valuation)

    @app.post('/api/purchases')
    def purchase():
        data = body()
        record = dict(id=uid(), title=text(data.get('title', ''), 1000), account=text(data.get('account', 'Manual record')),
                      source_ref=text(data.get('source_ref', ''), 1000), quantity=integer(data.get('quantity'), 1, 10000),
                      total_cents=integer(data.get('total_cents')), refund_cents=integer(data.get('refund_cents', 0)),
                      status=choice(data.get('status', 'completed'), ('completed', 'cancelled', 'refunded')),
                      condition=text(data.get('condition', '')), created_at=now(), currency='USD',
                      evidence_state=choice(data.get('evidence_state', 'user_entered'), ('user_entered', 'browser_observed')),
                      order_date=text(data.get('order_date', ''), 40), order_id=text(data.get('order_id', ''), 100),
                      cost_basis=text(data.get('cost_basis', ''), 1000))
        if not record['title'] or not record['source_ref'] or record['refund_cents'] > record['total_cents']:
            raise Invalid('Enter a title and source reference. Keep the refund within the total cost.')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if any(p['source_ref'] == record['source_ref'] and p['account'] == record['account'] for p in store.all('purchase', db)):
                raise Invalid('This account and purchase reference already exist.', 409)
            store.put('purchase', record, db)
            store.audit(db, 'purchase_added', record['id'], {'source_ref': record['source_ref']})
        return jsonify(record), 201

    @app.post('/api/cards/<id>/allocation')
    def allocation(id):
        data = body()
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            get('card', id, db)
            line = get('purchase', data.get('purchase_id'), db)
            if line['status'] in ('cancelled', 'refunded'):
                raise Invalid('A cancelled or refunded purchase cannot supply a card.')
            allocations = store.all('allocation', db)
            remaining = available(line, allocations, excluding=id)
            cost = integer(data.get('cost_cents'))
            if remaining['quantity'] < 1 or remaining['cents'] < cost:
                raise Invalid('This allocation exceeds the remaining quantity or cost.', 409)
            old = next((a for a in allocations if a['card_id'] == id), None)
            record = dict(id=old['id'] if old else uid(), card_id=id, purchase_id=line['id'], quantity=1,
                          cost_cents=cost, basis=text(data.get('basis', ''), 1000), evidence_state='estimated', created_at=now())
            if not record['basis']:
                raise Invalid('Describe the cost allocation basis.')
            store.put('allocation', record, db)
            store.audit(db, 'cost_allocated', id, record)
        return jsonify(record)

    @app.post('/api/cards/<id>/comparables')
    def comparable(id):
        data = body()
        record = dict(id=uid(), card_id=id, **identity(data), status=choice(data.get('status'), ('sold', 'asking', 'unknown')),
                      source_url=source_url(data.get('source_url', '')), sold_date=text(data.get('sold_date', ''), 10),
                      price_cents=integer(data.get('price_cents'), 1), shipping_cents=integer(data.get('shipping_cents', 0)),
                      currency=text(data.get('currency', 'USD'), 3), retrieved_at=now(), evidence_state='user_entered')
        with store.connect() as db:
            card = get('card', id, db)
            if data.get('match_reviewed') is True:
                record.update(match_reviewed=True, identity_signature=signature(card),
                              source_title=text(data.get('source_title', ''), 1000),
                              match_note=text(data.get('match_note', ''), 2000),
                              price_status=choice(data.get('price_status', 'known'), ('known', 'hidden_offer', 'unknown')),
                              shipping_known=data.get('shipping_known') is True,
                              evidence_state=choice(data.get('evidence_state', 'user_entered'), ('browser_observed', 'user_entered')),
                              condition_evidence=text(data.get('condition_evidence', ''), 1000))
            store.put('comparable', record, db)
            store.audit(db, 'comparable_added', id, {'comparable_id': record['id']})
        return jsonify(record), 201

    @app.get('/api/export/<format>')
    def export(format):
        with store.connect() as db:
            data = {kind+'s': store.all(kind, db) for kind in ('photo', 'observation', 'card', 'purchase', 'allocation', 'comparable')}
            for kind, key in (('listing', 'listings'), ('listing_research', 'listing_research'),
                              ('settings', 'settings'), ('simulation_run', 'simulation_runs')):
                data[key] = store.all(kind, db)
            data['audit'] = [dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id')]
            report = portfolio(data['cards'], data['comparables'], data['allocations'], analysis_costs(db))
        if format == 'json':
            output, mime = json.dumps({'schema_version': 2, 'exported_at': now(), **data, 'analysis': report}, indent=2), 'application/json'
        elif format == 'analysis-csv':
            stream = io.StringIO(newline='')
            columns = ('card_id', 'player', 'year', 'set', 'variant', 'serial_number', 'purchase_cost_cents', 'market_value_cents', 'net_proceeds_cents', 'profit_cents', 'break_even_cents', 'category_label', 'sample_count', 'confidence', 'recommendation', 'horizon', 'trigger', 'source_urls')
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            cards = {c['id']: c for c in data['cards']}
            comps = {c['id']: c for c in data['comparables']}
            for row in report['rows']:
                values = {**cards[row['card_id']], **row, 'source_urls': ' | '.join(comps[c]['source_url'] for c in row['included'])}
                writer.writerow({k: ("'"+v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v) for k, v in values.items()})
            output, mime = stream.getvalue(), 'text/csv'
        elif format == 'csv':
            stream = io.StringIO(newline='')
            columns = ('id',)+IDENTITY_FIELDS+('visual_description', 'serial_number', 'notes', 'revision', 'evidence_state')
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            for card in data['cards']:
                writer.writerow({k: ("'"+v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v) for k, v in card.items()})
            output, mime = stream.getvalue(), 'text/csv'
        else:
            raise Invalid('Select JSON or CSV.', 404)
        filename = 'sportscards-analysis.csv' if format == 'analysis-csv' else f'sportscards.{format}'
        return Response(output, mimetype=mime, headers={'Content-Disposition': f'attachment; filename="{filename}"'})

    @app.get('/')
    @app.get('/<path:path>')
    def frontend(path='index.html'):
        return send_from_directory(dist, path)

    register_pricing_api(app, store, Invalid, body, get, text, integer, choice, source_url, analysis_costs)
    register_listing_prep(app, store)

    if worker:
        recover(store)
        def run_worker():
            while True:
                try:
                    if not process_one(store):
                        time.sleep(1)
                except Exception:
                    app.logger.error('Queue poll failed.')
                    time.sleep(3)
        threading.Thread(target=run_worker, daemon=True, name='sportscards-worker').start()
    return app


if __name__ == '__main__':
    from waitress import serve
    os.umask(0o077)
    serve(create_app(worker=True), host=os.environ.get('SPORTSCARDS_HOST', '127.0.0.1'),
          port=int(os.environ.get('SPORTSCARDS_PORT', '8097')), threads=4, max_request_body_size=MAX_BYTES)
