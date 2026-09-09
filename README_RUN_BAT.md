# Chạy bằng file BAT

1. Giải nén zip.
2. Mở thư mục `auto_video_renderer`.
3. Chạy `setup.bat` một lần đầu để tạo `.venv` và cài thư viện.
4. Từ lần sau chỉ cần chạy `run.bat`.

`run.bat` dùng `pythonw.exe`, nên sẽ không mở cửa sổ CMD treo phía sau.

Nếu app không mở hoặc bị lỗi im lặng, chạy `run_debug.bat` để xem lỗi trong CMD.

Mặc định `setup.bat` ưu tiên Python tại:

```text
E:\appp\python\python.exe
```

Nếu Python của bạn nằm chỗ khác, mở `setup.bat` bằng Notepad rồi sửa dòng `PY_EXE` cho đúng đường dẫn.

## Ghi chú V5.3

`run.bat` dùng `pythonw.exe` và bản V5.3 đã ẩn luôn các process FFmpeg/FFprobe con, nên khi render sẽ không còn nháy cửa sổ CMD liên tục. Nếu cần xem lỗi thật thì dùng `run_debug.bat`.
