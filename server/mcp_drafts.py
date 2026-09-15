"""Validated, atomic updates to the one private listing draft manifest."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

from .analysis import signature
from .app import text
from .selling_prep import MAX_DRAFTS, MAX_MANIFEST_BYTES, _crop_file, _digest, prep_report
from .store import now, uid


def manifest_path(store):
    root = store.root.resolve()
    directory = store.root / 'listing-prep'
    path = directory / 'current.json'
    if not directory.resolve().is_relative_to(root) or path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Keep the listing draft file inside the private collection directory.')
    return path


def read_manifest(store):
    path = manifest_path(store)
    if not path.exists():
        return path, None, None
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError('The listing draft file is too large.')
    content = path.read_bytes()
    try:
        manifest = json.loads(content.decode('utf-8-sig'))
    except (UnicodeError, ValueError) as exc:
        raise ValueError('The listing draft file is unreadable.') from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get('drafts'), list):
        raise ValueError('The listing draft file has an invalid structure.')
    return path, manifest, hashlib.sha256(content).hexdigest()


def draft_report(store):
    _, manifest, digest = read_manifest(store)
    return {**prep_report(store, manifest), 'manifest_sha256': digest}


def save_draft(store, card_id, inputs, expected_digest):
    for key in ('condition_confirmed', 'terms_confirmed', 'photos_reviewed'):
        if inputs[key] is not True:
            raise ValueError('Confirm the owner condition, listing terms, and selected photos before saving a draft.')
    if not text(inputs['condition_source']):
        raise ValueError('Describe the owner source for the confirmed condition.')
    with store.connect() as db:
        # Coordinate MCP writers across processes and prevent card changes during validation.
        db.execute('BEGIN IMMEDIATE')
        path, existing, current_digest = read_manifest(store)
        if current_digest != expected_digest:
            raise ValueError('The draft batch changed. Read selling_prep and supply its current manifest_sha256.')
        card = store.get('card', card_id, db)
        if not card or card.get('revision') != inputs['card_revision']:
            raise ValueError('This card changed or is unavailable. Read its current revision before saving a draft.')
        hashes = {}
        for observation_id in inputs['photo_observation_ids']:
            observation = store.get('observation', observation_id, db)
            if not observation or observation.get('card_id') != card_id:
                raise ValueError('Use photos linked to this physical card.')
            crop = _crop_file(store, observation)
            if crop is None:
                raise ValueError('A selected crop file is unavailable or outside the private crop directory.')
            hashes[observation_id] = _digest(crop)
        draft = {**inputs, 'card_id': card_id, 'identity_signature': signature(card),
                 'photo_sha256': hashes, 'updated_at': now()}
        manifest = dict(existing or {'batch_id': uid(), 'created_at': now(), 'drafts': []})
        if any(not isinstance(item, dict) for item in manifest['drafts']):
            raise ValueError('Each listing draft must be an object.')
        rows = list(manifest['drafts'])
        positions = [index for index, item in enumerate(rows) if item.get('card_id') == card_id]
        if len(positions) > 1:
            raise ValueError('This card appears more than once in the draft batch.')
        if positions:
            rows[positions[0]] = draft
        else:
            rows.append(draft)
        if len(rows) > MAX_DRAFTS:
            raise ValueError('Use at most 100 listing drafts in one batch.')
        manifest.update(drafts=rows, updated_at=now())
        content = json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
        if len(content) > MAX_MANIFEST_BYTES:
            raise ValueError('The listing draft file is too large.')
        report = prep_report(store, manifest)
        result = next(item for item in report['drafts'] if item['card_id'] == card_id)
        allowed = {'Mark this draft ready after its review is complete.'} if inputs['status'] != 'ready' else set()
        blockers = [message for message in result['blockers'] if message not in allowed]
        if blockers:
            raise ValueError(' '.join(blockers))
        path.parent.mkdir(exist_ok=True, mode=0o700)
        pending = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.draft-', suffix='.tmp', delete=False) as output:
                pending = Path(output.name)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            pending.chmod(0o600)
            # Detect direct file edits made while this request validated the candidate.
            if read_manifest(store)[2] != current_digest:
                raise ValueError('The draft batch changed during validation. Read it before retrying.')
            store.audit(db, 'listing_draft_saved', card_id,
                        {'previous_manifest_sha256': current_digest,
                         'manifest_sha256': hashlib.sha256(content).hexdigest(),
                         'card_revision': card['revision'], 'condition_source': inputs['condition_source']})
            os.replace(pending, path)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)
    return {**report, 'manifest_sha256': hashlib.sha256(content).hexdigest(), 'saved_card_id': card_id}
