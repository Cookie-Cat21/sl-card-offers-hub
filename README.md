# Sri Lanka Card Offers Hub

Unofficial, auto-updating aggregator of Sri Lankan bank card offers. Pulls
directly from each bank's own public API, normalizes into one schema,
dedupes, and publishes as JSON + a static searchable site — refreshed weekly
by GitHub Actions.

**Not affiliated with any bank.** Data may be incomplete, stale, or wrong —
always confirm terms on the bank's own site before relying on an offer.

## Live sources (v1)

| Bank | Source | Endpoint |
|---|---|---|
| Sampath Bank | `sampath_api` | `card-promotions` (Premium/VISA/Mastercard categories) |
| HNB | `hnb_venus_api` | `get_all_web_card_promos` (credit + debit, fully paginated) |
| Visa | `visa_perks_api` | `portal/perks` (offers/promotions/benefits) |

Each of these was reverse-engineered and verified live on 2026-09-14 — see
the sibling docs repos under [Cookie-Cat21](https://github.com/Cookie-Cat21)
for the full research: [sampath-api-docs](https://github.com/Cookie-Cat21/sampath-api-docs),
[hnb-venus-api-docs](https://github.com/Cookie-Cat21/hnb-venus-api-docs),
[visa-lk-perks-api-docs](https://github.com/Cookie-Cat21/visa-lk-perks-api-docs).

Two of these sources needed non-obvious fixes that a naive integration would
have missed silently:
- **Sampath** returns a clean `200` with `{"data": [], "total": N}` unless
  the request also carries `locale: en` + `platform: web` headers — a
  false-healthy response, not an error.
- **Visa** needs a fully-populated `perkTypeRequests` array in the POST
  body (not just `siteId`), a `Content-Type: application/json` header, and
  a request `limit` of `1000` — `500` silently truncates the real total
  (641), and `2000`+ makes the API return nothing at all.

## Deliberately not included yet

- **ComBank, NTB, Amex** — real sources, but need actual HTML-parsing logic
  (none exists in this project yet). Adding one of these without a real
  parser would mean either scraping garbage or claiming coverage the repo
  doesn't have — skipped rather than faked.
- **PABC** — site blocks non-browser clients (Sucuri WAF challenge); see
  [pabc-card-offers-docs](https://github.com/Cookie-Cat21/pabc-card-offers-docs).
- **StanChart / HSBC retail** — both genuinely discontinued; HSBC retail
  was sold to NTB. See [sc-hsbc-offers-park-docs](https://github.com/Cookie-Cat21/sc-hsbc-offers-park-docs).
- **MyPromo.lk** — excluded on the aggregator's own ToS grounds; see
  [mypromo-park-docs](https://github.com/Cookie-Cat21/mypromo-park-docs).

## Schema

```json
{
  "id": "stable hash, dedup key",
  "bank": "Sampath Bank | HNB | Visa",
  "source": "sampath_api | hnb_venus_api | visa_perks_api",
  "card_type": "credit | debit | null",
  "category": "bank-specific category, or null",
  "title": "string",
  "description": "plain text, HTML tags stripped",
  "discount": "short discount string, or null",
  "image_url": "string or null",
  "valid_from": "ISO date or null",
  "valid_to": "ISO date or null",
  "source_url": "link back to the bank's own offers page",
  "fetched_at": "ISO timestamp of this pull"
}
```

## Running locally

```bash
pip install pyyaml  # if scripts grow a catalog dependency later; not needed today
python3 scripts/aggregate.py   # writes data/offers.json
python3 scripts/build_site.py  # writes site/index.html + site/offers.json
python3 -m http.server -d site 8000
```

## Automation

`.github/workflows/aggregate.yml` runs weekly (Monday 07:00 UTC, after the
source repos' own 06:00 probes), commits `data/offers.json` if it changed,
and deploys `site/` to GitHub Pages. Trigger it manually from the Actions
tab any time.

## Ethics

Public reads only — no login-gated data, no credential stuffing. Polite
rate limiting (1s between requests) matching the other Lankawa probe repos.
If a source starts blocking or ToS-restricts this, it gets dropped, not
worked around.
