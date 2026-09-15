"""Create an offline-copy backup with SQLite's online backup API."""
import argparse
import os
import datetime as dt
import json
import hashlib
from pathlib import Path
import shutil
import sqlite3

os.umask(0o077)

parser = argparse.ArgumentParser()
parser.add_argument('--source', default=str(Path.home() / '.sportscards'))
parser.add_argument('--destination', required=True)
args = parser.parse_args()
source, destination = Path(args.source).resolve(), Path(args.destination).resolve()
if destination == source or source in destination.parents:
    raise SystemExit('The backup directory must be outside the collection directory.')
destination.mkdir(parents=True, exist_ok=False, mode=0o700)
with sqlite3.connect(source/'collection.sqlite3') as src, sqlite3.connect(destination/'collection.sqlite3') as dst:
    src.backup(dst)
    records = [json.loads(row[0]) for row in dst.execute("SELECT data FROM records WHERE kind IN ('photo','observation')")]
for record in records:
    for key in ('original','preview','crop'):
        if key in record:
            relative = Path(record[key])
            if relative.is_absolute() or '..' in relative.parts:
                raise SystemExit('The database contains an invalid file path.')
            target = destination/relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(source/relative, target)
listing_manifest = source/'listing-prep'/'current.json'
listing_sha256 = None
if listing_manifest.exists():
    if not listing_manifest.resolve().is_relative_to(source):
        raise SystemExit('The listing draft file must stay inside the collection directory.')
    content = listing_manifest.read_bytes()
    target = destination/'listing-prep'/'current.json'
    target.parent.mkdir(mode=0o700)
    target.write_bytes(content)
    target.chmod(0o600)
    listing_sha256 = hashlib.sha256(content).hexdigest()
(destination/'manifest.json').write_text(json.dumps({'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
                                                    'records_with_files':len(records),'schema_version':2,
                                                    'listing_manifest_sha256':listing_sha256}, indent=2))
print(json.dumps({'backup':str(destination),'records_with_files':len(records),
                  'listing_manifest_copied':listing_sha256 is not None}))
