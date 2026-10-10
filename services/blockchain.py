import json
import os
from pathlib import Path

from dotenv import load_dotenv
from eth_abi import encode
from web3 import Web3

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=True)
load_dotenv(override=True)


def _read_env(name):
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


RPC_URL = _read_env("BLOCKCHAIN_RPC_URL")
CONTRACT_ADDRESS = _read_env("CONTRACT_ADDRESS")
PRIVATE_KEY = _read_env("VERIFIER_PRIVATE_KEY")


def _resolve_abi_path():
    configured = os.getenv("VERITY_ABI_PATH")
    candidates = []

    if configured:
        candidates.append(Path(configured).expanduser())

    candidates.extend(
        [
            BASE_DIR / "verity-chain" / "artifacts" / "contracts" / "VerityAudit.sol" / "VerityAudit.json",
            BASE_DIR / "verity" / "chain" / "artifacts" / "contracts" / "VerityAudit.sol" / "VerityAudit.json",
            BASE_DIR / "artifact" / "contracts" / "VerityAudit.sol" / "VerityAudit.json",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    fallback = candidates[0] if candidates else BASE_DIR / "verity-chain" / "artifacts" / "contracts" / "VerityAudit.sol" / "VerityAudit.json"
    return fallback


ABI_PATH = _resolve_abi_path()

if ABI_PATH.exists():
    with open(ABI_PATH, encoding="utf-8") as file:
        contract_abi = json.load(file)["abi"]
else:
    contract_abi = []

w3 = Web3(Web3.HTTPProvider(RPC_URL)) if RPC_URL else None
contract = None
account = None

if w3 is not None and CONTRACT_ADDRESS and PRIVATE_KEY:
    try:
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(CONTRACT_ADDRESS),
            abi=contract_abi,
        )
        account = w3.eth.account.from_key(PRIVATE_KEY)
    except (ValueError, TypeError) as exc:
        w3 = None
        contract = None
        account = None


def record_audit(operation, numbers, result, program_id):
    if w3 is None or contract is None or account is None:
        raise RuntimeError(
            "Blockchain configuration is incomplete. Set BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS, and VERIFIER_PRIVATE_KEY in your .env file or environment."
        )

    if not w3.is_connected():
        raise RuntimeError("Blockchain is not connected")

    if w3.eth.chain_id != 31337:
        raise RuntimeError("Unexpected blockchain network")

    if contract.functions.verifier().call() != account.address:
        raise RuntimeError("Wallet is not the authorized verifier")

    # These are canonical ABI-encoded commitments.
    operation_ids = {
        "sum": 1,
        "average": 2,
        "maximum": 3,
        "minimum": 4,
    }

    input_data = encode(
        ["uint32", "uint32[]"],
        [operation_ids[operation], numbers],
    )

    output_data = encode(["uint64"], [result])

    input_hash = Web3.keccak(input_data)
    output_hash = Web3.keccak(output_data)

    request_id = Web3.keccak(
        input_hash + output_hash + os.urandom(16)
    )

    if not isinstance(program_id, bytes) or len(program_id) != 32:
        raise ValueError("Program ID must be 32 bytes")

    transaction = contract.functions.recordAudit(
        request_id,
        input_hash,
        program_id,
        output_hash,
    ).build_transaction({
        "from": account.address,
        "chainId": w3.eth.chain_id,
        "nonce": w3.eth.get_transaction_count(account.address, "pending"),
        "gas": 300000,
        "gasPrice": w3.eth.gas_price,
    })

    signed = account.sign_transaction(transaction)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt.status != 1:
        raise RuntimeError("Blockchain transaction failed")

    return {
        "request_id": Web3.to_hex(request_id),
        "transaction_hash": Web3.to_hex(tx_hash),
        "block_number": receipt.blockNumber,
        "blockchain_status": "recorded",
    }