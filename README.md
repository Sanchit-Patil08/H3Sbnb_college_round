# Verity

Verity is a local demonstration of bonus-computation verification using Flask,
RISC Zero receipts, SHA-256 commitments, and a Hardhat commitment registry.

## What is verified

- The RISC Zero guest computes the bonus in integer cents (10% or 15%), with
  half-even rounding matching Python Decimal. Its public journal binds the
  operation, salary, rate, and result.
- The host verifies serialized receipts against its compiled guest image ID.
  Every investigation and blockchain submission verifies the receipt again;
  a saved boolean or a re-created SHA-256 hash cannot substitute for a proof.
- Fake development receipts are explicitly rejected, even with RISC0_DEV_MODE=1.
- The four investigations compare the delivered output, committed input,
  agreed program, and cryptographic receipt. Adversarial scenarios leave the
  original submission intact.
- The contract accepts commitment records only from its authorized wallet and
  rejects duplicate IDs. It DOES NOT verify RISC Zero proofs on chain. The Flask
  verifier performs that check before submitting the commitments.
- SQLite audit entries are hash-chained. This is tamper evidence relative to a
  trusted head hash, not immutable storage. Salaries appear in the public proof
  journal; this demo does not provide salary confidentiality.

## Local prerequisites

Use Python 3.13, Node.js supported by the installed Hardhat version, and Ubuntu
under WSL with Rust and RISC Zero 3.0.6 tools installed. The Python 3.15 install
shown in the original error tried to compile `ckzg`; use the working Python 3.13
virtual environment instead. On this machine it is `.venv313`.

```powershell
# For a fresh machine with Python 3.13 installed:
py -3.13 -m venv .venv313
.\.venv313\Scripts\python.exe -m pip install -r requirements.txt
```

The active Rust project is `verity/`, not the older nested `verity/verity/`
template. Build from the active project in WSL:

```bash
cd /mnt/c/Users/harsh/OneDrive/Desktop/Verity/H3Sbnb_college_round-main/H3Sbnb_college_round/verity
CARGO_TARGET_DIR=$HOME/verity/target cargo build -p host
```

The tested host on this machine is `/home/harsh/verity/target/debug/host`.
Rebuild the host whenever the guest changes; its image ID changes with the guest.
Receipts from other guest builds will not verify.

## Start the local application

1. In a separate PowerShell terminal, start the development blockchain:

   ```powershell
   cd verity-chain
   npm install  # only needed if dependencies are not installed
   npx hardhat compile
   npx hardhat node --hostname 127.0.0.1
   ```

2. From the repository root, deploy the contract and create/update local `.env`:

   ```powershell
   .\.venv313\Scripts\python.exe scripts/configure_local.py --host /home/harsh/verity/target/debug/host
   ```

   This helper intentionally configures only the local Hardhat chain (31337),
   using its public development wallet. Never use this wallet with real funds.
   `.env` is ignored by Git. The helper preserves unrelated `.env` settings.
   Restarting Hardhat resets its in-memory chain; redeploy with this helper and
   restart Flask afterward. Old chain records do not survive a node reset.

3. Run Flask:

   ```powershell
   .\.venv313\Scripts\python.exe app.py
   ```

4. Open <http://127.0.0.1:5000>. Create a computation, run the provider,
   investigate the normal scenario, then record on blockchain. The Investigation
   Lab also supports altered output/input, a different rate, and invalid proof.

Shell environment variables override `.env`. `RISC0_WSL_DISTRO` defaults to
`Ubuntu`; `RISC0_TIMEOUT` defaults to 600 seconds. Missing or incompatible hosts
are shown as unavailable, and missing contracts/wrong wallets disable recording.

Historical reports created before the receipt-verification repair are presented
as INCOMPLETE. Their stored evidence is preserved. Legacy requests are marked
PROOF_REBUILD_REQUIRED and can be executed again to generate a valid new receipt.

## Validation

```powershell
# Fast regression tests; live integration test is skipped by default.
.\.venv313\Scripts\python.exe -m unittest discover -s tests -v

# Real receipts and transactions; requires the host and running local node.
$env:VERITY_LIVE_TESTS='1'
.\.venv313\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:VERITY_LIVE_TESTS

# Smart-contract access control and duplicate protection.
cd verity-chain
npx hardhat test
```

Live tests use a temporary SQLite database and deploy a separate local contract.
They cover all five investigation scenarios, real transaction/readback, repeat
recording without another transaction, half-cent rounding, maximum salary,
receipt-journal tampering, the four arithmetic operations, and fake receipt
rejection. Mocked tests are explicitly distinguished from genuine proof tests.

This is a localhost development app, not an authenticated production service.
