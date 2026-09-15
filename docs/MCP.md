# Connect SportsCards to Codex

SportsCards provides 18 local MCP tools. No eBay developer account or API key is required.
Each person runs a separate server with their own collection and Codex account.
The server does not contact eBay, read browser credentials, or publish listings.

## Install

For automatic dashboard installation and project configuration, use [Install and connect](INSTALL.md).
The steps below also support an MCP-only installation.

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

Automatic setup creates `.codex/config.toml` inside the project.
Use that project file when changing an automatic setup.
The following manual instructions use your global configuration instead.
Avoid conflicting SportsCards entries in both files.

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
| `list_observations` | Read observation IDs, crop revisions, and parent photo review states. | No |
| `create_card` | Create a physical card from an unlinked observation and owner-confirmed details. | Yes |
| `update_card` | Update selected card fields at the current revision. | Yes |
| `link_observation` | Link another reviewed view of the same physical card. | Yes |
| `portfolio_analysis` | Read collection analysis. | No |
| `pricing_report` | Read sold evidence, asking evidence, and modeled estimates. | No |
| `simulation_preview` | Estimate sale outcomes without saving a run. | No |
| `save_simulation` | Calculate and save a run with its input evidence. | Yes |
| `list_simulations` | Read saved run summaries. | No |
| `get_simulation` | Read a saved run and its original inputs. | No |
| `selling_prep` | Read and validate existing local listing drafts. | No |
| `add_purchase` | Save a supplied purchase record. | Yes |
| `record_active_listing` | Append supplied asking-price evidence after identity review. | Yes |
| `record_sold_comparable` | Save reviewed sold evidence with a confirmed transaction price. | Yes |
| `save_listing_draft` | Create or replace one local listing draft with validated photos. | Yes |

`add_purchase` does not buy a card. `record_active_listing` does not create an eBay listing or visit the source URL.
`selling_prep` does not create a draft. It validates the existing `listing-prep/current.json` file in the collection directory.
`save_listing_draft` creates or updates that local file. It does not publish the draft.

Use the dashboard to upload photos, correct crops, and complete each parent photo review.
Codex can create cards, update card details, and link observations through the MCP tools after evidence review.
The MCP server does not start the photo worker.
The dashboard server processes uploaded photos while it runs.

## Create and update cards

1. Call `list_observations` to find the uploaded card views.
2. Inspect the selected crop before recording its identity or side.
3. Preserve the observation ID and its `crop_revision`.
4. Call `create_card` with the confirmed card details and `confirmation`.
5. Read the returned card ID and revision.
6. Call `link_observation` for a reviewed second view of that same physical card.

An observation represents one view. A card record represents one physical card.
`create_card` rejects an observation already linked to a card.
`link_observation` rejects an observation that belongs to another card.
It requires `same_physical_card_confirmed=true` and the current card and crop revisions.
A successful link increases the card revision.

`confirmation` contains `identity_confirmed`, `condition_confirmed`, and a `source_note` from the owner confirmation.
Use an applicable earlier owner statement when it still describes the card.
A professional grade also requires `grade_label_confirmed=true`.
The tools do not establish a grade from an image.
Unknown identity fields can remain empty.

Call `update_card` with the current `revision`, selected `changes`, and `confirmation`.
Unspecified card fields remain unchanged. Successful updates increase the revision.
The card retains the condition source. The audit record retains the supplied confirmation.
Identity changes can invalidate earlier market evidence.

## Record sold evidence

1. Inspect the source for the exact card and actual transaction price.
2. Read the card's current revision.
3. Call `record_sold_comparable` with that revision and the source evidence.

The tool requires an exact-match note, condition evidence, source title, URL, sale date, and positive price in cents.
Set `match_reviewed` and `transaction_price_confirmed` only when the evidence supports both statements.
The tool rejects a future date, an invalid date, and a stale card revision.
An undisclosed accepted offer cannot supply a confirmed transaction price.
Use `shipping_known=false` when shipping remains unknown. The pricing engine excludes unsupported price evidence.

## Save listing drafts

1. Read `get_card` for the current card revision and linked observations.
2. Review one front crop and one back crop.
3. Complete both parent photo reviews through the dashboard.
4. Call `selling_prep` to read `manifest_sha256`.
5. Call `save_listing_draft` with the draft and `expected_manifest_sha256`.
6. Read the returned validation report before describing the draft as ready.

Use `expected_manifest_sha256=null` only when no draft manifest exists.
For an existing manifest, supply its current hash.
The tool rejects a stale hash to prevent replacement of another saved change.
It preserves drafts for other cards and replaces only the selected card's draft.

The draft requires current `card_revision`, reviewed title and description, condition, item specifics, price, shipping, and two observation IDs.
List the observation IDs in front, then back order.
Set `condition_confirmed`, `terms_confirmed`, and `photos_reviewed` only after those reviews.
Record the owner condition source in `condition_source`.

The server calculates the identity signature and SHA256 hashes from the stored card and selected crop files.
It validates the candidate with the existing listing validator before replacing the manifest.
Invalid crop paths, missing files, stale card revisions, incomplete photo reviews, and invalid prices prevent the save.

Use `status="draft"` or `status="needs_review"` while the final draft review remains incomplete.
All other draft requirements still apply.
Use `status="ready"` only after the final review.
The validator checks the stored identity and crop hashes again whenever `selling_prep` reads the draft.

Fixed-price drafts use `listing_format="fixed_price"`.
Auction drafts use `listing_format="auction"` with `duration_days` of `1`, `3`, `5`, `7`, or `10`.
An auction requires a positive starting bid and no `minimum_offer_cents`.
The tool does not support reserve prices or an auction Buy It Now price.

## Example requests

- “List my cards with unknown prices.”
- “Show the evidence and purchase cost for this card.”
- “Preview a 90-day sale scenario with 1,000 trials and seed 42.”
- “Save this simulation so I can compare it later.”
- “Record this purchase from the receipt details I provide.”
- “Record this asking price from the source I provide.”
- “Create this card from the reviewed front photo using my confirmed card details.”
- “Link this back photo to the same physical card.”
- “Record this completed sale and its confirmed transaction price.”
- “Save a listing draft from these reviewed photos and confirmed terms.”
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
Draft saves validate the candidate before an atomic file replacement within the private collection directory.
Mutation tools declare `readOnlyHint=false`. All tools declare `openWorldHint=false`.
Creating a new server initializes its local collection directory and database.

## Verification

**Verified:** The SDK tests initialize the actual STDIO server, list all tools, and call each tool.
The tests use a temporary synthetic collection.
They check schemas, invalid inputs, token exclusion, deterministic previews, and saved records.
They also check owner confirmations, grade-label evidence, card and crop revisions, sold evidence, draft conflicts, and photo validation.

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
| The draft report is empty. | Use `save_listing_draft` to create a reviewed local draft. |
| A draft save reports a changed batch. | Read `selling_prep` and use its current `manifest_sha256`. |
| A card or crop revision fails. | Read and review the current record before retrying. |

Running `python -m server.mcp` directly waits for MCP protocol input.
This behavior is normal. Codex supplies that input after it starts the server.
