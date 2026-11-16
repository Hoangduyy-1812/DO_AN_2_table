# PC live demo — SVM 6 đặc trưng + FSM

Gói đầy đủ để thay chương trình PC cũ. Dựa trên LD2450_SO_SANH_FSM_CU_MOI, giữ nguyên mô hình và thuật toán; thêm runner SVM rõ ràng và sửa nhãn hiển thị điểm SVM. Không phải firmware nạp ESP32.

## Cài và chạy

1. Dừng Python/dashboard cũ. Đổi tên thư mục pc_live_demo cũ thành pc_live_demo_backup để giữ code và dữ liệu.
2. Giải nén thư mục pc_live_demo của gói này vào vị trí cũ. Giữ toàn bộ file và thư mục models đi kèm.
3. Máy cần Python 3.12 phù hợp các runner. Chạy CAI_THU_VIEN.cmd một lần; xem thông báo cài thành công trước khi tiếp tục.
4. Chạy CHAY_SVM_6F.cmd. Mở http://localhost:8080. ESP32 vẫn gửi TCP tới IPv4 máy PC, cổng 9000.
5. Terminal phải hiện MODEL: SVM RBF | FEATURES: 6 | WINDOW: 2 s | THRESHOLD: 0.2. Dashboard hiện tên SVM RBF (6 đặc trưng). Nếu nạp model lỗi, runner dừng, không chuyển âm thầm sang FSM thuần.

Lệnh tương đương:

```bat
py -3.12 run_svm_6f.py --esp32-url http://radar.local
```

Nếu tên radar.local không truy cập được, thay URL bằng IP thật của ESP32. Nếu muốn dùng cố định chiều cao 1,70 m, bỏ --esp32-url và chạy:

```bat
py -3.12 run_svm_6f.py --height 1.70
```

Runner đồng bộ dùng H thủ công làm giá trị ban đầu, sau đó ESP32 cập nhật lại khi đọc API thành công. Kiểm tra chiều cao hiện trên dashboard trước khi thử. Các ngưỡng tư thế được hiệu chỉnh tại H=1,70 m; đồng bộ H khác không tự hiệu chuẩn lại ngưỡng.

## Có AI nào?

- SVM RBF, pipeline StandardScaler và SVC; file models/fall_svm_6f_2s.joblib.
- Sáu đặc trưng: peak_radial_speed_mps, max_radial_accel_mps2, delta_x_m, delta_y_m, radial_velocity_variance, quiet_time_s.
- Cửa sổ 2 s, bước suy luận tối thiểu 175 ms. SVM tạo điểm nghi ngã; FSM yêu cầu cao độ thấp dưới 0,48 m và hậu kiểm 8 s trước khi cảnh báo.
- Tư thế riêng: Z>=0,9155 m là Đứng; 0,3555<=Z<0,9155 m là Ngồi/Cúi; Z<0,3555 m là Ở thấp/Nằm. Đây là phân nhóm bằng quy tắc, không phải lớp đầu ra SVM.
- RF được giữ trong models để đối chứng nhưng CHAY_SVM_6F.cmd không chạy RF. Không có bỏ phiếu SVM+RF.
- Gói giữ các runner A/B/C để thử nghiệm. CHAY_SVM_6F.cmd là lối vào chính, bật SVM và data3. Chạy trực tiếp web_dashboard.py không tham số vẫn là chế độ mặc định cũ; không dùng cách đó khi muốn SVM.

## Các file chính để tự đọc và sửa

| File | Vai trò |
|---|---|
| run_svm_6f.py | Lệnh chạy bắt buộc dùng mô hình SVM 6 đặc trưng |
| web_dashboard.py | Nhận dữ liệu, gọi model, hiển thị và cảnh báo |
| live_fall_fsm.py | FSM ngã riêng cho ba slot; reset khi mất dữ liệu |
| fall_window.py | Trích xuất và kiểm tra schema đặc trưng |
| posture_fsm.py, posture_config_1p7m.json | Nhãn tư thế và ngưỡng mới |
| fsm_parameters_1p7m.json, configured_fsm.py | Cấu hình phát hiện/hậu kiểm ngã |
| height_sync.py | Đọc chiều cao từ ESP32 |
| protocol.py, receiver.py, live_receiver.py | Giải mã, thu nhận và ghi dữ liệu |

Không chỉ chép web_dashboard.py hoặc run_svm_6f.py vào thư mục cũ: cần đầy đủ các module, JSON và file model. Không sửa 0,48 của hậu kiểm ngã thành 0,3555 của nhãn tư thế.

## Kết quả và giới hạn

Model không được huấn luyện lại trong gói này. Metrics giữ nguyên từ phép replay trước: SVM bộ 6 phát hiện 7/10 sự kiện với 1 cảnh báo sai; FSM thuần 8/10 với 0 cảnh báo sai. Không gọi SVM tốt hơn FSM theo số liệu này. Chưa kiểm tra gói trên Windows/ESP32 thật của người dùng. Theo dõi độc lập ba slot không đảm bảo nhận diện danh tính khi người đổi slot.

Chạy kiểm tra phần mềm bằng:

```bat
py -3.12 -m unittest discover -p "test_*.py"
```
