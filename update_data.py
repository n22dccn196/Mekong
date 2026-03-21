"""
CẬP NHẬT DỮ LIỆU THÔ TỪ API MRC → DÙNG ĐỂ HUẤN LUYỆN MODEL DỰ BÁO 27-29/12
- Fix lỗi so sánh timezone (tz-naive vs tz-aware)
- Đồng bộ toàn bộ về Asia/Ho_Chi_Minh
"""

import os
import sys
import json
import pandas as pd
import numpy as np
import requests
import re
from datetime import datetime, timedelta
from pathlib import Path
import pytz

# === CẤU HÌNH ===
BASE_DIR = Path(r"E:\HK1N3\KHDL 2\KHDL")
DATA_DIR = BASE_DIR / "data"
METADATA_PATH = BASE_DIR / "station_metadata_master.csv"

VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

MRC_HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'origin': 'https://monitoring.mrcmekong.org',
    'referer': 'https://monitoring.mrcmekong.org/',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'authorization': 'Bearer eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJtZWl0aHV5IiwiZXhwIjoxNzY4NDg2ODA3LCJhdXRoIjoiUk9MRV9SRVNFQVJDSCBST0xFX1VTRVIiLCJpYXQiOjE3NjU4OTQ4MDd9.cDR-9Bj7ujWdNAHY40qOn7f_S_lGWq9Quq6FfuKa-ChXBMuAPrNqP_UJZ10nJVqrqCoVTtQDdqhZfzrR4N0Mig'
}

# === HÀM HỖ TRỢ ===
def load_metadata():
    """Load station metadata from CSV"""
    if METADATA_PATH.exists():
        return pd.read_csv(METADATA_PATH)
    else:
        raise FileNotFoundError(f"❌ Không tìm thấy file meta {METADATA_PATH}")

def fetch_and_parse_historical_data(station_id):
    """Lấy và parse dữ liệu lịch sử cho 1 trạm"""
    try:
        station_id_padded = str(station_id).strip().zfill(6)
        url = f"https://api.mrcmekong.org/api/v1/time-series/telemetry/recent/measurement/{station_id_padded}"
        
        response = requests.get(url, headers=MRC_HEADERS, timeout=(10, 20))
        response.raise_for_status()
        
        content = response.text
        measurements_match = re.search(r'"measurements"\s*:\s*(\[[^\]]*\])', content)
        if not measurements_match:
            try:
                data = response.json()
                measurements = data if isinstance(data, list) else data.get("measurements", [])
            except:
                measurements = []
        else:
            measurements_str = measurements_match.group(1)
            measurements = json.loads(measurements_str)
        
        print(f"   📈 Đã lấy {len(measurements)} điểm từ API")
        
        records = []
        for pt in measurements:
            try:
                ts = None
                w = None
                r = 0.0
                
                if isinstance(pt, dict) and "d" in pt and "w" in pt:
                    ts_raw = pd.to_datetime(pt["d"])
                    w = float(pt["w"])
                    r = float(pt.get("r", 0.0))
                elif isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    ts_raw = pd.to_datetime(pt[0])
                    w = float(pt[1])
                    r = float(pt[2]) if len(pt) > 2 else 0.0
                else:
                    continue
                
                # Xử lý Timezone cho API data
                if ts_raw.tz is None:
                    ts = ts_raw.tz_localize("UTC")
                else:
                    ts = ts_raw
                ts = ts.tz_convert("Asia/Ho_Chi_Minh")
                
                records.append({
                    "timestamp": ts,
                    "Water_Level": w,
                    "Rainfall": r
                })
            except Exception:
                continue
        
        if not records:
            return pd.DataFrame()
        
        df = pd.DataFrame(records).set_index("timestamp").sort_index()
        print(f"   ✅ Đã parse thành công {len(df)} điểm hợp lệ")
        return df
        
    except Exception as e:
        print(f"   ❌ Lỗi lấy dữ liệu cho station {station_id}: {e}")
        return pd.DataFrame()

def update_raw_data_for_station(station_name, metadata_row, cutoff_time):
    """Cập nhật file dữ liệu thô cho 1 trạm"""
    print(f"\n🔄 Cập nhật dữ liệu cho trạm: {station_name}")
    
    # 1. Tìm file gốc
    pattern = f"*{station_name.replace(' ', '_')}*Water_Level*.csv"
    files = list(DATA_DIR.glob(pattern))
    if not files:
        print(f"   ⚠️ Không tìm thấy file gốc cho trạm {station_name}")
        return False
    
    raw_file = max(files, key=lambda f: f.stat().st_mtime)
    print(f"   📁 File gốc: {raw_file.name}")
    
    # 2. Đọc file gốc và FIX TIMEZONE
    try:
        df_raw = pd.read_csv(raw_file)
        df_raw['timestamp'] = pd.to_datetime(df_raw['timestamp'])
        
        # 🛠️ FIX QUAN TRỌNG: Gán timezone VN cho dữ liệu trong CSV cũ
        if df_raw['timestamp'].dt.tz is None:
            df_raw['timestamp'] = df_raw['timestamp'].dt.tz_localize('Asia/Ho_Chi_Minh')
        else:
            df_raw['timestamp'] = df_raw['timestamp'].dt.tz_convert('Asia/Ho_Chi_Minh')
            
        df_raw = df_raw.set_index('timestamp').sort_index()
        print(f"   📊 Dữ liệu gốc: {df_raw.index.min()} → {df_raw.index.max()}")
    except Exception as e:
        print(f"   ❌ Lỗi đọc file gốc: {e}")
        return False
    
    # 3. Lấy dữ liệu lịch sử từ API
    station_id = str(metadata_row.get("stationId", "")).strip()
    if not station_id or station_id == "nan":
        print(f"   ⚠️ Không có stationId cho {station_name}")
        return False

    df_api = fetch_and_parse_historical_data(station_id)
    if df_api.empty:
        print(f"   ⚠️ Không có dữ liệu lịch sử hợp lệ cho {station_name}")
        return False

    # 4. Lọc đến cutoff_time
    df_api = df_api[df_api.index <= cutoff_time]
    if df_api.empty:
        print(f"   ⚠️ Không còn dữ liệu sau khi cắt đến {cutoff_time}")
        return False
    
    print(f"   📉 Sau khi cắt: {len(df_api)} điểm ({df_api.index.min()} → {df_api.index.max()})")
    
    # 5. Gộp dữ liệu (Giờ đây cả df_raw và df_api đều là Asia/Ho_Chi_Minh nên so sánh được)
    try:
        cutoff_raw = df_api.index.min() - timedelta(minutes=15)
        df_old = df_raw[df_raw.index < cutoff_raw]
        df_updated = pd.concat([df_old, df_api], axis=0).sort_index()
        df_updated = df_updated[~df_updated.index.duplicated(keep='last')]
        
        print(f"   📊 Tổng sau gộp: {len(df_updated)} điểm ({df_updated.index.min()} → {df_updated.index.max()})")
        
        # 6. Lưu file mới
        ts_id = metadata_row.get("stationId", "unknown")
        new_filename = f"VN_{station_name.replace(' ', '_')}_Water_Level_{ts_id}_updated_{datetime.now().strftime('%Y%m%d')}.csv"
        new_filepath = DATA_DIR / new_filename
        
        df_updated.reset_index().to_csv(new_filepath, index=False)
        print(f"   ✅ Đã lưu: {new_filename}")
        return True
        
    except Exception as e:
        print(f"   ❌ Lỗi khi gộp/lưu dữ liệu: {e}")
        return False

# === HÀM CHÍNH ===
def main():
    print("=" * 80)
    print("🔄 CẬP NHẬT DỮ LIỆU THÔ TỪ API MRC → DÙNG CHO DỰ BÁO 27-29/12")
    print("=" * 80)
    
    try:
        metadata_df = load_metadata()
        print(f"✅ Đã tải {len(metadata_df)} trạm từ metadata")
    except Exception as e:
        print(f"❌ Lỗi khởi tạo: {e}")
        return
    
    cutoff_time = pd.Timestamp("2025-12-28 23:59:59").tz_localize('Asia/Ho_Chi_Minh')
    print(f"🎯 Thời gian cutoff: {cutoff_time}")
    
    try:
        # Đọc file CSV
        df_meta = pd.read_csv(METADATA_PATH)
        
        # Lấy danh sách tên trạm từ cột 'name'
        # .unique() giúp loại bỏ các tên trùng lặp (nếu có)
        target_stations = df_meta['name'].unique().tolist()
        
        print(f"✅ Đã tải {len(target_stations)} trạm từ file: {os.path.basename(METADATA_PATH)}")

    except Exception as e:
        print(f"❌ Lỗi khi đọc file metadata: {e}")
        # Fallback: Giữ lại danh sách mặc định nếu không đọc được file
        target_stations = [
            "Tan Chau", "Chau Doc", "Can Tho", "Stung Treng", "Kratie",
            "Kompong Cham", "Neak Luong", "Phnom Koy", "Prek Kdam", "Boribo"
        ]

    # Kiểm tra kết quả
    print(f"   Danh sách trạm: {target_stations}")
    
    success_count = 0
    for station in target_stations:
        meta_row = metadata_df[metadata_df["name"].str.strip() == station]
        if meta_row.empty:
            print(f"\n❌ Không tìm thấy metadata cho trạm: {station}")
            continue
        
        row = meta_row.iloc[0].to_dict()
        if update_raw_data_for_station(station, row, cutoff_time):
            success_count += 1
    
    print("\n" + "=" * 80)
    print("✅ HOÀN THÀNH CẬP NHẬT DỮ LIỆU")
    print(f"   - Thành công: {success_count}/{len(target_stations)} trạm")
    print("=" * 80)

if __name__ == "__main__":
    main()