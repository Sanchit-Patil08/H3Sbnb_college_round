import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class BlockchainConfigTests(unittest.TestCase):
    def test_import_without_required_env_vars(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            services_dir = project_root / "services"
            services_dir.mkdir()
            (services_dir / "__init__.py").write_text("", encoding="utf-8")
            source = (ROOT / "services" / "blockchain.py").read_text(encoding="utf-8")
            (services_dir / "blockchain.py").write_text(source, encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "BLOCKCHAIN_RPC_URL": "",
                    "CONTRACT_ADDRESS": "",
                    "VERIFIER_PRIVATE_KEY": "",
                },
                clear=True,
            ):
                sys.path.insert(0, str(project_root))
                try:
                    sys.modules.pop("services.blockchain", None)
                    blockchain = importlib.import_module("services.blockchain")
                    self.assertIsNone(blockchain.RPC_URL)
                    self.assertIsNone(blockchain.CONTRACT_ADDRESS)
                    self.assertIsNone(blockchain.PRIVATE_KEY)
                finally:
                    sys.path.remove(str(project_root))
                    sys.modules.pop("services.blockchain", None)


if __name__ == "__main__":
    unittest.main()
