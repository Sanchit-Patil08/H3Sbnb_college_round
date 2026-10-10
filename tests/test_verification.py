"""Regression tests. Mocked receipt tests are not evidence of real zkVM proving."""
import copy
import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

_import_db = tempfile.TemporaryDirectory()
_previous_db = os.environ.get("VERITY_DB")
os.environ["VERITY_DB"] = str(Path(_import_db.name) / "import.db")
import app as backend
if _previous_db is None:
    os.environ.pop("VERITY_DB", None)
else:
    os.environ["VERITY_DB"] = _previous_db


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch = patch.object(backend, "DB", str(Path(self.tmp.name) / "test.db"))
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        with closing(sqlite3.connect(backend.DB)) as db:
            db.executescript(backend.SCHEMA)
        self.client = backend.app.test_client()

    def create_request(self, salary="1000.05"):
        response = self.client.post("/api/requests", json={"salary": salary})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json["id"]

    def mocked_prover(self, operation, numbers):
        result = int(backend.Decimal(backend.ENGINE.execute(
            f"bonus-{numbers[1]}pct@1.0.0", {"salary": str(backend.Decimal(numbers[0]) / 100)})) * 100)
        return {"operation": 5, "numbers": numbers, "result": result,
                "proof_verified": True, "receipt": {"test_numbers": numbers, "test_result": result}}

    @staticmethod
    def mocked_verifier(receipt):
        if not isinstance(receipt, dict) or "test_numbers" not in receipt:
            raise ValueError("invalid test receipt")
        return {"operation": 5, "numbers": receipt["test_numbers"], "result": receipt["test_result"]}

    def test_invalid_requests(self):
        for body in ([1], "salary", {"salary": True}, {"salary": "NaN"},
                     {"salary": "Infinity"}, {"salary": -1}, {"salary": 100000001}):
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/api/requests", json=body).status_code, 400)
        rid = self.create_request("100000000")
        self.assertEqual(self.client.post(f"/api/requests/{rid}/record").status_code, 409)
        self.assertEqual(self.client.post(f"/api/requests/{rid}/investigate", json={"scenario": []}).status_code, 400)

    def test_full_flow_and_tamper_scenarios_with_mocked_host(self):
        with patch.object(backend, "generate_proof", self.mocked_prover), patch.object(backend, "verify_receipt", self.mocked_verifier):
            rid = self.create_request()
            self.assertEqual(self.client.post(f"/api/requests/{rid}/execute").status_code, 200)
            for scenario, expected in [("normal", "VERIFIED"), ("altered_output", "REJECTED"),
                                       ("altered_input", "REJECTED"), ("wrong_program", "REJECTED"), ("invalid_proof", "REJECTED")]:
                response = self.client.post(f"/api/requests/{rid}/investigate", json={"scenario": scenario})
                self.assertEqual(response.status_code, 200, response.json)
                self.assertEqual(response.json["verdict"], expected, response.json)
                self.assertEqual(self.client.get("/api/reports/" + response.json["run_id"]).status_code, 200)
            self.assertEqual(self.client.get(f"/api/requests/{rid}").json["status"], "VERIFIED")
        with closing(sqlite3.connect(backend.DB)) as db:
            previous = "0" * 64
            for row in db.execute("select ts,request_id,type,status,evidence,prev_hash,hash from audit order by seq"):
                self.assertEqual(row[5], previous)
                self.assertEqual(row[6], backend.sha([previous, *row[:5]]))
                previous = row[6]
        for url in ("/", "/api/dashboard", "/api/audit", "/api/scenarios", "/api/requests"):
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_receipt_flag_and_rehashed_journal_cannot_forge_proof(self):
        engine = backend.Risc0ProofEngine()
        self.assertNotEqual(engine.verify({"proof_verified": True})["status"], "VERIFIED")
        with patch.object(backend, "generate_proof", self.mocked_prover), patch.object(backend, "verify_receipt", self.mocked_verifier):
            receipt = engine.prove(backend.AGREED, {"salary": "1000.05"}, "100.00")
            self.assertEqual(engine.verify(receipt)["status"], "VERIFIED")
            for field, value in [("output", "100.001"), ("input_commitment", "0" * 64),
                                 ("program_id", "bonus-15pct@1.0.0"), ("program_digest", "0" * 64)]:
                bad = copy.deepcopy(receipt)
                bad["journal"][field] = value
                bad["receipt_ref"] = "risc0-" + backend.sha({"proof": bad["native_proof"], "journal": bad["journal"]})[:16]
                self.assertEqual(engine.verify(bad)["status"], "FAILED", field)

    def test_prover_failures_are_reported_without_losing_request(self):
        rid = self.create_request()
        with patch.object(backend, "generate_proof", side_effect=RuntimeError("prover offline")):
            response = self.client.post(f"/api/requests/{rid}/execute")
            self.assertEqual(response.status_code, 502)
        self.assertEqual(self.client.get(f"/api/requests/{rid}").json["status"], "CREATED")

    def test_legacy_report_is_not_presented_as_verified(self):
        report = backend.public_report({"mode": "RISC0", "verdict": "VERIFIED", "proof_status": "VERIFIED",
                                        "findings": [{"status": "PASSED"}], "limitations": []})
        self.assertEqual(report["verdict"], "INCOMPLETE")
        self.assertEqual(report["findings"][0]["code"], "LEGACY_UNVERIFIED")

    def test_verifier_unavailable_is_incomplete(self):
        with patch.object(backend, "verify_receipt", side_effect=RuntimeError("host is not configured")):
            result = backend.ENGINE.verify({"native_proof": {"receipt": {}}, "journal": {
                "program_id": backend.AGREED, "program_digest": backend.PROGRAMS[backend.AGREED]["digest"],
                "input_commitment": backend.sha({"salary": "100.00"}), "output": "10.00"}})
        self.assertEqual(result["status"], "INCOMPLETE")

    def test_explicit_verifier_rejection_is_failed(self):
        from services import risc0_engine

        with patch.object(risc0_engine, "_run_host", return_value={"proof_verified": False}):
            with self.assertRaisesRegex(ValueError, "receipt verification failed"):
                risc0_engine.verify_receipt({})


@unittest.skipUnless(os.getenv("VERITY_LIVE_TESTS") == "1", "Requires real RISC Zero host and local Hardhat RPC")
class LiveTests(unittest.TestCase):
    setUp = AppTests.setUp
    create_request = AppTests.create_request
    mocked_prover = AppTests.mocked_prover
    mocked_verifier = staticmethod(AppTests.mocked_verifier)

    def test_parallel_real_transactions_with_mocked_proofs(self):
        from web3 import Web3
        chain = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
        self.assertEqual(chain.eth.chain_id, 31337)
        chain.eth.account.enable_unaudited_hdwallet_features()
        account = chain.eth.account.from_mnemonic("test test test test test test test test test test test junk")
        artifact = json.loads((Path(__file__).resolve().parents[1] / "verity-chain/artifacts/contracts/VerityAudit.sol/VerityAudit.json").read_text())
        factory = chain.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
        deployed = chain.eth.wait_for_transaction_receipt(factory.constructor().transact({"from": account.address}))
        contract = chain.eth.contract(address=deployed.contractAddress, abi=artifact["abi"])
        with patch.multiple(backend, w3=chain, account=account, contract=contract, ABI_ERROR=None, CONFIG_ERROR=None), \
                patch.object(backend, "generate_proof", self.mocked_prover), patch.object(backend, "verify_receipt", self.mocked_verifier):
            ids = [self.create_request(str(100 + i)) for i in range(6)]
            for rid in ids:
                self.assertEqual(self.client.post(f"/api/requests/{rid}/execute").status_code, 200)
            nonce = chain.eth.get_transaction_count(account.address)
            def record(rid):
                with backend.app.test_client() as client:
                    response = client.post(f"/api/requests/{rid}/record")
                    return response.status_code, response.json
            with ThreadPoolExecutor(max_workers=6) as pool:
                responses = list(pool.map(record, ids))
            for status, data in responses:
                self.assertEqual(status, 200)
                self.assertEqual(data["status"], "RECORDED", data)
                self.assertTrue(contract.functions.requestExists(Web3.to_bytes(hexstr=data["request_id"])).call())
            self.assertEqual(chain.eth.get_transaction_count(account.address), nonce + 6)
            with ThreadPoolExecutor(max_workers=4) as pool:
                duplicates = list(pool.map(record, [ids[0]] * 4))
            self.assertTrue(all(data["tx"] == responses[0][1]["tx"] for _, data in duplicates))
            self.assertEqual(chain.eth.get_transaction_count(account.address), nonce + 6)

    def test_real_proof_blockchain_and_tampering(self):
        from services import risc0_engine
        from web3 import Web3
        chain = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
        self.assertEqual(chain.eth.chain_id, 31337)
        # Standard public Hardhat development account; never use with real funds.
        chain.eth.account.enable_unaudited_hdwallet_features()
        account = chain.eth.account.from_mnemonic("test test test test test test test test test test test junk")
        artifact = json.loads((Path(__file__).resolve().parents[1] / "verity-chain/artifacts/contracts/VerityAudit.sol/VerityAudit.json").read_text())
        factory = chain.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
        tx = factory.constructor().transact({"from": account.address})
        deployed = chain.eth.wait_for_transaction_receipt(tx)
        contract = chain.eth.contract(address=deployed.contractAddress, abi=artifact["abi"])
        with patch.multiple(backend, w3=chain, account=account, contract=contract, ABI_ERROR=None, CONFIG_ERROR=None):
            self.assertTrue(backend.CHAIN.enabled)
            rid = self.create_request()
            response = self.client.post(f"/api/requests/{rid}/execute")
            self.assertEqual(response.status_code, 200, response.json)
            for scenario, verdict in [("normal", "VERIFIED"), ("altered_output", "REJECTED"),
                                      ("altered_input", "REJECTED"), ("wrong_program", "REJECTED"), ("invalid_proof", "REJECTED")]:
                report = self.client.post(f"/api/requests/{rid}/investigate", json={"scenario": scenario})
                self.assertEqual(report.status_code, 200, report.json)
                self.assertEqual(report.json["verdict"], verdict, report.json)
            response = self.client.post(f"/api/requests/{rid}/record")
            self.assertEqual(response.json["status"], "RECORDED", response.json)
            self.assertTrue(response.json["tx"])
            saved = contract.functions.audits(Web3.keccak(text=rid)).call()
            self.assertTrue(saved[3])
            nonce = chain.eth.get_transaction_count(account.address)
            self.assertEqual(self.client.post(f"/api/requests/{rid}/record").json["status"], "RECORDED")
            self.assertEqual(chain.eth.get_transaction_count(account.address), nonce)
            print("LIVE: all five scenarios and on-chain record/readback/idempotency passed")
        for salary in ("0.05", "0.15", "100000000.00"):
            output = backend.ENGINE.execute(backend.AGREED, {"salary": salary})
            receipt = backend.ENGINE.prove(backend.AGREED, {"salary": salary}, output)
            self.assertEqual(backend.ENGINE.verify(receipt)["status"], "VERIFIED")
            tampered = copy.deepcopy(receipt)
            tampered["native_proof"]["receipt"]["journal"]["bytes"][0] ^= 1
            self.assertEqual(backend.ENGINE.verify(tampered)["status"], "FAILED")
        for operation, result in (("sum", 6), ("average", 2), ("maximum", 3), ("minimum", 1)):
            proof = risc0_engine.generate_proof(operation, [1, 2, 3])
            self.assertEqual(proof["result"], result)
            self.assertEqual(risc0_engine.verify_receipt(proof["receipt"])["result"], result)
        with patch.dict(os.environ, {"RISC0_DEV_MODE": "1", "WSLENV": "RISC0_DEV_MODE"}):
            with self.assertRaises(RuntimeError):
                risc0_engine.generate_proof("bonus", [100, 10])


if __name__ == "__main__":
    unittest.main()
