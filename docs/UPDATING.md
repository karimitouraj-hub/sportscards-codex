# Update and recover SportsCards

Back up the current collection before updating the code.
Use a new backup directory and keep the original collection.
The backup tool also verifies file hashes and restores into a new directory.

## Identify the active collection

Check the data path before copying anything.
The default is `.sportscards` in your home directory.
Your installation can use a different directory:

| Process | Where to check |
| --- | --- |
| Dashboard | The launcher's `--data-dir` argument or `SPORTSCARDS_DATA` environment variable |
| MCP server | The `--data` argument in `.codex/config.toml`, or its configured environment |

The project `.codex/config.toml` can override a global Codex configuration.
Do not assume that a change to the global configuration changed this project's data path.
Use the same absolute directory for the dashboard and MCP server.

In the commands below, replace these placeholders:

| Placeholder | Value |
| --- | --- |
| `PRIVATE_DATA_PATH` | The existing collection directory containing `collection.sqlite3` |
| `NEW_BACKUP_PATH` | A new directory outside the collection and repository |
| `NEW_RESTORE_PATH` | A different new directory outside the collection and repository |
| `PREVIOUS_COMMIT` | The full commit ID recorded before the update |

Keep backup locations and recovery notes private.
Use `python3` instead of `python` if your system requires it.
These backup commands need Python 3.11 or later and use only its standard library.

## Back up before an update

1. Record the displayed card count and current data path in your private notes.
2. Stop the dashboard with `Ctrl+C` in its terminal.
3. Close Codex sessions connected to this collection.
4. Wait for any other process writing this collection to stop.
5. Open a terminal in the repository directory.
6. Record the current code version in your private notes.

   ```text
   git rev-parse HEAD
   ```

7. Create the backup with the explicit current data path.

   ```text
   python scripts/backup.py --source "PRIVATE_DATA_PATH" --destination "NEW_BACKUP_PATH"
   ```

8. Verify the completed backup.

   ```text
   python scripts/backup.py --verify "NEW_BACKUP_PATH"
   ```

Both commands must exit successfully.
The backup reports its destination and copied-file count.
Verification checks file sizes, SHA256 hashes, database integrity, record count, and coverage of database-referenced media.
It also checks the current listing draft against the file manifest.
Keep the reported backup path with the previous commit ID.
If either command fails, resolve the failure before updating.

The tool rejects missing source databases, existing destinations, and destinations inside the source directory.
It publishes the destination only after copying and verification succeed.
The SQLite backup API includes committed WAL records in the database snapshot.
SQLite can create WAL coordination files beside the source database without changing its stored collection data.

Stopping writers is still necessary for a consistent collection backup.
The database snapshot and photo copies do not share one transaction.

## Update the code

1. Inspect the working tree.

   ```text
   git status --short
   ```

2. Preserve any local source changes before continuing.

   Commit reviewed source changes on a separate branch, or save them outside the repository.
   A stash is another option for reviewed paths:

   ```text
   git stash push -m "Local SportsCards changes before update" -- path/to/changed-source
   ```

   Replace the example path with your changed source file.
   This command does not include untracked files.
   Keep private data out of commits and stashes.
   Inspect `git status --short` again before the next step.

3. Download a fast-forward update.

   ```text
   git pull --ff-only
   ```

   If Git reports divergent history or local-file conflicts, preserve the checkout and resolve that issue first.
   Do not use `git reset --hard` to force an update over your changes.

4. Install the updated dependencies with the same private data path.

   ```text
   python scripts/setup.py --data-dir "PRIVATE_DATA_PATH"
   ```

5. Check the installation.

   ```text
   python scripts/setup.py --check
   ```

   The setup check uses temporary collection storage.
   It validates the MCP connection without opening your real collection.

6. Start the dashboard with that same path.

   ```text
   python scripts/start.py --data-dir "PRIVATE_DATA_PATH"
   ```

7. Open this checkout in a new Codex session.
8. Ask Codex to call SportsCards `status`.
9. Compare the card count with your pre-update record.
10. Open a known card and inspect its photos, purchase record, and saved evidence.
11. Inspect **Selling prep** if you keep listing drafts.

Review any preserved local changes before applying them to the updated code.
Keep the backup until you are satisfied with the updated collection.

## Restore without overwriting the original

Use this procedure if the updated application cannot use your collection correctly.
The restored collection reflects the backup time. Later edits remain in the original directory.

1. Stop the dashboard and connected Codex sessions.
2. Verify the backup from the checkout that contains this backup tool.

   ```text
   python scripts/backup.py --verify "NEW_BACKUP_PATH"
   ```

3. Restore into a new directory.

   ```text
   python scripts/backup.py --restore "NEW_BACKUP_PATH" --destination "NEW_RESTORE_PATH"
   ```

4. Verify the restored copy before starting an application against it.

   ```text
   python scripts/backup.py --verify "NEW_RESTORE_PATH"
   ```

5. Create a separate checkout of the previous code version.

   ```text
   git worktree add --detach "../sportscards-rollback" PREVIOUS_COMMIT
   ```

   The checkout path must be unused.
   This command preserves the updated checkout and its files.

6. Enter the rollback checkout.

   ```text
   cd ../sportscards-rollback
   ```

7. Follow that checkout's installation instructions with `NEW_RESTORE_PATH` as its collection directory.

   For a version that supports the current installer:

   ```text
   python scripts/setup.py --data-dir "NEW_RESTORE_PATH"
   python scripts/setup.py --check
   python scripts/start.py --data-dir "NEW_RESTORE_PATH"
   ```

   For an older version, use its README and MCP guide to configure both processes for the restored directory.

8. Open the rollback checkout in a new Codex session.
9. Verify the card count, sample photos, purchases, evidence, and listing drafts.

Keep the original collection, backup, and restored copy until you finish the comparison.
Do not combine databases by copying individual database files between running applications.
The app creates a new local session token for the restored collection.
After the application writes new data, the restored copy will no longer match the original backup hashes.

## Backup contents and omissions

| Included | Omitted |
| --- | --- |
| All SQLite tables and records | The local request token and browser credentials |
| Original photos referenced by stored photo records | Unreferenced originals or crops |
| Referenced previews and observation crops | Research captures and external evidence files |
| `listing-prep/current.json`, when present | Archived listing batches and other draft files |
| File hash manifest | Staging files, failed-upload samples, logs, and standalone exports |

The backup does not include application code, installed dependencies, or Codex configuration.
Save any omitted material you need separately before updating.
Keep the original directory so omitted files remain available.

New backups use manifest version `3`.
Older version `2` backups lack the complete file hash manifest.
The new verification and restore modes reject those older manifests.
Create a new version `3` backup from the intact original collection when possible.
Do not rename a legacy manifest version to bypass this check.

## Verification record

**Verified:** Synthetic backup and restore on Windows with Python 3.14.
The test compares file hashes and all SQLite tables before and after restoration.
It also covers missing sources, existing destinations, invalid media paths, damaged backups, configured data paths, and committed WAL records.
It rejects incomplete file manifests and inconsistent listing draft hashes.

**Not Tested:** Symlink rejection on this Windows account, which cannot create symlinks.
The test runs where the operating system permits symlink creation.
Real private collections and older application versions require their own recovery check.

Run the backup regression tests with the project interpreter:

```text
python -m pytest tests/test_backup.py -q
```

See [the tests](../tests/test_backup.py) and [backup implementation](../scripts/backup.py) for the checked behavior.
