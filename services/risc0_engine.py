import os
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

candidate_paths = [
    Path(os.getenv("RISC0_PROJECT_PATH", "")).expanduser() if os.getenv("RISC0_PROJECT_PATH") else None,
    BASE_DIR / "verity",
    BASE_DIR / "verity" / "verity",
    Path("/home/harsh/verity"),
]
RUST_PROJECT = next((p for p in candidate_paths if p and p.exists()), BASE_DIR / "verity")
HOST_BINARY = Path(os.getenv("RISC0_HOST_BIN", str(RUST_PROJECT / "target" / "debug" / "host"))).expanduser()

if not HOST_BINARY.exists() and os.name == "nt":
    alt = HOST_BINARY.with_suffix(".exe")
    if alt.exists():
        HOST_BINARY = alt


def _run_host(command, cwd):
    try:
        return subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, timeout=180, check=True)
    except OSError:
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if os.name == "nt" and wsl:
            wsl_binary = os.getenv("RISC0_HOST_BIN", "/home/harsh/verity/target/debug/host")
            return subprocess.run(
                [wsl, "-e", str(wsl_binary), *command[1:]],
                capture_output=True,
                text=True,
                timeout=180,
                check=True,
            )
        raise

OPERATIONS = {
    "sum": 1,
    "average": 2,
    "maximum": 3,
    "minimum": 4,
}


def generate_proof(operation, numbers):
    if operation not in OPERATIONS:
        raise ValueError("Unsupported operation")

    if (
        not isinstance(numbers, list)
        or not 1 <= len(numbers) <= 100
        or any(type(n) is not int or n < 0 or n > 4294967295 for n in numbers)
    ):
        raise ValueError("Invalid input numbers")

    command = [
        str(HOST_BINARY),
        str(OPERATIONS[operation]),
        *[str(n) for n in numbers],
    ]

    result = _run_host(command, RUST_PROJECT)

    output = {}

    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            output[key] = value

    if output.get("PROOF_VERIFIED") != "true":
        raise RuntimeError("Proof verification failed")

    if int(output["OPERATION"]) != OPERATIONS[operation]:
        raise RuntimeError("Operation mismatch")

    import ast

    proved_numbers = ast.literal_eval(output["INPUT"])

    if proved_numbers != numbers:
        raise RuntimeError("Input mismatch")

    return {
        "operation": operation,
        "numbers": numbers,
        "result": int(output["RESULT"]),
        "proof_verified": True,
    }