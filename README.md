# Mekong Forecasting Repository

Repository này được tách riêng để quản lý phiên bản sạch cho 4 file đã chốt phạm vi:

- `app14.py`
- `final3.py`
- `update_data.py`
- `final2 (2) - Copy.ipynb` (giữ nguyên output notebook)

## Mục tiêu
- Tạo lịch sử Git rõ ràng theo kịch bản từng bước.
- Kết nối với remote: `https://github.com/n22dccn196/Mekong.git`.
- Dễ audit thay đổi và bàn giao.

## Cấu trúc
- `app14.py`: logic/pipeline liên quan dự báo và tích hợp dữ liệu.
- `final3.py`: pipeline dự báo chính.
- `update_data.py`: cập nhật dữ liệu từ API MRC.
- `final2 (2) - Copy.ipynb`: notebook phân tích/thử nghiệm.
- `REPORT.md`, `REPORT.txt`: báo cáo chi tiết quy trình triển khai.

## Kịch bản commit (Conventional + tiếng Việt)
1. `chore(repo): initialize repository structure - khởi tạo cấu trúc repo`
2. `feat(core): add forecasting scripts - thêm các script dự báo chính`
3. `docs(notebook): add analysis notebook - thêm notebook phân tích`
4. `docs(report): add detailed execution report - thêm báo cáo chi tiết`

## Ghi chú
- Notebook được giữ nguyên output theo yêu cầu.
- Repo này không bao gồm dữ liệu lớn/ảnh kết quả từ workspace gốc.
