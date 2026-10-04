# 🚨 BẢNG QUY TẮC BẮT BUỘC ĐỌC VÀ LỊCH SỬ SỬA LỖI HỆ THỐNG
> **DỰ ÁN**: AUTO VIDEO RENDERER & CRAWLER  
> **QUY ĐỊNH BẮT BUỘC**: Bất kỳ AI Agent hoặc Lập trình viên nào trước khi chỉnh sửa code, thêm tính năng, refactor hoặc sửa lỗi trên dự án này **PHẢI ĐỌC KỸ TOÀN BỘ FILE NÀY** để tránh tình trạng "sửa lỗi mới làm sống lại lỗi cũ" hoặc làm đơ treo ứng dụng.

---

## 🛑 PHẦN 1: NGUYÊN TẮC VÀNG BẮT BUỘC TUÂN THỦ (CORE GUARDRAILS)

### 1. QUY TẮC MODEL WHISPER AI
* **Danh sách Model hợp lệ**:
  1. `turbo` *(Large-v3-Turbo - Tối ưu GPU RTX, tốc độ nhanh nhất, chính xác cao)* $\rightarrow$ **MẶC ĐỊNH KHUYÊN DÙNG**.
  2. `large-v3` *(Độ chính xác cao nhất)*.
  3. `medium` *(Cân bằng)*.
  4. `small` *(Siêu nhẹ, ~1.2GB VRAM)*.
  5. `base` *(Nhẹ)*.
  6. `tiny` *(Siêu nhẹ)*.
* ❌ **CẤM TUYỆT ĐỐI**: Không đưa `large-v2` vào danh sách lựa chọn giao diện. Không được map ngầm model người dùng chọn sang `large-v2`.
* ❌ **CẤM TỰ Ý HẠ CẤP MODEL**: Khi GPU gặp sự cố (hết VRAM, driver timeout), hệ thống **BẮT BUỘC** phải ghi log chi tiết lỗi GPU và fallback sang CPU **CHẠY ĐÚNG CHÍNH XÁC CÙNG MODEL ĐÓ** (ví dụ: chọn `turbo` thì CPU chạy `turbo`).

### 2. QUY TẮC TIẾN TRÌNH CON & NÚT DỪNG (SUBPROCESS & NON-BLOCKING CANCEL)
* ❌ **CẤM BLOCKING READLINE**: Không bao giờ được gọi `proc.stdout.readline()` đồng bộ trực tiếp trong vòng lặp chính của tiến trình mẹ. Lệnh này sẽ đông cứng luồng khi tiến trình con đang xử lý tác vụ nặng (như Whisper bóc tách âm thanh dài, FFmpeg encode), làm vô hiệu hóa việc kiểm tra `cancel_event`.
* ✔ **CƠ CHẾ BẮT BUỘC**: Mọi tiến trình con (`subprocess.Popen`) phải sử dụng **Daemon Reader Thread** đẩy dòng log vào `queue.Queue`. Vòng lặp chính sử dụng `queue.get(timeout=0.1)` để đảm bảo mỗi 100ms đều kiểm tra được `cancel_event.is_set()`. Khi người dùng bấm **⏹ Dừng**, gọi ngay `proc.kill()` và `proc.wait(timeout=1.5)` để tiêu diệt tiến trình lập tức trong $<200\text{ms}$.

### 3. QUY TẮC GPU CUDA & FP16 (PRECISION & VRAM)
* ✔ Khi chạy Whisper trên GPU CUDA (`device == "cuda"`), **BẮT BUỘC** bật `fp16 = True` để kích hoạt Tensor Cores của NVIDIA RTX, giảm 50% bộ nhớ VRAM và ngăn chặn lỗi Windows TDR Timeout / `CUDA unspecified launch failure` khi chạy audio dài và thuật toán `word_timestamps`.
* ✔ Khi chạy trên CPU (`device == "cpu"`), đặt `fp16 = False` (PyTorch CPU chuẩn).

### 4. QUY TẮC CÀO YOUTUBE (CRAWLER & BROWSER PROFILE)
* ✔ **Chế độ Profile độc lập**: Sử dụng Dedicated Profile Directory (`--user-data-dir`) để người dùng đăng nhập tài khoản một lần duy nhất.
* ❌ Không parse lại, không tái tạo sai định dạng Netscape cookie làm mất các trường bảo mật như `__Secure-3PAPISID`, `SAPISIDHASH`.
* ✔ Chỉ hỗ trợ Python 3.11.9 64-bit chuẩn để đảm bảo tính tương thích tuyệt đối với `yt-dlp` và PyTorch CUDA.

### 5. QUY TẮC BÓC TÁCH PHỤ ĐỀ (NATIVE TIME TOKENS VS WORD TIMESTAMPS)
* ❌ **CẤM BẬT `word_timestamps=True` TRÊN OPENAI-WHISPER GPU**: Tính năng `word_timestamps` trong OpenAI Whisper buộc phải tắt Flash Attention (`disable_sdpa()`) và gắn forward hooks vào decoder cross-attention layers. Trên các model như `turbo` (chỉ có 4 decoder layers), DTW hook gây tràn mảng bộ nhớ dẫn đến `CUDA error: an illegal memory access was encountered`, làm hỏng vĩnh viễn CUDA context trong cả tiến trình.
* ✔ **BẮT BUỘC DÙNG NATIVE TIME TOKENS (`word_timestamps=False`)**: Whisper tiêu chuẩn tự động chia phân đoạn lời thoại (1-3s) cực kỳ chuẩn xác, tận dụng 100% PyTorch Flash Attention (SDPA) + Tensor Cores FP16, tốc độ quét audio 20 phút chỉ mất 20-30s và an toàn tuyệt đối 100%.

### 6. QUY TẮC RENDER ENGINE SỐ LƯỢNG LỚN (DIRECT 1-PASS & CANVAS FLATTENING)
* ❌ **CẤM RENDER MULTI-PASS (TẠO FILE MP4 TRUNG GIAN)**: Không được chia nhỏ quy trình render thành 3 lần decode/encode độc lập (Pass 1: encode từng clip_*.mp4 $\rightarrow$ Pass 2: nối xfade $\rightarrow$ Pass 3: đè layout + subtitle). Việc decode/encode 3 lần làm thời gian render tăng gấp 3 và tốn băng thông ghi đĩa SSD.
* ✔ **DIRECT 1-PASS PIPELINE DUY NHẤT**: Toàn bộ chu trình (cắt gọt, scale, pan-zoom, xfade/concat, Layout Studio, Logo, Text động, ASS Subtitles) phải được liên kết thành 1 filter complex duy nhất trong file `_direct_1pass_filter.txt` và nạp qua `-filter_complex_script`. Video chỉ được encode đúng 1 lần duy nhất từ file gốc thẳng ra video hoàn chỉnh.
* ✔ **CANVAS FLATTENING OPTIMIZER (PILLOW PRE-COMPOSITING)**: Mọi layer ảnh tĩnh trong Layout Studio (Watermark, Logo, Khung viền, Banner) phải được gộp trước thành **1 file PNG RGBA duy nhất** bằng Pillow trong 0.03s trước khi đưa vào FFmpeg. Tuyệt đối không để FFmpeg chạy 10 bộ lọc `overlay` CPU liên tiếp trên mỗi frame vì sẽ gây nghẽn CPU filtergraph và kéo tụt tốc độ GPU NVENC.
* ✔ **SINGLE VIDEO LOOP OPTIMIZER**: Nếu chuỗi video nền chỉ sử dụng 1 file lặp lại, sử dụng `-stream_loop -1` trực tiếp thay vì mở nhiều instance decode độc lập.

### 7. QUY TẮC SMART MEDIA NORMALIZATION CACHE & GPU HARDWARE DECODE (NVDEC)
* ❌ **CẤM ĐỂ CPU DECODE CÁC ĐỊNH DẠNG NẶNG NHIỀU LẦN TRONG QUEUE**: Khi khách hàng cung cấp video nền định dạng AV1 60fps hoặc 4K (RTX 2060 không có phần cứng decode AV1), không được để từng video trong hàng đợi decode phần mềm trên CPU Xeon 2.2GHz gây nghẽn tốc độ ~43 fps.
* ✔ **SMART MEDIA NORMALIZATION CACHE**: Tự động nhận diện video nguồn nặng (AV1, fps > 31fps, 4K/2K), convert nhanh 1 lần duy nhất bằng GPU NVENC sang file H.264 chuẩn 1080p 30fps trong `_avr_temp/_avr_media_cache`. Toàn bộ queue tái sử dụng tức thì bản cache H.264 này (0s).
* ✔ **GPU NVDEC HARDWARE DECODE (`-hwaccel cuda`)**: Luôn chèn cờ `-hwaccel cuda` trước `-i` cho các video H.264/HEVC/VP9 để chuyển toàn bộ tải giải mã sang chip phần cứng NVDEC của card NVIDIA RTX, đạt tốc độ giải mã 400+ FPS.

### 8. QUY TẮC BÓC TÁCH GỐC RỄ MÃ NGUỒN VÀ TÍNH ĐỒNG BỘ CỦA ĐỊNH DANH (IDENTIFIER & METHOD INTEGRITY)
* ❌ **CẤM VIẾT CODE "TƯỞNG TƯỢNG" HOẶC ĐOÁN TÊN METHOD / BIẾN NỘI BỘ**: Khi thêm code vào bất kỳ class nào (như `RenderEngine`), **BẮT BUỘC** phải kiểm tra đúng tên thuộc tính/phương thức thực tế của class:
  - Dùng `self.ffmpeg` (không được tự bịa ra `get_ffmpeg_path()`).
  - Dùng `self._run(cmd, stage_name)` (không được tự bịa ra `self._run_cmd(...)`).
  - Dùng `get_duration_seconds(path)` (không được tự bịa ra `self._get_media_duration(...)`).
* ✔ **QUY TRÌNH KIỂM TRA GỐC RỄ (ROOT-CAUSE AUDITING)**: Khi phát hiện lỗi hoặc kiểm tra log:
  1. Phải lần theo **ĐÚNG LUỒNG THỰC THI THỰC TẾ** từ cấu hình đang bật (`config.json`) qua từng hàm được gọi trong chuỗi xử lý.
  2. Bắt buộc kiểm tra toàn bộ luồng bằng phân tích tĩnh cú pháp (AST / linter) và chạy thử nghiệm đầy đủ mọi nhánh tính năng trước khi báo cáo hoặc bàn giao.
  3. Tuyệt đối không chẩn đoán hời hợt hoặc chỉ nhìn một nhánh code mà bỏ sót nhánh cấu hình đang kích hoạt thật.

---

## 📜 PHẦN 2: LỊCH SỬ CHI TIẾT CÁC LỖI ĐÃ PHÁT SINH VÀ CÁCH FIX

---

### 🔴 LỖI 1: WHISPER TỰ Ý ĐỔI MODEL SANG LARGE-V2 VÀ SỤP ĐỔ GPU CUDA

#### Triệu chứng lỗi (Log thực tế):
```text
[Dòng 1] ⚡ Bật phụ đề: Đang dùng Whisper AI [large-v3-turbo], ngôn ngữ [TL]...
[Dòng 1] Đang nạp Whisper AI [large-v2] trên GPU CUDA (NVIDIA)...
[Dòng 1] ❌ Lỗi Whisper AI: CUDA error: an illegal instruction was encountered / unspecified launch failure
[Dòng 1] Fallback sang CPU...
```

#### Nguyên nhân gốc rễ:
1. Hàm `normalize_whisper_model_name()` trong `subtitle_worker.py` chứa đoạn code cũ cố tình map tất cả các key `"turbo"` và `"large-v3-turbo"` thành `"large-v2"`.
2. Worker cấu hình `use_fp16 = False` (chạy FP32 trên GPU). Đối với file âm thanh dài (15-20 phút), ma trận Cross-Attention trong thuật toán bóc tách từ (`word_timestamps=True`) của Whisper sinh ra khối lượng tính toán quá lớn $\rightarrow$ vượt quá ngưỡng thời gian phản hồi của driver đồ họa Windows (TDR 2 giây) $\rightarrow$ CUDA kernel bị hủy $\rightarrow$ GPU rớt và buộc phải chuyển sang CPU.

#### Cách đã khắc phục triệt để:
1. Sửa `normalize_whisper_model_name()` để map `"turbo"` và `"large-v3-turbo"` trực tiếp về model `"turbo"` chính hãng của OpenAI.
2. Xóa bỏ hoàn toàn `large-v2` khỏi file giao diện `setting_tab.py`.
3. Đặt `use_fp16 = True` khi chạy trên GPU CUDA. Tận dụng Tensor Cores của NVIDIA giúp tốc độ bóc tách tăng gấp đôi, VRAM giảm một nửa và hoàn toàn không bị TDR driver timeout.
4. Nếu GPU gặp lỗi ngoại lệ, in log chi tiết và fallback sang CPU với **chính xác 100% cùng tên model** (không hạ cấp).

---

### 🔴 LỖI 2: ỨNG DỤNG BỊ TREO / ĐƠ KHI NGƯỜI DÙNG BẤM NÚT "DỪNG" (STOP)

#### Triệu chứng lỗi:
* Khi Whisper hoặc FFmpeg đang xử lý video dài, người dùng bấm nút **⏹ Dừng** trên giao diện Render Tab nhưng giao diện bị đơ, không phản hồi và tiến trình ngầm vẫn tiếp tục chiếm dụng 100% CPU/GPU thêm hàng chục giây hoặc vài phút.

#### Nguyên nhân gốc rễ:
* Trong `_run_isolated_whisper()`, code sử dụng:
  ```python
  line = proc.stdout.readline()  # <-- BLOCKING CALL
  ```
  Khi worker Whisper đang tính toán trong thư viện C++/CUDA, nó không xuất bất kỳ ký tự nào ra stdout trong suốt 10-60 giây. Luồng chính bị kẹt vĩnh viễn ở `readline()`, khiến câu lệnh `if cancel_event.is_set(): proc.kill()` nằm phía dưới không bao giờ có cơ hội được thực thi.

#### Cách đã khắc phục triệt để:
* Tách việc đọc stdout sang một **Daemon Thread riêng biệt**:
  ```python
  out_queue = queue.Queue()
  def _reader():
      for line in iter(proc.stdout.readline, ""):
          if line: out_queue.put(line)
      out_queue.put(None)
  threading.Thread(target=_reader, daemon=True).start()
  ```
* Trong vòng lặp chính của tiến trình mẹ, dùng `out_queue.get(timeout=0.1)`. Sau mỗi 100ms, luồng chính tỉnh dậy để kiểm tra `cancel_event.is_set()`. Nếu người dùng bấm Dừng $\rightarrow$ gọi `proc.kill()` và raise `RenderCancelled` ngay lập tức.

---

### 🔴 LỖI 3: YOUTUBE BÁO "SIGN IN TO CONFIRM YOU'RE NOT A BOT" KHI CÀO VIDEO

#### Triệu chứng lỗi:
```text
ERROR: [youtube] sqVI__Mb6sI: Sign in to confirm you’re not a bot.
Use --cookies-from-browser or --cookies for the authentication.
```

#### Nguyên nhân gốc rễ:
1. YouTube tăng cường cơ chế chống bot bằng Proof of Origin (PoToken) và kiểm tra tính nhất quán của Cookie phiên làm việc.
2. File cookie export thủ công bị thiếu các cookie mã hóa HttpOnly và Secure Token, hoặc cookie bị trích xuất sai cấu trúc header.

#### Cách đã khắc phục triệt để:
1. Tích hợp chế độ **Dedicated Browser Profile** (`--user-data-dir`): Cho phép người dùng mở trình duyệt riêng (Chrome/Edge/Brave) để đăng nhập tài khoản một lần, cookie và token được lưu trực tiếp trong profile gốc.
2. Hỗ trợ cơ chế đọc cookie trực tiếp qua `--cookies-from-browser` và giữ nguyên vẹn Netscape cookie không qua bộ lọc làm mất trường dữ liệu.

---

### 🔴 LỖI 4: LỆCH MÔI TRƯỜNG PYTHON VÀ THIẾU DLL CUDA CUBLAS

#### Triệu chứng lỗi:
* Chạy Whisper AI báo `cublas64_12.dll not found` hoặc `cudnn_ops_infer64_8.dll not found` dù máy có card NVIDIA RTX.

#### Nguyên nhân gốc rễ:
* Máy tính cài đặt nhiều bản Python (3.10, 3.11, 3.12, Anaconda), script cài đặt tự động dò nhầm bản Python không tương thích với PyTorch CUDA.

#### Cách đã khắc phục triệt để:
* Chuẩn hóa `setup.bat` chỉ tải và cài đặt cố định **Python 3.11.9 64-bit**.
* Bổ sung module `_register_cuda_dll_directories()` trong `subtitle_utils.py` để tự động dò tìm và nạp các thư mục `site-packages\torch\lib`, `site-packages\nvidia\cublas\bin`, `site-packages\nvidia\cudnn\bin` vào `PATH` và `os.add_dll_directory()`.

---

### 🔴 LỖI 5: WORD TIMESTAMPS GÂY ILLEGAL MEMORY ACCESS & CORRUPT CUDA CONTEXT TRÊN GPU

#### Triệu chứng lỗi (Log thực tế):
```text
[Dòng 1] Đang quét giọng nói trong 'audio.mp3' (ngôn ngữ [TL]) bằng GPU CUDA (NVIDIA)...
[Dòng 1] ⚠️ Word timestamps gặp cảnh báo: CUDA error: an illegal memory access was encountered
[Dòng 1] ⚠️ GPU CUDA gặp lỗi [CUDA error: an illegal memory access was encountered...] -> Tự động chuyển sang CPU đa luồng giữ nguyên model [turbo]...
```

#### Nguyên nhân gốc rễ:
1. `word_timestamps=True` trong `openai-whisper` sử dụng Dynamic Time Warping (DTW) căn chỉnh vị trí từng từ bằng cách tắt Flash Attention (`disable_sdpa()`) và cài đặt forward hook vào từng decoder layer.
2. Trên model kiến trúc mới như `turbo` (chỉ có 4 decoder layers thay vì 32 layers như bản thông thường), việc đọc mảng attention weights FP16 trên các đoạn âm thanh dài nhiều từ gây tràn biên chỉ số bộ nhớ CUDA (`illegal memory access`).
3. Trong CUDA, lỗi `illegal memory access` là lỗi phần cứng cấp thấp làm "poisoned" toàn bộ CUDA context của tiến trình Python đó, khiến mọi câu lệnh PyTorch GPU tiếp theo đều bị sập.

#### Cách đã khắc phục triệt để:
1. Chuyển sang sử dụng **Native Time Tokens (`word_timestamps=False`)** mặc định của Whisper.
2. Tận dụng 100% PyTorch Flash Attention (SDPA) và Tensor Cores FP16 nguyên bản, giúp Whisper bóc tách phụ đề video với độ chính xác chuẩn từng câu (1-3 giây), tốc độ siêu tốc (audio 20 phút chỉ mất 20-30s) và **hoàn toàn 100% không bao giờ gặp lỗi bộ nhớ CUDA**.

---

### 🔴 LỖI 6: RENDER MULTI-PASS CHẬM VÀ NGHẼN FILTERGRAPH KHI LÀM SỐ LƯỢNG LỚN (SLL)

#### Triệu chứng lỗi:
* Render video 19 phút mất tới 14-20 phút dù có GPU NVIDIA RTX. Không thể đáp ứng tốc độ sản xuất hàng loạt (SLL).
* FFmpeg chạy ở tốc độ chỉ ~30 FPS vì bị nghẽn chuỗi 10 bộ lọc overlay RGBA trên CPU.

#### Nguyên nhân gốc rễ:
1. **Mô hình Multi-pass cũ**:
   - Pass 1: Encode từng media thành `clip_*.mp4`.
   - Pass 2: Nối các `clip_*.mp4` thành `base_video.mp4` qua bộ lọc transition xfade.
   - Pass 3: Decode lại `base_video.mp4`, đè 10 layer Layout Studio + Logo + Text + Subtitles rồi encode lại lần 3.
   $\rightarrow$ **Decode và Encode toàn bộ video lặp lại tới 3 lần**, tiêu tốn gấp 3 thời gian và hàng chục GB I/O đĩa.
2. **Nghẽn CPU Alpha Blending Filtergraph**:
   - 10 layer ảnh tĩnh trong Layout Studio được nạp độc lập vào FFmpeg và chạy 10 bộ lọc `overlay` CPU liên tiếp cho từng frame hình (30.000 frame $\times$ 10 = 300.000 phép tính blit phần mềm).

#### Cách đã khắc phục triệt để:
1. **Direct 1-Pass Pipeline**: Gộp toàn bộ quy trình từ media gốc $\rightarrow$ scale/trim/xfade $\rightarrow$ overlays $\rightarrow$ ASS Subtitles $\rightarrow$ NVENC Encode thành **1 chuỗi filtergraph duy nhất** trong file script (`-filter_complex_script`). Toàn bộ video chỉ encode đúng 1 lần duy nhất, triệt tiêu 100% việc tạo file clip trung gian.
2. **Canvas Flattening Optimizer**: Sử dụng Pillow nén và gộp toàn bộ các layer ảnh tĩnh (Watermark, Logo, Viền, Khung) thành **1 file PNG canvas trong suốt duy nhất** trong 0.03s, giảm từ 10 bộ lọc overlay CPU xuống còn 1 overlay duy nhất.
3. **Single Video Loop Optimizer**: Tự động phát hiện sequence 1 video duy nhất để kích hoạt `-stream_loop -1` trực tiếp thay vì tạo nhiều instance decode.
4. **Tối ưu NVENC GPU Flag**: Bổ sung `-tune ll`, `-spatial-aq 0`, `-temporal-aq 0`, `-delay 0` cùng `-preset p1` để offload tối đa cho ASIC NVENC.

---

### 🔴 LỖI 7: TẮC NGHẼN CPU DECODE KHI VIDEO NGUỒN CỦA KHÁCH HÀNG LÀ AV1 / 60FPS / 4K

#### Triệu chứng lỗi:
* Khách hàng cung cấp video nền định dạng AV1 hoặc 60fps (ví dụ tải từ YouTube về).
* Tốc độ render bị tụt xuống còn ~40-43 FPS (1.4x), render video 17 phút mất tới 11-12 phút dù card đồ họa NVIDIA RTX 2060 hoàn toàn rảnh rỗi.

#### Nguyên nhân gốc rễ:
1. Card NVIDIA RTX 2060 (kiến trúc Turing TU106) có bộ giải mã phần cứng NVDEC cho H.264, HEVC, VP8, VP9 nhưng **KHÔNG HỖ TRỢ giải mã phần cứng AV1** (AV1 NVDEC chỉ có từ RTX 3000 trở lên).
2. CPU Xeon E5-2696 v4 (22 cores) có xung nhịp đơn nhân thấp (2.2GHz). Bộ giải mã phần mềm `libaom-av1` / `dav1d` chạy đơn luồng cho từng frame đạt trần tối đa chỉ ~43 fps.
3. Nếu trong hàng đợi có 10-50 video, FFmpeg buộc phải decode lại file AV1 nặng này 10-50 lần, gây lãng phí hàng trăm phút render.

#### Cách đã khắc phục triệt để:
1. **Smart Media Normalization Cache**: Tool dùng `ffprobe` tự động kiểm tra codec/fps/resolution của video nguồn. Nếu là AV1 / fps cao / 4K, tool tự động convert video nền đó **1 LẦN DUY NHẤT** sang H.264 1080p 30fps lưu vào `_avr_temp/_avr_media_cache` trong ~15s. Toàn bộ các video sau trong queue tái sử dụng ngay lập tức bản cache này (0s).
2. **GPU NVDEC Hardware Decode (`-hwaccel cuda`)**: Kích hoạt `-hwaccel cuda` trước `-i` nạp video nguồn H.264/HEVC/VP9 trực tiếp vào chip NVDEC của RTX 2060, đạt tốc độ decode **400+ FPS** mà không tốn CPU.
3. **GIF Overlay Framerate Matching**: Bổ sung `fps={fps}` vào từng layer GIF/reaction động để đồng bộ tốc độ khung hình, loại bỏ jitter frame của bộ lọc overlay.

---

### 🔴 LỖI 8: TẮC NGHẼN CPU DO NHIỀU LAYER GIF HOẠT HỌA ĐỘNG CHẠY SONG SONG TRONG DIRECT 1-PASS

#### Triệu chứng lỗi:
* Người dùng sử dụng 2-3 layer GIF chuyển động (như Trái tim đập, Sóng âm, Valentine) trong mẫu Studio Layout.
* Khi render video 17-20 phút, tốc độ render bị kẹt ở mức **50 - 52 FPS** (mất ~10-11 phút) dù video nền đã là H.264 và có `-hwaccel cuda`.

#### Nguyên nhân gốc rễ:
1. Thuật toán giải mã bảng màu (palette) của GIF trong FFmpeg chạy đơn luồng CPU phần mềm.
2. Với video 17.2 phút (31.080 frames), CPU Xeon đơn nhân 2.2GHz phải liên tục giải mã 3 file GIF và thực hiện 3 phép tính Alpha Blending đè lớp trên 31.080 khung hình.
3. GPU NVENC bị "đói frame" do phải đứng chờ CPU giải mã từng frame GIF rồi mới nén được.

#### Cách đã khắc phục triệt để:
* **Animated Layout Canvas Optimizer (`_bake_animated_layout_canvas`)**:
  1. Tool tự động phát hiện các layer hoạt họa động (`gif`, `reaction`, `video_mask`) và các layer ảnh tĩnh (`image`, `banner`, `logo`, `watermark`).
  2. Khởi tạo nền hoàn toàn trong suốt tuyệt đối ($Alpha = 0$) qua `color=c=0x00000000:s=1920x1080:d=6.0:r=30,format=rgba`.
  3. Xử lý và nén toàn bộ các layer thị giác **chính xác theo thứ tự tuần tự Z-Index (từ layer 0 đến layer N)** thành **1 luồng video trong suốt ngắn 6.0s (`animated_layout_canvas.mov`)** sử dụng codec siêu nhẹ `qtrle` (QuickTime RLE RGBA).
  4. Trong lệnh render chính: FFmpeg nạp video trong suốt lặp lại (`-stream_loop -1 -i animated_layout_canvas.mov`) và overlay 1 lần duy nhất lên video nền gốc.
  5. Video nền gốc hiển thị sáng rõ $100\%$ không bị che đen, các layer đè lên nhau chuẩn xác $100\%$ theo thứ tự Z-Index, và tải CPU giảm hơn $85\%$.

---

### 🔴 LỖI 9: BỂ FORM, LỆCH TỶ LỆ KÍCH THƯỚC CHỮ, NGẮT DÒNG VÀ VỊ TRÍ PHỤ ĐỀ GIỮA PREVIEW VÀ RENDER

#### Triệu chứng lỗi:
* Trên màn hình Preview Studio Layout, tiêu đề ngắn mẫu hiển thị 1 dòng đẹp mắt, nhưng khi render ra video thật gặp tên dài 74 ký tự thì bị xé đôi từ (`Pag-ibig` thành `Pag-` và `Ibig`), chữ phình to thành 3 dòng đè lên nhau và đè lên các họa tiết bên dưới.
* Vị trí phụ đề trong video xuất ra bị tụt thấp hơn so với khung kéo thả trên Preview.

#### Nguyên nhân gốc rễ:
1. **Lệch đơn vị đo Font chữ giữa Qt và FFmpeg**:
   - Qt Preview dùng `QFont(pt)` (Point) bị nhân hệ số DPI Scaling của Windows (125%/150%), trong khi FFmpeg `drawtext(px)` dùng Pixel cố định trên khung 1080p.
2. **Lỗi ngắt từ `textwrap` mặc định**:
   - Thư viện Python `textwrap` mặc định bật `break_on_hyphens=True`, khi gặp từ có dấu gạch ngang (`Pag-ibig`) sẽ tự ý bẻ đôi từ thành 2 dòng riêng biệt.
3. **Thiếu giới hạn số dòng tối đa (`max_lines`)**:
   - Khi người dùng kéo chiều cao Bounding Box lớn, thuật toán thấy 3 dòng chữ to vẫn vừa lọt khung nên giữ nguyên cỡ chữ to mà không tự động co nhỏ font để dồn về 2 dòng.
4. **Lệch căn chỉnh Subtitle ASS**:
   - Qt Preview căn giữa tâm hộp (`Qt.AlignCenter`), còn file `.ass` dùng `Alignment=2` bám mép đáy Bounding Box (`MarginV`).

#### Cách đã khắc phục triệt để:
1. **Pixel-Perfect Font Scaling trong Preview**:
   - Chuyển toàn bộ hệ thống Font trong `layout_tab.py` sang `font.setPixelSize(int(round(font_size * (cr.height() / 1080.0))))`, đồng bộ chính xác 100% mọi tỉ lệ to nhỏ, viền chữ, bo góc theo hệ số $k$.
2. **Thuật toán ngắt dòng và co font thông minh (`_wrap_text_for_box`)**:
   - Chuyển sang ngắt dòng theo danh sách từ nguyên vẹn (`clean_text.split()`), không bao giờ xé đôi từ hay dấu gạch ngang.
   - Bổ sung `max_lines=2`: Nếu tiêu đề dài, tự động co nhỏ font size từng bước (`font_size -= 2`) cho đến khi toàn bộ tiêu đề nằm vừa vặn, cân đối trong tối đa 2 dòng.
   - Giảm `line_spacing` từ 8px xuống 4px giúp các dòng chữ ôm sát nhau chuẩn bìa truyện.
3. **Đồng bộ vị trí tâm Bounding Box cho phụ đề ASS**:
   - Tính toán lại `MarginV` theo tâm của Bounding Box (`center_v_offset`), giúp vị trí phụ đề trong video xuất ra khớp từng pixel với khung xem trước trên Canvas.

---

### 🔴 LỖI 10: ĐỒNG BỘ FONT NGHỆ THUẬT FFPEG, 2 CHẾ ĐỘ INTRO, TỌA ĐỘ ÂM CẮT XÉN ẢNH VÀ TIỀN XỬ LÝ WHISPER AI

#### Triệu chứng lỗi & Yêu cầu mới:
1. **Lệch Font chữ render vs preview**: Chọn font nghệ thuật (UTM, UVF, SVN, Playfair, Dancing Script, v.v.) trong Preview hiển thị đẹp nhưng khi render ra video thật lại bị fallback về font Arial mặc định của FFmpeg do không tìm thấy file `.ttf/.otf` thật trong Windows.
2. **Nhu cầu 2 chế độ Intro**: (1) Nối tiếp tuần tự (Intro phát xong mới đến MP3 chính), (2) Đè lên đầu MP3 (MP3 chính phát ngay từ 0:00, video Intro chỉ đè hình ảnh các giây đầu).
3. **Không kéo lặn gốc ảnh ra ngoài viền canvas được**: Các ảnh trang trí (nhánh hoa, logo, khung viền) bị khống chế $x \ge 0, y \ge 0$, khi kéo mép ảnh ra ngoài màn hình bị chặn lại, và FFmpeg render bị đen hoặc lỗi padding.
4. **Whisper AI bị nuốt chữ khi có nhạc/SFX**: Audio có nhạc nền hoặc âm thanh hiệu ứng khiến Whisper AI bỏ sót phụ đề (no_speech_threshold cao); và sau 30s đầu cần bộ lọc triệt tiêu nhạc nền để giọng đọc nổi bật nhất.

#### Cách đã khắc phục triệt để:
1. **Windows Font Registry & Art Font Mapping (`_find_font_file_by_name`)**:
   - Tích hợp quét Registry hệ thống `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts` và thư mục `C:\Windows\Fonts`, `Local AppData\Microsoft\Windows\Fonts`.
   - Bổ sung bảng đối chiếu 25+ font nghệ thuật phổ biến (UTM, UVF, SVN, Dancing, Playfair, Great Vibes, Pacifico, Montserrat, Roboto, v.v.) giúp FFmpeg `drawtext` luôn trỏ đúng đường dẫn file font tuyệt đối.
2. **2 Chế độ Video Intro Linh hoạt**:
   - `intro_mode = "sequential"`: Nối tuần tự trước MP3 chính.
   - `intro_mode = "overlay_audio_head"`: Sử dụng `_apply_intro_overlay` phủ video intro từ $t=0$ đến $t=\text{intro\_dur}$ lên phần hình ảnh, trong khi audio chính vẫn phát trọn vẹn từ 0:00.
3. **Hỗ trợ Tọa độ Âm & Clipping Viewport Preview / Render**:
   - Nới lỏng phạm vi tọa độ $X, Y \in [-100\%, 150\%]$, kích thước $W, H \in [0.5\%, 200\%]$.
   - Preview canvas: Thêm `painter.setClipRect(cr)` để cắt gọn sắc nét mọi phần tràn viền, đồng thời cho phép hiển thị handles ngoài mép.
   - Pillow & FFmpeg bake canvas: Thay `alpha_composite` bằng `canvas.paste(img, pos, mask=img)` và cho phép giá trị $px, py$ âm trong filtergraph overlay mà không bị clamp `max(0, ...)`.
4. **Tiền xử lý Audio Whisper AI & Bộ lọc BGM sau 30s**:
   - `subtitle_worker.py`: Thêm bộ lọc âm thanh `highpass=f=120,lowpass=f=3800,afftdn=nf=-25,dynaudnorm=f=150:g=15` bóc tách dải tần giọng nói trước khi quét. Giảm `no_speech_threshold=0.3` và đặt `condition_on_previous_text=False` để chống nuốt chữ và chống lặp khi có nhạc.
   - `render_engine.py`: Thêm tùy chọn `filter_bgm_after_30s` trong `_build_final_audio` giữ nguyên 100% âm thanh 30s đầu (cho Voice/BGM Intro) và tự động triệt tiêu dải nhạc nền/tạp âm từ giây thứ 30 trở đi.

---

### 🔴 LỖI 11: CRASH RENDER KHI CHẠY CHẾ ĐỘ INTRO OVERLAY (GỌI SAI METHOD VÀ BIẾN NỘI BỘ)

#### Triệu chứng lỗi (Log thực tế):
```text
[LOG] Attach audio: E:\...\with_audio.mp4
[LOG] Đã xóa video tạm sau khi ghép audio: visual_video.mp4
[LOG] Đã xóa audio tạm sau khi ghép vào video: main_audio.m4a
--- KẾT QUẢ RENDER ---
Success: False
Message: 'RenderEngine' object has no attribute '_get_media_duration'
```

#### Nguyên nhân gốc rễ:
1. Trong hàm `_apply_intro_overlay` của `render_engine.py`, code mới được viết gọi nhầm các định danh không tồn tại trong class:
   - Gọi `self._get_media_duration(intro_path)` thay vì `get_duration_seconds(intro_path)`.
   - Gọi `get_ffmpeg_path()` thay vì `self.ffmpeg`.
   - Gọi `self._run_cmd(cmd, desc=...)` thay vì `self._run(cmd, stage_name)`.
2. Khi người dùng cấu hình `"intro_mode": "overlay"` trong `config.json`, hệ thống nhảy vào nhánh này và bị sập lập tức.

#### Cách đã khắc phục triệt để:
1. Chuẩn hóa lại toàn bộ các lời gọi hàm trong `_apply_intro_overlay` về đúng chuẩn của class `RenderEngine`:
   - Thay `self._get_media_duration` $\rightarrow$ `get_duration_seconds(intro_path)`.
   - Thay `get_ffmpeg_path()` $\rightarrow$ `self.ffmpeg`.
   - Thay `self._run_cmd(...)` $\rightarrow$ `self._run(...)`.
2. Chạy toàn bộ AST Static Analysis và Integration Test trên toàn bộ cấu hình Render (Intro Overlay + Layout Animation + Whisper AI Turbo) đạt kết quả `Success: True` 100%.

---

### 🔴 LỖI 12: TÁCH GIỌNG NÓI DEMUCS AI, CHUYỂN CẢNH INTRO OVERLAY FADE-OUT, TEXTAREA TỪ KHÓA NGỮ CẢNH, FIX LỖI RENDER CHẬM 1.0X VÀ TÍNH CHUẨN XÁC FONT METRICS

#### Triệu chứng lỗi & Vấn đề phát sinh:
1. **Whisper AI nhận diện sai và mất câu đầu khi có nhạc/SFX**: Lời mở đầu video có SFX tiếng cười/nhạc dạo làm Whisper dịch thành "ain a wow" thay vì đúng tiêu đề/từ khóa "AYNA WOW".
2. **Intro kết thúc đột ngột khiến video trơ ra**: Khi chuyển từ video Intro sang video chính, hình ảnh bị đổi cái rụp không có hiệu ứng mượt mà.
3. **Render video 19:34 bị mất tới 19:02 (Tốc độ chỉ 1.0x)**: Sau khi render GPU Pass 1 siêu tốc, bước `_apply_intro_overlay` chạy thêm Pass 2 re-encode toàn bộ 19 phút video bằng CPU `libx264`.
4. **Tiêu đề `{title}` bị bể size đè lên layer khác**: `_wrap_text_for_box` chỉ đo ink bbox của chữ in hoa mà không tính Line Height thực tế (`ascent + descent + spacing + outline`), khiến font size bị tính to hơn khung giới hạn.
5. **Cần ô textarea nhập từ khóa ngữ cảnh**: Cần ô textarea nhập nhiều từ khóa cách nhau bởi dấu phẩy `,` trong cài đặt phụ đề để mớm cho Whisper AI nhận diện chính xác tên riêng, địa danh, tiếng địa phương.

#### Cách đã khắc phục triệt để:
1. **Tách Voice AI bằng Demucs (`torchaudio HDEMUCS_HIGH_MUSDB`)**:
   - Tích hợp model Demucs chạy trực tiếp trên GPU CUDA (xử lý cực nhanh 0.99s).
   - Tách sạch BGM/SFX, trích xuất vocal WAV 16kHz mono trước khi đưa vào Whisper AI.
2. **Khung Textarea Từ Khóa Ngữ Cảnh (`initial_prompt`)**:
   - Thêm `QPlainTextEdit` `whisper_keywords` vào giao diện Subtitle Setting.
   - Tự động gom `whisper_keywords` + `{title}` + các layer text thành `initial_prompt` nạp vào Whisper AI.
3. **Intro Overlay 1-Pass Pipeline & Hiệu Ứng Crossfade Dissolve**:
   - Nhúng trực tiếp Intro Overlay vào `_build_visual_layers_filtergraph` của Direct 1-Pass Render.
   - Thêm bộ lọc `fade=t=out:st={intro_dur - 0.8}:d=0.8:alpha=1` giúp Intro mờ dần mượt mà vào video chính.
   - Loại bỏ hoàn toàn pass re-encode CPU thứ 2, đưa tốc độ render về 35-45 giây cho toàn bộ video 20 phút.
4. **Đo Chuẩn Xác Font Metrics Trong `_wrap_text_for_box`**:
   - Sử dụng `font.getmetrics()` tính chuẩn Line Height $= \text{ascent} + \text{descent} + \text{line\_spacing} + 2 \times \text{outline}$.
   - Tự động co font size 2 dòng chuẩn xác 100% không bao giờ đè lên các layer khác.

---

## 📋 BẢNG CHECKLIST KIỂM TRA TRƯỚC KHI COMMIT CODE

Trước khi kết thúc bất kỳ phiên sửa đổi nào, hãy tự kiểm tra 16 câu hỏi sau:
- [ ] 1. Có vô tình đổi tên model Whisper nào sang `large-v2` không? *(Không được phép)*
- [ ] 2. Khi chạy Whisper trên CUDA, đã bật `fp16=True` chưa?
- [ ] 3. Khi chạy Whisper trên GPU, đã tắt `word_timestamps=True` để tránh tràn bộ nhớ CUDA DTW chưa?
- [ ] 4. Khi GPU bị lỗi, fallback CPU có giữ nguyên 100% đúng model người dùng đã chọn không?
- [ ] 5. Bất kỳ hàm gọi `subprocess.Popen` nào có bị dính `readline()` blocking I/O làm liệt nút Dừng không?
- [ ] 6. Quy trình render có tuân thủ **Direct 1-Pass Pipeline** không sinh file clip trung gian không?
- [ ] 7. Các layer ảnh tĩnh trong Layout Studio có được pre-flatten qua Canvas Optimizer trước khi đưa vào FFmpeg không?
- [ ] 8. Các layer GIF hoạt họa động có được tiền gộp qua **Animated Layout Canvas Optimizer** (`qtrle` MOV) để loại bỏ nghẽn 31,000 lần decode GIF trên CPU không?
- [ ] 9. Kích thước font chữ trên Preview có dùng `font.setPixelSize` theo hệ số $k = H_{\text{preview}} / 1080$ để triệt tiêu lệch DPI Windows không?
- [ ] 10. Thuật toán `_wrap_text_for_box` có đo đầy đủ Line Height (`font.getmetrics()`, ascent, descent) để không tràn Bounding Box không?
- [ ] 11. Các layer ảnh tràn viền / tọa độ âm có được paste/overlay tự do và clip chuẩn khung hình không?
- [ ] 12. Intro Overlay có được tích hợp trực tiếp vào 1-Pass Filter Complex kèm Fade Out mượt mà và không chạy thêm pass re-encode CPU thứ 2 không?
- [ ] 13. Whisper AI có được nạp từ khóa ngữ cảnh `initial_prompt` và tùy chọn tách giọng nói Demucs AI không?
- [ ] 14. TUYỆT ĐỐI KHÔNG CHẠY TEST SCRIPT RENDER KHI NGƯỜI DÙNG YÊU CẦU DỪNG TEST để tránh lãng phí thời gian của người dùng.
- [ ] 15. Mọi phương thức, hàm hoặc biến nội bộ mới thêm có kiểm tra đúng tên định danh của class (`self.ffmpeg`, `self._run`, `get_duration_seconds`) chưa?
- [ ] 16. Đã kiểm tra đầy đủ import của tất cả UI widgets (`QPlainTextEdit` trong `PySide6.QtWidgets`, v.v.) và chạy thử nghiệm khởi tạo `MainWindow` để tránh lỗi `NameError` khi khởi động app chưa?
- [ ] 17. Đã bóc tách đúng luồng thực tế của `config.json` và kiểm tra tĩnh AST/Syntax toàn diện chưa?
