# -*- coding: utf-8 -*-
"""
HỆ THỐNG DỰ BÁO MỰC NƯỚC MÊ KÔNG (MULTI-MODEL ENSEMBLE)
Tiêu chuẩn: ISLP (Statistical Learning) & PMML (Data Mining)
Author: AI Hydrologist
"""

import os
import json
import warnings
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from datetime import datetime, timedelta
import pytz

# Machine Learning Libraries
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import RidgeCV
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score, max_error
from joblib import dump, load

# --- 1. CẤU HÌNH HỆ THỐNG ---
BASE_DIR = Path(r"E:\HK1N3\KHDL 2\KHDL")
DATA_DIR = BASE_DIR / "data"
REGRESSION_DIR = BASE_DIR / "models" / "regression"
FORECAST_DIR = BASE_DIR / "models" / "forecasts"
METADATA_PATH = BASE_DIR / "station_metadata_master.csv"

# Tạo thư mục nếu chưa có
for d in [DATA_DIR, REGRESSION_DIR, FORECAST_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Cấu hình Timezone & Format
VN_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
DATE_FMT = '%Y-%m-%d %H:%M:%S'
warnings.filterwarnings('ignore')

# Mapping dự phòng nếu không có file metadata
DEFAULT_STATIONS = {
    "019803": "Tan_Chau",
    "019804": "Chau_Doc"
}

# --- 2. CÁC HÀM XỬ LÝ DỮ LIỆU (DATA PIPELINE) ---

def load_station_metadata():
    """Load danh sách trạm từ file master hoặc dùng mặc định."""
    if METADATA_PATH.exists():
        try:
            # Lưu ý: dtype={'stationId': str} để giữ số 0 ở đầu (ví dụ 019803)
            df = pd.read_csv(METADATA_PATH, dtype={'stationId': str})
            
            # SỬA QUAN TRỌNG: Cột tên trạm trong file csv của bạn là 'name'
            return dict(zip(df['stationId'], df['name']))
        except Exception as e:
            print(f"⚠️ Lỗi đọc CSV: {e}. Dùng danh sách mặc định.")
            return DEFAULT_STATIONS
    else:
        print("⚠️ Không tìm thấy file metadata. Dùng danh sách mặc định.")
        return DEFAULT_STATIONS

def fetch_and_update_data(station_id, station_name):
    """
    Bước 1: Cập nhật dữ liệu từ API hoặc File JSON mẫu.
    Output: CSV file updated đến 28/12/2025.
    """
    print(f"\n🔄 [UPDATE] Đang cập nhật dữ liệu trạm: {station_name} ({station_id})...")
    
    # Giả lập Training Date: Cuối ngày 28/12/2025
    SIMULATED_NOW = pd.Timestamp("2025-12-28 23:59:59").tz_localize(VN_TZ)
    
    raw_measurements = []
    source_used = ""

    # --- ƯU TIÊN 1: FILE JSON LOCAL ---
    # (Đường dẫn BASE_DIR phải được define trước đó, ví dụ: Path('E:/...'))
    json_path = BASE_DIR / f"{station_id}.json"
    
    if json_path.exists():
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Xử lý cấu trúc JSON linh hoạt
            if isinstance(data, dict):
                # Thử lấy key 'measurements' (API chuẩn) hoặc 'data' (format cũ)
                raw_measurements = data.get('measurements', data.get('data', []))
            elif isinstance(data, list):
                raw_measurements = data
                
            source_used = f"File Local ({json_path.name})"
            print(f"   📂 Tìm thấy file JSON cục bộ: {json_path.name}")
            
        except Exception as e:
            print(f"   ❌ Lỗi đọc file JSON local: {e}")

    # --- ƯU TIÊN 2: GỌI API THẬT (Nếu chưa có dữ liệu từ local) ---
    if not raw_measurements:
        url = f"https://api.mrcmekong.org/api/v1/time-series/telemetry/recent/measurement/{station_id}"
        try:
            # Timeout 10s để tránh treo tool
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                api_data = response.json()
                # Cấu trúc API: root -> 'measurements' -> list
                raw_measurements = api_data.get('measurements', [])
                source_used = "API (mrcmekong.org)"
                print(f"   ☁️ Đã tải dữ liệu từ API: {url}")
            else:
                print(f"   ⚠️ API trả về lỗi: {response.status_code}")
                
        except Exception as e:
            print(f"   ❌ Lỗi kết nối API: {e}")

    # --- XỬ LÝ DỮ LIỆU (PARSING & FILTERING) ---
    if not raw_measurements:
        print("   ⚠️ Không có dữ liệu mới từ cả File lẫn API. Bỏ qua.")
        return None

    new_data = []
    for m in raw_measurements:
        try:
            # Parse thời gian (Key 'd') và Value (Key 'w')
            ts_str = m.get('d')
            val_str = m.get('w')
            
            if ts_str is None or val_str is None:
                continue

            # UTC -> VN Timezone
            ts = pd.to_datetime(ts_str, utc=True).tz_convert(VN_TZ)
            wl = float(val_str)

            # Chỉ lấy dữ liệu quá khứ (đến 28/12)
            if ts <= SIMULATED_NOW:
                new_data.append({'timestamp': ts, 'Water_Level': wl})
                
        except (ValueError, TypeError):
            continue

    if not new_data:
        print("   ⚠️ Dữ liệu rỗng sau khi lọc thời gian (Backtest limit).")
        return None

    # Tạo DataFrame
    df = pd.DataFrame(new_data).sort_values('timestamp').drop_duplicates('timestamp')
    df = df.set_index('timestamp')
    
    # --- LƯU FILE CSV CẬP NHẬT ---
    # (Đường dẫn DATA_DIR phải được define trước đó)
    today_str = datetime.now().strftime('%Y%m%d')
    file_name = f"VN_{station_name}_Water_Level_{station_id}_updated_{today_str}.csv"
    
    # Đảm bảo thư mục tồn tại
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
    save_path = DATA_DIR / file_name
    
    # Format lại ngày giờ để lưu CSV (bỏ múi giờ để tương thích Excel tốt hơn)
    df_save = df.copy()
    df_save.index = df_save.index.tz_localize(None) 
    df_save.to_csv(save_path)
    
    print(f"   ✅ Đã lưu file: {file_name}")
    print(f"   📅 Data range ({source_used}): {df.index.min()} -> {df.index.max()}")
    
    return df

def feature_engineering_pmml(df):
    """
    Bước 2: Feature Engineering chuẩn PMML Chương 11.
    Tạo Time features, Lags, Rolling stats.
    """
    df = df.copy()
    
    # 1. Resample 15 phút (Đảm bảo tính liên tục)
    df = df.resample('15min').asfreq()
    
    # 2. Xử lý Missing Data (Không dropna thô bạo)
    # Nội suy cho các khoảng ngắn, sau đó bfill/ffill
    df['Water_Level'] = df['Water_Level'].interpolate(method='linear', limit=12) # 3h
    df['Water_Level'] = df['Water_Level'].fillna(method='bfill').fillna(method='ffill')
    
    # 3. Time Features (Cyclical encoding)
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['dayofyear'] = df.index.dayofyear
    
    # Chu kỳ ngày (24h)
    df['hour_sin'] = np.sin(2 * np.pi * (df['hour'] + df['minute']/60) / 24)
    df['hour_cos'] = np.cos(2 * np.pi * (df['hour'] + df['minute']/60) / 24)
    # Chu kỳ năm
    df['day_sin'] = np.sin(2 * np.pi * df['dayofyear'] / 365.25)
    df['day_cos'] = np.cos(2 * np.pi * df['dayofyear'] / 365.25)
    
    # 4. Lag Features (Quan trọng nhất cho Nhật triều)
    # Lag 96 (24h) là mạnh nhất (ACF ~ 0.9)
    lags = [1, 4, 96, 672] # 15p, 1h, 24h, 1 tuần
    for lag in lags:
        df[f'lag_{lag}'] = df['Water_Level'].shift(lag)
        
    # 5. Rolling Statistics (Velocity & Trend)
    # Window 96 (24h)
    df['roll_mean_96'] = df['Water_Level'].rolling(window=96).mean()
    df['roll_std_96'] = df['Water_Level'].rolling(window=96).std()
    df['velocity_96'] = df['Water_Level'].diff(96)
    
    # 6. Fill NaN sinh ra do Lags (Chiến lược: Backfill để giữ dòng đầu tiên)
    df = df.fillna(method='bfill').fillna(df['Water_Level'].mean())
    
    # Xóa cột tạm
    drop_cols = ['hour', 'minute', 'dayofyear']
    df = df.drop(columns=drop_cols, errors='ignore')
    
    return df

# --- 3. HUẤN LUYỆN & DỰ BÁO (MODEL PIPELINE) ---

def train_and_select_model(df, target='Water_Level'):
    """
    Bước 3: Huấn luyện so sánh 3 model (ISLP Ch.6 & 8).
    Chọn model có RMSE thấp nhất trên tập Validation.
    """
    print("\n🧠 [TRAIN] Đang huấn luyện và so sánh mô hình...")
    
    # Tách Train/Val
    # Train: < 27/12 (Dùng để học)
    # Val: 27/12 (Dùng để chọn model tốt nhất)
    cutoff_date = pd.Timestamp("2025-12-27 00:00:00").tz_localize(VN_TZ)
    
    train_mask = df.index < cutoff_date
    # Lấy 1 ngày làm validation
    val_mask = (df.index >= cutoff_date) & (df.index < cutoff_date + timedelta(days=1))
    
    # Nếu data quá ngắn, fallback split theo tỷ lệ
    if val_mask.sum() == 0:
        split_idx = int(len(df) * 0.9)
        train_data = df.iloc[:split_idx]
        val_data = df.iloc[split_idx:]
    else:
        train_data = df[train_mask]
        val_data = df[val_mask]
        
    X_train, y_train = train_data.drop(columns=[target]), train_data[target]
    X_val, y_val = val_data.drop(columns=[target]), val_data[target]
    
    # Scaler
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    
    # Định nghĩa Model
    models = {
        'Ridge': RidgeCV(alphas=[0.01, 0.1, 1.0, 10.0]),
        'RandomForest': RandomForestRegressor(n_estimators=100, max_depth=15, min_samples_leaf=2, n_jobs=-1, random_state=42),
        'GradientBoosting': GradientBoostingRegressor(n_estimators=100, max_depth=5, random_state=42)
    }
    
    best_rmse = float('inf')
    best_model = None
    best_name = ""
    
    print(f"   📊 Train size: {len(X_train)}, Val size: {len(X_val)}")
    
    for name, model in models.items():
        try:
            model.fit(X_train_scaled, y_train)
            preds = model.predict(X_val_scaled)
            rmse = np.sqrt(mean_squared_error(y_val, preds))
            
            # Kiểm tra Underfitting (Flatline check)
            std_pred = np.std(preds)
            if std_pred < 0.01:
                print(f"   ⚠️ {name}: Bị Underfitting (std={std_pred:.4f}). Bỏ qua.")
                continue
                
            print(f"   👉 {name}: RMSE = {rmse:.4f} m")
            
            if rmse < best_rmse:
                best_rmse = rmse
                best_model = model
                best_name = name
        except Exception as e:
            print(f"   ❌ Lỗi {name}: {e}")
            
    print(f"🏆 WINNER: {best_name} (RMSE={best_rmse:.4f})")
    
    # Retrain best model on ALL data up to 28/12 (để dự báo cho 29/12)
    # Tuy nhiên để đánh giá công bằng 27-28, ta giữ model hiện tại
    # Ở đây tôi giữ model train < 27 để thực hiện Backtest chuẩn
    return best_model, scaler, best_name

def recursive_forecast(model, scaler, df_history, steps=288): # 3 ngày * 96 bước
    """
    Bước 4: Dự báo đệ quy (Recursive Forecasting).
    Cần thiết vì các biến Lag phụ thuộc vào giá trị dự báo trước đó.
    """
    print(f"\n🔮 [FORECAST] Đang dự báo {steps} bước tương lai (Recursive)...")
    
    last_window = df_history.copy()
    predictions = []
    
    # Start timestamp: Tiếp theo của history
    start_ts = last_window.index[-1] + timedelta(minutes=15)
    current_ts = start_ts
    
    # Lấy danh sách cột feature (trừ target)
    feature_cols = [c for c in last_window.columns if c != 'Water_Level']
    
    for i in range(steps):
        # 1. Xây dựng dòng dữ liệu mới (features)
        new_row = {}
        
        # Time features
        new_row['hour_sin'] = np.sin(2 * np.pi * (current_ts.hour + current_ts.minute/60) / 24)
        new_row['hour_cos'] = np.cos(2 * np.pi * (current_ts.hour + current_ts.minute/60) / 24)
        new_row['day_sin'] = np.sin(2 * np.pi * current_ts.dayofyear / 365.25)
        new_row['day_cos'] = np.cos(2 * np.pi * current_ts.dayofyear / 365.25)
        
        # Lag & Rolling features (Lấy từ dữ liệu quá khứ + dự báo)
        # Nối history và dự báo hiện tại
        full_series = pd.concat([last_window['Water_Level']] + [pd.Series(p['pred'], index=[p['ts']]) for p in predictions])
        
        # Tính Lags
        for lag in [1, 4, 96, 672]:
            new_row[f'lag_{lag}'] = full_series.iloc[-lag] if len(full_series) >= lag else full_series.iloc[-1]
            
        # Tính Rolling
        w = 96
        if len(full_series) >= w:
            new_row[f'roll_mean_{w}'] = full_series.iloc[-w:].mean()
            new_row[f'roll_std_{w}'] = full_series.iloc[-w:].std()
            new_row[f'velocity_{w}'] = full_series.iloc[-1] - full_series.iloc[-w]
        else:
            new_row[f'roll_mean_{w}'] = full_series.mean()
            new_row[f'roll_std_{w}'] = 0
            new_row[f'velocity_{w}'] = 0
            
        # Tạo DataFrame cho 1 dòng
        X_input = pd.DataFrame([new_row])[feature_cols]
        
        # Scale
        X_scaled = scaler.transform(X_input)
        
        # Predict
        pred_val = model.predict(X_scaled)[0]
        
        # Lưu kết quả
        predictions.append({'ts': current_ts, 'pred': pred_val})
        current_ts += timedelta(minutes=15)
        
    # Convert to DataFrame
    forecast_df = pd.DataFrame(predictions)
    forecast_df = forecast_df.rename(columns={'ts': 'timestamp', 'pred': 'predicted_water_level'})
    return forecast_df

# --- 4. MAIN PROGRAM ---

def main():
    print("🌊 STARTING WATER LEVEL FORECAST SYSTEM")
    print("="*50)

    # 1. Load Metadata
    stations = load_station_metadata()
    print(f"✅ Đã tải {len(stations)} trạm.")
    
    # 2. Loop qua từng trạm (SỬA: Dùng .items() vì stations là dictionary)
    for target_station_id, station_name in stations.items():
        print(f"\n🔹 Đang xử lý: {station_name} (ID: {target_station_id})")
        print("-" * 30)

        try:
            # --- A. UPDATE DATA ---
            df = fetch_and_update_data(target_station_id, station_name)
            if df is None:
                print("❌ Không có dữ liệu để chạy.")
                continue
            if df.empty:
                print(f"   ⚠️ Trạm {station_name} dữ liệu rỗng. -> Bỏ qua.")
                continue
            # --- B. FEATURE ENGINEERING ---
            df_features = feature_engineering_pmml(df)
            
            # Cắt dữ liệu Train: Chỉ lấy đến hết 26/12 để Backtest cho 27, 28, 29
            # (Giả lập chúng ta đang đứng ở ngày 26 để dự báo 3 ngày tới)
            cutoff_train = pd.Timestamp("2025-12-26 23:59:59").tz_localize(VN_TZ)
            df_train_final = df_features[df_features.index <= cutoff_train]
            
            if len(df_train_final) < 1000:
                print("⚠️ Dữ liệu train quá ít.")
            
            # --- C. TRAIN MODEL ---
            model, scaler, model_name = train_and_select_model(df_train_final)
            
            # --- D. FORECAST 3 DAYS (27, 28, 29) ---
            # Dự báo 3 ngày = 3 * 24 * 4 = 288 steps
            forecast_df = recursive_forecast(model, scaler, df_train_final, steps=960)
            
            # --- E. EVALUATION & SAVE ---
            # Format Output
            forecast_df['status'] = forecast_df['predicted_water_level'].apply(lambda x: 'FLOOD' if x >= 4.5 else 'NORMAL')
            forecast_df['day'] = (forecast_df['timestamp'].dt.day - 26).clip(lower=1) # Ngày 27 là day 1
            
            # Lưu file CSV Forecast
            today_str = datetime.now().strftime('%Y%m%d')
            csv_path = FORECAST_DIR / f"{station_name}_forecast_{today_str}_v001.csv"
            
            # Chỉnh timestamp về format yêu cầu (có timezone +07:00)
            # Lưu ý: forecast_df['timestamp'] đang là timezone aware
            forecast_df.to_csv(csv_path, index=False, date_format='%Y-%m-%d %H:%M:%S%z')
            print(f"\n💾 Saved Forecast: {csv_path.name}")
            
            # Đánh giá so với thực tế (Dữ liệu gốc df chứa thực tế 27-28)
            comparison = pd.merge(forecast_df, df, left_on='timestamp', right_index=True, how='inner')
            
            if not comparison.empty:
                y_true = comparison['Water_Level']
                y_pred = comparison['predicted_water_level']
                
                # Metrics
                rmse = np.sqrt(mean_squared_error(y_true, y_pred))
                mae = mean_absolute_error(y_true, y_pred)
                r2 = r2_score(y_true, y_pred)
                bias = np.mean(y_pred - y_true)
                max_err = max_error(y_true, y_pred)
                
                print("\n📈 EVALUATION REPORT (27-28 Dec):")
                print(f"   RMSE:      {rmse:.4f} m (Target < 0.3m)")
                print(f"   MAE:       {mae:.4f} m")
                print(f"   Bias:      {bias:.4f} m")
                print(f"   Max Error: {max_err:.4f} m")
                print(f"   Correlation: {np.corrcoef(y_true, y_pred)[0,1]:.4f}")
                
                # Save Metrics
                metrics_df = pd.DataFrame([
                    {'Metric': 'RMSE', 'Value': rmse},
                    {'Metric': 'MAE', 'Value': mae},
                    {'Metric': 'Bias', 'Value': bias},
                    {'Metric': 'R2', 'Value': r2}
                ])
                metrics_df.to_csv(BASE_DIR / f"{station_name}_error_metrics.csv", index=False)
                
                # Plot
                plt.figure(figsize=(12, 6))
                plt.plot(comparison['timestamp'], y_true, label='Actual (Thực đo)', color='blue', linewidth=2)
                plt.plot(comparison['timestamp'], y_pred, label='Forecast (Dự báo)', color='red', linestyle='--', linewidth=2)
                plt.title(f"Forecast Validation: {station_name} (RMSE={rmse:.3f}m) - Model: {model_name}")
                plt.ylabel("Water Level (m)")
                plt.xlabel("Date")
                plt.legend()
                plt.grid(True, alpha=0.3)
                plt.tight_layout()
                plt.savefig(BASE_DIR / f"{station_name}_forecast_comparison.png")
                print(f"🖼️ Saved Plot: {station_name}_forecast_comparison.png")

                print(f"   ✅ Đã xử lý xong {station_name}")   
            else:
                print("⚠️ Không có dữ liệu thực tế trùng khớp để đánh giá.")

        except Exception as e:
            # Bắt lỗi bất ngờ (ví dụ: lỗi tính toán, lỗi file...) và vẫn đi tiếp
            print(f"   ❌ Lỗi ngoại lệ (Crash) tại trạm {station_name}: {e}")
            print("   -> Đang chuyển sang trạm kế tiếp...")
            continue
    print("\n🏁 ĐÃ HOÀN TẤT QUÉT TOÀN BỘ DANH SÁCH TRẠM.")
if __name__ == "__main__":
    main()