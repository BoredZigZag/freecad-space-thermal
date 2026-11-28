# SPDX-License-Identifier: MIT OR Apache-2.0
import copy
import csv
import json
import unittest
from pathlib import Path
from fcst_tools.delivery import (
    package_from_title, validate_foundation_acceptance, validate_release_assignments, validate_scope,
)

ROOT = Path(__file__).resolve().parents[1]


class DeliveryScopeTests(unittest.TestCase):
    def setUp(self):
        def read(name):
            return json.loads((ROOT / name).read_text(encoding="utf-8"))
        with (ROOT / "plans/work-packages.csv").open(encoding="utf-8", newline="") as stream:
            packages = list(csv.DictReader(stream))
        self.args = [read("plans/delivery-scope.json"), packages, read("plans/evidence/WP-01.json"),
                     read("inventory/gaps.json"), read("CMakePresets.json"), read("ci/host-profile.json")]

    def test_deferred_platform_cannot_enter_active_scope(self):
        self.assertEqual(validate_scope(*self.args), [])
        for platform in ["Linux", "macOS"]:
            changed = copy.deepcopy(self.args)
            changed[0]["active_platforms"].append(platform)
            self.assertIn("non_windows_active_platform", validate_scope(*changed))

    def test_stretch_goals_cannot_become_work_packages_or_release_gates(self):
        for field, value in [("work_package", "WP-22"), ("completion_gate", "Q2"), ("blocks_delivery", True)]:
            changed = copy.deepcopy(self.args)
            changed[0]["stretch_goals"]["SG-PLATFORMS"][field] = value
            self.assertIn("stretch_goal_in_committed_delivery", validate_scope(*changed))
        changed = copy.deepcopy(self.args)
        changed[1].append({"id": "WP-22"})
        self.assertIn("stretch_goal_in_committed_delivery", validate_scope(*changed))

    def test_inventory_closure_cannot_claim_qualification_or_lose_gap_owner(self):
        changed = copy.deepcopy(self.args)
        changed[0]["wp01"]["qualification_claim"] = True
        changed[3]["gaps"][0]["owner_work_package"] = "WP-01"
        errors = validate_scope(*changed)
        self.assertIn("inventory_completion_or_qualification_claim_invalid", errors)
        self.assertIn("qualification_gap_not_assigned", errors)

    def test_interoperability_is_deferred_without_blocking_v1(self):
        self.assertEqual(validate_scope(*self.args), [])
        for field, value in [("current_development_line", "v1"),
                             ("completed_native_scope", "v2"),
                             ("thermal_software_interoperability", "v1"),
                             ("closure_order", ["v2", "v1"]),
                             ("v2_only_work_packages", ["WP-08", "WP-09", "WP-21"])]:
            with self.subTest(field=field):
                changed = copy.deepcopy(self.args)
                changed[0]["product_releases"][field] = value
                self.assertIn("product_release_scope_mismatch", validate_scope(*changed))
        for native, deferred in [("WP-15", "WP-08"), ("WP-19", "WP-10")]:
            with self.subTest(native=native):
                changed = copy.deepcopy(self.args)
                package = next(row for row in changed[1] if row["id"] == native)
                package["depends_on"] += ";" + deferred
                self.assertIn("v1_package_depends_on_v2_interoperability", validate_scope(*changed))
        changed = copy.deepcopy(self.args)
        native = next(row for row in changed[1] if row["id"] == "WP-16")
        native["automated_suites"] += ";SUITE-VENDOR"
        changed[3]["gaps"][0]["owner_work_package"] = "WP-19"
        self.assertIn("v1_package_requires_vendor_suite", validate_scope(*changed))
        self.assertIn("qualification_gap_not_assigned", validate_scope(*changed))

        def indexed_rows(file, key):
            with (ROOT / file).open(encoding="utf-8", newline="") as stream:
                return {row[key]: row for row in csv.DictReader(stream)}

        trace = indexed_rows("plans/requirement-traceability.csv", "requirement_id")
        profiles = indexed_rows("plans/compatibility-test-plan.csv", "profile_id")
        scope = copy.deepcopy(self.args[0])
        self.assertEqual(validate_release_assignments(scope, trace, profiles), [])
        trace["VNV-012"]["primary_work_package"] = "WP-19"
        trace["VNV-013"]["supporting_work_packages"] = "WP-08"
        profiles["ESA-NATIVE"]["primary_work_package"] = "WP-16"
        self.assertEqual(validate_release_assignments(scope, trace, profiles), [
            "compatibility_profile_has_native_owner", "shared_v2_evidence_owner_mismatch",
            "v2_requirement_has_native_owner",
        ])
        del scope["product_releases"]["shared_v2_evidence_owners"]["TST-014"]
        self.assertIn("shared_v2_evidence_owner_mismatch", validate_release_assignments(scope, trace, profiles))

    def test_foundation_handoff_cannot_be_omitted_or_depend_on_its_consumers(self):
        self.assertEqual(validate_scope(*self.args), [])
        changed = copy.deepcopy(self.args)
        changed[1] = [row for row in changed[1] if row["id"] != "WP-05.5"]
        self.assertIn("foundation_handoff_missing_or_misordered", validate_scope(*changed))
        changed = copy.deepcopy(self.args)
        foundation = next(row for row in changed[1] if row["id"] == "WP-05.5")
        foundation["depends_on"] += ";WP-13"
        self.assertIn("foundation_handoff_missing_or_misordered", validate_scope(*changed))
        changed = copy.deepcopy(self.args)
        consumer = next(row for row in changed[1] if row["id"] == "WP-06")
        consumer["depends_on"] = "WP-04;WP-05"
        self.assertIn("foundation_handoff_missing_or_misordered", validate_scope(*changed))

    def test_fractional_identity_and_acceptance_fail_closed(self):
        self.assertEqual(package_from_title("WP-05.5: Foundation handoff"), "WP-05.5")
        for title in ("WP-05.50: Alias", "WP-5.5: Noncanonical", "WP-05.6: Unapproved", "WP-22: Unapproved"):
            self.assertIsNone(package_from_title(title))
        def rows(name):
            with (ROOT / name).open(encoding="utf-8", newline="") as stream:
                return list(csv.DictReader(stream))
        cases = rows("plans/WP-05.5-acceptance.csv")
        requirements = {row["id"] for name in ("spec/requirements.csv", "plans/automated-test-requirements.csv") for row in rows(name)}
        suites = {row["id"] for row in rows("plans/test-suites.csv")}
        path=ROOT/"plans/evidence/WP-05.5.json"
        evidence=json.loads(path.read_bytes()) if path.is_file() else None
        self.assertEqual(validate_foundation_acceptance(cases, requirements, suites, evidence), [])
        for damaged in (cases[:-1], cases + [cases[0]]):
            self.assertIn("foundation_acceptance_coverage_mismatch", validate_foundation_acceptance(damaged, requirements, suites, evidence))
        changed = copy.deepcopy(cases)
        changed[0]["requirement_ids"] += ";TST-999"
        self.assertIn("foundation_acceptance_unknown_or_duplicate_reference", validate_foundation_acceptance(changed, requirements, suites))
        changed = copy.deepcopy(cases)
        changed[0]["status"] = "passed"
        self.assertIn("foundation_acceptance_unsubstantiated_or_incomplete", validate_foundation_acceptance(changed, requirements, suites))
