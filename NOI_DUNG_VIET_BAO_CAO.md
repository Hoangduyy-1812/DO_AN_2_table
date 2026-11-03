# TỔNG HỢP NỘI DUNG VÀ SỐ LIỆU ĐƯA VÀO BÁO CÁO ĐỒ ÁN 2
*Tài liệu tóm tắt phục vụ viết chương Thực nghiệm & Đánh giá kết quả (Lưu tại: `DO_AN_2/NOI_DUNG_VIET_BAO_CAO.md`)*
*Ngày cập nhật: 03/11/2026*

---

## I. TỔNG QUAN BỘ DỮ LIỆU THỰC NGHIỆM (DATASET OVERVIEW)

### 1. Bảng số liệu tổng hợp
*(Tổng hợp từ 75 phiên đo và kiểm toán khung dữ liệu gốc)*

| Thông số | Giá trị thực tế | Ghi chú khoa học |
| :--- | :---: | :--- |
| **Tổng số phiên đo (Trials)** | **75 phiên** | 72 phiên có người (A, B, C) + 3 phiên phòng trống |
| **Các vị trí thử nghiệm** | **A, B, C** | A (~2.1m trực diện), B (~1.5m trực diện), C (~2.4m lệch trái) |
| **Tổng số khung dữ liệu (Frames)** | **70.941 khung** | Giải mã bit-level từ gói nhị phân gốc, 0 lỗi UART |
| **Tần số lấy mẫu thực tế** | **~11,24 Hz** | Đo từ nhịp dấu thời gian ESP32 ($\Delta t \approx 88,98\text{ ms}$) |
| **Lọc trễ hàng đợi (`backlog_ms > 500 ms`)** | **16,52% bị cách ly** | 11.719 khung dồn cũ trước khi kết nối TCP; còn 59.222 khung mới |
| **Phân chia tập Dữ liệu** | **47 Train / 24 Test** | Cố định: Lượt `01, 02` làm phát triển/train; Lượt `03` làm test giữ riêng |
| **File loại trừ do thiếu khung hợp lệ** | **1 file** | `A_dung_ngoi_nhanh_01` (chỉ còn 17 khung đơn mục tiêu mới đạt chuẩn) |

### 2. Phân tích hiện tượng Phòng trống (Empty Room Analysis)
- Trong 3 file `phong_trong_01, 02, 03`, xét trên **3.256 khung** có `backlog_ms <= 500 ms`: có **0/3.256 khung** xuất hiện mục tiêu trong dải $0 \le Y \le 3,3\text{ m}$.
- Toàn bộ các mục tiêu mà radar phát hiện ở phòng trống đều nằm ở cự ly xa với trung vị lần lượt là: **5,398 m, 5,333 m và 5,325 m**.
- **Giải pháp đề xuất trong báo cáo:** Giới hạn vùng quan tâm (ROI) $0 \le Y \le 3,2\text{ m}$ để triệt tiêu hoàn toàn mục tiêu ảo ở phòng trống. Ngưỡng này chỉ loại bỏ **1,68%** (866 / 51.545 khung) dữ liệu hợp lệ trong 72 file có người.

---

## II. DANH MỤC HÌNH ẢNH ĐỒ THỊ ĐƯA VÀO BÁO CÁO
*(Các file hình đã được xuất sẵn tại thư mục: `03_HINH_DA_VE/`)*

1. **`traces_x.png` & `traces_y.png`:**
   - Minh chứng quỹ đạo tọa độ $X$ (cao độ) và $Y$ (cự ly) của 4 kịch bản điển hình (Ngã, Nằm, Cúi, Ngồi nhanh) qua 3 vị trí A, B, C.
2. **`empty_room_targets.png`:**
   - Minh họa số lượng mục tiêu trong 3 file phòng trống và chứng minh các mục tiêu chỉ xuất hiện ở khoảng cách xa ngoài vùng thử nghiệm.
3. **`confusion_matrix_trial_level.png`:**
   - Ma trận nhầm lẫn của mô hình Baseline SVM trên tập kiểm thử độc lập 24 file.

---

## III. BẢNG PHÂN ĐOẠN NHÃN GIAI ĐOẠN (PHASE SEGMENTATION)
*(Tóm tắt tính trực tiếp từ file: `04_DA_CHIA_NHAN_GIAI_DOAN/01_tong_hop_949_doan_nhan_71_file.csv`)*
- Dữ liệu của 71 file hợp lệ được bóc tách tự động thành **949 đoạn hành động** không chồng lấn thời gian (`overlaps = 0`), thuộc 13 nhóm nhãn:

| Nhóm hành động (`activity_label`) | Số đoạn | Thời lượng trung vị ($s$) | Cao độ $\hat{Z}$ trung vị ($m$) | Đỉnh tốc độ trung vị ($m/s$) | Đặc trưng động học nhận diện |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Đứng (`STAND`)** | 295 | 4,45 | +1,22 | 0,39 | Duy trì cao độ ổn định vùng ngực/bụng |
| **Đang đứng dậy (`STAND_UP`)** | 185 | 0,80 | +0,89 | 0,24 | Quá trình nâng trọng tâm từ thấp lên cao |
| **Đang ngồi ghế (`SIT_DOWN`)** | 108 | 0,80 | +0,92 | 0,16 | Quá trình hạ trọng tâm xuống mặt ghế |
| **Ngồi ghế (`SIT`)** | 96 | 4,63 | +0,67 | 0,56 | Giữ ổn định ở cao độ mặt ghế |
| **Cúi nhặt đồ (`BEND`)** | 50 | 2,40 | +0,62 | 0,35 | Hình chữ "V": hạ thấp rồi đứng thẳng dậy ngay |
| **Té ngã (`FALL`)** | **27** | **0,53** | **+0,58** | **1,52** *(max 2,24)* | **Rơi tự do đột ngột, sập sàn rất nhanh** |
| **Nằm sau khi ngã (`LYING_POST_FALL`)** | 30 | 17,00 | -0,12 | 0,88 | Nằm bất động sát mặt sàn sau cú ngã |
| **Hạ người nằm chủ động (`LIE_DOWN`)** | **20** | **0,98** | **+0,62** | **0,48** | **Hạ người có kiểm soát (chống tay/ngồi trước)** |
| **Nằm trên nệm (`LYING`)** | 23 | 16,02 | +0,08 | 0,79 | Nằm yên trên nệm trong kịch bản nằm |
| **Đang ngồi xổm (`SQUAT_DOWN`)** | 29 | 0,62 | +0,71 | 0,24 | Hạ người xuống tư thế ngồi xổm |
| **Ngồi xổm (`SQUAT`)** | 31 | 8,90 | +0,31 | 0,39 | Hạ sâu sát sàn nhưng không sập tự do |
| **Đi lại (`WALK`)** | 14 | 22,69 | +1,28 | 0,60 | Trọng tâm cao, Doppler dao động liên tục |
| **Đoạn tụt thấp nghi vấn (`UNVERIFIED_LOW_DIP`)** | 41 | 1,42 | +0,34 | 0,39 | Tụt thấp ngắn (<5s) hoặc đứt dấu radar |

> 📌 **Điểm nhấn so sánh then chốt giữa Ngã thật và Nằm chủ động:**
> - Cú ngã (`FALL`) diễn ra chỉ trong **`0,53 s`** với tốc độ đỉnh đạt **`1,52 m/s`** (gấp 3,17 lần nằm chủ động).
> - Nằm chủ động (`LIE_DOWN`) diễn ra từ tốn trong **`0,98 s`** với tốc độ êm ái **`0,48 m/s`**.

---

## IV. BẢNG KẾT QUẢ ĐÁNH GIÁ MÔ HÌNH (PERFORMANCE EVALUATION)

### 1. Cấp độ Toàn phiên đo (Whole-trial Baseline)
*(Mô hình SVM RBF chạy trên 18 đặc trưng tóm tắt phiên đo)*

- **Trên tập Phát triển (Cross-Validation giữa Lượt 01 và 02 - 47 file):**
  - Accuracy: **91,49%**
  - Precision lớp Ngã: **66,67%**
  - Recall lớp Ngã: **66,67%** (bỏ sót 2 file ngã ở vị trí A)
  - F1-score lớp Ngã: **66,67%**
- **Trên tập Kiểm thử giữ riêng (Lượt 03 độc lập - 24 file):**
  - Accuracy: **95,83% (Đúng 23 / 24 file)**
  - Precision lớp Ngã: **75,00%**
  - Recall lớp Ngã: **100,00% (Bắt đúng 3 / 3 file ngã)**
  - F1-score lớp Ngã: **85,71%**
  - **Phân tích lỗi duy nhất:** File `C_nam_chu_dong_03` bị nhầm thành Ngã do đặc trưng toàn phiên của file này có phân vị tốc độ `abs_speed_q95 = 0,48 m/s` và thời gian nằm thấp `longest_z_le_50cm_s = 23,49 s` trùng với phân bố của các file ngã trong tập train.

### 2. Cấp độ Sự kiện thời gian thực (Đánh giá FSM Offline)
*(Bộ dò sự kiện hạ người kết hợp FSM 4 trạng thái, áp dụng luật ghép cặp 1-1 trên tập kiểm thử Lượt 03)*

| Tiêu chí đánh giá sự kiện | Kết quả trên tập Test (Lượt 03) | Ý nghĩa kỹ thuật |
| :--- | :---: | :--- |
| **Tỷ lệ nhận diện từng cú ngã** | **8 / 10 cú ngã (80,0%)** | Bắt đúng 8 cú ngã chuẩn; 2 cú bị lọt do tốc độ thấp hoặc mất dấu radar |
| **Báo động giả (False Alarms)** | **0 cảnh báo** (trên 21 file không ngã) | Không ghi nhận báo động giả trên 21 file không ngã được đánh giá (Cúi, Nằm, Ngồi) |
| **Cảnh báo dư (Spurious Alarms)** | **0 cảnh báo** (trên 3 file ngã) | Mỗi cú ngã chỉ kích hoạt duy nhất 1 lần chuông báo |
| **Phân loại cấp độ file từ sự kiện** | **24 / 24 file đúng (100%)** | Cả 3 file ngã đều có cảnh báo, 21 file không ngã không hề có cảnh báo |
| **Độ trễ cảnh báo (Alarm Latency)** | **~8,01 giây** | Thời gian xác nhận bất động sau va chạm trước khi phát chuông |

---

## V. CÂU TRẢ LỜI MẪU CHO CÁC CÂU HỎI VẶN CỦA HỘI ĐỒNG

1. **Hỏi: "Dữ liệu phòng trống tại sao lại có mục tiêu?"**
   - *Trả lời:* "Dạ trong 3 file phòng trống, toàn bộ mục tiêu đều nằm ở cự ly xa từ 5,3m trở lên (ngoài vùng thử nghiệm). Trong vùng quan tâm từ 0 đến 3,3m, radar ghi nhận 0 mục tiêu trong suốt 3.256 khung. Nhóm đã đề xuất bộ lọc ROI 3,2m để loại bỏ hoàn toàn các phản xạ ở xa này."
2. **Hỏi: "Tại sao mô hình SVM toàn phiên lại đoán nhầm file C_nam_chu_dong_03?"**
   - *Trả lời:* "Dạ do cách tiếp cận whole-trial tính phân vị q95 trên cả file 100 giây làm mất đi đỉnh vận tốc rơi tức thời 0,5 giây, khiến file nằm chủ động có vector đặc trưng cấp phiên rất giống file ngã. Khi chuyển sang thuật toán FSM xét đúng cửa sổ rơi và quá trình hạ người, hệ thống đã phân biệt đúng hoàn toàn (0 báo động giả)."
3. **Hỏi: "Bảng nhãn giai đoạn được tạo bằng cách nào?"**
   - *Trả lời:* "Dạ bảng nhãn được phân đoạn bán tự động dựa trên tín hiệu cao độ Z và vận tốc Doppler trong các kịch bản đã biết (Signal-segmented within known scenario). Các đoạn đứt quãng do mất dấu radar được đánh dấu nghi vấn (needs_review) để đảm bảo tính khách quan."
