"""
Smoke tests — fast sanity checks run first by the operator.
Output PASS/FAIL lines parsed by the operator.

Writes a 'smoke' marker to run_log so that regression.py can verify the
marker was cleared by the restore-regression checkpoint step.
"""
import os, sys, requests

BASE = os.environ.get("APP_URL", "http://svc-backend:8080")

passed = failed = 0


def t(name, fn):
    global passed, failed
    try:
        ok, reason = fn()
        if ok:
            print(f"PASS smoke {name}")
            passed += 1
        else:
            print(f"FAIL smoke {name}: {reason}")
            failed += 1
    except Exception as e:
        print(f"FAIL smoke {name}: {e}")
        failed += 1


t("health",        lambda: (requests.get(BASE + "/healthz",      timeout=5).status_code == 200, "not 200"))
t("version",       lambda: ("version" in requests.get(BASE + "/api/version", timeout=5).json(), "no version field"))
t("products_list", lambda: (isinstance(requests.get(BASE + "/api/products", timeout=5).json(), list), "not a list"))
t("categories",    lambda: (isinstance(requests.get(BASE + "/api/categories", timeout=5).json(), list), "not a list"))
t("stats",         lambda: ("total_products" in requests.get(BASE + "/api/stats", timeout=5).json(), "no total_products"))

# Write smoke marker — regression checks this was cleared by restore-regression.
try:
    requests.post(BASE + "/api/run-log", json={"suite": "smoke"}, timeout=5)
except Exception as e:
    print(f"FAIL smoke run_log_write: {e}")
    failed += 1

print(f"Results: {passed} passed, {failed} failed")
sys.exit(1 if failed > 0 else 0)
