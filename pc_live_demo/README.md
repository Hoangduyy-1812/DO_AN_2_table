# Thử trực tiếp ngưỡng trạng thái cũ và ngưỡng lấy từ dữ liệu

Đúng mục tiêu: thay thử ngưỡng nhận diện trạng thái bằng giá trị chọn từ dữ liệu repo rồi đo lại trên cùng khung dữ liệu. Gói này có dashboard chạy được với ba chế độ đối chiếu, không chỉ là bảng ngưỡng.

## Kết quả trực tiếp

Chỉ so sánh ba nhóm mà bản cũ thực sự có: Đứng; Ngồi/Cúi; Ở thấp/Nằm. Cùng 12.356 khung có nhãn đủ điều kiện trong 21 phiên lượt 03:

| Chỉ tiêu | Ngưỡng cũ | Ngưỡng từ dữ liệu |
|---|---:|---:|
| Tỷ lệ đúng theo khung | 86,92% | 91,84% |
| Macro F1 ba nhóm | 85,62% | 90,93% |
| Nhận đúng nhóm Đứng (recall) | 81,98% | 89,13% |
| Nhận đúng nhóm Ngồi/Cúi (recall) | 84,05% | 91,72% |
| Nhận đúng nhóm Nằm (recall) | 100,00% | 97,80% |

19/21 phiên có số khung đúng tăng, 2/21 giảm. Các khung trong một phiên tương quan; không coi 12.356 khung là 12.356 thử nghiệm độc lập.

Khi thử FSM nhân quả tách đủ bốn nhãn, recall Đứng 89,13%, Ngồi 85,96%, Cúi 32,91%, Nằm 97,80%; macro F1 bốn lớp 74,46%. Cúi vẫn phân biệt kém. Bản cũ không tách Ngồi/Cúi nên không gán cho nó một accuracy bốn lớp để so sánh sai.

Không trình bày mức 91,84% là accuracy phát hiện ngã hoặc accuracy bốn hành vi. Đó là tỷ lệ đúng theo khung của ba nhóm trạng thái chung giữa hai bản.

## Ngưỡng được thay thật

| Tham số | Cũ | Chọn từ lượt 01–02 |
|---|---:|---:|
| Ranh giới Ở thấp/Nằm và Ngồi/Cúi | 0,480 m | 0,3555 m |
| Ranh giới Ngồi/Cúi và Đứng | 1,000 m | 0,9155 m |
| Mức hạ thấp để dự đoán nghi cúi | Chưa có | 0,241 m |
| Thời gian theo dõi nghi cúi | Chưa có | 2,49 giây |

Hai ngưỡng cao độ được chọn trên KHUNG hợp lệ của lượt 01–02, tối đa hóa recall trung bình ba nhóm. BEND được gộp cùng SIT khi so sánh chung. Đây khác phép khảo sát trước chỉ dùng trung vị theo ĐOẠN tư thế tĩnh; vì vậy kết quả 0,3555/0,9155 không phải hai ứng viên 0,293/0,9045 trước đó.

Ứng viên ngưỡng cúi lấy từ phân vị mức hạ/thời lượng của các đoạn BEND trong lượt 01–02, rồi chọn bằng macro F1 bốn lớp trên phần phát triển. Chỉ sau khi chốt cấu hình mới replay lượt 03. Không chọn lại tham số theo kết quả lượt 03.

## Cách chạy A/B

Dừng dashboard cũ bằng Ctrl+C. Giải nén gói này ra thư mục mới và mở PowerShell trong thư mục chứa web_dashboard.py:

    py -3.12 -m pip install -r requirements.txt

Sau đó nhấp đúp đúng một file:

| File chạy | Chế độ |
|---|---|
| CHAY_A_NGUONG_CU.cmd | SVM bộ 6 + FSM báo ngã; phân nhóm tư thế dùng ngưỡng cũ |
| CHAY_B_NGUONG_TU_DU_LIEU.cmd | Cùng SVM/FSM báo ngã, thay hai ngưỡng tư thế bằng ngưỡng từ dữ liệu |
| CHAY_C_THU_4_HANH_VI.cmd | Thử thêm nhánh nghi cúi theo quá trình hạ người, còn hạn chế |

Mở http://localhost:8080. ESP32 tiếp tục gửi TCP tới IPv4 PC tại cổng 9000. Không chạy hai bản cùng lúc trên cùng cổng. Các file chạy cũng đọc H_mount từ http://radar.local/api/state như gói trước.

Lệnh tương ứng:

    py -3.12 web_dashboard.py --model models/fall_svm_6f_2s.joblib --posture-mode old --esp32-url http://radar.local --no-mqtt
    py -3.12 web_dashboard.py --model models/fall_svm_6f_2s.joblib --posture-mode data3 --esp32-url http://radar.local --no-mqtt
    py -3.12 web_dashboard.py --model models/fall_svm_6f_2s.joblib --posture-mode data4 --esp32-url http://radar.local --no-mqtt

Dừng lệnh trước rồi chạy lệnh tiếp theo. Bỏ --esp32-url nếu chỉ thử chiều cao cố định 1,70 m từ cấu hình. Nếu dùng IP thay radar.local thì phải là IP thực tế của ESP32.

## FSM bốn tư thế thử nghiệm hoạt động thế nào?

- Cao độ >=0,9155 m: STAND.
- Cao độ <0,3555 m: LYING (trên UI ghi Ở THẤP/NẰM vì Z là proxy).
- Vùng giữa: SIT, trừ khi có quá trình vừa rời vùng đứng, hạ >=0,241 m và chưa quá 2,49 giây; khi đó dự đoán BEND.
- BEND là dự đoán nhân quả NGHI CÚI trong quá trình hạ, chưa phải xác nhận nhờ biết trước rằng người sẽ đứng lại. Giao diện ghi rõ “NGHI CÚI (đang theo dõi)”.
- Nếu tiếp tục ở vùng giữa quá thời gian theo dõi thì chuyển về SIT. Khi đứng lại thì chuyển STAND; không dùng tương lai để sửa nhãn các khung đã qua.
- Mất slot, đổi nguồn, bỏ khung hoặc thay chiều cao sẽ reset bộ theo dõi; khoảng cách khung >0,35 giây cũng reset.

Nhánh này dễ nhầm ngồi xuống thành nghi cúi trong thời gian đầu. Kết quả recall cúi 32,91% cho thấy chưa đủ tốt để dùng như bộ nhận diện bốn hành vi hoàn chỉnh.

## Phần phát hiện ngã được giữ riêng

SVM vẫn dùng sáu đặc trưng gốc, cửa sổ 2 giây và mô hình đã train. FSM phát cảnh báo ngã vẫn giữ cấu hình trước, bao gồm thời gian duy trì thấp 8 giây. Ngưỡng tư thế 0,3555 m KHÔNG thay ngưỡng hậu kiểm ngã 0,48 m. Thử đổi ngưỡng tư thế không được gọi là đã nâng recall ngã.

Hai file mô hình 6 đặc trưng trong models giữ nguyên byte so với gói LD2450_CHAY_TRUC_TIEP_6F. Không thay đầu vào ML, không train lại để làm số liệu tư thế đẹp hơn.

## Tái lập từ dữ liệu repo

Dữ liệu samples.csv A/B/C và bảng nhãn thuộc bộ DO_AN_2 đã đối chiếu với repo Hoangduyy-1812/DO_AN_2_table. Tập phát triển lượt 01–02, phần đánh giá lượt 03. Gói không kèm lại toàn bộ dữ liệu.

Trong thư mục evaluation:

    py -3.12 compare_postures.py --data-root "DUONG_DAN/comparison_data" --out results_tu_chay

comparison_data nằm trong gói LD2450_AI_6F_2s_SO_SANH.zip đã gửi trước, hoặc dùng thư mục gốc dữ liệu tương ứng trong repo.

results/comparison.json chứa ma trận nhầm lẫn, số khung theo lớp và kết quả từng phiên. test_frame_predictions.csv chứa timestamp, Z, nhãn tham chiếu, kết quả cũ và mới để kiểm tra từng khung. development_search.json ghi toàn bộ lưới thử tham số cúi.

## Phạm vi đánh giá

- Tham chiếu bốn tư thế chỉ gồm STAND, SIT, BEND, LYING và LYING_POST_FALL (hai nhãn nằm gộp thành LYING).
- Không ép WALK, SQUAT, FALL hoặc các pha chuyển tiếp vào một trong bốn nhãn khi đánh giá; chúng vẫn chạy qua bộ theo dõi nhưng không tính accuracy bốn nhãn. Không được suy rộng kết quả cho toàn bộ tám kịch bản.
- Cả bản cũ và mới dùng cùng dữ liệu valid: một slot, backlog<=500 ms, lọc trung vị ba mẫu và reset khi đứt chuỗi. Không chọn riêng khung thuận lợi cho bản mới.
- Nhãn phân đoạn bán tự động từ radar, có thể phụ thuộc ngưỡng/quy tắc và có đoạn chưa hoàn hảo. Đây chưa phải ground truth độc lập.
- Lượt 03 đã được xem trong các phân tích trước; phép thử mang tính thăm dò, chưa phải một đợt kiểm thử mù mới.
- Kết quả thuộc cấu hình 1,70 m. Nhập H_mount khác chỉ cập nhật công thức, không tự xác nhận ngưỡng mới phù hợp ở độ cao đó.

## Kiểm tra

    py -3.12 -m unittest discover -p "test_*.py"

27 kiểm tra phần mềm đã qua. Đã thử HTTP/TCP thật trong môi trường kiểm tra, gửi 25 khung mô phỏng cho từng chế độ old/data3/data4, nhận ACK và kiểm tra nhãn tư thế trong SSE. Chưa thử trên ESP32 thật hoặc máy Windows của người dùng.
