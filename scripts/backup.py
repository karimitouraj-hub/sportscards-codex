"""Back up a collection, verify its hashes, or restore into a new directory."""
import argparse
from contextlib import closing
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import sqlite3
import tempfile


SCHEMA_VERSION = 3
MEDIA_DIRECTORIES = {'original': 'originals', 'preview': 'previews', 'crop': 'crops'}


def file_hash(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def contained_file(root, name):
    """Resolve an existing file without following a link outside the selected root."""
    if not isinstance(name, str) or not name:
        raise ValueError('A backup file path is invalid.')
    relative = Path(name)
    if relative.is_absolute() or PureWindowsPath(name).drive or '..' in relative.parts:
        raise ValueError('A backup file path must stay inside its directory.')
    selected = (root / relative).resolve()
    if not selected.is_relative_to(root) or not selected.is_file():
        raise ValueError(f'A required file is missing or outside its directory: {name}')
    return selected


def read_database(path, immutable=False):
    # mode=ro prevents sqlite3 from creating a database when the source is missing.
    query = '?mode=ro&immutable=1' if immutable else '?mode=ro'
    return sqlite3.connect(path.as_uri() + query, uri=True, timeout=30)


def check_database(path, immutable=False):
    with closing(read_database(path, immutable)) as db:
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('The collection database did not pass its integrity check.')
        return db.execute('SELECT COUNT(*) FROM records').fetchone()[0]


def new_destination(source, destination):
    supplied = Path(destination).expanduser()
    if supplied.exists() or supplied.is_symlink():
        raise ValueError('The destination must be a new directory.')
    selected = supplied.resolve()
    if selected == source or selected.is_relative_to(source):
        raise ValueError('The destination must be outside the source directory.')
    return selected


def publish_copy(destination, writer):
    """Leave no completed destination when validation or copying fails."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{destination.name}-', dir=destination.parent) as temporary:
        staging = Path(temporary).resolve()
        staging.chmod(0o700)
        result = writer(staging)
        if destination.exists() or destination.is_symlink():
            raise ValueError('The destination appeared during copying. Use a new directory.')
        staging.rename(destination)
    return result


def backup_collection(source, destination):
    source = Path(source).expanduser().resolve()
    database = contained_file(source, 'collection.sqlite3')
    destination = new_destination(source, destination)

    def write(staging):
        snapshot = staging / 'collection.sqlite3'
        with closing(read_database(database)) as src, closing(sqlite3.connect(snapshot)) as dst:
            src.backup(dst)
            records = [json.loads(row[0]) for row in dst.execute(
                "SELECT data FROM records WHERE kind IN ('photo','observation')")]
        snapshot.chmod(0o600)
        selected = {'collection.sqlite3': snapshot}
        for record in records:
            if not isinstance(record, dict):
                raise ValueError('A photo or observation record is invalid.')
            for key, directory in MEDIA_DIRECTORIES.items():
                if key not in record:
                    continue
                name = record[key]
                original = contained_file(source, name)
                relative = Path(name)
                if relative.parts[0] != directory:
                    raise ValueError(f'The {key} file must stay inside {directory}.')
                relative_name = relative.as_posix()
                if relative_name in selected:
                    continue
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                expected_hash = file_hash(original)
                shutil.copyfile(original, target)
                target.chmod(0o600)
                if file_hash(target) != expected_hash:
                    raise ValueError('A source photo changed during copying. Stop the app and retry.')
                selected[relative_name] = target

        listing = source / 'listing-prep' / 'current.json'
        listing_sha256 = None
        if listing.exists() or listing.is_symlink():
            original = contained_file(source, 'listing-prep/current.json')
            target = staging / 'listing-prep' / 'current.json'
            target.parent.mkdir(mode=0o700)
            content = original.read_bytes()
            target.write_bytes(content)
            target.chmod(0o600)
            listing_sha256 = hashlib.sha256(content).hexdigest()
            selected['listing-prep/current.json'] = target

        manifest = {
            'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'schema_version': SCHEMA_VERSION,
            'records_with_files': len(records),
            'record_count': check_database(snapshot, immutable=True),
            'listing_manifest_sha256': listing_sha256,
            'files': {name: {'sha256': file_hash(path), 'bytes': path.stat().st_size}
                      for name, path in sorted(selected.items())},
        }
        (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        (staging / 'manifest.json').chmod(0o600)
        verify_backup(staging)
        return {'backup': str(destination), 'records_with_files': len(records),
                'listing_manifest_copied': listing_sha256 is not None,
                'verified_files': len(selected), 'schema_version': SCHEMA_VERSION}

    return publish_copy(destination, write)


def verify_backup(source):
    source = Path(source).expanduser().resolve()
    manifest_path = contained_file(source, 'manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('This backup has no supported hash manifest. Create a new version 3 backup.')
    files = manifest.get('files')
    if not isinstance(files, dict) or 'collection.sqlite3' not in files:
        raise ValueError('The backup manifest must include the collection database.')
    for name, expected in files.items():
        path = contained_file(source, name)
        if (name not in ('collection.sqlite3', 'listing-prep/current.json')
                and Path(name).parts[0] not in MEDIA_DIRECTORIES.values()):
            raise ValueError('The backup manifest contains an unsupported file.')
        if not isinstance(expected, dict) or path.stat().st_size != expected.get('bytes'):
            raise ValueError(f'The backup file size does not match: {name}')
        if file_hash(path) != expected.get('sha256'):
            raise ValueError(f'The backup file hash does not match: {name}')
    database = contained_file(source, 'collection.sqlite3')
    if check_database(database, immutable=True) != manifest.get('record_count'):
        raise ValueError('The backup record count does not match.')
    expected_files = {'collection.sqlite3'}
    with closing(read_database(database, immutable=True)) as db:
        records = [json.loads(row[0]) for row in db.execute(
            "SELECT data FROM records WHERE kind IN ('photo','observation')")]
    for record in records:
        if not isinstance(record, dict):
            raise ValueError('A photo or observation record is invalid.')
        for key, directory in MEDIA_DIRECTORIES.items():
            if key not in record:
                continue
            name = record[key]
            contained_file(source, name)
            relative = Path(name)
            if relative.parts[0] != directory:
                raise ValueError(f'The {key} file must stay inside {directory}.')
            expected_files.add(relative.as_posix())
    listing_name = 'listing-prep/current.json'
    listing_path = source / listing_name
    if listing_name in files:
        expected_files.add(listing_name)
        if manifest.get('listing_manifest_sha256') != files[listing_name]['sha256']:
            raise ValueError('The listing draft hash does not match the file manifest.')
    elif (manifest.get('listing_manifest_sha256') is not None
          or listing_path.exists() or listing_path.is_symlink()):
        raise ValueError('The listing draft is missing from the file manifest.')
    if set(files) != expected_files:
        raise ValueError('The file manifest does not match the database-referenced files.')
    return manifest


def restore_backup(source, destination):
    source = Path(source).expanduser().resolve()
    manifest = verify_backup(source)
    destination = new_destination(source, destination)

    def write(staging):
        for name in (*manifest['files'], 'manifest.json'):
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(contained_file(source, name), target)
            target.chmod(0o600)
        verify_backup(staging)
        return {'restored': str(destination), 'verified_files': len(manifest['files']),
                'record_count': manifest['record_count']}

    return publish_copy(destination, write)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--source', help='Collection directory to back up. Defaults to SPORTSCARDS_DATA or ~/.sportscards.')
    mode.add_argument('--verify', metavar='BACKUP', help='Verify a version 3 backup without writing files.')
    mode.add_argument('--restore', metavar='BACKUP', help='Restore a verified backup into a new directory.')
    parser.add_argument('--destination', help='New backup or restore directory, outside the source directory.')
    args = parser.parse_args()
    if args.verify:
        if args.destination:
            parser.error('--verify does not use --destination.')
        manifest = verify_backup(args.verify)
        result = {'verified': str(Path(args.verify).expanduser().resolve()),
                  'verified_files': len(manifest['files']), 'record_count': manifest['record_count']}
    else:
        if not args.destination:
            parser.error('--destination is required for backup or restore.')
        if args.restore:
            result = restore_backup(args.restore, args.destination)
        else:
            source = args.source or os.environ.get('SPORTSCARDS_DATA') or str(Path.home() / '.sportscards')
            result = backup_collection(source, args.destination)
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, sqlite3.Error) as error:
        raise SystemExit(f'Backup operation failed: {error}') from None
