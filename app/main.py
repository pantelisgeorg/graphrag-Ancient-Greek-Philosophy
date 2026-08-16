"""Entry point: start the GraphRAG GUI."""
from __future__ import annotations

import os
import signal
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

# QtWebEngine on some Linux setups requires this flag, set before QApplication is constructed.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("GraphRAG GUI")
    app.setOrganizationName("graphrag-gui")

    # Make Ctrl+C in the launching terminal quit the app. Qt's C++ event loop
    # blocks Python signal delivery; a 200 ms idle timer lets the Python
    # interpreter run periodically so SIGINT can be handled.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    sigint_pump = QTimer()
    sigint_pump.start(200)
    sigint_pump.timeout.connect(lambda: None)

    # Import after QApplication so QtWebEngine initializes against the right app.
    from .ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
