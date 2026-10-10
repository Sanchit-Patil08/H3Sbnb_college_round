"""Boundary, adversarial, lifecycle and concurrency checks on isolated databases."""
import copy
import json
import os
import random
import sqlite3
import unittest
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import MagicMock, patch

import test_verification as fixtures
backend = fixtures.backend
from services import risc0_engine


class EdgeCases(unittest.TestCase):
    setUp = fixtures.AppTests.setUp
    create_request = fixtures.AppTests.create_request
    mocked_prover = fixtures.AppTests.mocked_prover
    mocked_verifier = staticmethod(fixtures.AppTests.mocked_verifier)

    def test_salary_boundaries_and_invalid_types(self):
        invalid = [None, True, False, [], {}, "", " ", "abc", "NaN", "sNaN", "Infinity", "-Infinity",
                   "0", "-0", "-0.01", "0.004", "0.005", "100000000.001", "100000000.01",
                   "1e9999", "1e-9999", "1' OR 1=1--", "₹100", "1,000"]
        for salary in invalid:
            with self.subTest(salary=salary):
                response = self.client.post("/api/requests", json={"salary": salary})
                self.assertEqual(response.status_code, 400)
                self.assertIsInstance(response.json.get("error"), str)
        for value, expected in [("0.006", "0.01"), ("0.01", "0.01"), ("1.005", "1.00"),
                                ("1.015", "1.02"), ("99999999.99", "99999999.99"),
                                ("100000000", "100000000.00"), ("1e2", "100.00"), (100, "100.00")]:
            with self.subTest(value=value):
                response = self.client.post("/api/requests", json={"salary": value})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json["inputs"]["salary"], expected)

    def test_non_object_and_malformed_investigation_bodies(self):
        with patch.object(backend, "generate_proof", self.mocked_prover), patch.object(backend, "verify_receipt", self.mocked_verifier):
            rid = self.create_request()
            self.client.post(f"/api/requests/{rid}/execute")
            for body in ([], False, 0, "", None, [1], "normal"):
                with self.subTest(body=body):
                    response = self.client.post(f"/api/requests/{rid}/investigate", data=json.dumps(body), content_type="application/json")
                    self.assertEqual(response.status_code, 400)
            response = self.client.post(f"/api/requests/{rid}/investigate", data='{"scenario":', content_type="application/json")
            self.assertEqual(response.status_code, 400)

    def test_scenario_matrix_at_minimum_rounding_and_maximum(self):
        with patch.object(backend, "generate_proof", self.mocked_prover), patch.object(backend, "verify_receipt", self.mocked_verifier):
            for salary in ("0.01", "0.05", "0.15", "1.25", "99999999.99", "100000000.00"):
                rid = self.create_request(salary)
                self.assertEqual(self.client.post(f"/api/requests/{rid}/execute").status_code, 200)
                for scenario in backend.SCENARIOS:
                    with self.subTest(salary=salary, scenario=scenario):
                        response = self.client.post(f"/api/requests/{rid}/investigate", json={"scenario": scenario})
                        self.assertEqual(response.status_code, 200, response.json)
                        self.assertEqual(response.json["verdict"], "VERIFIED" if scenario == "normal" else "REJECTED")

    def test_rounding_matches_integer_oracle_for_1000_seeded_amounts(self):
        rng = random.Random(20261011)
        for _ in range(1000):
            cents = rng.randint(1, 10_000_000_000)
            for rate in (10, 15):
                quotient, remainder = divmod(cents * rate, 100)
                expected = quotient + int(remainder > 50 or (remainder == 50 and quotient % 2))
                actual = backend.ENGINE.execute(f"bonus-{rate}pct@1.0.0", {"salary": f"{cents // 100}.{cents % 100:02}"})
                self.assertEqual(int(backend.Decimal(actual) * 100), expected)

    def test_missing_resources_and_lifecycle(self):
        for path in ("/api/requests/missing", "/api/requests/missing/reports", "/api/reports/missing"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)
        for action in ("execute", "investigate", "record"):
            self.assertEqual(self.client.post(f"/api/requests/missing/{action}").status_code, 404)
        rid = self.create_request()
        self.assertEqual(self.client.post(f"/api/requests/{rid}/investigate").status_code, 409)
        with patch.object(backend, "generate_proof", side_effect=self.mocked_prover) as prover:
            self.assertEqual(self.client.post(f"/api/requests/{rid}/execute").status_code, 200)
            self.assertEqual(self.client.post(f"/api/requests/{rid}/execute").status_code, 200)
            self.assertEqual(prover.call_count, 1, "Repeat execution should reuse the stored receipt")

    def test_corrupt_stored_submissions_fail_closed_without_500(self):
        with patch.object(backend, "generate_proof", self.mocked_prover), patch.object(backend, "verify_receipt", self.mocked_verifier):
            rid = self.create_request()
            self.client.post(f"/api/requests/{rid}/execute")
            with closing(sqlite3.connect(backend.DB)) as db:
                good = json.loads(db.execute("select submission from requests where id=?", (rid,)).fetchone()[0])
            cases = [None, [], {}, {"receipt": {"proof_verified": True}}, {"receipt": []}]
            for field, value in (("journal", None), ("journal", {}), ("receipt_ref", None)):
                bad = copy.deepcopy(good)
                bad["receipt"][field] = value
                cases.append(bad)
            for field, value in (("output", None), ("output", "sNaN"), ("program_id", []), ("input_commitment", [])):
                bad = copy.deepcopy(good)
                bad["receipt"]["journal"][field] = value
                cases.append(bad)
            for value in (None, "sNaN", [], "Infinity", "not-money"):
                bad = copy.deepcopy(good)
                bad["claimed_output"] = value
                cases.append(bad)
            for index, bad in enumerate(cases):
                with self.subTest(index=index):
                    with closing(sqlite3.connect(backend.DB)) as db:
                        db.execute("update requests set submission=? where id=?", (json.dumps(bad), rid))
                        db.commit()
                    response = self.client.post(f"/api/requests/{rid}/investigate")
                    self.assertIn(response.status_code, (200, 409), response.data[:300])
                    if response.status_code == 200:
                        self.assertIn(response.json["verdict"], ("REJECTED", "INCOMPLETE"))
                    self.assertEqual(self.client.post(f"/api/requests/{rid}/record").status_code, 409)

    def test_concurrent_creations_preserve_one_audit_chain(self):
        def create(index):
            with backend.app.test_client() as client:
                response = client.post("/api/requests", json={"salary": str(index + 1)})
                return response.status_code, response.json
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(create, range(80)))
        self.assertTrue(all(status == 201 for status, _ in results))
        self.assertEqual(len({data["id"] for _, data in results}), 80)
        with closing(sqlite3.connect(backend.DB)) as db:
            rows = db.execute("select ts,request_id,type,status,evidence,prev_hash,hash from audit order by seq").fetchall()
        self.assertEqual(len(rows), 80)
        previous = "0" * 64
        for row in rows:
            self.assertEqual(row[5], previous)
            self.assertEqual(row[6], backend.sha([previous, *row[:5]]))
            previous = row[6]

    def test_concurrent_execution_generates_only_one_receipt(self):
        rid = self.create_request()
        start = threading.Barrier(2)
        def slow_prover(operation, numbers):
            time.sleep(0.15)
            return self.mocked_prover(operation, numbers)
        def execute(_):
            start.wait(timeout=5)
            with backend.app.test_client() as client:
                return client.post(f"/api/requests/{rid}/execute").status_code
        with patch.object(backend, "generate_proof", side_effect=slow_prover) as prover:
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(execute, range(2)))
            self.assertEqual(statuses, [200, 200])
            self.assertEqual(prover.call_count, 1)

    def test_repeat_record_preserves_transaction_reference(self):
        with patch.object(backend, "generate_proof", self.mocked_prover), patch.object(backend, "verify_receipt", self.mocked_verifier):
            rid = self.create_request()
            self.client.post(f"/api/requests/{rid}/execute")
            results = [{"status": "RECORDED", "request_id": "chain-id", "tx": "0xoriginal", "block_number": 7},
                       {"status": "RECORDED", "request_id": "chain-id", "tx": None}]
            with patch.object(backend.CHAIN, "record", side_effect=results):
                self.client.post(f"/api/requests/{rid}/record")
                response = self.client.post(f"/api/requests/{rid}/record")
                self.assertEqual(response.json["tx"], "0xoriginal")
                self.assertEqual(response.json["block_number"], 7)

    def test_unavailable_or_wrong_blockchain_is_disabled(self):
        rpc, contract, account = MagicMock(), MagicMock(), MagicMock()
        rpc.is_connected.return_value = True
        rpc.eth.chain_id = 31337
        rpc.eth.get_code.return_value = b"contract"
        account.address = "authorized"
        contract.functions.verifier.return_value.call.return_value = "authorized"
        with patch.multiple(backend, w3=rpc, contract=contract, account=account, CONFIG_ERROR=None, ABI_ERROR=None):
            self.assertTrue(backend.CHAIN.enabled)
            for connected, chain_id, code, verifier in [(False,31337,b"x","authorized"), (True,1,b"x","authorized"),
                                                         (True,31337,b"","authorized"), (True,31337,b"x","attacker")]:
                rpc.is_connected.return_value = connected
                rpc.eth.chain_id = chain_id
                rpc.eth.get_code.return_value = code
                contract.functions.verifier.return_value.call.return_value = verifier
                self.assertFalse(backend.CHAIN.enabled)
                self.assertEqual(backend.CHAIN.record({})["status"], "NOT_SUBMITTED")
            rpc.eth.send_raw_transaction.assert_not_called()

    def test_invalid_prover_inputs_do_not_launch_host(self):
        with patch.object(risc0_engine, "_run_host") as host:
            for values in ([], [True], [-1], [1.5], ["1"], [16_000_000_001], [1] * 101, None):
                with self.subTest(values=str(values)[:50]):
                    with self.assertRaises(ValueError):
                        risc0_engine.generate_proof("sum", values)
            host.assert_not_called()


@unittest.skipUnless(os.getenv("VERITY_LIVE_TESTS") == "1", "Requires real RISC Zero host")
class LiveEdges(unittest.TestCase):
    def test_real_bonus_rounding_matrix(self):
        for cents in (1, 5, 15, 25, 35, 9999999999, 10000000000, 16000000000):
            for rate in (10, 15):
                with self.subTest(cents=cents, rate=rate):
                    proof = risc0_engine.generate_proof("bonus", [cents, rate])
                    whole, remainder = divmod(cents * rate, 100)
                    expected = whole + int(remainder > 50 or (remainder == 50 and whole % 2))
                    self.assertEqual(proof["result"], expected)
                    self.assertEqual(risc0_engine.verify_receipt(proof["receipt"])["result"], expected)

    def test_real_arithmetic_zero_duplicates_and_maximum_vector(self):
        for numbers in ([0], [7, 7, 7], [0, 16000000000], [16000000000] * 100):
            expected = {"sum": sum(numbers), "average": sum(numbers) // len(numbers),
                        "minimum": min(numbers), "maximum": max(numbers)}
            for operation, result in expected.items():
                with self.subTest(operation=operation, length=len(numbers)):
                    proof = risc0_engine.generate_proof(operation, numbers)
                    self.assertEqual(proof["result"], result)
                    self.assertEqual(risc0_engine.verify_receipt(proof["receipt"])["result"], result)
