#!/usr/bin/env bash
# Launcher for the GraphRAG GUI.
set -euo pipefail
cd "$(dirname "$0")"

# QtWebEngine needs this on many Linux setups.
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:---no-sandbox}"

exec .venv/bin/python -m app.main "$@"
