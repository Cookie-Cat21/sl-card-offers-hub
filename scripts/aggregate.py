#!/usr/bin/env python3
"""Pulls live card offers from verified Sri Lanka bank APIs and writes a
single normalized, deduplicated feed to data/offers.json.

Sources (v1 — all clean JSON APIs, no HTML scraping):
  - Sampath Bank card-promotions API (3 categories)
  - HNB Venus card-promo API (credit + debit, fully paginated)
  - Visa LK perks API (offers/promotions/benefits)

Each source's request shape (headers, body, pagination) was reverse-engineered
and verified live on 2026-09-14 — see the sibling *-docs repos under
Cookie-Cat21 (sampath-api-docs, hnb-venus-api-docs, visa-lk-perks-api-docs)
for the full research notes and catalog entries this script is based on.

Deliberately NOT included yet (needs real HTML-parsing work, not just a
request fix): ComBank rewards-promotions, NTB promotions hub, Amex
supermarket offers. PABC, StanChart/HSBC and MyPromo are excluded because
those sources are dead, WAF-blocked, or ToS-blocked upstream — see
pabc-card-offers-docs / sc-hsbc-offers-park-docs / mypromo-park-docs.
"""
from __future__ import annotations

import codecs
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _cp1252_fallback(err: UnicodeDecodeError) -> tuple[str, int]:
    """Reinterpret just the invalid byte(s) as cp1252 instead of dropping
    them as U+FFFD, so an isolated bad byte in an otherwise-UTF-8 response
    doesn't corrupt into an unrecoverable replacement character."""
    bad = err.object[err.start:err.end]
    return bad.decode("cp1252", errors="replace"), err.end


codecs.register_error("cp1252_fallback", _cp1252_fallback)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "offers.json"
UA = "SlCardOffersHubBot/1.0 (+https://github.com/Cookie-Cat21/sl-card-offers-hub; educational, aggregates public bank offer listings)"
DELAY = 1.0


def decode_body(raw: bytes) -> str:
    # Some upstream APIs (observed on Sampath) mix UTF-8 with a stray raw
    # Windows-1252 byte (e.g. 0xAE for (R) instead of &reg;) inside an
    # otherwise-valid UTF-8 JSON response. Decoding the whole body as one
    # encoding or the other corrupts one side or the other; reinterpret
    # only the bad byte(s) as cp1252 and keep everything else as UTF-8.
    return raw.decode("utf-8", errors="cp1252_fallback")


def fetch(url: str, method: str = "GET", body: bytes | None = None, headers: dict | None = None) -> tuple[int, str]:
    h = {"User-Agent": UA, "Accept": "application/json,*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, decode_body(res.read())
    except urllib.error.HTTPError as e:
        return e.code, decode_body(e.read())
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def epoch_ms_to_iso(ms) -> str | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except (ValueError, TypeError):
        return None


def make_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def fetch_sampath() -> list[dict]:
    """Sampath card-promotions API. Needs headers locale/platform or it
    silently returns {"data":[],"total":N} with a 200 — see
    sampath-api-docs and sl-bank-card-offers-docs catalog notes."""
    categories = ["Premium_Offers", "VISA_Offers", "Mastercard_Offers"]
    headers = {"locale": "en", "platform": "web", "Accept": "application/json, text/plain, */*"}
    offers: list[dict] = []
    for category in categories:
        page = 1
        size = 50
        while True:
            url = f"https://www.sampath.lk/api/card-promotions?category={category}&page_number={page}&size={size}"
            status, text = fetch(url, headers=headers)
            time.sleep(DELAY)
            if status != 200:
                print(f"  [sampath] {category} page {page}: HTTP {status}")
                break
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                print(f"  [sampath] {category} page {page}: bad JSON")
                break
            rows = payload.get("data") or []
            if not rows:
                break
            for row in rows:
                offers.append({
                    "id": make_id("sampath", str(row.get("id"))),
                    "bank": "Sampath Bank",
                    "source": "sampath_api",
                    "card_type": None,
                    "category": category,
                    "title": row.get("company_name") or strip_html(row.get("short_description"))[:80],
                    "description": strip_html(row.get("promotion_details") or row.get("description")),
                    "discount": strip_html(row.get("short_discount") or row.get("discounts")),
                    "image_url": row.get("image_url"),
                    "valid_from": epoch_ms_to_iso(row.get("display_on")),
                    "valid_to": epoch_ms_to_iso(row.get("expire_on")),
                    "source_url": "https://www.sampath.lk/sampath-cards/credit-card-offer",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                })
            total = payload.get("total", 0)
            if page * size >= total:
                break
            page += 1
    print(f"  [sampath] {len(offers)} offers")
    return offers


def fetch_hnb() -> list[dict]:
    """HNB Venus card-promo API. Fully paginated, credit + debit."""
    offers: list[dict] = []
    for card_type in ["credit", "debit"]:
        page = 1
        limit = 100
        total_pages = None
        while total_pages is None or page <= total_pages:
            url = f"https://venus.hnb.lk/api/get_all_web_card_promos?page={page}&limit={limit}&cardType={card_type}"
            status, text = fetch(url)
            time.sleep(DELAY)
            if status != 200:
                print(f"  [hnb] {card_type} page {page}: HTTP {status}")
                break
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                print(f"  [hnb] {card_type} page {page}: bad JSON")
                break
            total = payload.get("total", 0)
            total_pages = -(-total // limit) if total else 0
            for row in payload.get("data") or []:
                offers.append({
                    "id": make_id("hnb", card_type, str(row.get("id"))),
                    "bank": "HNB",
                    "source": "hnb_venus_api",
                    "card_type": card_type,
                    "category": None,
                    "title": row.get("title"),
                    "description": strip_html(row.get("valid")),
                    "discount": None,
                    "image_url": row.get("thumb"),
                    "valid_from": None,
                    "valid_to": row.get("to"),
                    "source_url": "https://www.hnb.lk/cards/card-promotions",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                })
            page += 1
    print(f"  [hnb] {len(offers)} offers")
    return offers


def fetch_visa() -> list[dict]:
    """Visa LK perks API. Needs Content-Type: application/json (probe.py's
    generic harness omits it by default) and a populated perkTypeRequests
    array — see visa-lk-perks-api-docs catalog notes."""
    perk_types = ["OFFERS", "PROMOTIONS", "BENEFITS"]
    offers: list[dict] = []
    # limit=1000 was verified as the safe ceiling: >=2000 makes the API
    # return an empty result instead of erroring or truncating cleanly, and
    # 1000 already comes back under-full (641/1000 for OFFERS) confirming
    # it isn't truncating the real total. Re-verify this if perk counts grow.
    LIMIT = 1000
    for perk_type in perk_types:
        body = json.dumps({
            "siteId": "www.visa.com.lk",
            "perkTypeRequests": [
                {"requestIdentifier": None, "perkType": perk_type, "locale": "en_lk", "pageRequest": {"index": 0, "limit": LIMIT}}
            ],
        }).encode()
        status, text = fetch(
            "https://www.visa.com.lk/offers/api/portal/portal/perks/",
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        time.sleep(DELAY)
        if status != 200:
            print(f"  [visa] {perk_type}: HTTP {status}")
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            print(f"  [visa] {perk_type}: bad JSON")
            continue
        for group in payload.get("perksGroups") or []:
            if group.get("resultCount") == LIMIT:
                print(f"  [visa] WARNING: {perk_type} returned exactly the limit ({LIMIT}) — may be truncated, raise LIMIT and re-check")
            for row in group.get("perks") or []:
                offers.append({
                    "id": make_id("visa", str(row.get("sourceId")), perk_type),
                    "bank": "Visa",
                    "source": "visa_perks_api",
                    "card_type": None,
                    "category": perk_type,
                    "title": row.get("title"),
                    "description": strip_html(row.get("shortDescription")),
                    "discount": None,
                    "image_url": row.get("image"),
                    "valid_from": None,
                    "valid_to": None,
                    "source_url": "https://www.visa.com.lk/en_lk/visa-offers-and-perks/",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                })
    print(f"  [visa] {len(offers)} offers")
    return offers


def main() -> None:
    print("Fetching Sampath...")
    all_offers = fetch_sampath()
    print("Fetching HNB...")
    all_offers += fetch_hnb()
    print("Fetching Visa...")
    all_offers += fetch_visa()

    seen: set[str] = set()
    deduped = []
    for o in all_offers:
        if o["id"] in seen:
            continue
        seen.add(o["id"])
        deduped.append(o)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": ["sampath_api", "hnb_venus_api", "visa_perks_api"],
        "count": len(deduped),
        "offers": deduped,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(deduped)} offers to {OUT}")


if __name__ == "__main__":
    main()
