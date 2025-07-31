#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys
from pathlib import Path
from datetime import timedelta

import requests
from bs4 import BeautifulSoup  # type: ignore
from dateutil import parser as dtparse  # type: ignore
from ics import Calendar, Event  # type: ignore

try:
    from ics.alarms.display import DisplayAlarm  # type: ignore
except ImportError:
    DisplayAlarm = None  # type: ignore  # graceful fallback

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate .ics for Wakefield bin collections")
    p.add_argument("--url", help="Full Wakefield ‘where‑i‑live’ URL for your address")
    p.add_argument("--output", default="collections.ics", help="Path to write the calendar")
    p.add_argument("--verbose", "-v", action="store_true", help="Chatty output")
    return p.parse_args()


DATE_RE = re.compile(r"[A-Za-z]+,?\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}")
EMOJI = {
    "Household waste": "🗑️",
    "Mixed recycling": "♻️",
    "Garden waste recycling": "🌿",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_date(text: str) -> _dt.date | None:
    m = DATE_RE.search(text)
    if not m:
        return None
    try:
        return dtparse.parse(m.group(0), dayfirst=False).date()
    except (ValueError, OverflowError):
        return None


def _scrape(url: str, *, verbose: bool = False) -> list[tuple[str, _dt.date]]:
    r = requests.get(url, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    collections: list[tuple[str, _dt.date]] = []

    for colldiv in soup.select("div.colldates"):
        heading_tag = colldiv.find_previous("div", class_="u-mb-4")
        bin_type = heading_tag.get_text(strip=True) if heading_tag else "Bin"

        # Next collection
        container = colldiv.parent
        if container:
            for div in container.find_all("div", class_="u-mb-2"):
                if "Next collection" in div.get_text():
                    d = _extract_date(div.get_text())
                    if d:
                        collections.append((bin_type, d))
                        if verbose:
                            print(f"Found next {bin_type}: {d}")
                    break

        # Future list
        for li in colldiv.select("ul li"):
            d = _extract_date(li.get_text(" ", strip=True))
            if d:
                collections.append((bin_type, d))

    unique = {(b, d) for b, d in collections}
    return sorted(unique, key=lambda bd: bd[1])


def _build_calendar(events: list[tuple[str, _dt.date]]) -> Calendar:
    cal = Calendar()
    for bin_type, date in events:
        ev = Event()
        SHORT = {"Household waste": "Household Waste", "Mixed recycling": "Recycling", "Garden waste recycling": "Garden"}
        name = f"{EMOJI.get(bin_type, '')} {SHORT.get(bin_type, bin_type)}".strip()
        ev.name = name
        ev.begin = _dt.datetime.combine(date, _dt.time.min).astimezone()
        ev.make_all_day()
        ev.description = f"Put out the {bin_type.lower()} bin.".capitalize()
        ev.location = "Kerbside"
        ev.categories = [bin_type]
        # 12‑hour pre‑alarm if supported
        if DisplayAlarm:
            ev.alarms.append(DisplayAlarm(trigger=timedelta(hours=-12), display_summary=name))
        cal.events.add(ev)
    return cal


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ns = _parse_args()
    url = ns.url or os.getenv("BINCOLL_URL")
    if not url:
        sys.exit("Error: --url arg or BINCOLL_URL env var required")

    events = _scrape(url, verbose=ns.verbose)
    if ns.verbose:
        for b, d in events:
            print(f"{d.isoformat()}: {b}")

    cal = _build_calendar(events)
    out_path = Path(ns.output)
    out_path.write_text(cal.serialize(), encoding="utf-8")
    if ns.verbose:
        print(f"Wrote {out_path} containing {len(events)} events.")


if __name__ == "__main__":
    sys.exit(main())
