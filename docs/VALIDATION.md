# Update validation record

Verified on 2026-09-15 UTC. The five improvements were published in priority order.
All test collections, card images, purchases, and market evidence were synthetic.

| Priority | Update | Verification |
| --- | --- | --- |
| 1 | [Installation](INSTALL.md) | Fresh checkout installation and dashboard build passed. The real MCP SDK initialized the server, discovered its tools, and read temporary collection status. All 17 setup tests passed, including custom storage, preserved settings, and TOML boundaries. |
| 2 | [Browser setup](BROWSER_SETUP.md) | Instructions were checked against official Codex documentation. A Chrome connection check opened and read Example Domain. Local documentation links and anchors resolved. |
| 3 | [MCP tools](MCP.md) | Real STDIO tests covered card creation and editing, photo linking, sold comparisons, and draft saving. Rejection checks covered stale revisions, conflicting drafts, and invalid photos. The installed server exposed 18 tools. |
| 4 | [Backup and updates](UPDATING.md) | Backup and restore tests compared records and file hashes. They checked committed WAL data, damaged backups, missing media, unsafe paths, and overwrite refusal. On Windows, 18 tests passed and one symlink test was skipped because the account could not create symlinks. The Linux CI run passed. |
| 5 | [Synthetic walkthrough](WALKTHROUGH.md) | Six generator tests passed. They checked counts, linked images, unknown values, evidence, repeatable simulation results, the listing ZIP, and overwrite refusal. Chrome showed the generated collection, analysis, pricing engine, saved simulation, and ready draft. No browser console warnings or errors were recorded. |

The final local suite passed **202 tests**, with **one Windows symlink test skipped**.
The production dashboard build passed.
The [GitHub Actions history](https://github.com/karimitouraj-hub/sportscards-codex/actions) records checks for each published commit.
CI runs the full Python suite and dashboard build on Ubuntu with Python 3.12 and Node.js 22.
It also generates project MCP configuration and checks the real SDK connection.

These checks verify local application behavior and the documented browser connection test.
They do not establish marketplace submission, actual client workspace trust, every phone image format, or future card prices.
