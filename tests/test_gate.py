# SPDX-License-Identifier: MIT OR Apache-2.0
from copy import deepcopy
import json
from pathlib import Path
import unittest
from fcst_app import capabilities
from fcst_tools.gate import evaluate


class GateTests(unittest.TestCase):
    def test_missing_and_zero_cases_rejected(self):
        self.assertEqual(evaluate([], [])["status"], "failed")
        self.assertEqual(evaluate(["required"], [])["status"], "failed")

    def test_p0_rejects_substituted_results_and_false_recovery(self):
        from fcst_tools.p0 import CRITERIA, METRICS, assess
        criteria = json.loads((Path(__file__).resolve().parents[1]/CRITERIA).read_bytes())
        model, edited, series = 'a'*64, 'b'*64, 'c'*64
        host = dict(model_hash=model, edited_model_hash=edited, temperature_hash=series,
                    samples=21, contour_error=0, history_matches=True, stale_rejected=True,
                    terminal_states=['cancelled','interrupted'], partial_results=0, recovered=True)
        clients = dict(model_hash=model, fixture_hash='d'*64, mesh_hash='e'*64, samples=21,
                       cli_temperature_hash=series, mcp_temperature_hash=series, parity_error_K=0, reconnect=True,
                       metrics=dict.fromkeys(METRICS, 0) | dict(view_factor=.5, quadrature_difference=0))
        assess(host, clients, criteria)
        for reported in (dict(host, temperature_hash='0'*64), dict(host, edited_model_hash=model),
                         dict(host, partial_results=1), dict(host, terminal_states=['cancelled','failed']),
                         dict(host, stale_rejected=False), dict(host, history_matches=False)):
            with self.assertRaises(ValueError):
                assess(reported, clients, criteria)
        incorrect = deepcopy(clients)
        incorrect['metrics']['radiation_power_error_W'] = float('nan')
        with self.assertRaises(ValueError):
            assess(host, incorrect, criteria)

    def test_skipped_blocked_and_failed_rejected(self):
        for status in ["skipped", "blocked", "failed", "interrupted", "cancelled"]:
            self.assertEqual(evaluate(["required"], [{"id": "required", "status": status}])["status"], "failed")

    def test_duplicate_and_substituted_coverage_rejected(self):
        record = {"id": "required", "status": "passed"}
        self.assertEqual(evaluate(["required"], [record, record])["status"], "failed")
        self.assertEqual(evaluate(["other"], [record])["status"], "failed")

    def test_correct_coverage_passes(self):
        self.assertEqual(evaluate(["required"], [{"id": "required", "status": "passed"}])["status"], "passed")

    def test_skeleton_never_claims_solver_implementation(self):
        self.assertFalse(capabilities()["solver_available"])
        self.assertFalse(capabilities()["vendor_runtime_required"])
