# Connect SportsCards to Codex

SportsCards provides 12 local MCP tools. No eBay developer account or API key is required.
Each person runs a separate server with their own collection and Codex account.
The server does not contact eBay, read browser credentials, or publish listings.

## Install

1. Open a terminal in the repository directory.
2. Create the Python environment.

   ```sh
   python -m venv .venv
   ```

3. Install the MCP dependencies.

   Windows PowerShell:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements-mcp.txt
   ```

   macOS or Linux:

   ```sh
   .venv/bin/python -m pip install -r requirements-mcp.txt
   ```

The [dashboard setup](../README.md) also installs these dependencies.
The MCP server does not require Node.js or a running dashboard.

## Configure Codex

1. Open `~/.codex/config.toml`.
2. Add the configuration for your operating system.
3. Replace each repository path with its absolute path on your computer.

Windows example:

```toml
[mcp_servers.sportscards]
command = 'C:/path/to/sportscards-codex/.venv/Scripts/python.exe'
args = ['-m', 'server.mcp']
cwd = 'C:/path/to/sportscards-codex'
startup_timeout_sec = 30
tool_timeout_sec = 120
```

macOS or Linux example:

```toml
[mcp_servers.sportscards]
command = '/path/to/sportscards-codex/.venv/bin/python'
args = ['-m', 'server.mcp']
cwd = '/path/to/sportscards-codex'
startup_timeout_sec = 30
tool_timeout_sec = 120
```

4. Restart Codex.
5. Ask Codex to call the SportsCards `status` tool.

Codex starts the server through STDIO. The `cwd` setting lets Python find the `server` module.
See the [official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) for configuration details.

The default collection directory is `~/.sportscards`. The dashboard uses the same default.
To use another directory, add its absolute path to `args`:

```toml
args = ['-m', 'server.mcp', '--data', 'C:/path/to/my-private-cards']
```

The server also accepts `SPORTSCARDS_DATA`. The `--data` argument takes priority.
Use the same directory for the dashboard and MCP server.

## Tools

| Tool | Purpose | Writes local records |
| --- | --- | --- |
| `status` | Read health and record counts. | No |
| `list_cards` | Search card identities with `query`, `limit`, and `offset`. | No |
| `get_card` | Read a card, stored evidence, allocations, and analysis. | No |
| `portfolio_analysis` | Read collection analysis. | No |
| `pricing_report` | Read sold evidence, asking evidence, and modeled estimates. | No |
| `simulation_preview` | Estimate sale outcomes without saving a run. | No |
| `save_simulation` | Calculate and save a run with its input evidence. | Yes |
| `list_simulations` | Read saved run summaries. | No |
| `get_simulation` | Read a saved run and its original inputs. | No |
| `selling_prep` | Read and validate existing local listing drafts. | No |
| `add_purchase` | Save a supplied purchase record. | Yes |
| `record_active_listing` | Append supplied asking-price evidence after identity review. | Yes |

`add_purchase` does not buy a card. `record_active_listing` does not create an eBay listing or visit the source URL.
`selling_prep` does not create a draft. It validates the existing `listing-prep/current.json` file in the collection directory.

Use the dashboard to upload photos, review card identities, and edit card records.
The MCP server does not start the photo worker.
The dashboard server processes uploaded photos while it runs.

## Example requests

- “List my cards with unknown prices.”
- “Show the evidence and purchase cost for this card.”
- “Preview a 90-day sale scenario with 1,000 trials and seed 42.”
- “Save this simulation so I can compare it later.”
- “Record this purchase from the receipt details I provide.”
- “Record this asking price from the source I provide.”
- “Check my existing listing drafts for missing photos or evidence.”

An unknown value is not zero. Asking prices are not confirmed sale prices.
Simulation results are estimates from the stored evidence and assumptions.
The tools do not provide live market data.

Simulation options include `trials`, `seed`, `horizon_days`, `strategy`, `card_ids`, `listing_factor`, and `p30`.
Supported strategies are `individual`, `bundle`, `hold`, and `markdown`.
Omitted price assumptions use the saved pricing settings.
The default preview uses 1,000 trials, seed 42, and a 90-day horizon.

## Data and validation

The server calls a fixed set of local application functions and routes within its own process.
It opens no HTTP listener. It provides no arbitrary HTTP request tool or file access tool.
It keeps the dashboard session token inside the process.
Tool responses contain collection data that Codex needs for the requested task.

Input schemas reject unsupported fields and invalid types.
Application validators check evidence URLs, timestamps, card revisions, and purchase totals.
Mutation tools declare `readOnlyHint=false`. All tools declare `openWorldHint=false`.
Creating a new server initializes its local collection directory and database.

## Verification

**Verified:** The SDK tests initialize the actual STDIO server, list all tools, and call each tool.
The tests use a temporary synthetic collection.
They check schemas, invalid inputs, token exclusion, deterministic previews, and saved records.

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest tests/test_mcp.py -q
```

macOS or Linux:

```sh
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest tests/test_mcp.py -q
```

**Not Tested:** Every Codex client version and operating system.
The initial transport verification used Windows and Python 3.14.

The adapter pins `mcp==1.30.0`, the maintained v1 SDK with FastMCP.
The [official Python SDK documentation](https://py.sdk.modelcontextprotocol.io/v1/) describes that interface.
SDK v2 uses a different server interface.

## Troubleshooting

| Result | Action |
| --- | --- |
| Python cannot find `server.mcp`. | Set `cwd` to the repository directory. |
| Python cannot find `mcp`. | Install `requirements-mcp.txt` with the configured Python executable. |
| The collection is empty. | Check the data directory used by both processes. |
| A photo stays queued. | Start the dashboard server to run the photo worker. |
| A listing revision fails. | Read the current card before recording the evidence again. |
| The draft report is empty. | Prepare a local listing manifest before calling `selling_prep`. |

Running `python -m server.mcp` directly waits for MCP protocol input.
This behavior is normal. Codex supplies that input after it starts the server.
