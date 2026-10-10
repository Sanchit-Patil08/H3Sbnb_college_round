"""Deploy the local demo contract and configure .env. Requires a running Hardhat node."""
import argparse
import json
from pathlib import Path
from web3 import Web3
from dotenv import set_key

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Absolute RISC Zero host path (Linux path for WSL)")
    args = parser.parse_args()
    chain = Web3(Web3.HTTPProvider("http://127.0.0.1:8545", request_kwargs={"timeout": 5}))
    if not chain.is_connected() or chain.eth.chain_id != 31337:
        raise SystemExit("Start a local Hardhat node on port 8545 first (chain ID 31337).")
    # This public development mnemonic is exclusively for the loopback demo chain.
    chain.eth.account.enable_unaudited_hdwallet_features()
    account = chain.eth.account.from_mnemonic("test test test test test test test test test test test junk")
    artifact = json.loads((ROOT / "verity-chain/artifacts/contracts/VerityAudit.sol/VerityAudit.json").read_text())
    contract = chain.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
    tx = contract.constructor().transact({"from": account.address})
    receipt = chain.eth.wait_for_transaction_receipt(tx)
    if receipt.status != 1:
        raise SystemExit("Contract deployment failed")
    settings = {"BLOCKCHAIN_RPC_URL": "http://127.0.0.1:8545", "CONTRACT_ADDRESS": receipt.contractAddress,
                "VERIFIER_PRIVATE_KEY": account.key.hex(),
                "VERITY_ABI_PATH": "./verity-chain/artifacts/contracts/VerityAudit.sol/VerityAudit.json",
                "RISC0_HOST_BIN": args.host, "RISC0_WSL_DISTRO": "Ubuntu"}
    for key, value in settings.items():
        set_key(ROOT / ".env", key, value)
    print("Local demo contract deployed:", receipt.contractAddress)
    print("Configured .env for the local development chain. Restart Flask to load it.")


if __name__ == "__main__":
    main()
