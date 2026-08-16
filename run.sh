#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Required for QtWebEngine on many Linux configs (esp. when Chromium sandbox isn't usable).
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:---no-sandbox}"

# Leave QT_QPA_PLATFORM unset by default — Qt picks the best available plugin
# (xcb on X11, wayland on Wayland). Override explicitly if needed, e.g.
#   QT_QPA_PLATFORM=wayland ./run.sh

exec .venv/bin/python -m app.main "$@"
