# Jupyter Book — Group 18 arXiv Project

## Build locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
jupyter-book build .
```

PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
jupyter-book build .
```

The book executes its notebooks during build. The M1 notebooks use only aggregated, verified shard metrics and do not require the raw corpus. Do not commit raw archives, extracted corpus, Parquet tables, checkpoints, API caches, logs containing sensitive information, or API keys.
