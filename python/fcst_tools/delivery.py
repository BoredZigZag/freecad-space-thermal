# SPDX-License-Identifier: MIT OR Apache-2.0
"""Scope decisions cannot silently become broader delivery/support claims."""
import re


COMMITTED_WORK_PACKAGES = frozenset({f"WP-{i:02d}" for i in range(1, 22)} | {"WP-05.5"})
V2_ONLY_WORK_PACKAGES = frozenset({"WP-08", "WP-09", "WP-10", "WP-21"})
V2_ONLY_REQUIREMENTS = frozenset({"VNV-003", "VNV-004", "VNV-009", "VNV-012", "TST-007", "TST-018"})
SHARED_REQUIREMENTS = frozenset({"INT-001", "RAD-005", "RAD-010", "TST-014", "TST-015", "VNV-001", "VNV-011", "VNV-013"})
FOUNDATION_CASES = frozenset(
    [f"WP055-INV-{i:03d}" for i in range(1, 3)]
    + [f"WP055-HOST-{i:03d}" for i in range(1, 5)]
    + [f"WP055-CTR-{i:03d}" for i in range(1, 6)]
    + [f"WP055-NUM-{i:03d}" for i in range(1, 3)]
    + [f"WP055-STORE-{i:03d}" for i in range(1, 5)]
    + [f"WP055-{group}-{i:03d}" for group in ("AUDIT", "TOOL", "PUB", "HAND") for i in range(1, 3)]
)


def package_from_title(title):
    match = re.match(r"^(WP-\d{2}(?:\.\d+)?):", title)
    return match[1] if match and match[1] in COMMITTED_WORK_PACKAGES else None


def target_release(scope, package_id):
    """Return the first product release that requires the work package."""
    releases = scope["product_releases"]
    if package_id in releases["v2_only_work_packages"]:
        return releases["thermal_software_interoperability"]
    return releases["completed_native_scope"]


def validate_release_assignments(scope, trace, profiles):
    """Keep native completion and deferred evidence with their release owners."""
    errors = set()
    if any(row["primary_work_package"] not in V2_ONLY_WORK_PACKAGES for row in profiles.values()):
        errors.add("compatibility_profile_has_native_owner")
    for requirement, row in trace.items():
        requires_v2 = requirement in V2_ONLY_REQUIREMENTS or (
            requirement.startswith("INT-") and requirement not in SHARED_REQUIREMENTS)
        if requires_v2 and row["primary_work_package"] not in V2_ONLY_WORK_PACKAGES:
            errors.add("v2_requirement_has_native_owner")

    shared = scope["product_releases"].get("shared_v2_evidence_owners", {})
    if set(shared) != SHARED_REQUIREMENTS or any(
            owner not in V2_ONLY_WORK_PACKAGES or requirement not in trace
            or trace[requirement]["primary_work_package"] in V2_ONLY_WORK_PACKAGES
            or owner not in trace[requirement]["supporting_work_packages"].split(";")
            for requirement, owner in shared.items()):
        errors.add("shared_v2_evidence_owner_mismatch")
    return sorted(errors)


def validate_foundation_acceptance(rows, requirements, suites, evidence=None):
    errors = []
    identifiers = [row.get("case_id") for row in rows]
    if set(identifiers) != FOUNDATION_CASES or len(identifiers) != len(set(identifiers)):
        errors.append("foundation_acceptance_coverage_mismatch")
    for row in rows:
        reqs = row.get("requirement_ids", "").split(";")
        selected = row.get("automated_suites", "").split(";")
        if (not set(reqs) <= set(requirements) or "TST-022" not in reqs
                or len(reqs) != len(set(reqs)) or not set(selected) <= set(suites)
                or len(selected) != len(set(selected))):
            errors.append("foundation_acceptance_unknown_or_duplicate_reference")
        substantiated = row.get("status") == "planned"
        if row.get("status") == "passed" and evidence and evidence.get("status") == "complete":
            collected = evidence.get("acceptance", [])
            substantiated = (len(collected) == len(FOUNDATION_CASES)
                and {c.get("id") for c in collected} == FOUNDATION_CASES
                and all(c.get("status") == "passed" for c in collected)
                and evidence.get("input_sha256") and evidence.get("tested_candidate"))
        if (not substantiated or not row.get("owner_role")
                or not row.get("automated_acceptance") or not row.get("evidence_contract")):
            errors.append("foundation_acceptance_unsubstantiated_or_incomplete")
    return sorted(set(errors))
def validate_scope(scope, packages, evidence, gaps, presets, host):
    errors = []
    if (scope.get("active_platforms") != ["Windows"] or
            scope.get("active_presets") != ["windows-debug", "windows-release"] or
            set(host.get("platforms", {})) != {"Windows"}):
        errors.append("non_windows_active_platform")
    active = {p["name"] for p in presets.get("configurePresets", []) if not p.get("hidden")}
    if active != set(scope.get("active_presets", [])):
        errors.append("active_presets_mismatch")
    by_id = {p["id"]: p for p in packages}
    releases = scope.get("product_releases", {})
    v2_packages = releases.get("v2_only_work_packages", [])
    if (releases.get("current_development_line") != "v0.x"
            or releases.get("completed_native_scope") != "v1"
            or releases.get("thermal_software_interoperability") != "v2"
            or releases.get("closure_order") != ["v1", "v2"]
            or len(v2_packages) != len(V2_ONLY_WORK_PACKAGES)
            or set(v2_packages) != V2_ONLY_WORK_PACKAGES
            or not releases.get("deferral_reason")):
        errors.append("product_release_scope_mismatch")
    for package_id, package in by_id.items():
        if package_id not in V2_ONLY_WORK_PACKAGES:
            if V2_ONLY_WORK_PACKAGES.intersection(package.get("depends_on", "").split(";")):
                errors.append("v1_package_depends_on_v2_interoperability")
            if "SUITE-VENDOR" in package.get("automated_suites", "").split(";"):
                errors.append("v1_package_requires_vendor_suite")
    goal = scope.get("stretch_goals", {}).get("SG-PLATFORMS", {})
    if (set(by_id) != COMMITTED_WORK_PACKAGES
            or scope.get("windows_gates") != ["Q0", "P0", "Q1", "Q2"]
            or goal != {"platforms": ["macOS", "Linux"], "status": "uncommitted",
                        "work_package": None, "completion_gate": None, "blocks_delivery": False}):
        errors.append("stretch_goal_in_committed_delivery")
    foundation = by_id.get("WP-05.5", {})
    if (foundation.get("first_delivery") != "P0" or foundation.get("completion_gate") != "P0"
            or set(foundation.get("depends_on", "").split(";")) != {f"WP-{i:02d}" for i in range(1, 6)}
            or any("WP-05.5" not in by_id.get(consumer, {}).get("depends_on", "").split(";")
                   for consumer in ("WP-06", "WP-07", "WP-13", "WP-16"))):
        errors.append("foundation_handoff_missing_or_misordered")
    expected = {p: {"stretch_goal": "SG-PLATFORMS", "status": "uncommitted"} for p in ["Linux", "macOS"]}
    if scope.get("deferred_platforms") != expected:
        errors.append("missing_deferred_platform_disposition")
    if (by_id.get("WP-01", {}).get("status") != "complete" or evidence.get("status") != "complete"
            or evidence.get("blockers") or scope.get("wp01", {}).get("qualification_claim") is not False):
        errors.append("inventory_completion_or_qualification_claim_invalid")
    for gap in gaps.get("gaps", []):
        owner = gap.get("owner_work_package")
        if (owner not in V2_ONLY_WORK_PACKAGES or owner not in by_id
                or not gap.get("required_gate") or gap.get("status") != "blocked"):
            errors.append("qualification_gap_not_assigned")
    return sorted(set(errors))
