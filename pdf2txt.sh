# Standalone PDF → .txt helper for GraphRAG ingest.
# Drops cleaned text files into a project's `input/` directory.
# Run with: ./pdf2txt.sh  (or  .venv/bin/python -m app.pdf_to_text)

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

exec .venv/bin/python -m app.pdf_to_text "$@"


