"""Capture README screenshots from a running stack (UI on :5173 or :8080).

    pip install playwright && playwright install chromium
    python tools/screenshots.py http://localhost:5173
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173"
OUT = Path(__file__).resolve().parents[1] / "docs" / "images"


def first(status: str, hostname: str | None = None) -> str:
    items = httpx.get(
        f"{BASE}/api/v1/onboardings",
        params={"status": status, "limit": 100},
        headers={"Authorization": "Bearer dev-requester"},
    ).json()["items"]
    items = [i for i in items if hostname is None or i["hostname"] == hostname] or items
    return items[0]["id"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for scheme in ("dark", "light"):
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2,
                                    color_scheme=scheme)
            page.goto(BASE)
            page.evaluate("localStorage.setItem('hatch.token', 'dev-requester')")

            def shot(path: str, name: str, after=None) -> None:
                page.goto(f"{BASE}{path}")
                page.wait_for_timeout(1200)
                if after:
                    after()
                    page.wait_for_timeout(1200)
                page.screenshot(path=str(OUT / f"{name}-{scheme}.png"))

            shot("/", "dashboard")
            shot(f"/onboardings/{first('COMPLETED', 'ams-dc1-leaf-02')}", "onboarding")
            shot(f"/onboardings/{first('FAILED')}", "failed")
            shot(f"/onboardings/{first('COMPLETED', 'ams-dc1-leaf-01')}", "compliance",
                 lambda: page.get_by_role("button", name="Compliance").click())
            shot(f"/onboardings/{first('COMPLETED', 'ams-dc1-leaf-01')}", "diff",
                 lambda: (page.get_by_role("button", name="Config").click(),
                          page.wait_for_timeout(600),
                          page.get_by_role("button", name="Golden config").click()))
            shot("/onboardings", "list")
            page.close()
        browser.close()
    print(f"saved to {OUT}")


if __name__ == "__main__":
    main()
