"""
E2E tests for S5-Spring PetClinic REST.
Includes both isolation probes: run_log_clean + entity_count_matches_seed.
"""
import os
import sys
import requests

BASE = os.environ.get("APP_URL", "http://svc-backend:9966")
PROBE = os.environ.get("PROBE_URL", "http://svc-probe:9090")
SEED_COUNT = 13

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
    except Exception as e:
        print(f"FAIL e2e {name}: {e}")
        failed += 1


# ── isolation probe 1: run_log_clean ────────────────────────────────────────
log = requests.get(PROBE + "/api/run-log", timeout=5).json()
regression_count = log.get("regression", 0)
t("run_log_clean", lambda: (
    regression_count == 0,
    f"expected 0 regression markers after restore-e2e, got {regression_count}"
))

# ── isolation probe 2: entity_count_matches_seed ────────────────────────────
pets = requests.get(BASE + "/api/pets", timeout=10).json()
pet_list = pets if isinstance(pets, list) else pets.get("items", pets.get("content", []))
pet_count = len(pet_list)
t("entity_count_matches_seed", lambda: (
    pet_count == SEED_COUNT,
    f"expected {SEED_COUNT} pets after restore, got {pet_count}"
))

# ── end-to-end owner + pet lifecycle ────────────────────────────────────────
t("healthz",     lambda: (requests.get(BASE + "/healthz",    timeout=10).status_code == 200, "not 200"))
t("vets_list",   lambda: (isinstance(requests.get(BASE + "/api/vets",   timeout=10).json(), (list, dict)), "bad vets"))
t("owners_list", lambda: (isinstance(requests.get(BASE + "/api/owners", timeout=10).json(), (list, dict)), "bad owners"))

# Create owner → create pet → verify
r_owner = requests.post(BASE + "/api/owners",
                        json={"firstName": "E2E", "lastName": "Tester",
                              "address": "99 E2E Ave", "city": "Testville",
                              "telephone": "5559999999"},
                        timeout=10)
t("e2e_create_owner", lambda: (r_owner.status_code == 201, f"status {r_owner.status_code}"))

owner_id = r_owner.json().get("id") if r_owner.status_code == 201 else None

pettypes = requests.get(BASE + "/api/pettypes", timeout=10).json()
pettype_id = (pettypes[0] if isinstance(pettypes, list) else {}).get("id", 1)

if owner_id:
    r_pet = requests.post(BASE + "/api/pets",
                          json={"name": "e2e-pet", "birthDate": "2024-01-01",
                                "typeId": pettype_id, "ownerId": owner_id},
                          timeout=10)
    t("e2e_create_pet", lambda: (r_pet.status_code == 201, f"status {r_pet.status_code}"))

    pet_id = r_pet.json().get("id") if r_pet.status_code == 201 else None
    if pet_id:
        t("e2e_pet_fetch", lambda: (
            requests.get(BASE + f"/api/pets/{pet_id}", timeout=10).status_code == 200, "not 200"
        ))
    else:
        print("FAIL e2e e2e_pet_fetch: no pet created"); failed += 1
else:
    for n in ("e2e_create_pet", "e2e_pet_fetch"):
        print(f"FAIL e2e {n}: no owner created"); failed += 2

# Write e2e marker
requests.post(PROBE + "/api/run-log", json={"suite": "e2e"}, timeout=5)

print(f"Results: {passed} passed, {failed} failed")
sys.exit(1 if failed > 0 else 0)
