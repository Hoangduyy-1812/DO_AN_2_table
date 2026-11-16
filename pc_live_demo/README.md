# PC live demo — FSM OR SVM 6 đặc trưng

Bản cập nhật theo yêu cầu ngày 13/11/2026: một trong hai nhánh FSM động học hoặc SVM đạt điều kiện thì bắt đầu NGHI NGÃ. Hậu kiểm giữ nguyên: quan sát cao độ thấp liên tục đủ 8 giây trên chuỗi dữ liệu hợp lệ mới phát cảnh báo.

## Chạy trên Windows

1. Dừng dashboard cũ. Giữ thư mục cũ làm bản sao để không mất dữ liệu đã thu.
2. Giải nén thư mục pc_live_demo mới, không chép đè lẫn các module của bản khác.
3. Nếu chưa có thư viện, chạy CAI_THU_VIEN.cmd (Python 3.12).
4. Chạy **CHAY_FSM_OR_SVM.cmd**. Chỉ có một file chạy chính; không còn các file chạy A/B/C.
5. Mở http://localhost:8080. Terminal phải có dòng `CANDIDATE: FSM OR SVM`; dashboard phải ghi `FSM OR SVM RBF (6 đặc trưng)`.

Lệnh tương đương:

```bat
py -3.12 run_fsm_or_svm.py --esp32-url http://radar.local
```

Nếu dùng IP thật của ESP32, thay URL trên. Nếu không đồng bộ chiều cao qua API, chạy với chiều cao thật, ví dụ:

```bat
py -3.12 run_fsm_or_svm.py --height 1.70
```

Ngưỡng tư thế được hiệu chỉnh ở H = 1,70 m. Khi bật đọc chiều cao ESP32, H = 1,70 m là giá trị ban đầu cho tới khi API trả về thành công; xem trạng thái đồng bộ trên giao diện.

## Điều kiện chính xác

**Nhánh FSM động học:** trong 1,25 s có cao độ trước đó >= 0,90 m; hiện tại Z < 0,40 m; giảm ít nhất 0,50 m; vận tốc xuyên tâm đỉnh >= 0,78 m/s.

**Nhánh SVM:** có cửa sổ hợp lệ gần đủ 2 giây; điểm SVM mới tính >= 0,2 và Z < 0,48 m. Điểm là decision_function, không phải xác suất 20%.

Chỉ cần một nhánh đúng là chuyển ngay sang SUSPECTED_FALL. Không cần chờ cả hai đồng ý. Nhánh FSM vẫn được xét khi SVM đang gom cửa sổ. Điểm SVM cũ chỉ được hiển thị tham khảo, không dùng để kích hoạt nghi ngã ở khung chưa có suy luận mới.

Ứng viên ghi nguồn tại thời điểm tạo: RULE (FSM), ML (SVM) hoặc RULE+ML (cả hai đúng ở khung tạo ứng viên). Nhánh còn lại kích hoạt muộn hơn không khởi động lại đồng hồ 8 giây. Khi đã nghi ngã, việc điểm SVM giảm không tự hủy ứng viên; Z >= 0,48 m hoặc reset dữ liệu sẽ hủy. Mất slot, khoảng khung > 0,35 s, timestamp không tăng, đổi nguồn, bỏ khung hoặc trễ vượt mức cho phép vẫn có thể reset theo quy tắc của bản PC trước.

ALARM_TRIGGERED sau khi liên tục ở thấp đủ 8 giây; Z >= 0,55 m tái kích hoạt. Đây là hậu kiểm duy trì thấp, không phải xác nhận vận tốc bằng 0 suốt 8 giây.

## Hiển thị và nhiều mục tiêu

Ba slot có cửa sổ, FSM và ứng viên riêng. Nguồn nghi ngã được hiện trên banner và dòng trạng thái từng slot bên dưới bản đồ. Các ô lớn và đồ thị vẫn hiển thị một slot ưu tiên: báo động, rồi nghi ngã, rồi giám sát. Xử lý nhiều slot trong phần mềm không phải bằng chứng đã kiểm chứng với nhiều người thật và đổi danh tính slot.

Nhãn tư thế giữ nguyên data3: Z >= 0,9155 m là Đứng; 0,3555 <= Z < 0,9155 m là Ngồi/Cúi; Z < 0,3555 m là Ở thấp/Nằm. Ngưỡng tư thế không thay ngưỡng hậu kiểm 0,48 m.

## Các file thay đổi

| File | Thay đổi |
|---|---|
| live_fall_fsm.py | Thêm candidate_mode=or, kiểm tra hai nhánh độc lập, lưu trigger_source |
| web_dashboard.py | Truyền chế độ OR, hiện chế độ và nguồn nghi ngã, ghi cấu hình phiên |
| run_fsm_or_svm.py | Luôn nạp đúng SVM 6 đặc trưng và bật OR |
| CHAY_FSM_OR_SVM.cmd | Lệnh chạy chính thay các runner cũ |
| replay_or.py | So sánh ba chế độ bằng mô hình cố định, không huấn luyện lại |
| test_or_detector.py | Kiểm tra nhánh độc lập, hậu kiểm, nguồn kích hoạt, mất dấu và ba slot |

Model SVM và sáu công thức đặc trưng giữ nguyên. Firmware ESP32 không được sửa; chưa có đường gửi kết quả AI từ PC về ESP32. Nhánh FSM trong OR là luật trên PC, không lấy trực tiếp cờ báo động từ radar.local.

## Kết quả replay mới

Cùng 24 phiên lượt 03, 10 sự kiện ngã tham chiếu và 21 phiên không ngã; không chỉnh model hoặc ngưỡng theo kết quả này:

| Cách tạo nghi ngã | Phát hiện / 10 | Bỏ sót | Cảnh báo sai/dư | Event F1 | Trễ trung bình |
|---|---:|---:|---:|---:|---:|
| FSM thuần PC | 8 | 2 | 0 | 88,89% | 7,930 s |
| SVM 6 đặc trưng + hậu kiểm | 7 | 3 | 1 | 77,78% | 8,173 s |
| FSM OR SVM + hậu kiểm | 8 | 2 | 1 | 84,21% | 7,908 s |

OR bắt thêm một sự kiện so với SVM riêng trong phép replay này; chưa bắt thêm so với FSM thuần và vẫn có một báo sai. OR không đảm bảo hết bỏ sót. Không lấy kết quả này làm độ chính xác thời gian thực trên thiết bị của người dùng.

Chi tiết, nguồn cảnh báo và giới hạn trong `results/or_comparison.json`. Nhãn bán tự động từ radar, phép replay lọc chất lượng đơn mục tiêu giống thí nghiệm cũ; lượt 03 đã được xem trước, không phải kiểm thử mù mới. Độ trễ tính từ đầu nhãn LYING_POST_FALL đến cảnh báo của sự kiện ghép được, không phải lúc người thật bắt đầu ngã. `models/metrics_svm_6f.json` là kết quả SVM trước cập nhật OR, giữ để truy vết.

Tái lập (data-root chứa A_direction, B_direction, C_direction và 04_DA_CHIA_NHAN_GIAI_DOAN):

```bat
py -3.12 replay_or.py --data-root "DUONG_DAN_DU_LIEU"
py -3.12 -m unittest discover -p "test_*.py"
```

Đã chạy đạt 37 kiểm tra phần mềm; kiểm tra HTTP, TCP ACK và SSE với ba slot mô phỏng dùng model SVM thật; kiểm tra cú pháp JavaScript. Chưa thử trên Windows/ESP32 thật của người dùng. Kiểm tra luồng mô phỏng không thay thế đánh giá độ chính xác phát hiện ngã.

Để khảo sát baseline bằng CLI chuyên dụng, web_dashboard.py vẫn hỗ trợ chế độ ML mặc định. Khi sử dụng hằng ngày, luôn dùng CHAY_FSM_OR_SVM.cmd hoặc run_fsm_or_svm.py để bảo đảm bật OR.
