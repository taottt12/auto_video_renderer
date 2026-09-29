from __future__ import annotations

import sys
from pathlib import Path

# Thêm thư mục gốc và src_app vào sys.path
_ROOT = Path(__file__).resolve().parent
_SRC_APP = _ROOT / "src_app"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_SRC_APP) not in sys.path:
    sys.path.insert(0, str(_SRC_APP))

from PySide6.QtWidgets import QApplication

from src_app.core.paths import ensure_dirs
from src_app.ui.main_window import MainWindow


def main() -> int:
    ensure_dirs()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

