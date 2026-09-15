# Browser setup for Codex

SportsCards uses browser tools for marketplace research and authorized listing work.
Its MCP server handles local collection records. It does not connect to eBay or read browser credentials.
No eBay developer account or API key is required by this workflow.

**Verified:** Official setup documentation checked on 2026-09-14.
The connected Chrome route passed the rendered **Example Domain** check during release validation.
**Not Tested:** A fresh browser installation on every platform or account, or successful eBay automation for every user.
Browser availability depends on your Codex client, rollout, and workspace settings.

## Choose a browser route

| Your setup | Route |
| --- | --- |
| Codex in the ChatGPT desktop app | Use the built-in `@Browser`, or connect your regular browser below. |
| Codex CLI or IDE extension | The built-in Browser is unavailable. Use a separately configured browser tool or the manual workflow below. |
| No usable browser tool | Keep the local MCP connection. Enter evidence and publish listings manually. |

OpenAI describes these client limits in [Browser](https://learn.chatgpt.com/docs/browser).

Installing the SportsCards skill does not install browser tools.
The CLI `/plugins` menu can install compatible plugins, but desktop-only plugins still require the desktop app.
The IDE extension does not support plugins.
See [Plugins](https://learn.chatgpt.com/docs/plugins).

## Connect your regular Chrome or Edge browser

This route can use the browser profile where you already signed into eBay.

1. Update the ChatGPT desktop app.
2. Open **Settings > Computer Use**.
3. Select Chrome or Edge.
4. Install the requested plugin.
5. Select **Install** to open the extension store.
6. Install the ChatGPT extension.
7. Return to settings and confirm that **Manage** appears.
8. Enable the browser toggle.
9. Start a new Codex chat with the extension's browser profile.
10. Select `@Chrome` or `@Edge` from the mention menu.

Use **More browsers** for other listed browsers.
Review site permissions through **Manage**.
These steps follow the [official extension setup](https://learn.chatgpt.com/docs/chrome-extension).

Sign into eBay yourself in that browser when needed.
Complete authentication and account challenges through the website.
Do not paste passwords, authentication codes, cookies, or session tokens into chat or project configuration.
SportsCards has no credential-import step.

## Use the built-in browser

The desktop app includes `@Browser` without a separate extension installation.
Use this prompt after starting the dashboard:

```text
@Browser open http://127.0.0.1:8097 and report the visible page title.
```

Its separate profile does not inherit your regular browser login.
Sign in directly when needed.
The documented built-in browser cannot automate file uploads.
Upload card photos yourself when needed, or use a supported upload method in your connected regular browser.
See [Browser operations and limits](https://learn.chatgpt.com/docs/browser).

Computer Use is a separate desktop capability on supported macOS and Windows setups.
If needed, open **Plugins > Computer Use** and install or enable it.
Enable its server and skill switches.
On macOS, grant the requested Screen Recording and Accessibility permissions.
For native Windows app control, keep the target app visible on the active desktop.
See [Computer Use setup](https://learn.chatgpt.com/docs/computer-use).

## Check the connection

Run these checks before a marketplace task.
Use the browser mention that you selected above.

1. Ask Codex which browser tools are available in the current chat.
2. Ask it to open `https://example.com` and report the visible heading.
3. Confirm that it reports **Example Domain** from the rendered page.
4. Open eBay yourself in the same browser profile.
5. Ask Codex to report only whether that page is signed in.
6. Confirm that the result matches the page you see.
7. Ask Codex to call the SportsCards `status` tool separately.

Expected results:

- [ ] Codex can inspect the selected browser page through an available tool.
- [ ] The selected browser contains the intended eBay session.
- [ ] The SportsCards `status` call succeeds for your local collection.
- [ ] `ebay_connected` remains `false` in the MCP status result. This is expected.
- [ ] The dashboard opens on the computer running SportsCards.

An MCP connection test does not test browser access.
A browser page title supplied from memory does not establish a working connection.
The checks above do not require a purchase, a listing, or an account change.

## Research cards through your browser

Use a bounded request such as:

```text
Use $sportscards and @Chrome. Research these selected cards through pages
I can access. Record exact matches, source URLs, dates, currency, and buyer
shipping. Separate sold transactions from active asking prices.
Keep uncertain matches unresolved.
```

Inspect the actual source page before saving evidence.
Match the year, set, player, number, variant, print run, and raw or graded state.
Do not treat an active ask, undisclosed accepted offer, or disappeared listing as a verified sale price.
Use the [collection workflow](WORKFLOW.md#save-market-evidence) for evidence review rules.

If the website blocks automation, continue with the manual workflow.
This project provides no scraping service, hidden API, or access-control bypass.

## Manual workflow

This route works without Codex browser access.

1. Open the marketplace in your own browser.
2. Inspect the exact card and source record.
3. Copy the source URL and relevant visible facts.
4. Give Codex the facts or an appropriate screenshot.
5. Identify each record as a completed sale, active ask, or purchase.
6. Review the proposed local record before saving it.

Useful evidence fields:

| Field | What to record |
| --- | --- |
| Source | Page URL and source title |
| Timing | Observation date and displayed sale date, when available |
| Price | Visible amount, currency, and buyer shipping |
| Identity | Card details that support the match |
| Limits | Unknown shipping, hidden sale price, unclear variant, or other missing evidence |

Keep missing amounts unknown.
Remove unrelated account details from screenshots.
Keep research captures and purchase records outside the public repository.
Supported local tools appear in [MCP setup](MCP.md#tools).

For listing publication:

1. Prepare the local draft through the [listing workflow](WORKFLOW.md#prepare-and-publish-listings).
2. Download the ready listing package from **Selling prep**.
3. Enter the reviewed text and terms in your marketplace listing form.
4. Upload the matching front and back photos.
5. Inspect the final photos, condition, price, and shipping.
6. Publish the listing yourself.
7. Verify the resulting listing and save its URL in your private records.

If Codex has browser access, it can perform authorized steps within your stated terms.
Existing authorization still applies when the cards, terms, and action remain the same.
Browser or workspace controls can require their own access prompts.
After an uncertain submission, inspect the account before retrying to prevent duplicate listings.

## Troubleshooting

| Problem | Action |
| --- | --- |
| Chrome or Edge is missing from mentions | Check the browser toggle and active extension profile. |
| The extension cannot connect | Update the desktop app, restart the browser, then start a new chat. |
| The selected site is blocked | Review its entry under **Settings > Computer Use > Manage**. |
| Chrome cannot upload a local photo | Open the extension details and check **Allow access to file URLs**. |

See [extension troubleshooting](https://learn.chatgpt.com/docs/chrome-extension) for further steps.

| Problem | Action |
| --- | --- |
| The built-in browser asks for a new login | Sign in there, or select your connected regular browser. |
| MCP works but eBay does not | Check browser setup separately. The MCP server has no eBay connection. |
| Browser tools are absent in this client | Use a supported desktop setup or the manual workflow. |
| The dashboard cannot open | Start SportsCards on the same computer and use the URL printed by its launcher. |
| A site requires a CAPTCHA or account check | Complete the website step yourself. Continue manually if access remains blocked. |
| A workspace control disables browser access | Use the manual workflow or ask your administrator about availability. |

Keep the dashboard local. Publishing its port is not a browser connection fix.
