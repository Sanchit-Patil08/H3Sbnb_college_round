"""Versioned JSON interface to the locally trusted RISC Zero host executable."""
import json
import os
import shutil
import subprocess
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)
OPERATIONS = {"sum": 1, "average": 2, "maximum": 3, "minimum": 4, "bonus": 5}

def _run_host(args, payload=None):
    binary = os.getenv("RISC0_HOST_BIN", "").strip()
    if not binary:
        raise RuntimeError("RISC0_HOST_BIN must point to the rebuilt Verity RISC Zero host")
    command = [binary, *args]
    if os.name == "nt" and binary.startswith("/"):
        wsl = shutil.which("wsl.exe")
        if not wsl:
            raise RuntimeError("WSL is required for the Linux RISC Zero host")
        command = [wsl, "-d", os.getenv("RISC0_WSL_DISTRO", "Ubuntu"), "-e", *command]
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            cwd=BASE_DIR, capture_output=True, text=True,
                            timeout=int(os.getenv("RISC0_TIMEOUT", "600")), check=False)
    if result.returncode:
        error_type = ValueError if args == ["verify"] else RuntimeError
        raise error_type("RISC Zero host failed: " + (result.stderr.strip()[-1500:] or "unknown error"))
    try:
        output = json.loads(result.stdout)
        if output.get("protocol") != "verity-risc0/v2":
            raise ValueError("protocol mismatch")
        return output
    except (ValueError, AttributeError) as exc:
        raise RuntimeError("Incompatible RISC Zero host; rebuild verity/host") from exc

def proof_status():
    try:
        info = _run_host(["info"])
        return {"available": True, "image_id": info["image_id"],
                "detail": "Host available; receipts are verified against its compiled guest image."}
    except Exception as exc:
        return {"available": False, "detail": str(exc)}

def verify_receipt(receipt):
    if not isinstance(receipt, dict):
        raise ValueError("Missing serialized RISC Zero receipt")
    output = _run_host(["verify"], receipt)
    if output.get("proof_verified") is not True:
        raise ValueError("RISC Zero receipt verification failed")
    return output

def generate_proof(operation, numbers):
    if operation not in OPERATIONS:
        raise ValueError("Unsupported operation")
    if (not isinstance(numbers, list) or not 1 <= len(numbers) <= 100
            or any(type(n) is not int or not 0 <= n <= 16_000_000_000 for n in numbers)):
        raise ValueError("Invalid input numbers")
    output = _run_host(["prove", str(OPERATIONS[operation]), *map(str, numbers)])
    if (output.get("proof_verified") is not True or output.get("operation") != OPERATIONS[operation]
            or output.get("numbers") != numbers or not isinstance(output.get("receipt"), dict)):
        raise RuntimeError("Proof result does not match the requested computation")
    return output
