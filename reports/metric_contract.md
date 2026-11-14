# Metric contract — T09 Multi-Market Privacy Decision Gate

| Mục | Khai báo |
|---|---|
| Track | T09 |
| Primary metric | Critical-miss Rate (evaluator `eval_t09`) |
| Tăng tốt hay giảm tốt? | **lower** (thấp = tốt) |
| Đơn vị đánh giá | case (1 case = 1 CASE-XX.json) |
| Công thức | case rủi ro (gold ≠ GO) bị cho GO / tổng case rủi ro (= 1 − High-risk HOLD Recall) |
| Cách ghép pred ↔ GT | theo `case_id`; case thiếu trong decisions.csv tính là GO (worst case) |
| Candidate pool cố định | 12 case; official = split `eval` (CASE-09..12); `--split all` chỉ để tự kiểm |
| Review budget B | 12 (review toàn bộ 12 case, xếp theo rủi ro) |
| Seed | 42 (pipeline là rule-based, xác định, không ngẫu nhiên) |
| Threshold policy | Không có ngưỡng học từ dữ liệu. Duy nhất `max_retention_days = 365` là chính sách nội bộ giả định, chốt trước khi eval |
| Guardrail | false HOLD rate ≤ 0.5 (primary chỉ hợp lệ khi guardrail PASS) |
| Eval split (không dùng để tune) | CASE-09..12. Luật được viết từ nguyên tắc pháp lý + case dev 01..08, không chỉnh theo kết quả eval |
| Chỉ số lỗi xấu | critical miss (false GO); false HOLD |
| Slices báo cáo | theo market (VN/EU/US-CA/SG/IN); theo loại lỗi (cross-border / lawful basis / consent / retention) |
| Độ bất định | N rất nhỏ (4 eval, 12 all) → báo từng case, không báo CI |
| Baselines | (1) consent→GO (sai có chủ ý); (2) HOLD tất cả (critical-miss 0 nhưng FAIL guardrail) |
| Ngày giờ chốt + người chốt | ______ |
