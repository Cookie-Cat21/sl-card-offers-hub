"""HTML scrapers for ComBank, NTB, and Amex card offer pages.

Unlike the JSON-API sources in aggregate.py, these three have no API to
call — the offer list is only ever rendered as HTML. Each parser below is
built against the live page structure observed on 2026-09-14 and is
inherently more fragile than a JSON contract: if a bank redesigns its
offers page, the corresponding parser will need updating (it will likely
start silently returning 0 offers rather than crashing — see the
`min_expected` sanity check in fetch_html_sources()).

Uses only Python's stdlib html.parser — no new dependencies.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser


def _classes(attrs: dict) -> set[str]:
    return set((attrs.get("class") or "").split())


class _SectionCapture:
    """Generic depth-tracked text capture: start capturing a named field
    when a matching tag opens, keep capturing through arbitrarily nested
    children, stop exactly when that same tag closes — regardless of how
    many other tags open/close inside it. Handles the common HTML-scraping
    bug of a naive parser losing text because of one extra nested <span>."""

    def __init__(self):
        self.stack: list[tuple[str, int]] = []  # (field, depth_when_opened)

    def start(self, field: str, depth: int):
        self.stack.append((field, depth))

    def data(self, cur: dict, text: str):
        if self.stack and text.strip():
            field = self.stack[-1][0]
            cur[field] = (cur.get(field, "") + " " + text.strip()).strip()

    def end(self, depth: int):
        while self.stack and self.stack[-1][1] >= depth:
            self.stack.pop()

    @property
    def active(self) -> bool:
        return bool(self.stack)


class ComBankParser(HTMLParser):
    """https://www.combank.lk/rewards-promotions — each offer is an
    <a class="reward ..."> containing a background-image div, a percentage
    badge, and a reward-content block with category/title/valid-date."""

    def __init__(self):
        super().__init__()
        self.offers: list[dict] = []
        self.depth = 0
        self.cur: dict | None = None
        self.cur_depth = 0
        self.cap = _SectionCapture()

    def handle_starttag(self, tag, attrs_list):
        attrs = dict(attrs_list)
        cls = _classes(attrs)
        self.depth += 1
        if tag == "a" and "reward" in cls:
            self.cur = {"href": attrs.get("href", ""), "image": None}
            self.cur_depth = self.depth
            self.cap = _SectionCapture()
            return
        if self.cur is None:
            return
        if tag == "div" and "reward-image" in cls:
            style = attrs.get("style", "")
            m = re.search(r"url\(['\"]?([^'\")]+)['\"]?\)", style)
            if m:
                self.cur["image"] = m.group(1)
        elif tag == "div" and "offer-tag" in cls:
            self.cap.start("discount", self.depth)
        elif tag == "p" and "category" in cls:
            self.cap.start("category", self.depth)
        elif tag == "h3":
            self.cap.start("title", self.depth)
        elif tag == "p" and "valid-date" in cls:
            self.cap.start("valid", self.depth)

    def handle_endtag(self, tag):
        if self.cur is None:
            self.depth = max(0, self.depth - 1)
            return
        if self.cap.active:
            self.cap.end(self.depth)
        if tag == "a" and self.depth == self.cur_depth:
            self.offers.append(self.cur)
            self.cur = None
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if self.cur is not None:
            self.cap.data(self.cur, data)


class NtbParser(HTMLParser):
    """https://www.nationstrust.com/promotions — each offer is a
    <div class="promo-box"> with an <img>, a category "tag" div, merchant
    (h6) + title (h5), and a footer with a valid-date <small> + link."""

    def __init__(self):
        super().__init__()
        self.offers: list[dict] = []
        self.depth = 0
        self.cur: dict | None = None
        self.cur_depth = 0
        self.img_taken = False
        self.cap = _SectionCapture()

    def handle_starttag(self, tag, attrs_list):
        attrs = dict(attrs_list)
        cls = _classes(attrs)
        self.depth += 1
        if tag == "div" and "promo-box" in cls:
            self.cur = {"href": "", "image": None}
            self.cur_depth = self.depth
            self.img_taken = False
            self.cap = _SectionCapture()
            return
        if self.cur is None:
            return
        if tag == "img" and not self.img_taken:
            self.cur["image"] = attrs.get("src")
            self.img_taken = True
        elif tag == "div" and "tag" in cls:
            self.cap.start("category", self.depth)
        elif tag == "h6":
            self.cap.start("merchant", self.depth)
        elif tag == "h5":
            self.cap.start("title", self.depth)
        elif tag == "small":
            self.cap.start("valid", self.depth)
        elif tag == "a" and not self.cur["href"]:
            href = attrs.get("href", "")
            if href:
                self.cur["href"] = href

    def handle_endtag(self, tag):
        if self.cur is None:
            self.depth = max(0, self.depth - 1)
            return
        if self.cap.active:
            self.cap.end(self.depth)
        if tag == "div" and self.depth == self.cur_depth:
            self.offers.append(self.cur)
            self.cur = None
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if self.cur is not None:
            self.cap.data(self.cur, data)


class AmexParser(HTMLParser):
    """https://www.americanexpress.lk/en/offers/supermarket-offers — each
    offer is an <a class="alloffer-box-inner"> with an image + a
    value-limit discount badge, then a heading, a (usually empty)
    location, and a final unclassed <div> holding the validity text."""

    def __init__(self):
        super().__init__()
        self.offers: list[dict] = []
        self.depth = 0
        self.cur: dict | None = None
        self.cur_depth = 0
        self.img_taken = False
        self.seen_heading = False
        self.cap = _SectionCapture()

    def handle_starttag(self, tag, attrs_list):
        attrs = dict(attrs_list)
        cls = _classes(attrs)
        self.depth += 1
        if tag == "a" and "alloffer-box-inner" in cls:
            self.cur = {"href": attrs.get("href", ""), "image": None}
            self.cur_depth = self.depth
            self.img_taken = False
            self.seen_heading = False
            self.cap = _SectionCapture()
            return
        if self.cur is None:
            return
        if tag == "img" and not self.img_taken:
            self.cur["image"] = attrs.get("src")
            self.img_taken = True
        elif "value-limit" in cls:
            self.cap.start("discount", self.depth)
        elif "alloffer-heading" in cls:
            self.cap.start("title", self.depth)
            self.seen_heading = True
        elif "offer-location" in cls:
            self.cap.start("location", self.depth)
        elif tag == "div" and not cls and self.seen_heading:
            self.cap.start("valid", self.depth)

    def handle_endtag(self, tag):
        if self.cur is None:
            self.depth = max(0, self.depth - 1)
            return
        if self.cap.active:
            self.cap.end(self.depth)
        if tag == "a" and self.depth == self.cur_depth:
            self.offers.append(self.cur)
            self.cur = None
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if self.cur is not None:
            self.cap.data(self.cur, data)
