"""
E2E tests — Playwright/Chromium, output PASS/FAIL parsed by the operator.

Isolation probes:
  product_count_matches_seed:
    regression.py creates 'exp-product' → DB has SEED_COUNT+1 products.
    With isolation ON  → restore-e2e removes exp-product → card_count == SEED_COUNT → PASS.
    With isolation OFF → exp-product persists             → card_count == SEED_COUNT+1 → FAIL.

  run_log_clean:
    regression.py writes suite='regression' to run_log.
    With isolation ON  → restore-e2e truncates run_log → reg_count == 0 → PASS.
    With isolation OFF → run_log accumulates           → reg_count == 1 → FAIL.
"""
import os, sys, requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

FRONTEND = os.environ.get("APP_URL", os.environ.get("FRONTEND_URL", "http://svc-frontend:3000"))
BASE     = os.environ.get("BACKEND_URL", "http://svc-backend:8080")

# Hardcoded: must match the number of products inserted by migration 002_seed_data.py.
SEED_PRODUCT_COUNT = 5

passed = failed = 0


def t(name, fn):
    global passed, failed
    try:
        ok, reason = fn()
        if ok:
            print(f"PASS e2e {name}")
            passed += 1
        else:
            print(f"FAIL e2e {name}: {reason}")
            failed += 1
    except PWTimeout as e:
        print(f"FAIL e2e {name}: playwright timeout — {e}")
        failed += 1
    except Exception as e:
        print(f"FAIL e2e {name}: {e}")
        failed += 1


# ── isolation probe via run_log (API) ───────────────────────────────────────
try:
    reg_count = requests.get(BASE + "/api/run-log", timeout=5).json().get("regression", 0)
except Exception:
    reg_count = -1

t("run_log_clean", lambda: (
    reg_count == 0,
    f"expected 0 regression markers (restore clears run_log), got {reg_count} (isolation drift)"
))

# ── Playwright UI tests ─────────────────────────────────────────────────────
with sync_playwright() as pw:
    browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
    page    = browser.new_page()

    page.goto(FRONTEND + "/", timeout=10000)
    page.wait_for_timeout(1000)
    _catalog_count = page.locator(".card").count()
    t("catalog_loads", lambda: (
        _catalog_count >= 1,
        f"expected ≥1 card, got {_catalog_count}",
    ))

    t("pr_badge", lambda: (
        "PR #" in page.content(), "PR badge not found in page"
    ))

    page.locator(".card").first.click()
    page.wait_for_timeout(500)
    _detail_visible = page.locator("#detail").is_visible()
    t("product_detail_panel", lambda: (
        _detail_visible, "detail panel not visible"
    ))

    t("related_section", lambda: (
        page.locator("#related-section").is_visible(), "related section not visible"
    ))

    page.locator("#close-btn").click()
    page.wait_for_timeout(300)
    _detail_hidden = not page.locator("#detail").is_visible()
    t("close_detail", lambda: (
        _detail_hidden, "detail panel still visible after close"
    ))

    # Discount filter: filtered count must be ≤ unfiltered count.
    page.goto(FRONTEND + "/", timeout=10000)
    total_before = page.locator(".card").count()
    page.fill("#filter", "50")
    page.click("button:has-text('Filter')")
    page.wait_for_timeout(500)
    total_after = page.locator(".card").count()
    t("discount_filter", lambda: (
        total_after <= total_before,
        f"filtered ({total_after}) > unfiltered ({total_before})"
    ))

    # Isolation probe: card count must equal the known seed count.
    # regression.py adds 'exp-product'; restore-e2e should remove it.
    page.goto(FRONTEND + "/", timeout=10000)
    page.wait_for_timeout(500)
    card_count = page.locator(".card").count()
    t("product_count_matches_seed", lambda: (
        card_count == SEED_PRODUCT_COUNT,
        f"UI shows {card_count} products, expected {SEED_PRODUCT_COUNT} seed products "
        f"(isolation drift: regression-created product was not removed)"
    ))

    browser.close()

print(f"Results: {passed} passed, {failed} failed")
sys.exit(1 if failed > 0 else 0)
