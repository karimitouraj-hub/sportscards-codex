# Collection workflow

Use the dashboard for visual review and the MCP server for supported local operations.
Use your own browser session for authorized marketplace research or publication.
Read [MCP setup](MCP.md) for installation and tool details.

## Review photos

1. Open **Photo inbox**.
2. Upload your card photos.
3. Review each detected rectangle.
4. Correct the crop or add a missed observation.
5. Set each observation to the front or back.
6. Link repeated views to the existing physical card.
7. Confirm the card details from clear evidence.
8. Mark each parent photo reviewed when the review is complete.

An observation is one view of a card. A card record represents one physical card.
Two photos of one card do not create two inventory items.
Two separate copies of the same variant require separate card records.
Compare the player, card number, set, variant, serial number, and visible features before linking views.

Supported still-image formats are JPEG, PNG, WebP, HEIC, and HEIF.
Each upload selection accepts up to 20 photos.
Each file has a 40 MB limit. The collection has a 250-observation limit.
Original photo bytes remain unchanged. Crop corrections create new crop files.
Actual camera files can differ from synthetic format tests.

Local OCR provides unconfirmed text when its optional system dependency is available.
It does not establish card identity or condition.
Reflections, sleeves, and compression can resemble defects.
Request a clearer view when the evidence cannot distinguish them.

## Record purchases

1. Open **Purchases**.
2. Select **Add purchase** to enter a purchase record.
3. Preserve the quantity, refunds, and source reference.
4. Compare each purchase with the confirmed physical card.
5. Allocate the recorded cost only when the match has sufficient evidence.
6. Record the method for any estimated lot allocation.

A purchase may contain cards outside the current collection.
Purchase records currently use USD only. Preserve other currencies in your source evidence instead of entering them as USD amounts.
An unallocated purchase does not create new card inventory.
Unknown purchase costs remain unknown.
Do not substitute an asking price, sold comparison, or zero for a missing purchase cost.

## Save market evidence

1. Review the exact card identity before research.
2. Search through a marketplace interface you can access.
3. Inspect the source page for each candidate comparison.
4. Record its URL, date, currency, price, shipping, and matching details.
5. Identify the record as a completed sale or an active listing.
6. Record exclusions and unsuccessful searches when useful.

Compare the set, year, player, number, parallel, print run, autograph, memorabilia, and raw or graded state.
Exclude mismatched variants and lots from single-card comparisons.
A seller asking price does not establish a sale.
A disappeared listing does not prove a sale.
An undisclosed accepted offer does not establish its transaction price.
Keep direct quotations distinct from your observations and estimates.

The application does not refresh saved marketplace evidence automatically.
An identity change can make earlier evidence ineligible until reviewed again.
The engine uses a 90-day sold-evidence window and a 14-day active-listing window.

## Compare scenarios

1. Open **Analysis** to inspect sold evidence and purchase allocations.
2. Review the selling cost assumptions.
3. Open **Engine** to inspect asking references and evidence coverage.
4. Select cards for a simulation.
5. Choose the strategy and time horizon.
6. Review the sale-probability and price assumptions.
7. Run the simulation.
8. Inspect the saved inputs before interpreting the result.

Unknown values remain outside the modeled price total.
Simulated cash and retained inventory value describe different measures.
Read [Pricing engine](PRICING_ENGINE.md) before using scenario results for a selling decision.

## Prepare and publish listings

1. Select the physical cards for sale.
2. Confirm the current condition with the owner or an existing explicit condition statement.
3. Select one confirmed front crop and one confirmed back crop for each card.
4. Prepare the title, description, item details, price, shipping, and sale format.
5. Review the local draft and its validation blockers.
6. Download the ready listing package when available.
7. Use your marketplace browser session to complete the authorized publication.
8. Verify the resulting listing before recording it as live.

Codex can create and update private drafts with `save_listing_draft`.
The tool calculates identity signatures and photo hashes, then validates the candidate before saving it.
Read `selling_prep` first and supply its current `manifest_sha256` to prevent conflicting updates.
Supply the current card revision and the reviewed front and back observation IDs.
The MCP tools do not publish listings.
Codex needs compatible browser tools to operate a signed-in marketplace page.
You can also publish the prepared package yourself.

Reuse authorization that still applies to the exact cards, terms, and action.
Request clarification only when a material detail or authorization is missing.
After an uncertain submission, inspect the account before retrying to prevent a duplicate listing.

Do not infer a professional grade from photos.
Describe supported facts without inventing defects, authenticity, provenance, or condition assurances.
Keep purchase costs and internal price guidance out of buyer-facing listing text.

### Private draft file

The application reads `listing-prep/current.json` inside the private collection directory.
The dashboard displays this file. The MCP `save_listing_draft` tool provides validated draft editing.
Use the MCP tool for routine changes.
The structure below documents the advanced local file format.

Use this structure with values from the actual reviewed collection:

```json
{
  "batch_id": "my-reviewed-batch",
  "created_at": "2026-09-14T12:00:00Z",
  "drafts": [
    {
      "card_id": "REPLACE_WITH_CARD_ID",
      "title": "REPLACE_WITH_REVIEWED_TITLE",
      "description": "REPLACE_WITH_REVIEWED_DESCRIPTION",
      "condition": "REPLACE_WITH_CONFIRMED_CONDITION",
      "specifics": {"Player": "REPLACE_WITH_PLAYER"},
      "listing_format": "fixed_price",
      "price_cents": 2000,
      "shipping_cents": 400,
      "minimum_offer_cents": null,
      "identity_signature": "REPLACE_WITH_CURRENT_IDENTITY_SIGNATURE",
      "photo_observation_ids": ["REPLACE_WITH_FRONT_ID", "REPLACE_WITH_BACK_ID"],
      "photo_sha256": {
        "REPLACE_WITH_FRONT_ID": "REPLACE_WITH_FRONT_FILE_SHA256",
        "REPLACE_WITH_BACK_ID": "REPLACE_WITH_BACK_FILE_SHA256"
      },
      "status": "draft"
    }
  ]
}
```

The prices and timestamp above are synthetic examples, not recommended terms.
Replace all placeholders before using the file.
Use `server.analysis.signature(card)` to calculate the current identity signature.
Calculate each SHA256 hash from the selected crop file bytes.
Use the stored observation IDs in front, then back order.
Both observations must be confirmed and linked to the same physical card.
Their parent photos must have completed review.

The validator requires each crop to reach 500 pixels on its longest side and remain within its 12 MB file limit.
This local validation does not establish current marketplace photo rules.
Do not rescale a poor photo merely to clear the check.
Use a clearer source photo when needed.

Keep `status` as `draft` or `needs_review` while questions remain.
Set it to `ready` after the evidence, photos, condition, and terms pass review.
Inspect `selling_prep` or **Selling prep** for remaining blockers.

For an auction, use `listing_format: "auction"` and an allowed `duration_days`: `1`, `3`, `5`, `7`, or `10`.
`price_cents` then means the starting bid.
Auction drafts require a positive starting bid.
Set `minimum_offer_cents`, `reserve_price_cents`, and `buy_it_now_price_cents` to `null`.
These are local draft constraints, not a statement of all marketplace options.

The [draft validator](../server/selling_prep.py) defines the full format.
The [synthetic tests](../tests/test_selling_prep.py) show valid examples and rejected drafts.

## Keep private data local

The default data directory is `.sportscards` in your home directory.
`SPORTSCARDS_DATA` can select another private directory.
Use a location outside the repository.

The backup command requires a new destination directory outside the collection directory:

```text
python scripts/backup.py --source /path/to/private-collection --destination /path/to/new-backup
```

Replace both paths with your own locations.
Run the command with the project Python interpreter.
Keep collection backups and browser account data out of public GitHub attachments.
