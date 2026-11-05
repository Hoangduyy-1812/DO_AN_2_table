# HỆ THỐNG PHÁT HIỆN TÉ NGÃ TRONG NHÀ SỬ DỤNG CẢM BIẾN mmWAVE RADAR 24GHz & FSM

> **Đồ án Chuyên ngành 2 & Luận văn Tốt nghiệp ngành Kỹ thuật Điện tử - Viễn thông / Hệ thống Nhúng**  
> **Cảm biến:** HLK-LD2450 (24GHz FMCW mmWave Radar, UART 256.000 bps, 10-11 Hz)  
> **Cơ cấu phần cứng:** ESP32-S3 FreeRTOS TCP Bridge | Kỹ thuật lắp xoay dọc $90^\circ$ ($H_{\text{mount}} = 1.7\text{ m}$)  
> **Xử lý trung tâm:** Finite State Machine (FSM 4 trạng thái) & Real-time Web Dashboard trên PC

---

## Tổng quan kho mã nguồn (Repository Structure)

```text
DO_AN_2_table/
├── 04_DA_CHIA_NHAN_GIAI_DOAN/          # Dữ liệu phân đoạn nhãn & Thuật toán FSM đánh giá offline
│   ├── 01_tong_hop_949_doan_nhan_71_file.csv    # 949 đoạn nhãn không chồng lấn thời gian (overlaps = 0)
│   ├── 02_nhan_giai_doan_TRAIN_01_02.csv        # Tập phát triển (47 file Lượt 01 + 02)
│   ├── 03_nhan_giai_doan_TEST_03.csv            # Tập kiểm thử độc lập (24 file Lượt 03)
│   ├── 04_file_bi_loai_thieu_khung.csv          # File loại trừ do thiếu khung hợp lệ (A_dung_ngoi_nhanh_01)
│   ├── 05_ket_qua_danh_gia_su_kien_TEST_03.csv  # Kết quả đánh giá sự kiện FSM chi tiết từng file
│   ├── danh_gia_su_kien_fsm.py                  # Script tái lập thuật toán FSM (chống lỗi nhảy slot, ghép cặp 1-1)
│   └── samples_da_gan_nhan_72_file/             # Toàn bộ 72 file CSV đã gán nhãn từng khung
├── pc_live_demo/                       # Bộ công cụ chạy trực tiếp thời gian thực (Live Streaming & Web GUI)
│   ├── web_dashboard.py                         # Giao diện Web Dashboard Dark Tech (Canvas 2D Radar, Đồ thị 60FPS, Còi Web Audio)
│   ├── live_receiver.py                         # Chương trình nhận TCP hiển thị Console HUD trực quan
│   ├── live_fall_fsm.py                         # Module thuật toán FSM online stream (reset an toàn khi đứt frame/nhảy slot)
│   ├── protocol.py                              # Bộ giải mã bit-level giao thức nhị phân LD2450 V1.03
│   ├── receiver.py                              # Bộ thu TCP và ghi dữ liệu nhị phân/CSV
│   └── test_live_demo.py                        # Bộ kiểm thử hồi quy tiêu chuẩn (4/4 test cases passed)
├── NOI_DUNG_VIET_BAO_CAO.md            # Tài liệu tổng hợp toàn bộ bảng số liệu, đặc trưng động học & câu hỏi phản biện
└── README.md                           # Tài liệu hướng dẫn sử dụng và kiểm chứng mã nguồn
```

---

##  Kết quả Thực nghiệm & Kiểm chứng 

### 1. Đánh giá Sự kiện FSM Offline (Tập Test Lượt 03 - 24 File giữ riêng)
*Thuật toán phát hiện sự kiện rơi đột ngột kết hợp xác minh nằm bất động $\ge 8.0\text{ s}$, áp dụng luật ghép cặp 1-1 và đếm cảnh báo dư:*

| Tiêu chí đánh giá sự kiện | Kết quả thực tế | Ghi chú kỹ thuật |
| :--- | :---: | :--- |
| **Phân loại cấp độ file từ sự kiện** | **24 / 24 file đúng (100%)** | Bắt trúng cả 3 file ngã, không báo động trên 21 file thường |
| **Tỷ lệ nhận diện từng cú ngã (Episode-level)** | **8 / 10 cú ngã (80,0%)** | Bắt đúng 8 cú ngã chuẩn; 2 cú ngã lọt do tốc độ thấp hoặc gián đoạn đa mục tiêu |
| **Báo động giả (False Alarms)** | **0 cảnh báo** (trên 21 file không ngã) | Không ghi nhận báo động giả trên 21 file thường (Cúi, Nằm, Ngồi) |
| **Cảnh báo dư (Spurious Alarms)** | **0 cảnh báo** (trên 3 file ngã) | Mỗi cú ngã chỉ kích hoạt duy nhất 1 lần chuông báo |
| **Độ trễ cảnh báo trung bình** | **~8,01 giây** | Thời gian xác nhận nằm bất động sau va chạm |

### 2. Mô hình Toàn phiên Baseline SVM 
- **Tập Train (Lượt 01 + 02 - 47 file):** Accuracy **91,49%**, F1-score lớp Ngã **66,67%**.
- **Tập Test giữ riêng (Lượt 03 - 24 file):** Accuracy **95,83% (23 / 24 file)**, F1-score lớp Ngã **85,71%**.

### 3. Phân đoạn Động học then chốt (949 đoạn hành động)
- **Té ngã (`FALL` - 27 đoạn):** Thời lượng trung vị **`0,53 s`**, Đỉnh tốc độ trung vị **`1,52 m/s`** *(max `2,24 m/s`)* $\to$ Rơi tự do rất nhanh.
- **Nằm chủ động (`LIE_DOWN` - 20 đoạn):** Thời lượng trung vị **`0,98 s`**, Đỉnh tốc độ trung vị **`0,48 m/s`** $\to$ Chậm và êm ái gấp 3,17 lần so với ngã.

---

## Hướng dẫn Chạy Thử nghiệm (How to Run)

### 1. Tái lập Kết quả Đánh giá Sự kiện FSM Offline
Chạy script đánh giá trên tập kiểm thử Lượt 03:
```bash
python 04_DA_CHIA_NHAN_GIAI_DOAN/danh_gia_su_kien_fsm.py
```
*Kết quả xuất ra màn hình và lưu tại file `04_DA_CHIA_NHAN_GIAI_DOAN/05_ket_qua_danh_gia_su_kien_TEST_03.csv`.*

### 2. Chạy Bộ Kiểm thử Hồi quy (Regression Suite)
Chạy bộ unit test tiêu chuẩn kiểm tra loại trừ khung lỗi, chống nhảy slot và xử lý lặp TCP:
```bash
python -m unittest discover -s pc_live_demo -p test_live_demo.py
```
*(Kết quả: 4/4 bài test đạt chuẩn `OK` trong < 0.05s)*.

### 3. Khởi động Giao diện Web Dashboard Trực tiếp (Live Web GUI)
Chạy giao diện giám sát thời gian thực có bản đồ phòng 2D, đồ thị 60 FPS và còi báo động:
```bash
cd pc_live_demo
python web_dashboard.py
```
- Tự động mở trình duyệt tại: **`http://localhost:8080`**.
- Lắng nghe kết nối TCP từ ESP32 tại cổng: **`9000`**.
- Hỗ trợ nút **` Giả lập Ngã Demo`** trực tiếp trên Web để thử nghiệm phản ứng của còi báo và đồ thị mà không cần tự ngã.

### 4. Khởi động Terminal Receiver 
Nếu chỉ muốn chạy giao diện dòng lệnh:
```bash
cd pc_live_demo
python live_receiver.py --port 9000 --trial DEMO_LIVE_01 --activity kiem_chung_fsm
```
*(Mỗi khung hình hiển thị: Mốc thời gian, Tọa độ $X, Y$, Cao độ $\hat{Z}$, Vận tốc và Trạng thái FSM đếm ngược thời gian nằm sàn)*.
