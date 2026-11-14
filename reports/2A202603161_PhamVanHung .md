 — Day 06 Data Lab (Field-to-Release PoC)


## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | SOLO (làm cá nhân) |
| Challenge | T09 · Multi-Market Privacy Decision Gate |
| Thành viên + vai trò | 1. **Phạm Văn Hùng** (Lead / Data / Core algorithm / QA / Review + report — một người đảm nhiệm tất cả) |
| Git URL | https://github.com/hungpham10122004-boop/K5-Day6-L2-DataGovernanceAndPrivacy |
| Tag `demo-180m` (commit) | `63dd33e` |
| Deadline (giờ VN) | **12h ngày 15/11** |
## 01 · Problem statement

- **Ai bị ảnh hưởng khi hệ thống sai:** (a) người đi đường và tài xế khác bị quay video nhưng không được thông báo / không có căn cứ xử lý hợp pháp; (b) công ty dữ liệu ô tô chịu rủi ro bị phạt, buộc dừng xử lý; (c) DPO/legal phải sửa hậu quả khi một case rủi ro bị cho phát hành nhầm.
- **Điểm nghẽn:** 12 case dữ liệu lái xe ở nhiều thị trường (VN, EU, US-CA, SG, IN) mỗi case có consent, notice, lưu trữ, chuyển dữ liệu xuyên biên giới, DPIA, lưu giữ khác nhau. Rà soát tay chậm, dễ bỏ sót, và lối tắt "có consent là xong" bỏ sót rủi ro chuyển dữ liệu và căn cứ pháp lý theo từng thị trường.
- **Đầu vào → đầu ra:** `fixtures/t09_privacy_gate/cases/CASE-XX.json` + file rule YAML có phiên bản → `out/decisions.csv` (`case_id, decision ∈ {GO, HOLD, REWORK}, reason_codes`) kèm `rule_ids`, `sources`, `advisory` để truy vết.
- **Tiêu chí GO / HOLD / REWORK (chốt trước khi chạy eval):**
  - **HOLD**: có rule chặn (thiếu căn cứ pháp lý, chuyển dữ liệu xuyên biên giới không có cơ chế/đánh giá tác động, thiếu DPIA, PII thô trên cloud, không mã hoá trên cloud, trẻ em, hoặc case có ghi chú mơ hồ cần legal).
  - **REWORK**: lỗi sửa được (thiếu notice, consent không hợp lệ/không có bằng chứng, lưu giữ không giới hạn hoặc quá 365 ngày).
  - **GO**: không rule nào đang có hiệu lực bị kích hoạt. Khi nhiều rule cùng bắt: HOLD > REWORK > GO.
- **Giả định cần DPO/legal xác nhận:** ngưỡng lưu giữ 365 ngày là chính sách nội bộ giả định; số điều luật VN (Luật 91/2025, NĐ 356/2025) lấy từ file mẫu của giảng viên, chưa đối chiếu văn bản gốc; luật Ấn Độ (DPDP) chưa hiệu lực nên chỉ là advisory.

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---|---|---|---|
| dev (CASE-01..08) | 8 | `fixtures/t09_privacy_gate/cases/` (synthetic:tools/make_fixtures.py, seed 42) | CC0-1.0 | Có |
| eval (CASE-09..12) | 4 | như trên; **không có `gt/`** trong repo học viên | CC0-1.0 | Có |

- **Schema:** mỗi case có `market, purpose, data_types, data_subjects, lawful_basis, consent{obtained, granular, withdrawable, record_available}, notice_given, storage{raw_retained, location, encryption_at_rest}, transfer{cross_border, destination, mechanism, transfer_impact_assessment}, retention_days, dpia_done, minors_possible, anonymization, ambiguity_notes`.
- **Class mapping:** quyết định chuẩn GO/HOLD/REWORK; 13 reason code theo `policy_example.yaml` của giảng viên.
- **Seed:** 42 (pipeline rule-based, xác định; seed chỉ để đúng contract). **Cách chia split:** theo case (dev 01–08 / eval 09–12) do đề cho sẵn; tôi không tự chia lại.
- **`manifest.csv` verified (sha256):** có — `python -m tools.verify_manifests` → 14 manifests, 0 failing. (Lưu ý: trên Windows phải ép LF bằng `.gitattributes`, nếu không hash lệch do CRLF — xem mục 09.)
- **Dữ liệu thật:** không dùng.

## 03 · Research & design

- **Tài liệu tham chiếu và lý do chọn kỹ thuật:** chọn policy engine dạng rule (YAML) thay vì ML vì (1) chỉ có 12 case, không có tập huấn luyện đủ lớn; (2) pháp lý cần truy vết từng điều khoản; (3) rule có phiên bản và nguồn dễ để DPO kiểm tra. Danh sách nguồn ở mục 11.
- **Data flow:** `cases/*.json` + manifest check → **load** (policy YAML, kiểm tra rule hợp lệ) → **process** (`policy_engine.evaluate_case`) → **rank** (`review_queue.csv`, xếp theo rủi ro) → **review** (reviewer điền `review_queue_reviewed.csv`, override + `audit_log.jsonl`) → **decide** (`decision.json`, `decision_log.csv`) → `decisions.csv`.
- **Thành phần offline:** không có model/weights; chỉ thư viện Python (pandas, PyYAML). Không gọi mạng (`--offline` chặn socket).
- **Rule DSL:** `when: {all|any: [{field, op, value}]}`, op ∈ eq, ne, in, not_in, is_null, not_null, truthy, falsy, gt, contains. 18 rule: 8 chung (`R-GEN-*`), 4 EU, 4 VN, 2 IN (chưa hiệu lực).
- **Trade-offs:**
  - Ưu tiên an toàn: ambiguity → HOLD (đúng giao thức lab) đổi lại có thể tăng false HOLD (CASE-09).
  - Rule tách theo thị trường vì VN không có "lợi ích hợp pháp" (legitimate interest) còn EU/SG thì có.
  - Rule có `effective_date` sau ngày đánh giá (`as_of_date = 2026-11-14`) chỉ ghi advisory, tránh coi luật chưa hiệu lực là vi phạm.
  - Ngưỡng 365 ngày đặt trong config, chốt trước khi eval.

## 04 · Baseline vs PoC

- **Baseline (A):** "có consent thì GO, không thì HOLD" (`src/baseline_t09.py`) — sai có chủ ý theo đề. **Baseline tầm thường (B):** HOLD tất cả (`src/baseline_t09_hold_all.py`) — critical-miss = 0 theo định nghĩa nhưng sẽ FAIL guardrail false-HOLD ≤ 0.5. Commit: `63dd33e`.
- **PoC:** policy engine 18 rule (`src/policy_engine.py`, `configs/policy/privacy_policy_v1.yaml`). Commit: `63dd33e`.
- **Cùng budget / heldout / seed:** cùng 12 case, B = 12, seed 42, cùng split.

**Bảng 1 · Baseline vs PoC.** Chưa chạy được `python -m src.compare` vì thiếu `gt/` nên **chưa có** `reports/metrics_*.json`. Bảng dưới là phần so sánh **không cần nhãn gốc** (đếm từ `out/baseline/decisions.csv` và `out/poc/decisions.csv`), không phải metric chính thức:

| Chỉ số (đơn vị) | Baseline A | PoC | Ghi chú |
|---|---|---|---|
| Primary: Critical-miss Rate (eval) | **chưa có** | **chưa có** | cần `gt/gold_decisions.csv` của giảng viên; higher/lower: **lower là tốt** |
| Số case cho GO (N=12) | 4 | 2 | baseline cho GO CASE-02, 03, 07, 09 |
| Số case HOLD / REWORK (N=12) | 8 / 0 | 9 / 1 | PoC tách REWORK cho CASE-05 |
| Số case hai bên quyết định khác nhau | 7 / 12 | | CASE-02, 03, 05, 06, 07, 09, 10 |
| Runtime / 100 items | ~0.15 s (0.0179 s / 12 case) | ~1.4 s (0.1719 s / 12 case) | CPU 12 luồng, Windows, Python 3.12.8; gồm cả khởi tạo |

## 05 · Evaluation protocol

- **Công thức primary:** Critical-miss Rate = số case rủi ro (gold ≠ GO) bị cho GO / tổng số case rủi ro; **thấp là tốt**; đơn vị = case. Case thiếu trong `decisions.csv` tính là GO (worst case). Chi tiết ở `reports/metric_contract.md`.
- **Guardrail:** false HOLD rate ≤ 0.5. Primary chỉ hợp lệ khi guardrail PASS.
- **Threshold / budget:** B = 12 (review toàn bộ 12 case); `max_retention_days = 365`; `as_of_date = 2026-11-14`. Đã chốt trong `configs/lab.yaml` **trước khi** có kết quả eval.
- **Không tune trên eval:** rule viết từ nguyên tắc pháp lý và case dev 01–08; tôi **không** chỉnh rule theo CASE-09..12 hay theo kết quả chấm. 
- **Độ bất định:** N = 4 (eval), 12 (all) nên không có CI có ý nghĩa; báo từng case.
- **Lệnh evaluate:** `python -m src.evaluate --track t09 --pred out/poc/decisions.csv --run-name poc --out reports/metrics_poc.json` (giảng viên chạy).

## 06 · Result slices

Kết quả PoC theo thị trường (từ `out/poc/decisions.csv`; **không phải metric so với gold**):

| Slice (market) | N | Baseline A (GO/HOLD) | PoC (GO/REWORK/HOLD) | Ghi chú |
|---|---|---|---|---|
| VN | 4 | 2 / 2 | 0 / 0 / 4 | CASE-01, 12 thiếu căn cứ (VN không có legitimate interest); CASE-03 consent không hợp lệ + PII thô trên cloud; CASE-07 chuyển dữ liệu không đánh giá tác động |
| EU | 4 | 1 / 3 | 1 / 0 / 3 | CASE-02 không cơ chế chuyển dữ liệu; CASE-04 thiếu DPIA; CASE-08 căn cứ unknown + mơ hồ; CASE-10 GO |
| US-CA | 2 | 0 / 2 | 0 / 1 / 1 | CASE-05 thiếu notice → REWORK; CASE-11 mơ hồ về ngưỡng CCPA → HOLD |
| SG | 1 | 0 / 1 | 1 / 0 / 0 | CASE-06 GO |
| IN | 1 | 1 / 0 | 0 / 0 / 1 | CASE-09 HOLD vì có ghi chú mơ hồ; 2 rule DPDP chỉ advisory |

- **Failure case 1 (baseline: "có consent là xong") — CASE-02 và CASE-07:** cả hai có consent đầy đủ nên baseline cho GO. Nhưng CASE-02 (EU) chuyển dữ liệu sang nước thứ ba không đủ mức bảo vệ mà `mechanism = null`; CASE-07 (VN) chuyển ra nước ngoài với `mechanism = unknown` và chưa có hồ sơ đánh giá tác động. Root cause: consent chỉ trả lời "có căn cứ xử lý không", không trả lời "có được chuyển ra nước ngoài không". PoC bắt bằng `R-EU-XB-01` và `R-VN-02` → HOLD.
- **Failure case 2 (baseline) — CASE-03:** có consent nhưng `granular = false`, `withdrawable = false` (consent gộp, không rút lại được), kèm khuôn mặt thô lưu trên cloud và `retention_days = null`. Baseline cho GO. PoC: `R-VN-04` (CONSENT_INVALID), `R-GEN-PII-01`, `R-GEN-RET-01` → HOLD.
- **Điểm yếu của PoC (cần nói thẳng):**
  - CASE-09 (IN) bị HOLD chỉ vì ghi chú mơ hồ, trong khi hai vi phạm tiềm năng (không có bản ghi consent, có thể có trẻ em) thuộc luật chưa hiệu lực. Nếu gold là GO thì đây là false HOLD.
  - CASE-06 (SG) được GO vì **chưa có rule riêng cho SG** (PDPA); GO ở đây là do thiếu rule, không phải do đã kiểm tra kỹ. Đây là lỗ hổng độ bao phủ.
  - CASE-11 (US-CA) có `precise_location` (dữ liệu nhạy cảm theo CPRA) nhưng PoC chỉ HOLD do mơ hồ, chưa có rule riêng cho dữ liệu nhạy cảm.
- **Latency / compute:** 0.1719 s cho 12 case (~14 ms/case), máy 12 luồng, Windows, Python 3.12.8.

## 07 · Human & decision

- **Review queue:** `out/poc/review_queue.csv` — 12 case (B = 12), xếp theo `score = mức quyết định (HOLD 2 / REWORK 1 / GO 0) + 0.1 × số rule bắt + 0.05 nếu có advisory`; cột `evidence_path` trỏ tới file case JSON.
- **Override + audit log:** reviewer điền `reviewer`, `reviewer_decision` (approve / reject / edit / escalate / skip), `override_value` (GO/HOLD/REWORK), `review_note` vào `out/poc/review_queue_reviewed.csv` rồi chạy lại. Quy tắc: `edit`/`reject` phải có `override_value`; **đổi từ HOLD/REWORK sang GO bắt buộc có `review_note`**; `escalate` ép HOLD; thiếu `reviewer` thì lỗi rõ ràng. Mọi thay đổi ghi vào `out/poc/audit_log.jsonl` (ai, khi nào, trước/sau, lý do) và cột `final_source` trong `decisions.csv` (`policy` hay `human:*`). Có test tự động cho luồng này (`test_review_override_to_go_requires_note_and_is_audited`).
- **Decision policy + reason_code + owner:** `decision.json` quyết định cho cả lô: có ≥1 HOLD → HOLD (`CASES_ON_HOLD`); không HOLD nhưng có REWORK → REWORK (`CASES_NEED_REWORK`); còn lại GO (`ALL_CASES_CLEARED`). Owner đọc từ `configs/lab.yaml` (`owner`). Kết quả lần chạy hiện tại: **HOLD** (9 case HOLD).
- **Khi nào HOLD/REWORK thay vì tự động release:** mọi rule `needs_legal_review: true` (hiện là toàn bộ rule) đều cần DPO/legal xác nhận trước khi phát hành thật; công cụ chỉ hỗ trợ rà soát.
- qtđ.- **Bằng chứng review thực tế:** tôi (PhạmHùăn Hung, reviewer) đã review 5/12 case trên `review_queue.csv` ngày 2026-11-14; kết quả lưu ở `reports/review_queue.csv`, `reports/audit_log.jsonl`, `reports/decisions_poc_after_review.csv`.

  | Case | Quyết định của máy | Hành động của reviewer | Kết quả cuối | Lý do |
  |---|---|---|---|---|
  | CASE-09 (IN) | HOLD | **edit → REWORK** | REWORK (`human:edit`) | DPDP chưa hiệu lực đến 13/05/2027 nên chưa phải vi phạm hiện tại; yêu cầu bổ sung bản ghi consent và xác minh dữ liệu trẻ em trước ngày đó |
  | CASE-11 (US-CA) | HOLD | **escalate** | HOLD (`human:escalate`) | Chưa rõ công ty có thuộc ngưỡng CCPA; có `precise_location` là dữ liệu nhạy cảm; chuyển legal |
  | CASE-12 (VN) | HOLD | approve | HOLD | Nhiều vi phạm nghiêm trọng |
  | CASE-05 (US-CA) | REWORK | approve | REWORK | Bổ sung notice at collection |
  | CASE-06 (SG) | GO | approve (có ghi chú) | GO | GO tạm thời vì chưa có rule PDPA cho SG; cần legal xác nhận |

  Trích `audit_log.jsonl` (dán 2 dòng thật từ file của bạn vào đây).

  Sau review: 8 HOLD / 2 REWORK / 2 GO; quyết định cả lô vẫn là **HOLD** (`CASES_ON_HOLD`). Bảng ở mục 04 và 06 dùng bản **tự động trước review** (`reports/decisions_poc_auto.csv`), không dùng bản sau review, để so sánh công bằng với baseline.

## 08 · Reproduce & tests

```bash
python -m venv .venv && .\.venv\Scripts\Activate.ps1 && pip install -r requirements.txt
python -m src.main --config configs/lab.yaml --track t09 --output out/poc --run-name poc --offline --seed 42
python -m src.main --track t09 --pipeline src.baseline_t09 --output out/baseline --run-name baseline --offline --seed 42
python -m src.evaluate --track t09 --pred out/poc/decisions.csv --run-name poc --out reports/metrics_poc.json   # cần gt/ của giảng viên
python -m pytest -q
```

- **Output `pytest -q`:** không có test failed (một số test `s` = skipped vì thiếu `gt/`, bình thường). 8 test của nhóm trong `tests/test_t09_policy.py`: pipeline end-to-end; ưu tiên HOLD > REWORK > GO; luật chưa hiệu lực chỉ là advisory; VN không có legitimate interest còn EU có; rule thiếu nguồn bị từ chối; baseline consent-only bỏ sót; override sang GO cần ghi chú + audit log; thiếu thư mục cases → lỗi rõ ràng (exit 2).
- **Máy / OS / Python:** Windows, CPU 12 luồng, Python 3.12.8 (repo mục tiêu 3.11–3.13). **git sha:** `63dd33e`. **[BẠN ĐIỀN: tên CPU nếu muốn]**

## 09 · Limitations & ethics

- **Pháp lý / PII / license:** dữ liệu synthetic (CC0), không có PII thật. Tuyên bố rõ: **không** khẳng định "đạt GDPR / luật Việt Nam" từ kết quả tự động; số điều luật VN chưa đối chiếu văn bản gốc; ngưỡng 365 ngày là giả định.
- **Điều chưa biết / false alarm:** chưa có số liệu so với gold; CASE-09 có thể là false HOLD; SG và dữ liệu nhạy cảm CPRA thiếu rule; rule chưa mô hình hoá "mức độ mơ hồ" mà chỉ dùng ghi chú trống/không trống.
- **Nếu scale 10×:** rule YAML vẫn xác định và nhanh (~14 ms/case); nút thắt thật sự là review thủ công và việc DPO phải duy trì rule khi luật đổi. Cần quy trình cập nhật `effective_date` và `policy_version`.
- **Vấn đề kỹ thuật đã gặp:** trên Windows, Git tự đổi LF → CRLF làm sha256 trong `manifest.csv` không khớp (14 fixture FAIL). Khắc phục bằng `core.autocrlf=false` và `.gitattributes` (`* text=auto eol=lf`).
- **Kế hoạch cải tiến:** thêm rule PDPA (SG) và rule dữ liệu nhạy cảm CPRA; tách `ambiguity` thành mức độ; đối chiếu số điều VN/EU/CA với văn bản gốc; thêm bảng đối chiếu HOLD/REWORK/GO theo từng điều khoản cho DPO.

## 10 · Team contribution

**Bảng 2 · Individual contribution evidence** (làm cá nhân; đối chiếu `git shortlog -sne --all` và `reports/team_contributions.csv`)

| Học viên | Git author/email | Module / vai trò | Commit SHA / diff chứng minh | Trình bày? |
|---|---|---|---|---|
| **Phạm Văn Hùng** | **https://github.com/hungpham10122004-boop/K5-Day6-L2-DataGovernanceAndPrivacy** | Toàn bộ: policy YAML, `policy_engine.py`, `pipeline.py`, baseline, tests, report | `7f4cb0d` (.gitattributes), `63dd33e` (T09 policy, pipeline, baseline, tests) | Có |

## 11 · References

| URL | Ngày xem | 1–2 dòng ý nghĩa |
|---|---|---|
| https://eur-lex.europa.eu/eli/reg/2016/679/oj (GDPR) | **14/11** | Căn cứ cho các rule EU/chung: Art. 5(1)(c),(e), 6(1), 7, 8, 13–14, 25, 32, 35, Chapter V (44–49). |
| https://thuvienphapluat.vn/van-ban/Bo-may-hanh-chinh/Luat-Bao-ve-du-lieu-ca-nhan-2025-so-91-2025-QH15-625628.aspx | **14/11** | Luật BVDLCN 91/2025/QH15 (và NĐ 356/2025): căn cứ cho `R-VN-*`; số điều cần đối chiếu văn bản gốc. |
| `fixtures/t09_privacy_gate/rules/policy_example.yaml`, `docs/tracks/T09.md` | 2026-11-14 | Cấu trúc rule mẫu, reason code, lưu ý VN không có legitimate interest, ngày hiệu lực DPDP (13/05/2027). |
| CCPA/CPRA; EDPB Guidelines 01/2020 (xe kết nối); DPDP Rules 2025 | **14/11** | Được đề bài nêu làm tài liệu gốc; rule tương ứng (notice, DPIA, advisory Ấn Độ) cần đối chiếu trực tiếp. |

---

**Bảng 3 · Checklist chốt khi nộp**

- [x] Link repo và tag cuối cùng; input mẫu không chứa PII thật (synthetic CC0).
- [x] 1 lệnh run, 1 lệnh evaluate, 1 lệnh tests; không cần download khi chạy.
- [ ] Baseline/PoC metrics (`metrics_*.json`): **chưa có** vì thiếu `gt/`; ≥1 failure case: có; reviewer evidence: ; decision log
- [x] License/source provenance, data splits, seed, offline environment; GT/eval N: eval N = 4 (không có GT).
- [ ] Mỗi thành viên ≥1 commit thực chất: có 2 commit, **[BẠN ĐIỀN]** kiểm tra tên/email khớp `team_contributions.csv`.
