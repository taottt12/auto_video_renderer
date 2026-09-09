# Auto Video Renderer v5.2 Long Transition Safe

Bản này được tối ưu lại từ nhánh 4.3.x để render hàng loạt nhẹ hơn, tránh tình trạng một video dài 40-50 phút bị encode lại nhiều lần ở các bước logo/watermark/audio.

## Điểm mới chính

### 1. Pipeline render v5.x nhẹ hơn
Luồng xử lý mới:

1. Đọc duration audio chính.
2. Tạo video nền từ ảnh/video, chỉ lấy vừa đủ theo audio.
3. Mix audio ở dạng audio-only: audio chính + nhạc nền + audio quảng bá.
4. Gắn logo + watermark + text trong một pass video duy nhất.
5. Ghép video + audio bằng stream copy.
6. Move file cuối sang output và dọn temp.

Điểm quan trọng: logo, watermark, text không còn bị tách thành nhiều lần encode riêng.

### 2. Audio quảng bá có ducking
Trong nhóm **Audio quảng bá / chèn giữa video** có thêm:

- **Giảm audio chính khi promo phát**
- **Âm lượng chính khi promo**
- **Duck trước promo**
- **Duck sau promo**

Mặc định audio chính sẽ giảm còn 35% khi promo phát, giúp audio quảng bá nổi lên và không bị xung đột với giọng đọc chính.

### 3. Temp folder riêng
Trong nhóm **Hiệu năng / CPU / GPU** có thêm ô **Temp folder**.

- Bỏ trống: temp nằm tại `Output folder/_avr_temp/`.
- Có chọn thư mục: temp nằm tại `Temp folder/_avr_temp/`.

Khi render thành công, job temp sẽ tự dọn nếu bật **Tự xóa cache/temp sau khi render**.

### 4. Kiểm tra dung lượng trước khi render
Tool kiểm tra riêng dung lượng ổ temp và ổ output trước khi render để tránh lỗi FFmpeg:

```text
No space left on device
```

### 5. Bitrate nhẹ hơn cho render hàng loạt
NVENC/CPU không còn để bitrate nhảy quá cao kiểu 18-20 Mbps ở mức thông thường. Preset mới nhẹ hơn:

- Draft: khoảng 4 Mbps ở 1080x1920 30fps
- Standard: khoảng 6 Mbps
- High: khoảng 9 Mbps
- Ultra: khoảng 12 Mbps

Với video truyện/audio, nên dùng **Standard** trước. Nếu ổn rồi mới tăng High.

## Gợi ý setting để chạy nhiều luồng

- Encoder: NVIDIA GPU / NVENC
- Quality: Standard
- FPS: 30
- Transition: Không transition hoặc Fade nhẹ
- Số luồng: test 2 → 4 → 5/6
- Output folder và Temp folder nên để ổ còn trống nhiều
- Bật tự dọn temp
- Tắt giữ temp khi lỗi nếu không debug

### 6. Intro/outro fast path v5.1
Bản v5.1 cải tiến riêng phần intro/outro:

- Nếu intro/outro đã cùng chuẩn với output/main video: nối bằng `-c copy`, gần như chỉ copy file, không encode lại video chính.
- Nếu intro/outro khác chuẩn: chỉ chuẩn hóa intro/outro, còn main video 40-50 phút vẫn giữ nguyên.
- Nếu FFmpeg không nối copy được do file nguồn quá lệch chuẩn: tool mới fallback qua remux TS trước, rồi mới dùng safe fallback cuối cùng.

Chuẩn intro/outro nên dùng:

```text
MP4, H.264, AAC, 48000Hz stereo, cùng độ phân giải, cùng FPS với output
```


### 7. Fix WinError 206 khi video dài có quá nhiều clip transition

Bản v5.2 sửa lỗi Windows:

```text
[WinError 206] The filename or extension is too long
```

Nguyên nhân là khi audio dài 40-60 phút, tool có thể tạo vài trăm clip ảnh/video. Nếu bật transition, FFmpeg phải tạo một chuỗi `xfade` rất dài; Windows không cho chạy command quá dài nên lỗi trước cả khi FFmpeg xử lý.

Cách sửa trong v5.2:

- Tự chia transition thành nhiều batch nhỏ.
- Dùng `-filter_complex_script` để ghi filter ra file thay vì nhét toàn bộ vào command line.
- Xóa clip tạm sau từng batch để giảm dung lượng temp.
- Có setting **Batch transition tối đa** trong nhóm **Hiệu năng / CPU / GPU**. Mặc định 36, nên để khoảng 24-40 nếu render video rất dài.

Nếu muốn nhanh nhất cho hàng nghìn video, chọn **Không transition**. Nếu vẫn muốn có fade, dùng batch 24-36 sẽ ổn hơn.

## Lưu ý

Intro/outro MP4 vẫn phù hợp. Muốn nhanh nhất khi render hàng nghìn video thì nên xuất sẵn intro/outro đúng chuẩn output để v5.1 đi theo fast path copy.

## V5.3 - Auto effect/transition + ẩn cửa sổ FFmpeg

- Thêm Effect mode:
  - `Auto nhẹ không lặp`: tự đổi zoom/pan nhẹ theo từng ảnh, tránh một kiểu lặp xuyên suốt.
  - `Auto phong phú không lặp`: tự đổi nhiều kiểu zoom/pan hơn.
- Thêm Transition:
  - `Auto nhẹ không lặp`: tự đổi fade/slide nhẹ, tránh transition giống nhau liên tiếp.
  - `Auto đa dạng không lặp`: tự đổi nhiều kiểu transition hơn.
- Fix lỗi Windows tự bật/tắt cửa sổ CMD/FFmpeg liên tục khi render bằng `pythonw.exe`.
  - FFmpeg/FFprobe vẫn chạy bình thường ở nền.
  - Không còn bị cướp focus khi đang làm việc trên máy.

Gợi ý render hàng loạt: dùng `Auto nhẹ không lặp`, transition duration `0.3s - 0.5s`, quality `Standard`, temp đặt ở ổ còn nhiều dung lượng.
