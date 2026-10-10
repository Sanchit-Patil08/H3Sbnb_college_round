# Verity

<p align="center">
  <strong>Verifiable Outsourced Computation & Tamper-Evident Audit Logging Platform</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python Version" />
  <img src="https://img.shields.io/badge/Framework-Flask_3.1-black.svg" alt="Flask" />
  <img src="https://img.shields.io/badge/Proof_Engine-zkVM_Ready_(Simulated)-orange.svg" alt="Proof Engine" />
  <img src="https://img.shields.io/badge/Audit_Log-SHA--256_Hash--Chained-green.svg" alt="Audit Trail" />
  <img src="https://img.shields.io/badge/License-MIT-lightgrey.svg" alt="License" />
</p>

---

## 📌 Overview

**Verity** solves the trust problem in outsourced and untrusted cloud computations. When offloading sensitive business logic—such as bonus payroll, compliance checks, or algorithmic evaluations—requesters traditionally must trust that:
1. The remote worker ran the **agreed program**,
2. On the **unmodified inputs**, and
3. Returned the **authentic result** without post-computation tampering.

Verity provides an end-to-end architecture demonstrating **verifiable compute** using cryptographic commitments, proof-engine abstraction (ready for zkVMs like RISC Zero), hash-chained tamper-evident audit logs, and an interactive adversarial test laboratory.

---

## ⚡ Key Features

- 🔐 **Commitment-Based Compute:** Canonical JSON serialization and SHA-256 commitments ensure input and program integrity before computation begins.
- 🧩 **Pluggable Proof Engine:** Clean adapter architecture (`SimulatedProofEngine`) exposing `execute`, `prove`, and `verify` interfaces—ready for drop-in zero-knowledge proof backends (e.g., RISC Zero zkVM).
- ⛓️ **Tamper-Evident Hash-Chained Audit Trail:** Every event (creation, execution, proof generation, investigation) is cryptographically chained (`prev_hash` + event metadata $\to$ `hash`) for verifiable event logs.
- 🧪 **Interactive Adversarial Test Suite:** Built-in scenario simulator allowing instant evaluation of normal workflows vs. attacks:
  - **Normal Computation:** Honest inputs, agreed program, authentic output.
  - **Altered Output:** Proof is genuine, but delivered answer is manipulated post-computation.
  - **Altered Input:** Provider computes on unauthorized/mutated input values.
  - **Wrong Program:** Provider executes an unagreed program (e.g. 15% rate instead of agreed 10%).
  - **Invalid Proof:** Forged proof seal submitted to test verifier enforcement.
- 🔍 **Four Pillars of Verification:**
  1. **Output Integrity:** Confirms returned answer matches the proof-bound journal output.
  2. **Input Integrity:** Matches journal commitment to the initial stored commitment.
  3. **Program Integrity:** Validates that the executed binary/rule digest matches the agreed spec.
  4. **Proof Validity:** Cryptographic verification of the proof receipt and seal.
- 📊 **Real-Time Web Dashboard:** Responsive single-page interface with metrics, audit log inspector, scenario runners, and run reports.

---

## 🏛️ System Architecture

```text
 Requester                      Verity Platform                     Compute Provider
    │                                  │                                   │
    │  1. Submit Inputs & Program Spec  │                                   │
    ├─────────────────────────────────>│                                   │
    │                                  ├─ Calculate SHA-256 Commitments    │
    │                                  ├─ Append to Hash-Chained Audit Log │
    │                                  │                                   │
    │                                  │  2. Dispatch Execution            │
    │                                  ├──────────────────────────────────>│
    │                                  │                                   ├─ Execute Code
    │                                  │                                   ├─ Generate Proof & Seal
    │                                  │  3. Return Claimed Output + Proof │
    │                                  │<──────────────────────────────────┤
    │                                  │                                   │
    │  4. Run 4-Point Investigation    │                                   │
    │<─────────────────────────────────┤                                   │
    │                                  ├─ 1. Output Integrity              │
    │                                  ├─ 2. Input Integrity               │
    │                                  ├─ 3. Program Integrity             │
    │                                  ├─ 4. Proof Seal Validity           │
    │                                  │                                   │
    │  5. Final Verdict (VERIFIED/REJECTED)                                │
    │<─────────────────────────────────┤                                   │
```

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.10+**
- **pip**

### 1. Clone & Navigate
```bash
git clone https://github.com/Sanchit-Patil08/H3Sbnb_college_round.git
cd H3Sbnb_college_round
```

### 2. Setup Virtual Environment

#### Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Application
```bash
python app.py
```

The application will start at:
👉 **[http://127.0.0.1:5000](http://127.0.0.1:5000)**

---

## 📡 API Reference

### Requests & Lifecycle
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/requests` | Create a new verifiable computation request |
| `GET` | `/api/requests` | List all computation requests |
| `GET` | `/api/requests/<id>` | Fetch specific request details |
| `POST` | `/api/requests/<id>/execute` | Execute computation and generate proof receipt |
| `POST` | `/api/requests/<id>/record` | Record/anchor commitment via chain adapter |

### Verification & Investigation
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/requests/<id>/investigate` | Run four-pillar verification (supports adversarial scenarios) |
| `GET` | `/api/requests/<id>/reports` | List all investigation runs for a request |
| `GET` | `/api/reports/<run_id>` | Fetch detailed investigation report and evidence |

### Analytics & Audit Trail
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/dashboard` | Aggregated statistics, recent runs, and verification rates |
| `GET` | `/api/audit` | Query hash-chained audit logs with filter params |
| `GET` | `/api/scenarios` | List available test scenarios |
| `GET` | `/api/integrations` | Adapter runtime statuses (Proof Engine & Blockchain) |

---

## 📁 Repository Structure

```
├── app.py                  # Flask backend, adapters, audit logger, and API endpoints
├── requirements.txt        # Pinned Python package dependencies
├── .gitignore              # Git ignore rules (.venv, *.db, caches)
├── README.md               # Project documentation
├── templates/
│   ├── base.html           # Core HTML shell & typography
│   ├── index.html          # Dashboard & verification interface
│   └── partials/
│       ├── icons.html      # Inline SVG icon partials
│       ├── sidebar.html    # Navigation sidebar
│       └── topbar.html     # Application topbar
└── static/
    ├── css/
    │   └── main.css        # Modern design system & styling
    └── js/
        ├── app.js          # App bootstrapper
        ├── core.js         # API client & utilities
        └── pages.js        # Interactive views, forms, & investigation runners
```

---

## 🛡️ Security & Integrity Model

- **Deterministic Serialization:** Commitments are generated from canonical JSON representations (`separators=(',', ':')`, `sort_keys=True`).
- **Chain of Custody:** The audit log maintains an immutable hash chain:
  $$\text{Hash}_i = \text{SHA256}(\text{Hash}_{i-1} \parallel \text{Timestamp} \parallel \text{RequestID} \parallel \text{Type} \parallel \text{Status} \parallel \text{Evidence})$$
- **Simulation Disclaimer:** The default engine runs in `SIMULATION` mode for rapid local evaluation. Cryptographic verification seals are simulated with SHA-256 and explicitly tagged for transparency.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
