# Sri Lanka Card Offers Hub

Unofficial, auto-updating aggregator of Sri Lankan bank card offers. Pulls
directly from each bank's own public API, normalizes into one schema,
dedupes, and publishes as JSON + a static searchable site — refreshed weekly
by GitHub Actions.

**Not affiliated with any bank.** Data may be incomplete, stale, or wrong —
always confirm terms on the bank's own site before relying on an offer.

## Live sources

| Bank | Source | Type | Endpoint |
|---|---|---|---|
| Sampath Bank | `sampath_api` | JSON API | `card-promotions` (Premium/VISA/Mastercard categories) |
| HNB | `hnb_venus_api` | JSON API | `get_all_web_card_promos` (credit + debit, fully paginated) |
| Visa | `visa_perks_api` | JSON API | `portal/perks` (offers/promotions/benefits) |
| Commercial Bank | `combank_html` | HTML scrape | `rewards-promotions` page |
| Nations Trust Bank | `ntb_html` | HTML scrape | `promotions` hub |
| Amex | `amex_html` | HTML scrape | `supermarket-offers` page |

Each of these was reverse-engineered and verified live on 2026-09-14 — see
the sibling docs repos under [Cookie-Cat21](https://github.com/Cookie-Cat21)
for the full research: [sampath-api-docs](https://github.com/Cookie-Cat21/sampath-api-docs),
[hnb-venus-api-docs](https://github.com/Cookie-Cat21/hnb-venus-api-docs),
[visa-lk-perks-api-docs](https://github.com/Cookie-Cat21/visa-lk-perks-api-docs),
[combank-api-docs](https://github.com/Cookie-Cat21/combank-api-docs),
[ntb-amex-offers-docs](https://github.com/Cookie-Cat21/ntb-amex-offers-docs).

Several of these needed non-obvious fixes that a naive integration would
have missed silently:
- **Sampath** returns a clean `200` with `{"data": [], "total": N}` unless
  the request also carries `locale: en` + `platform: web` headers — a
  false-healthy response, not an error.
- **Visa** needs a fully-populated `perkTypeRequests` array in the POST
  body (not just `siteId`), a `Content-Type: application/json` header, and
  a request `limit` of `1000` — `500` silently truncates the real total
  (641), and `2000`+ makes the API return nothing at all.
- **Amex**'s old catalog URL (`/en-lk/benefits/consumer/supermarket-offers/`)
  is dead — served an Incapsula error page, confirmed with a real browser
  too, not just a bot block. Real path is `/en/offers/supermarket-offers`.

### Known issue: ComBank/NTB block GitHub Actions' IPs

Both work fine run from a normal residential IP, but consistently return
`403` when the weekly workflow runs them from a GitHub Actions runner
(GitHub's runner IP ranges are commonly blocklisted by WAFs since they're
a frequent source of scraping traffic) — this isn't a bug in the parser,
it's an IP-based block on the runner itself. **Not working around it**
with a proxy or spoofed origin — same call as the PABC/Sucuri decision:
if a site blocks the automation's actual network, that's the site's
call to make.

To avoid the obvious failure mode this exposed — a blocked fetch
silently overwriting good data with nothing — `aggregate.py` loads the
previous run's `data/offers.json`, and any source that comes back empty
falls back to its last-known-good offers instead of vanishing from the
feed. This actually happened on this repo's very first scheduled run:
the initial push succeeded (real IP), the very next automated run wiped
190 ComBank/NTB offers before the fallback existed. The site now surfaces
a `stale_sources` warning banner when this happens, so a viewer can see
data is cached rather than assuming everything is current.

### HTML scrapers

`scripts/html_sources.py` has one `html.parser.HTMLParser` subclass per
site (`ComBankParser`, `NtbParser`, `AmexParser`) — no external
dependencies. These are inherently more fragile than the JSON sources: if
a bank redesigns its offers page, the parser won't crash, it'll silently
return fewer (or zero) offers. `aggregate.py` logs a warning if any
HTML source returns suspiciously few offers (below a rough expected
floor), so a redesign shows up in the Action logs instead of just quietly
degrading. Validity dates are extracted from free-form prose ("Valid on
2nd, 16th and 30th September 2026") with a best-effort regex that takes
the *last* date mentioned — correct for the common "valid until X" phrasing,
not guaranteed for every wording a bank might use.

## Deliberately not included

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
  "bank": "Sampath Bank | HNB | Visa | Commercial Bank | Nations Trust Bank | Amex",
  "source": "sampath_api | hnb_venus_api | visa_perks_api | combank_html | ntb_html | amex_html",
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
