# Install and connect

Use Git, Python 3.11 or later, and Node.js 22 or later with npm.
Open a terminal inside your cloned repository.

1. Install the application and configure Codex.

   ```text
   python scripts/setup.py
   ```

2. Open this repository as your Codex workspace.
3. Review the project before accepting any workspace trust prompt.
4. Start a new conversation.
5. Ask: `Use $sportscards and check status.`
6. Start the dashboard.

   ```text
   python scripts/start.py
   ```

7. Open [the local dashboard](http://127.0.0.1:8097).

Use `python3` on systems where `python` is unavailable.
The setup command installs dependencies, builds the dashboard, and writes `.codex/config.toml` in this checkout.
It uses absolute paths to the local Python environment and server module.
It then tests MCP initialization, tool discovery, and status against temporary synthetic storage.
This test does not read your collection or use your Codex account.

Project configuration applies to trusted workspaces in compatible local Codex clients.
The installer does not grant trust or configure a browser.
See [official MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
The generated `.codex` directory stays out of Git.
Your global Codex settings remain unchanged.

## Check or repair

To check the existing setup:

```text
python scripts/setup.py --check
```

To configure already installed dependencies:

```text
python scripts/setup.py --skip-install
```

Run the full setup again after moving this checkout or after an incomplete installation.
Setup preserves unrelated project settings and saves a backup before an existing file changes.
The backup preserves the original file bytes.
An unmanaged `mcp_servers.sportscards` entry causes setup to stop without replacing it.
Use the [manual configuration guide](MCP.md) to review that entry.
Only remove a conflicting entry after saving its settings.

Setup also stops when its managed server contains manual fields, such as `env`, `enabled`, or `enabled_tools`.
It does not remove those fields or reset their values.
Settings outside the managed markers and unsupported argument forms also require manual review.
The configuration file remains unchanged when setup rejects these conflicts.
Use the manual guide to retain custom settings.

If Codex cannot find the tools, confirm that its workspace is this checkout.
Check whether project trust or an administrator policy prevents local MCP servers.
Use manual configuration when your client does not load project settings.
To select another collection for MCP:

```text
python scripts/setup.py --skip-install --data-dir /path/to/private-cards
```

Replace the example path with your own directory.
Start the dashboard with `python scripts/start.py --data-dir /path/to/private-cards` using that same path.
Repeat setup preserves this selection. Supply another `--data-dir` value to change it.
The setup result prints a dashboard command with the same selected data directory.
The connection check still uses temporary data instead of your selected collection.
For automatic setup, edit the project `.codex/config.toml` rather than a conflicting global server entry.
The default directory is `~/.sportscards`.

**Verified:** Automated tests cover preservation, repeat setup, managed updates, malformed TOML, and conflicting settings.
They also check manual fields, argument changes, TOML table boundaries, exact backup bytes, and custom data directories.
The setup check verifies the real SDK connection on the machine where it runs.
It does not establish browser availability or complete marketplace access.
