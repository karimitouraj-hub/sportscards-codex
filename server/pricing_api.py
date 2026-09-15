"""Append-only listing evidence and reproducible pricing scenario endpoints."""
import csv
import datetime as dt
import hashlib
import io
import json
import math

from flask import Response, jsonify, request

from .analysis import signature
from .store import now, uid
from .valuation import comparable_source
from .pricing_engine import engine_report, simulate, simulate_release, DEFAULT_SETTINGS


MAX_LISTINGS_PER_CARD = 1000
MAX_RESEARCH_PER_CARD = 500
MAX_RUNS = 1000
SETTING_LIMITS = {'listing_factor': (0, 2), 'p30': (0, 1),
                  'market_sigma': (0, 2), 'player_sigma': (0, 2),
                  'product_sigma': (0, 2), 'card_sigma': (0, 2)}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def run_summary(run):
    return {key: run.get(key) for key in ('id', 'created_at', 'type', 'version', 'seed', 'options', 'summary')}


def register_pricing_api(app, store, Invalid, body, get, text, integer, choice, source_url, analysis_costs):
    """Register routes under the application's existing host and token protection."""
    def timestamp(value, label):
        value = text(value, 50)
        try:
            parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError()
            parsed = parsed.astimezone(dt.timezone.utc)
            if parsed > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
                raise ValueError()
            if parsed.year < 2000:
                raise ValueError()
        except ValueError:
            raise Invalid(f'Use a valid {label} time with a time zone. Do not use a future time.')
        return parsed.isoformat()

    def boolean(value):
        if type(value) is not bool:
            raise Invalid('Use true or false for this field.')
        return value

    def settings(db):
        record = store.get('settings', 'pricing-settings', db)
        return {**DEFAULT_SETTINGS, **(record.get('settings', {}) if record else {})}

    def run_count(db):
        return db.execute("SELECT COUNT(*) FROM records WHERE kind='simulation_run'").fetchone()[0]

    def snapshot(db):
        return {'cards': store.all('card', db), 'comparables': store.all('comparable', db),
                'allocations': store.all('allocation', db), 'listings': store.all('listing', db),
                'costs': analysis_costs(db), 'settings': settings(db)}

    def report_from(data):
        report = engine_report(**data)
        cards = {card['id']: card for card in data['cards']}
        for row in report['rows']:
            row['listing_research'] = cards[row['card_id']].get('listing_research')
            row['listing_research_current'] = bool(row['listing_research'] and
                                                  row['listing_research'].get('identity_signature') == signature(cards[row['card_id']]))
        report['data_fingerprint'] = digest(data)
        return report

    @app.get('/api/pricing-engine')
    def pricing_report():
        with store.connect() as db:
            data = snapshot(db)
        return jsonify(report_from(data))

    @app.get('/api/cards/<id>/listings')
    def card_listings(id):
        with store.connect() as db:
            card = get('card', id, db)
            rows = [r for r in store.all('listing', db) if r['card_id'] == id]
        return jsonify(card_id=id, revision=card['revision'], listings=rows, research=card.get('listing_research'))

    @app.post('/api/cards/<id>/listings')
    def add_listing(id):
        data = body()
        if boolean(data.get('match_reviewed')) is not True:
            raise Invalid('Confirm the exact card identity before you save the listing.')
        observed_at = timestamp(data.get('observed_at', now()), 'observation')
        record = dict(card_id=id, match_reviewed=True,
                      ask_cents=integer(data.get('ask_cents'), 1),
                      shipping_cents=integer(data.get('shipping_cents', 0)),
                      shipping_known=boolean(data.get('shipping_known', False)),
                      currency=choice(data.get('currency', 'USD'), ('USD', 'AUD', 'CAD', 'GBP', 'EUR')),
                      status=choice(data.get('status', 'active'), ('active', 'ended', 'sold', 'unknown')),
                      observed_at=observed_at, source_url=source_url(data.get('source_url', '')),
                      source_title=text(data.get('source_title', ''), 1000),
                      seller=text(data.get('seller', ''), 250),
                      physical_copy_key=text(data.get('physical_copy_key', ''), 250),
                      buying_format=choice(data.get('buying_format', 'fixed_price'), ('fixed_price', 'auction')),
                      evidence_state=choice(data.get('evidence_state', 'user_entered'), ('browser_observed', 'user_entered')),
                      notes=text(data.get('notes', ''), 4000))
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            card = get('card', id, db)
            if type(data.get('revision')) is not int or data['revision'] != card['revision']:
                raise Invalid('This card changed. Refresh before you save.', 409)
            record['identity_signature'] = signature(card)
            record['card_revision'] = card['revision']
            record['source_key'] = comparable_source(record['source_url'])
            previous = [r for r in store.all('listing', db) if r['card_id'] == id]
            # Repeat submissions with a supplied timestamp return the original record.
            observation_digest = digest(record)
            repeat = next((r for r in previous if r.get('observation_digest') == observation_digest), None)
            if repeat:
                return jsonify(repeat), 200
            if len(previous) >= MAX_LISTINGS_PER_CARD:
                raise Invalid('This card reached the 1,000-observation limit. Export the evidence before further review.', 409)
            same_source = [r for r in previous if r.get('source_key') == record['source_key']]
            first = min([observed_at] + [r['first_observed_at'] for r in same_source])
            record.update(id=uid(), created_at=now(), first_observed_at=first, observation_digest=observation_digest)
            store.put('listing', record, db)
            store.audit(db, 'listing_observed', id, {'listing_id': record['id'], 'observation_digest': observation_digest})
        return jsonify(record), 201

    @app.put('/api/cards/<id>/listing-research')
    def listing_research(id):
        data = body()
        record = dict(card_id=id, query=text(data.get('query', ''), 1000),
                      url=source_url(data.get('url', '')), limitations=text(data.get('limitations', ''), 4000),
                      reviewed_at=timestamp(data.get('reviewed_at', now()), 'review'), evidence_state='assisted_review')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            card = get('card', id, db)
            if type(data.get('revision')) is not int or data['revision'] != card['revision']:
                raise Invalid('This card changed. Refresh before you save.', 409)
            record['identity_signature'] = signature(card)
            research_digest = digest(record)
            previous = [r for r in store.all('listing_research', db) if r['card_id'] == id]
            repeat = next((r for r in previous if r.get('research_digest') == research_digest), None)
            if repeat:
                return jsonify(repeat)
            if len(previous) >= MAX_RESEARCH_PER_CARD:
                raise Invalid('This card reached the 500-review limit. Export the evidence before further review.', 409)
            record.update(id=uid(), created_at=now(), research_digest=research_digest)
            store.put('listing_research', record, db)
            if not card.get('listing_research') or record['reviewed_at'] >= card['listing_research']['reviewed_at']:
                card['listing_research'] = record
            store.put('card', card, db)
            store.audit(db, 'listing_research_reviewed', id, {'research_id': record['id']})
        return jsonify(record)

    @app.patch('/api/pricing-settings')
    def update_settings():
        data = body()
        if any(key not in SETTING_LIMITS for key in data):
            raise Invalid('Use only supported pricing assumptions.')
        for key, value in data.items():
            low, high = SETTING_LIMITS[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise Invalid(f'Use a finite {key} value between {low} and {high}.')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            updated = {**settings(db), **data}
            store.put('settings', dict(id='pricing-settings', settings=updated, updated_at=now()), db)
            store.audit(db, 'pricing_settings_changed', 'pricing-settings', updated)
        return jsonify(updated)

    def save_run(kind, options):
        with store.connect() as db:
            data = snapshot(db)
            if run_count(db) >= MAX_RUNS:
                raise Invalid('The application reached the 1,000-run limit. Export the saved runs before further simulation.', 409)
        report = report_from(data)
        try:
            result = simulate(report, options) if kind == 'collection' else simulate_release(options, data['costs'])
        except ValueError as error:
            raise Invalid(str(error))
        effective_options = result.get('options', options)
        run = dict(id=uid(), created_at=now(), type=kind, version=report['version'],
                   inputs_digest=digest({'type': kind, 'options': effective_options, 'report': report}),
                   data_fingerprint=report['data_fingerprint'], settings=data['settings'], costs=data['costs'],
                   seed=effective_options.get('seed', options.get('seed', 42)), options=effective_options,
                   requested_options=options,
                   result=result, summary=result.get('summary', {}),
                   input_report=report)
        # The input report preserves every modeled price, source, and assumption.
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if run_count(db) >= MAX_RUNS:
                raise Invalid('The application reached the 1,000-run limit. Export the saved runs before further simulation.', 409)
            store.put('simulation_run', run, db)
            store.audit(db, 'pricing_simulated', run['id'], {'type': kind, 'inputs_digest': run['inputs_digest']})
        return jsonify(run), 201

    @app.post('/api/pricing-engine/simulate')
    def collection_simulation():
        return save_run('collection', body())

    @app.post('/api/pricing-engine/releases')
    def release_simulation():
        return save_run('release', body())

    @app.get('/api/pricing-engine/runs')
    def saved_runs():
        value = request.args.get('limit', '50')
        if not value.isdigit() or not 1 <= int(value) <= 200:
            raise Invalid('Use a run limit between 1 and 200.')
        with store.connect() as db:
            rows = [json.loads(row[0]) for row in db.execute(
                "SELECT data FROM records WHERE kind='simulation_run' ORDER BY rowid DESC LIMIT ?", (int(value),))]
            total = run_count(db)
        return jsonify(runs=[run_summary(r) for r in rows], total=total)

    @app.get('/api/pricing-engine/runs/<id>')
    def saved_run(id):
        return jsonify(get('simulation_run', id))

    @app.get('/api/export/simulation/<id>')
    def export_simulation(id):
        record = get('simulation_run', id)
        return Response(json.dumps({'schema_version': 1, 'exported_at': now(), 'run': record}, indent=2),
                        mimetype='application/json', headers={'Content-Disposition': f'attachment; filename="sportscards-simulation-{record["id"]}.json"'})

    @app.get('/api/export/pricing-csv')
    def export_pricing():
        with store.connect() as db:
            report = report_from(snapshot(db))
        columns = ('card_id', 'player', 'year', 'set', 'variant', 'grade', 'number', 'purchase_cost_cents',
                   'sold_value_cents', 'sold_sample_count', 'active_ask_cents', 'active_sample_count',
                   'active_seller_count', 'listing_scenario_cents', 'price_source', 'scenario_price_cents',
                   'scenario_net_cents', 'scenario_profit_cents', 'confidence', 'latest_observed_at',
                   'first_observed_at', 'listing_factor', 'sold_source_urls', 'listing_source_urls',
                   'research_query', 'research_url', 'research_limitations')
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for row in report['rows']:
            research = row.get('listing_research') or {}
            values = {**row, 'listing_factor': report['settings']['listing_factor'],
                      'sold_source_urls': ' | '.join(r['source_url'] for r in row.get('sold_sources', [])),
                      'listing_source_urls': ' | '.join(r['source_url'] for r in row.get('active_sources', [])),
                      'research_query': research.get('query', ''), 'research_url': research.get('url', ''),
                      'research_limitations': research.get('limitations', '')}
            writer.writerow({key: "'"+value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value
                             for key, value in values.items()})
        return Response(stream.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="sportscards-pricing.csv"'})
