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
An unmanaged `mcp_servers.sportscards` entry causes setup to stop without replacing it.
Use the [manual configuration guide](MCP.md) to review that entry.
Only remove a conflicting entry after saving its settings.

If Codex cannot find the tools, confirm that its workspace is this checkout.
Check whether project trust or an administrator policy prevents local MCP servers.
Use manual configuration when your client does not load project settings.
For a custom data directory, configure the same `SPORTSCARDS_DATA` value for the dashboard and MCP server.
The default directory is `~/.sportscards`.

**Verified:** Automated tests cover preservation, repeat setup, managed updates, malformed TOML, and conflicting settings.
The setup check verifies the real SDK connection on the machine where it runs.
It does not establish browser availability or complete marketplace access.
