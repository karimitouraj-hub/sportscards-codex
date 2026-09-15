# SportsCards for Codex

A free, open-source card collection workspace for people who use their own Codex.
It includes a local dashboard, an MCP server, and a Codex skill.
No eBay developer account or project API key is required.

Use it to review card photos, record purchases, save market evidence, compare sale scenarios, and prepare listing drafts.
Each person keeps their collection and account access on their own computer.

## What it does

| Component | Purpose |
| --- | --- |
| Dashboard | Review photos, physical cards, purchases, evidence, simulations, and listing drafts. |
| MCP server | Give Codex tools for the local collection. |
| Codex skill | Guide photo review, evidence checks, purchase matching, and listing preparation. |
| Your browser | Review signed-in marketplace pages and complete authorized account actions. |

The MCP server does not connect to eBay or reuse your browser login.
Browser work requires compatible browser tools in your Codex environment.
See [Browser setup and manual fallback](docs/BROWSER_SETUP.md).
You can also enter evidence manually.
This project does not include browser tools, automatic marketplace synchronization, or a hosted AI service.

## Start the dashboard

Requirements: Git, Python 3.11 or later, and Node.js 22 or later with npm.
Use your own Codex access for the assistant workflow.

1. Clone the repository.

   ```text
   git clone https://github.com/karimitouraj-hub/sportscards-codex.git
   ```

2. Enter the project directory.

   ```text
   cd sportscards-codex
   ```

3. Install the application and configure its local MCP connection.

   ```text
   python scripts/setup.py
   ```

4. Start the application.

   ```text
   python scripts/start.py
   ```

5. Open [http://127.0.0.1:8097](http://127.0.0.1:8097).

On systems that use `python3`, use `python3 scripts/start.py`.
Setup creates `.venv`, installs dependencies, builds the dashboard, and verifies the MCP connection.
Read [installation and repair](docs/INSTALL.md) for setup checks and configuration details.
The first launch requires internet access for dependency downloads.
Press `Ctrl+C` in the terminal to stop the application.

The application starts with an empty collection.
Upload your own photos through **Photo inbox**.
Read the [collection workflow](docs/WORKFLOW.md) for the next steps.
To try the full workflow first, use the [synthetic collection walkthrough](docs/WALKTHROUGH.md).
It includes generated photos, example evidence, a saved simulation, and a ready listing draft.

## Connect Codex

1. Open this repository as your Codex workspace.
2. Use the project configuration created by setup, or follow [manual MCP setup](docs/MCP.md).
3. Start a new Codex conversation after registration.
4. Ask Codex to use `$sportscards`.

The project skill is [`.agents/skills/sportscards/SKILL.md`](.agents/skills/sportscards/SKILL.md).
Example requests:

```text
Use $sportscards. Review these photos and link repeated views to the same physical card.
```

```text
Use $sportscards. Match these purchase records to my confirmed cards. Leave uncertain matches unresolved.
```

```text
Use $sportscards. Prepare listing drafts for my selected cards using my confirmed condition and shipping choices.
```

Without browser tools, Codex can use the local MCP tools and evidence you provide.
Marketplace research and publication through Codex require a separate browser capability.
Signing into eBay does not turn this MCP server into an eBay API client.

## Data and limits

Private data defaults to `.sportscards` in your home directory.
Use setup's `--data-dir` option to select another directory outside this repository.
Start the dashboard with the matching command that setup prints.
An explicit data-directory argument overrides `SPORTSCARDS_DATA`.
Keep photos, purchase exports, account records, browser sessions, and backups out of Git.
The dashboard has no account login and binds to the local computer by default.
Do not expose its port to the public internet.

Photo detection and optional OCR produce proposals that need review.
They do not establish identity, authenticity, condition, or professional grade.
Sold evidence, asking prices, purchase costs, and simulated values remain separate.
The [pricing engine](docs/PRICING_ENGINE.md) uses explicit assumptions, not a validated price forecast.
Listing packages contain drafts and photos. They do not publish listings.

Use your own authorized marketplace access.
This project provides no bulk scraper or mechanism to bypass access controls or paywalls.

## Development

Read [Update and recover](docs/UPDATING.md) before updating an existing collection.

Install the project dependencies through the launcher before these checks.
Use the project interpreter for Python commands.

| Platform | Install test dependency | Run tests |
| --- | --- | --- |
| Windows | `.venv\Scripts\python.exe -m pip install pytest` | `.venv\Scripts\python.exe -m pytest -q` |
| macOS / Linux | `.venv/bin/python -m pip install pytest` | `.venv/bin/python -m pytest -q` |

Build the dashboard with `npm run build`.

Tests use synthetic fixtures and temporary collection directories.
CI checks the Python tests and dashboard build.
Real phone uploads and platform-specific behavior require separate verification.
See the [update validation record](docs/VALIDATION.md) for the five published improvements.

Contributions are welcome. Include reproduction steps and relevant verification results.
Use synthetic cards and account records in issues, screenshots, tests, and examples.

Released under the [MIT License](LICENSE).
This community project has no affiliation with eBay or OpenAI.
