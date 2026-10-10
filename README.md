# Verity

Verity is a verifiable compute and tamper-evident audit logging demonstration platform built with Flask. It showcases commitment-based computation verification, zero-knowledge proof simulation, and hash-chained audit trails.

## Features

- **Commitment-Based Compute:** Cryptographic commitment to input parameters and agreed execution programs.
- **Proof Engine Abstraction:** Modular proof adapter architecture (`SimulatedProofEngine`) ready for zkVM integration (e.g., RISC Zero).
- **Tamper-Evident Audit Trail:** SHA-256 hash-chained audit log for integrity tracking across all requests and runs.
- **Interactive Verification Suite:** Test suite covering normal runs, tampered outputs, tampered programs, and proof validation states.
- **Modern UI:** Clean, responsive web dashboard for configuring inputs, executing verifiable tasks, and inspecting audit trails.

---

## Getting Started

### Prerequisites

- Python 3.10+
- `pip`

### Installation

1. **Clone the repository:**
   ```bash
   git clone <YOUR_GITHUB_REPOSITORY_URL>
   cd Verity
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # Windows (PowerShell)
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1

   # macOS / Linux
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

### Running the Application

Start the Flask development server:
```bash
python app.py
```

The application will be available at:
`http://127.0.0.1:5000`

---

## Project Structure

```
Verity/
├── app.py                # Main Flask backend application & adapters
├── requirements.txt      # Python dependencies
├── .gitignore            # Git exclusion rules
├── templates/            # HTML templates (Jinja2)
│   ├── base.html
│   ├── index.html
│   └── partials/         # Modular layout partials
└── static/               # Client-side assets
    ├── css/              # Application stylesheets
    └── js/               # Frontend logic & interactions
```
