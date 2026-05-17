"""PHASE 2 — Categorize per-assertion outcomes.

Maps (subject_id, suite, assertion_id) → category from the 8 allowed categories,
plus a boolean `is_isolation_sensitive` flag used for downstream analysis.

The category set is fixed by prompt.txt PHASE 2:
  isolation_probe, baseline_count, functional_api, auth_permission,
  schema_validation, infra, timeout, unknown.
"""
from __future__ import annotations

import re
from typing import Tuple

ALLOWED_CATEGORIES = (
    "isolation_probe",
    "baseline_count",
    "functional_api",
    "auth_permission",
    "schema_validation",
    "infra",
    "timeout",
    "unknown",
)

# ---------------------------------------------------------------------------
# Explicit lookup — high-confidence categorisation for the assertions we know.
# Keyed by assertion_id alone (assertion names are unique per subject in practice
# and they have the same role across subjects when they share a name).
# ---------------------------------------------------------------------------

_BY_ASSERTION: dict[str, str] = {
    # === isolation probes (harness probe service /api/run-log) ===
    "run_log_clean": "isolation_probe",

    # === baseline-count probes (count == SEED_COUNT) ===
    "product_count_matches_seed": "baseline_count",
    "list_count_matches_seed": "baseline_count",
    "check_count_matches_seed": "baseline_count",
    "website_count_matches_seed": "baseline_count",
    "pet_count_matches_seed": "baseline_count",
    "entity_count_matches_seed": "baseline_count",

    # === infra / readiness ===
    "healthz": "infra",
    "health": "infra",

    # === auth / session ===
    "login": "auth_permission",
    "login_valid": "auth_permission",
    "me": "auth_permission",
    "me_endpoint": "auth_permission",
    "token": "auth_permission",

    # S4: teams_list requires team membership (broken-upstream; now removed)
    "teams_list": "auth_permission",

    # === functional API — listings / details / CRUD ===
    "version": "functional_api",
    "categories": "functional_api",
    "stats": "functional_api",

    "products_list": "functional_api",
    "product_detail": "functional_api",
    "product_related": "functional_api",
    "product_reviews": "functional_api",
    "product_not_found": "functional_api",
    "discounted": "functional_api",
    "create_product": "functional_api",

    "lists_get": "functional_api",
    "list_get": "functional_api",
    "list_create": "functional_api",
    "list_delete": "functional_api",
    "subscriber_create": "functional_api",
    "subscribers": "functional_api",
    "subscribers_list": "functional_api",
    "campaigns": "functional_api",
    "campaigns_list": "functional_api",
    "templates": "functional_api",
    "templates_list": "functional_api",
    "results": "functional_api",
    "data": "functional_api",
    "id": "functional_api",
    "total": "functional_api",
    "lists_returns_data": "functional_api",

    "checks_list": "functional_api",
    "channels": "functional_api",
    "check_create": "functional_api",
    "check_fetch": "functional_api",
    "check_ping": "functional_api",
    "check_delete": "functional_api",
    "ping_url": "functional_api",
    "checks": "functional_api",

    "websites_list": "functional_api",
    "website_create": "functional_api",
    "website_fetch": "functional_api",
    "website_delete": "functional_api",
    # S4 e2e_stats requires query params (broken-upstream; now removed)
    "e2e_stats": "functional_api",
    "e2e_send_event": "functional_api",

    "vets_list": "functional_api",
    "owners_list": "functional_api",
    "pets_list": "functional_api",
    "pettypes": "functional_api",
    "specialties": "functional_api",
    "owner_create": "functional_api",
    "owner_fetch": "functional_api",
    "owner_update": "functional_api",
    "owner_delete": "functional_api",
    "e2e_create_owner": "functional_api",
    "e2e_create_pet": "functional_api",
    "e2e_pet_fetch": "functional_api",
    "e2e_me": "functional_api",

    "content": "functional_api",
    "items": "functional_api",
    "count": "functional_api",

    # === S1 e2e (browser-driven flows via Playwright probes) ===
    "frontend_home": "functional_api",
    "catalog_loads": "functional_api",
    "pr_badge": "functional_api",
    "product_detail_panel": "functional_api",
    "related_section": "functional_api",
    "close_detail": "functional_api",
    "discount_filter": "functional_api",

    # noise — these "names" come from suite markers (POST /api/run-log {"suite": "x"})
    # that the test code keeps for cross-suite verification. Categorize as unknown.
    "smoke": "unknown",
    "regression": "unknown",
    "e2e": "unknown",
}

# ---------------------------------------------------------------------------
# Regex fallback — only used when the explicit map misses.
# ---------------------------------------------------------------------------

_REGEX_FALLBACK: list[tuple[re.Pattern, str]] = [
    (re.compile(r".*run_log.*"),               "isolation_probe"),
    (re.compile(r".*_count_matches_seed$"),    "baseline_count"),
    (re.compile(r"^health.*"),                  "infra"),
    (re.compile(r"^(login|token|me|auth).*"),   "auth_permission"),
    (re.compile(r".*_(list|fetch|get|create|update|delete|ping)$"), "functional_api"),
]


def categorize(subject_id: str, suite: str, assertion_id: str) -> str:
    """Return one of ALLOWED_CATEGORIES for the given assertion."""
    if assertion_id in _BY_ASSERTION:
        return _BY_ASSERTION[assertion_id]
    for pat, cat in _REGEX_FALLBACK:
        if pat.match(assertion_id):
            return cat
    return "unknown"


def is_isolation_sensitive(assertion_id: str, category: str) -> bool:
    """An assertion is isolation-sensitive iff its outcome can flip when the
    operator's checkpoint/restore step does or does not run between suites."""
    return category in ("isolation_probe", "baseline_count")


def normalize_failure_signature(message: str) -> str:
    """Compact a failure message into a stable signature for grouping similar fails.

    Rules:
      - lowercase
      - replace all integers with "N"
      - replace UUID-like 8-12 hex sequences with "HEX"
      - trim whitespace
      - cap to 80 chars
    """
    if not message:
        return ""
    s = message.lower().strip()
    s = re.sub(r"\b[0-9a-f]{8,}\b", "HEX", s)
    s = re.sub(r"\b\d+\b", "N", s)
    s = re.sub(r"\s+", " ", s)
    return s[:80]


def parse_expected_observed(message: str) -> Tuple[str, str]:
    """Best-effort extraction of (expected, observed) from a failure message.

    Recognised patterns:
      - "expected X, got Y"
      - "expected X (rest)"
      - "status XXX"  (HTTP)
      - "not XXX"
      - "<reason> (NX (cause))"  (variants)
    Returns ("", "") if nothing structured is recognised.
    """
    if not message:
        return ("", "")
    s = message.strip()

    m = re.search(r"expected\s+(.+?)(?:,\s*got\s+(.+?))?(?:\s*\(|$)", s, re.IGNORECASE)
    if m:
        return (m.group(1).strip(), (m.group(2) or "").strip())

    m = re.match(r"status\s+(\d+)", s, re.IGNORECASE)
    if m:
        return ("2xx", m.group(1))

    m = re.match(r"not\s+(\d+)", s, re.IGNORECASE)
    if m:
        return (m.group(1), "non-" + m.group(1))

    return ("", "")
