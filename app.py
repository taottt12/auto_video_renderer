import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

# Cấu hình chống crash OpenMP đa luồng, CUDA module loading và mã hóa UTF-8
os.environ["CUDA_MODULE_LOADING"] = "LAZY"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["QT_FORCE_STDERR_LOGGING"] = "1"

# Xóa các biến ép buộc hạn chế bộ nhớ cuBLAS gây lỗi CUBLAS_STATUS_EXECUTION_FAILED
os.environ.pop("CUBLAS_WORKSPACE_CONFIG", None)
os.environ.pop("CT2_CUDA_ALLOCATOR", None)

# Thêm thư mục gốc và src_app vào sys.path
_ROOT = Path(__file__).resolve().parent
_SRC_APP = _ROOT / "src_app"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_SRC_APP) not in sys.path:
    sys.path.insert(0, str(_SRC_APP))

from PySide6.QtWidgets import QApplication

from src_app.core.paths import ensure_dirs, LOG_DIR
from src_app.core.subtitle_utils import ensure_cuda_whisper_libraries, _register_cuda_dll_directories
from src_app.ui.main_window import MainWindow


def _setup_crash_logger() -> None:
    """Bắt và ghi nhận tất cả ngoại lệ chưa được xử lý để tránh Python/Qt sập đột ngột không rõ lý do."""
    ensure_dirs()
    crash_file = LOG_DIR / "crash.log"

    def _global_excepthook(exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(crash_file, "a", encoding="utf-8") as f:
                f.write(f"\n[{t}] CRASH EXCEPTION (Main Thread):\n{msg}\n")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def _thread_excepthook(args):
        msg = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(crash_file, "a", encoding="utf-8") as f:
                f.write(f"\n[{t}] CRASH EXCEPTION (Thread {args.thread.name}):\n{msg}\n")
        except Exception:
            pass
        print(f"⚠️ Đã bắt lỗi luồng [{args.thread.name}]: {args.exc_value}", file=sys.stderr)

    sys.excepthook = _global_excepthook
    threading.excepthook = _thread_excepthook


def main() -> int:
    _setup_crash_logger()
    ensure_cuda_whisper_libraries()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

