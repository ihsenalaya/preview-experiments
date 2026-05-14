"""
Regression tests — output lines PASS/FAIL parsed by the operator.

Isolation probe (run_log_clean):
  smoke.py writes suite='smoke' to run_log before this suite runs.
  With isolation ON  → restore-regression truncates run_log → smoke_count == 0 → PASS.
  With isolation OFF → run_log accumulates               → smoke_count == 1 → FAIL.
  This is the primary metric for the flakiness experiment (RQ1).
"""
import os, sys, requests

BASE     = os.environ.get("APP_URL",      "http://svc-backend:8080")
FRONTEND = os.environ.get("FRONTEND_URL", "http://svc-frontend:3000")

passed = failed = 0


def t(name, fn):
    global passed, failed
    try:
        ok, reason = fn()
        if ok:
            print(f"PASS regression {name}")
            passed += 1
        else:
            print(f"FAIL regression {name}: {reason}")
            failed += 1
    except Exception as e:
        print(f"FAIL regression {name}: {e}")
        failed += 1


def _first_pid():
    try:
        products = requests.get(BASE + "/api/products", timeout=10).json()
        if products:
            return products[0]["id"]
    except Exception:
        pass
    return None


# ── isolation-sensitive probe ───────────────────────────────────────────────
# smoke.py wrote suite='smoke' before this suite. If restore-regression ran,
# run_log is clean and smoke_count == 0.
log_counts = requests.get(BASE + "/api/run-log", timeout=5).json()
smoke_count = log_counts.get("smoke", 0)
t("run_log_clean", lambda: (
    smoke_count == 0,
    f"expected 0 smoke markers (restore clears run_log), got {smoke_count} (isolation drift)"
))

# ── functional tests ────────────────────────────────────────────────────────

t("health",        lambda: (requests.get(BASE + "/healthz",   timeout=5).status_code == 200, "not 200"))
t("frontend_home", lambda: (requests.get(FRONTEND + "/",      timeout=5).status_code == 200, "frontend not 200"))
t("products_list", lambda: (isinstance(requests.get(BASE + "/api/products", timeout=5).json(), list), "not a list"))

pid = _first_pid()
if pid:
    t("product_detail",  lambda: ("id" in requests.get(BASE + f"/api/products/{pid}",          timeout=5).json(), "no id field"))
    t("product_related", lambda: ("products" in requests.get(BASE + f"/api/products/{pid}/related", timeout=5).json(), "no products field"))
    t("product_reviews", lambda: (isinstance(requests.get(BASE + f"/api/products/{pid}/reviews", timeout=5).json(), list), "not a list"))
else:
    for name in ("product_detail", "product_related", "product_reviews"):
        print(f"FAIL regression {name}: no products in DB")
        failed += 3

t("product_not_found", lambda: (requests.get(BASE + "/api/products/99999", timeout=5).status_code == 404, "expected 404"))
t("discounted",        lambda: ("products" in requests.get(BASE + "/api/products/discounted?min_discount=0", timeout=5).json(), "bad response"))
t("stats",             lambda: ("total_products" in requests.get(BASE + "/api/stats", timeout=5).json(), "no total_products"))

# ── write operation (creates cross-suite state for isolation test in e2e) ───
r = requests.post(BASE + "/api/products",
                  json={"name": "exp-product", "price": 9.99, "discount_pct": 20, "stock": 5},
                  timeout=5)
t("create_product", lambda: (r.status_code == 201, f"status {r.status_code}"))

# Write regression marker — e2e.py checks this was cleared by restore-e2e.
requests.post(BASE + "/api/run-log", json={"suite": "regression"}, timeout=5)

print(f"Results: {passed} passed, {failed} failed")
sys.exit(1 if failed > 0 else 0)
