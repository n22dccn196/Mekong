# """
# 🌊 MEKONG FLOOD FORECASTING DASHBOARD
# Professional Single-Page Dashboard - Streamlit Native
# ======================================================
# Version: 3.0.1 (14-Day Forecast)
# """
# import streamlit as st
# import pandas as pd
# import numpy as np
# import requests
# import math
# import time
# from datetime import datetime, timedelta
# from pathlib import Path
# import joblib
# import warnings
# import plotly.graph_objects as go
# from plotly.subplots import make_subplots
# import folium
# from streamlit_folium import st_folium
# from concurrent.futures import ThreadPoolExecutor, as_completed
# from typing import Dict, List, Tuple, Optional
# import os
# warnings.filterwarnings('ignore')

# # =============================================================================
# # PAGE CONFIG
# # =============================================================================
# st.set_page_config(
#     page_title="🌊 Mekong Flood Forecast",
#     page_icon="🌊",
#     layout="wide",
#     initial_sidebar_state="expanded"
# )

# # =============================================================================
# # CONFIGURATION
# # =============================================================================
# BASE_DIR = Path(__file__).parent
# MODELS_DIR = BASE_DIR / "models"
# REGRESSION_DIR = MODELS_DIR / "regression"
# SCALERS_DIR = MODELS_DIR / "scalers"
# DATA_DIR = BASE_DIR / "data"
# FORECAST_DIR = MODELS_DIR / "forecasts"
# METADATA_PATH = BASE_DIR / "station_metadata_master.csv"
# PERFORMANCE_PATH = MODELS_DIR / "station_performance.csv"
# MOUTH_LAT, MOUTH_LON = 9.47, 106.35
# CACHE_TTL_SECONDS = 3600
# MAX_WEATHER_WORKERS = 10
# WEATHER_API_DELAY = 0.1

# MRC_API_URL = "https://api.mrcmekong.org/api/v1/time-series/telemetry/recent/stations"
# MRC_HEADERS = {
#     'accept': 'application/json, text/plain, */*',
#     'accept-language': 'en-US,en;q=0.9,vi-VN;q=0.8,vi;q=0.7',
#     'origin': 'https://monitoring.mrcmekong.org',
#     'referer': 'https://monitoring.mrcmekong.org/',
#     'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
#     'sec-ch-ua-mobile': '?0',
#     'sec-ch-ua-platform': '"Windows"',
#     'sec-fetch-dest': 'empty',
#     'sec-fetch-mode': 'cors',
#     'sec-fetch-site': 'same-site',
#     'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
# }
# OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
# SENTINEL_VALUE = -1.0

# FEATURE_COLS = [
#     'water_level', 'water_level_lag1', 'water_level_lag2', 'water_level_lag3',
#     'water_level_rolling_mean_7', 'water_level_rolling_std_7', 'rate_of_change',
#     'precipitation_sum', 'temperature_2m_max', 'et0_fao_evapotranspiration',
#     'rain_lag1', 'rain_lag2', 'rain_rolling_3d',
#     'latitude', 'longitude', 'elevation', 'dist_to_ocean_km',
#     'month', 'is_flood_season'
# ]

# # =============================================================================
# # SESSION STATE
# # =============================================================================
# if 'last_updated' not in st.session_state:
#     st.session_state.last_updated = None
# if 'data_source' not in st.session_state:
#     st.session_state.data_source = 'unknown'

# # =============================================================================
# # HELPER FUNCTIONS
# # =============================================================================
# def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
#     """Calculate great-circle distance in km"""
#     R = 6371
#     lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
#     dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
#     a = math.sin(dlat/2)**2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon/2)**2
#     return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# # =============================================================================
# # CACHED RESOURCE LOADERS
# # =============================================================================
# @st.cache_resource
# def load_station_model(station_name: str):
#     """
#     Load trained regression model and scaler for a specific station.
    
#     Args:
#         station_name: Station name (e.g., 'Tan_Chau', 'Chau_Doc')
    
#     Returns:
#         model_artifact: dict with model, feature_names, metrics
#         scaler: StandardScaler object
#         success: bool
#     """
#     # Normalize station name (replace spaces with underscores)
#     station_id = station_name.replace(" ", "_").replace("'", "")
    
#     model_path = REGRESSION_DIR / f"best_regressor_{station_id}.pkl"
#     scaler_path = SCALERS_DIR / f"scaler_{station_id}.pkl"
    
#     if model_path.exists() and scaler_path.exists():
#         try:
#             model_artifact = joblib.load(model_path)
#             scaler = joblib.load(scaler_path)
#             return model_artifact, scaler, True
#         except Exception as e:
#             print(f"Error loading model for {station_name}: {e}")
#             return None, None, False
#     return None, None, False

# @st.cache_resource
# def load_all_station_models():
#     """
#     Load all available station models into a dictionary.
    
#     Returns:
#         dict: {station_name: (model_artifact, scaler)}
#     """
#     models_dict = {}
    
#     if REGRESSION_DIR.exists():
#         for model_file in REGRESSION_DIR.glob("best_regressor_*.pkl"):
#             station_id = model_file.stem.replace("best_regressor_", "")
#             scaler_path = SCALERS_DIR / f"scaler_{station_id}.pkl"
            
#             if scaler_path.exists():
#                 try:
#                     model_artifact = joblib.load(model_file)
#                     scaler = joblib.load(scaler_path)
#                     models_dict[station_id] = (model_artifact, scaler)
#                 except Exception:
#                     continue
    
#     return models_dict

# @st.cache_data
# def load_station_performance() -> pd.DataFrame:
#     """
#     Load station performance metrics from CSV.
    
#     Returns:
#         DataFrame with columns: Station, Best_Algo, RMSE, R2, MAE
#     """
#     if PERFORMANCE_PATH.exists():
#         return pd.read_csv(PERFORMANCE_PATH)
#     return pd.DataFrame()

# # =============================================================================
# # ✅ SỬA: load_station_forecast — hỗ trợ 14 ngày, căn vào T
# # =============================================================================
# def load_station_forecast(station_name: str, T: Optional[pd.Timestamp] = None) -> pd.DataFrame:
#     """
#     Load 14-day forecast from CSV for a station.
#     Dates are calculated dynamically: T−7 → T+6 (14 days total).
#     Args:
#         station_name: Station name (e.g., 'Tan_Chau')
#         T: Time of latest real measurement (from API). If None, fallback to today.
#     Returns:
#         DataFrame with columns: date, day, best_model_prediction, stacking_prediction, etc.
#     """
#     station_id = station_name.replace(" ", "_").replace("'", "")
#     forecast_path = FORECAST_DIR / f"{station_id}_forecast.csv"
    
#     if forecast_path.exists():
#         try:
#             df = pd.read_csv(forecast_path)
            
#             # Determine reference time T
#             if T is None:
#                 T = pd.Timestamp.now().normalize()  # fallback
            
#             # Generate 14 dates: T−7, T−6, ..., T+6
#             forecast_dates = pd.date_range(
#                 start=T - timedelta(days=7),
#                 periods=14,
#                 freq='D'
#             )
            
#             # Truncate or pad to 14 rows
#             df = df.head(14).copy()
#             if len(df) < 14:
#                 pad_df = pd.DataFrame({col: [np.nan] * (14 - len(df)) for col in df.columns})
#                 df = pd.concat([df, pad_df], ignore_index=True)
            
#             df = df.iloc[:14].copy()
#             df['date'] = forecast_dates[:14]
#             df['day'] = range(1, 15)  # 1 to 14
#             df['days_from_T'] = (df['date'] - T).dt.days  # −7 to +6
            
#             return df.reset_index(drop=True)
#         except Exception as e:
#             print(f"Error loading forecast for {station_name}: {e}")
#             return pd.DataFrame()
#     return pd.DataFrame()

# # =============================================================================
# # CÁC HÀM KHÁC — giữ nguyên (fetch weather, engineer, predict, map, v.v.)
# # =============================================================================
# def check_new_data_available(df_current: pd.DataFrame) -> Tuple[bool, str]:
#     """
#     Check if MRC API has newer data than the last forecast.
    
#     Args:
#         df_current: Current stations DataFrame
    
#     Returns:
#         Tuple[has_new_data, message]
#     """
#     # Get latest measurement time from API
#     latest_api_time = None
#     for _, row in df_current.iterrows():
#         ts = row.get('last_measurement')
#         if pd.notna(ts) and ts:
#             try:
#                 dt = pd.to_datetime(ts)
#                 if latest_api_time is None or dt > latest_api_time:
#                     latest_api_time = dt
#             except:
#                 pass
    
#     if latest_api_time is None:
#         return False, "Không có dữ liệu thời gian từ API"
    
#     # Check latest forecast file modification time
#     forecast_summary = FORECAST_DIR / "stacking_comparison_summary.csv"
#     if forecast_summary.exists():
#         forecast_mtime = datetime.fromdate(os.path.getmtime(forecast_summary))
#         if latest_api_time > forecast_mtime:
#             return True, f"Có dữ liệu mới từ MRC API ({latest_api_time.strftime('%Y-%m-%d %H:%M')})"
#         else:
#             return False, f"Forecast đã cập nhật ({forecast_mtime.strftime('%Y-%m-%d %H:%M')})"
#     else:
#         return True, "Chưa có forecast, cần tạo mới"

# @st.cache_resource
# def load_metadata() -> pd.DataFrame:
#     """Load station metadata"""
#     if METADATA_PATH.exists():
#         return pd.read_csv(METADATA_PATH)
#     return pd.DataFrame()

# def _fetch_single_weather(lat: float, lon: float, station_id: str) -> Tuple[str, dict]:
#     """Fetch weather for a single station"""
#     time.sleep(WEATHER_API_DELAY)
#     try:
#         params = {
#             "latitude": lat,
#             "longitude": lon,
#             "daily": "precipitation_sum,temperature_2m_max,et0_fao_evapotranspiration",
#             "past_days": 7,
#             "forecast_days": 1,
#             "timezone": "Asia/Bangkok"
#         }
#         response = requests.get(OPEN_METEO_URL, params=params, timeout=10)
#         if response.status_code == 200:
#             return station_id, {"success": True, "data": response.json()}
#         return station_id, {"success": False}
#     except Exception:
#         return station_id, {"success": False}


# def fetch_all_weather_parallel(stations: List[dict]) -> Dict[str, dict]:
#     """Fetch weather data for all stations in parallel"""
#     weather_results = {}
    
#     with ThreadPoolExecutor(max_workers=MAX_WEATHER_WORKERS) as executor:
#         futures = {}
#         for station in stations:
#             lat = station.get('latitude', 0)
#             lon = station.get('longitude', 0)
#             station_id = str(station.get('stationId', ''))
            
#             if lat and lon and lat != 0 and lon != 0:
#                 future = executor.submit(_fetch_single_weather, lat, lon, station_id)
#                 futures[future] = station_id
        
#         for future in as_completed(futures):
#             try:
#                 station_id, result = future.result()
#                 weather_results[station_id] = result
#             except Exception:
#                 weather_results[futures[future]] = {"success": False}
    
#     return weather_results

# def load_historical_csv_data(station_name: str) -> pd.DataFrame:
#     """Load historical data from CSV"""
#     station_name_clean = station_name.replace(" ", "_").replace("'", "").lower()
    
#     for csv_file in DATA_DIR.glob("*.csv"):
#         if station_name_clean in csv_file.stem.lower():
#             try:
#                 df = pd.read_csv(csv_file, parse_dates=['date'])
#                 df = df.sort_values('date').tail(30)
#                 return df
#             except Exception:
#                 continue
#     return pd.DataFrame()

# def load_all_stations_from_csv(metadata_df: pd.DataFrame) -> List[dict]:
#     """Fallback: Load all station data from CSV files"""
#     stations = []
    
#     for _, row in metadata_df.iterrows():
#         station_name = row.get('name', '')
#         station_id = str(row.get('stationId', ''))
#         lat = row.get('latitude', 15.0)
#         lon = row.get('longitude', 105.0)
#         flood_stage = row.get('floodStage', None)
#         alarm_stage = row.get('alarmStage', None)
        
#         hist_df = load_historical_csv_data(station_name)
        
#         if not hist_df.empty and 'value' in hist_df.columns:
#             water_level = hist_df['value'].iloc[-1]
#             yesterday_level = hist_df['value'].iloc[-2] if len(hist_df) > 1 else water_level
#         else:
#             water_level = 5.0
#             yesterday_level = 5.0
        
#         stations.append({
#             'stationId': station_id,
#             'name': station_name,
#             'latitude': lat,
#             'longitude': lon,
#             'water_level': water_level,
#             'yesterday_level': yesterday_level,
#             'flood_stage': flood_stage if pd.notna(flood_stage) else None,
#             'alarm_stage': alarm_stage if pd.notna(alarm_stage) else None,
#             'historical_df': hist_df,
#             'data_source': 'csv'
#         })
    
#     return stations

# def engineer_features(df: pd.DataFrame, lat: float, lon: float, weather_data: dict = None) -> pd.DataFrame:
#     """Engineer all 19 features for ML prediction"""
#     df = df.copy()
    
#     if 'value' in df.columns:
#         df['water_level'] = df['value']
#     elif 'water_level' not in df.columns:
#         return pd.DataFrame()
    
#     df['water_level_lag1'] = df['water_level'].shift(1)
#     df['water_level_lag2'] = df['water_level'].shift(2)
#     df['water_level_lag3'] = df['water_level'].shift(3)
#     df['water_level_rolling_mean_7'] = df['water_level'].rolling(window=7, min_periods=1).mean()
#     df['water_level_rolling_std_7'] = df['water_level'].rolling(window=7, min_periods=1).std()
#     df['rate_of_change'] = df['water_level'] - df['water_level'].shift(1)
    
#     if weather_data and weather_data.get('success') and 'daily' in weather_data.get('data', {}):
#         daily = weather_data['data']['daily']
#         df['precipitation_sum'] = daily.get('precipitation_sum', [0])[-1] or 0
#         df['temperature_2m_max'] = daily.get('temperature_2m_max', [30])[-1] or 30
#         df['et0_fao_evapotranspiration'] = daily.get('et0_fao_evapotranspiration', [5])[-1] or 5
#     else:
#         df['precipitation_sum'] = SENTINEL_VALUE
#         df['temperature_2m_max'] = SENTINEL_VALUE
#         df['et0_fao_evapotranspiration'] = SENTINEL_VALUE
    
#     df['rain_lag1'] = df['precipitation_sum'].shift(1).fillna(SENTINEL_VALUE)
#     df['rain_lag2'] = df['precipitation_sum'].shift(2).fillna(SENTINEL_VALUE)
#     df['rain_rolling_3d'] = df['precipitation_sum'].rolling(window=3, min_periods=1).mean()
    
#     df['latitude'] = lat
#     df['longitude'] = lon
#     df['elevation'] = lat * 10
#     df['dist_to_ocean_km'] = haversine_distance(lat, lon, MOUTH_LAT, MOUTH_LON)
    
#     if 'date' in df.columns:
#         df['month'] = pd.to_datetime(df['date']).dt.month
#     else:
#         df['month'] = datetime.now().month
    
#     df['is_flood_season'] = df['month'].apply(lambda m: 1 if 6 <= m <= 11 else 0)
    
#     for col in FEATURE_COLS:
#         if col in df.columns:
#             df[col] = df[col].fillna(SENTINEL_VALUE)
    
#     return df

# def make_regression_prediction(model_artifact: dict, scaler, features_df: pd.DataFrame,
#                                flood_stage: float) -> Tuple[float, float]:
#     """
#     Make water level prediction using trained regression model.
    
#     Args:
#         model_artifact: dict with 'model' and 'feature_names'
#         scaler: StandardScaler object
#         features_df: DataFrame with engineered features
#         flood_stage: Flood threshold for the station
    
#     Returns:
#         predicted_level: Predicted water level (m)
#         flood_probability: Probability based on predicted level vs flood stage
#     """
#     try:
#         model = model_artifact['model']
#         feature_names = model_artifact.get('feature_names', FEATURE_COLS)
        
#         # Prepare features - use model's expected features
#         available_features = [f for f in feature_names if f in features_df.columns]
        
#         if not available_features:
#             return None, 0.3
        
#         # Add missing features with sentinel value
#         for col in feature_names:
#             if col not in features_df.columns:
#                 features_df[col] = SENTINEL_VALUE
        
#         X = features_df[feature_names].tail(1).values
#         X = np.nan_to_num(X, nan=SENTINEL_VALUE, posinf=1e10, neginf=-1e10)
        
#         # Scale and predict
#         X_scaled = scaler.transform(X)
#         predicted_level = float(model.predict(X_scaled)[0])
        
#         # Calculate flood probability based on predicted level
#         if flood_stage is not None and flood_stage > 0:
#             # Sigmoid-like probability based on how close to flood stage
#             ratio = predicted_level / flood_stage
#             if ratio >= 1.0:
#                 flood_prob = min(0.95, 0.5 + (ratio - 1.0) * 0.5)
#             else:
#                 flood_prob = max(0.05, ratio * 0.5)
#         else:
#             flood_prob = 0.3
        
#         return predicted_level, flood_prob
    
#     except Exception as e:
#         print(f"Prediction error: {e}")
#         return None, 0.3

# def make_prediction(model, scaler, features_df: pd.DataFrame) -> Tuple[float, int]:
#     """Legacy: Make flood prediction using trained classifier (fallback)"""
#     try:
#         for col in FEATURE_COLS:
#             if col not in features_df.columns:
#                 features_df[col] = SENTINEL_VALUE
        
#         X = features_df[FEATURE_COLS].tail(1).values
#         X = np.nan_to_num(X, nan=SENTINEL_VALUE, posinf=1e10, neginf=-1e10)
        
#         X_scaled = scaler.transform(X)
#         pred_proba = model.predict_proba(X_scaled)[0]
#         pred_class = model.predict(X_scaled)[0]
        
#         flood_prob = float(pred_proba[1]) if len(pred_proba) > 1 else float(pred_proba[0])
#         return flood_prob, int(pred_class)
#     except Exception:
#         return 0.5, 0
# @st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
# def fetch_all_stations_data(_metadata_hash: str) -> pd.DataFrame:
#     """
#     Main data fetching function - returns consolidated DataFrame.
#     Columns: stationId, name, latitude, longitude, water_level, yesterday_level,
#              rainfall_24h, flood_stage, flood_probability, predicted_level, 
#              model_name, status, historical_df
#     """
#     metadata_df = load_metadata()
    
#     # Load all station-specific models
#     station_models = load_all_station_models()
    
#     stations_data = []
#     mrc_success = False
#     mrc_stations = []
    
#     # Try MRC API
#     try:
#         response = requests.get(MRC_API_URL, headers=MRC_HEADERS, timeout=30)
#         if response.status_code == 200:
#             mrc_data = response.json()
#             if isinstance(mrc_data, list) and len(mrc_data) > 0:
#                 mrc_stations = mrc_data
#                 mrc_success = True
#     except Exception:
#         pass
    
#     # Fallback to CSV if API fails
#     if not mrc_success:
#         csv_stations = load_all_stations_from_csv(metadata_df)
        
#         for station in csv_stations:
#             station_name = station['name']
#             station_id_key = station_name.replace(" ", "_").replace("'", "")
#             lat, lon = station['latitude'], station['longitude']
#             hist_df = station.get('historical_df', pd.DataFrame())
#             flood_stage = station['flood_stage']
            
#             predicted_level = None
#             model_name = "N/A"
#             flood_prob = 0.3
            
#             # Try to use station-specific model
#             if station_id_key in station_models:
#                 model_artifact, scaler = station_models[station_id_key]
#                 model_name = model_artifact.get('model_name', 'Unknown')
                
#                 if not hist_df.empty:
#                     features_df = engineer_features(hist_df, lat, lon, None)
#                     if not features_df.empty:
#                         predicted_level, flood_prob = make_regression_prediction(
#                             model_artifact, scaler, features_df, flood_stage
#                         )
            
#             # Fallback probability calculation
#             if predicted_level is None:
#                 flood_prob = station['water_level'] / flood_stage if flood_stage is not None and flood_stage > 0 else 0.3
            
#             status = "NORMAL" if flood_prob < 0.5 and (flood_stage is None or station['water_level'] < flood_stage * 0.9) else "ALARM"
            
#             stations_data.append({
#                 'stationId': station['stationId'],
#                 'name': station_name,
#                 'latitude': lat,
#                 'longitude': lon,
#                 'water_level': station['water_level'],
#                 'yesterday_level': station['yesterday_level'],
#                 'rainfall_24h': 0.0,
#                 'flood_stage': flood_stage,
#                 'flood_probability': flood_prob,
#                 'predicted_level': predicted_level,
#                 'model_name': model_name,
#                 'status': status,
#                 'last_measurement': None,  # CSV fallback has no date
#                 'historical_df': hist_df
#             })
        
#         return pd.DataFrame(stations_data)
    
#     # Process MRC API data
#     meta_lookup = {str(row.get('stationId', '')): row.to_dict() for _, row in metadata_df.iterrows()}
    
#     # Build station list for weather
#     stations_for_weather = []
#     for station in mrc_stations:
#         station_id = str(station.get('stationId', station.get('id', '')))
#         lat = float(station.get('latitude', station.get('lat', 0)))
#         lon = float(station.get('longitude', station.get('lon', 0)))
        
#         if lat == 0 or lon == 0:
#             meta = meta_lookup.get(station_id, {})
#             lat = float(meta.get('latitude', 15.0))
#             lon = float(meta.get('longitude', 105.0))
        
#         stations_for_weather.append({'stationId': station_id, 'latitude': lat, 'longitude': lon})
    
#     # Parallel weather fetch
#     weather_results = fetch_all_weather_parallel(stations_for_weather)
    
#     # Process each station
#     for station in mrc_stations:
#         try:
#             station_id = str(station.get('stationId', station.get('id', '')))
#             name = station.get('stationName', station.get('name', f'Station_{station_id}'))
#             station_id_key = name.replace(" ", "_").replace("'", "")
#             lat = float(station.get('latitude', station.get('lat', 0)))
#             lon = float(station.get('longitude', station.get('lon', 0)))
            
#             meta = meta_lookup.get(station_id, {})
#             if lat == 0 or lon == 0:
#                 lat = float(meta.get('latitude', 15.0))
#                 lon = float(meta.get('longitude', 105.0))
            
#             flood_stage = meta.get('floodStage', None)
#             if pd.isna(flood_stage):
#                 flood_stage = None
            
#             alarm_stage = meta.get('alarmStage', None)
#             if pd.isna(alarm_stage):
#                 alarm_stage = None
            
#             # Get water level
#             observations = station.get('observations', station.get('data', []))
#             if isinstance(observations, list) and len(observations) > 0:
#                 latest = observations[-1] if isinstance(observations[-1], dict) else {'value': observations[-1]}
#                 water_level = float(latest.get('value', latest.get('waterLevel', 5.0)))
#                 yesterday_level = float(observations[-2].get('value', water_level)) if len(observations) > 1 else water_level
#             else:
#                 water_level = float(station.get('waterLevel', station.get('value', 5.0)))
#                 yesterday_level = water_level
            
#             # Get weather
#             weather = weather_results.get(station_id, {"success": False})
#             rainfall_24h = 0.0
#             if weather.get('success') and 'daily' in weather.get('data', {}):
#                 precip_list = weather['data']['daily'].get('precipitation_sum', [0])
#                 rainfall_24h = float(precip_list[-1]) if precip_list else 0.0
            
#             # Load historical
#             hist_df = load_historical_csv_data(name)
#             if hist_df.empty:
#                 dates = pd.date_range(end=datetime.now(), periods=10, freq='D')
#                 hist_df = pd.DataFrame({
#                     'date': dates,
#                     'value': [water_level + np.random.normal(0, 0.2) for _ in range(10)]
#                 })
            
#             # Add current
#             current_row = pd.DataFrame({'date': [datetime.now()], 'value': [water_level]})
#             combined_df = pd.concat([hist_df, current_row], ignore_index=True)
            
#             # Remove duplicate dates - keep the last occurrence
#             combined_df['date'] = pd.to_datetime(combined_df['date'])
#             combined_df = combined_df.drop_duplicates(subset=['date'], keep='last')
#             combined_df = combined_df.sort_values('date').reset_index(drop=True)
            
#             # Predict using station-specific model
#             predicted_level = None
#             model_name = "N/A"
#             flood_prob = 0.3
            
#             if station_id_key in station_models:
#                 model_artifact, scaler = station_models[station_id_key]
#                 model_name = model_artifact.get('model_name', 'Unknown')
                
#                 features_df = engineer_features(combined_df, lat, lon, weather)
#                 if not features_df.empty:
#                     predicted_level, flood_prob = make_regression_prediction(
#                         model_artifact, scaler, features_df, flood_stage
#                     )
            
#             # Fallback probability calculation
#             if predicted_level is None:
#                 flood_prob = water_level / flood_stage if flood_stage is not None and flood_stage > 0 else 0.3
            
#             # Determine status based on lastStatus from API or calculated
#             last_status_api = station.get('lastStatus', 'NA')
#             if last_status_api == 'FLOOD':
#                 status = "FLOOD"
#             elif last_status_api == 'ALARM':
#                 status = "ALARM"
#             elif last_status_api == 'NORMAL':
#                 status = "NORMAL"
#             elif last_status_api == 'NODATA':
#                 status = "NODATA"
#             else:
#                 # Fallback: calculate based on water level
#                 if flood_prob >= 0.5 or (flood_stage is not None and water_level >= flood_stage * 0.9):
#                     status = "ALARM"
#                 else:
#                     status = "NORMAL"
            
#             # Get lastMeasurement date from API
#             last_measurement = station.get('lastMeasurement', None)
            
#             stations_data.append({
#                 'stationId': station_id,
#                 'name': name,
#                 'latitude': lat,
#                 'longitude': lon,
#                 'water_level': water_level,
#                 'yesterday_level': yesterday_level,
#                 'rainfall_24h': rainfall_24h,
#                 'flood_stage': flood_stage,
#                 'alarm_stage': alarm_stage,
#                 'flood_probability': flood_prob,
#                 'predicted_level': predicted_level,
#                 'model_name': model_name,
#                 'status': status,
#                 'last_measurement': last_measurement,
#                 'historical_df': combined_df
#             })
            
#         except Exception:
#             continue
    
#     return pd.DataFrame(stations_data)

# def create_network_map(df: pd.DataFrame) -> folium.Map:
#     """Create Folium map with all stations colored by status (MRC style)"""
#     center_lat = df['latitude'].mean() if not df.empty else 15.0
#     center_lon = df['longitude'].mean() if not df.empty else 105.0
    
#     m = folium.Map(location=[center_lat, center_lon], zoom_start=6, tiles='cartodbpositron')
    
#     # MRC color scheme
#     status_colors = {
#         'FLOOD': 'red',
#         'ALARM': 'orange', 
#         'NORMAL': 'green',
#         'NODATA': 'gray'
#     }
    
#     for _, row in df.iterrows():
#         status = row['status']
#         color = status_colors.get(status, 'blue')
#         is_critical = status in ['FLOOD', 'ALARM']
        
#         # Format date for popup
#         last_meas = row.get('last_measurement', None)
#         if pd.notna(last_meas) and last_meas:
#             try:
#                 dt = pd.to_datetime(last_meas)
#                 time_str = dt.strftime('%Y-%m-%d %H:%M')
#             except:
#                 time_str = str(last_meas)[:16]
#         else:
#             time_str = "N/A"
        
#         popup_html = f"""
#         <b>{row['name']}</b><br>
#         Water Level: {row['water_level']:.2f} m<br>
#         Rainfall: {row['rainfall_24h']:.1f} mm<br>
#         Status: <span style="color:{color}; font-weight:bold;">{status}</span><br>
#         Last Update: {time_str}
#         """
        
#         folium.CircleMarker(
#             location=[row['latitude'], row['longitude']],
#             radius=10 if is_critical else 7,
#             popup=folium.Popup(popup_html, max_width=250),
#             color=color,
#             fill=True,
#             fillColor=color,
#             fillOpacity=0.7 if is_critical else 0.5,
#             weight=2
#         ).add_to(m)
    
#     return m

# # =============================================================================
# # ✅ SỬA: create_14day_forecast_chart (thay thế create_7day_forecast_chart)
# # =============================================================================
# def create_14day_forecast_chart(
#     forecast_df: pd.DataFrame,
#     hist_df: pd.DataFrame,
#     station_name: str,
#     flood_stage: float,
#     alarm_stage: float = None,
#     T: Optional[pd.Timestamp] = None
# ) -> go.Figure:
#     """
#     Create 14-day forecast chart: T−7 → T+6
#     - Observe: days ≤ T (from hist_df)
#     - Forecast: days > T (from forecast_df)
#     """
#     fig = go.Figure()
    
#     # ===== 1. Observed data (≤ T) =====
#     observed_plot = pd.DataFrame()
#     avg_level = 0.0
    
#     if not hist_df.empty and 'date' in hist_df.columns:
#         hist_plot = hist_df.copy()
#         hist_plot['date'] = pd.to_datetime(hist_plot['date'])
#         hist_plot = hist_plot.drop_duplicates(subset=['date'], keep='last').sort_values('date')
        
#         value_col = 'value' if 'value' in hist_plot.columns else 'water_level'
        
#         if T is not None:
#             observed_plot = hist_plot[hist_plot['date'] <= T].tail(14)
#         else:
#             observed_plot = hist_plot.tail(14)
        
#         if not observed_plot.empty:
#             avg_level = observed_plot[value_col].mean()
#             fig.add_trace(
#                 go.Scatter(
#                     x=observed_plot['date'],
#                     y=observed_plot[value_col],
#                     mode='lines+markers',
#                     name='Observe (m)',
#                     line=dict(color='#1E88E5', width=2),
#                     marker=dict(size=6, symbol='circle')
#                 )
#             )
    
#     # ===== 2. Forecast lines (all 14 days, with future highlighted) =====
#     if not forecast_df.empty and 'date' in forecast_df.columns:
#         forecast_plot = forecast_df.copy()
#         forecast_plot['date'] = pd.to_datetime(forecast_plot['date'])
        
#         # Full forecast line (T−7 → T+6)
#         fig.add_trace(
#             go.Scatter(
#                 x=forecast_plot['date'],
#                 y=forecast_plot['best_model_prediction'],
#                 mode='lines+markers',
#                 name='Forecast - Best Model',
#                 line=dict(color='#FF9800', width=2, dash='dash'),
#                 marker=dict(size=5, symbol='diamond-open')
#             )
#         )
        
#         fig.add_trace(
#             go.Scatter(
#                 x=forecast_plot['date'],
#                 y=forecast_plot['stacking_prediction'],
#                 mode='lines+markers',
#                 name='Forecast - Stacking',
#                 line=dict(color='#9C27B0', width=2, dash='dot'),
#                 marker=dict(size=5, symbol='square-open')
#             )
#         )
        
#         # Highlight future (days > T) with solid markers
#         if T is not None:
#             future_data = forecast_plot[forecast_plot['date'] > T]
#             if not future_data.empty:
#                 fig.add_trace(
#                     go.Scatter(
#                         x=future_data['date'],
#                         y=future_data['best_model_prediction'],
#                         mode='markers',
#                         name='Best Model (Future)',
#                         marker=dict(size=8, symbol='diamond', color='#FF9800')
#                     )
#                 )
#                 fig.add_trace(
#                     go.Scatter(
#                         x=future_data['date'],
#                         y=future_data['stacking_prediction'],
#                         mode='markers',
#                         name='Stacking (Future)',
#                         marker=dict(size=8, symbol='square', color='#9C27B0')
#                     )
#                 )
    
#     # ===== 3. Threshold lines =====
#     if flood_stage and flood_stage > 0:
#         fig.add_hline(
#             y=flood_stage,
#             line_dash="dash",
#             line_color="red",
#             annotation_text=f"Flood Level: {flood_stage:.1f}m",
#             annotation_position="right"
#         )
    
#     if alarm_stage and alarm_stage > 0:
#         fig.add_hline(
#             y=alarm_stage,
#             line_dash="dash",
#             line_color="orange",
#             annotation_text=f"Alarm Level: {alarm_stage:.1f}m",
#             annotation_position="right"
#         )
    
#     if avg_level > 0:
#         fig.add_hline(
#             y=avg_level,
#             line_dash="dot",
#             line_color="gray",
#             annotation_text=f"Average: {avg_level:.2f}m",
#             annotation_position="left"
#         )
    
#     # ===== 4. Layout =====
#     title = f"📊 14-Day Forecast (T−7 → T+6): {station_name}"
#     if T is not None:
#         title += f" [T = {T.strftime('%Y-%m-%d')}]"
    
#     fig.update_layout(
#         title=title,
#         xaxis_title="Date",
#         yaxis_title="Water Level (m)",
#         legend=dict(
#             orientation="h",
#             yanchor="bottom",
#             y=1.02,
#             xanchor="center",
#             x=0.5,
#             font=dict(size=11)
#         ),
#         height=420,
#         margin=dict(l=50, r=50, t=100, b=70),
#         hovermode='x unified',
#         xaxis=dict(
#             range=[
#                 forecast_df['date'].min() if not forecast_df.empty else (T - timedelta(days=10)) if T else datetime.now() - timedelta(days=10),
#                 forecast_df['date'].max() if not forecast_df.empty else (T + timedelta(days=10)) if T else datetime.now() + timedelta(days=10)
#             ]
#         )
#     )
    
#     return fig
# def load_historical_yearly_data(station_name: str) -> pd.DataFrame:
#     """
#     Load historical data from train.csv AND test.csv for seasonal chart.
#     Returns DataFrame with date, water_level columns.
#     """
#     station_name_clean = station_name.replace(" ", "_").replace("'", "")
#     train_path = DATA_DIR / station_name_clean / "train.csv"
#     test_path = DATA_DIR / station_name_clean / "test.csv"
    
#     dfs = []
    
#     # Load train.csv (2000-2020)
#     if train_path.exists():
#         try:
#             df_train = pd.read_csv(train_path)
#             df_train['date'] = pd.to_datetime(df_train['date'])
#             dfs.append(df_train[['date', 'water_level']])
#         except Exception:
#             pass
    
#     # Load test.csv (2021-2025)
#     if test_path.exists():
#         try:
#             df_test = pd.read_csv(test_path)
#             df_test['date'] = pd.to_datetime(df_test['date'])
#             dfs.append(df_test[['date', 'water_level']])
#         except Exception:
#             pass
    
#     if dfs:
#         combined = pd.concat(dfs, ignore_index=True)
#         combined = combined.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
#         return combined
    
#     return pd.DataFrame()
# # Các hàm khác giữ nguyên: create_seasonal_chart, create_hydrograph, v.v.
# def create_seasonal_chart(station_name: str, flood_stage: float,
#                           forecast_df: pd.DataFrame = None,
#                           current_water_level: float = None) -> go.Figure:
#     """
#     Create seasonal water level chart like MRC style.
#     X-axis: Months (Nov -> Dec -> Jan -> ... -> Oct)
#     Each year/season is a separate colored line.
#     Shows: Min, Max, AVG, and current season with forecast.
    
#     Args:
#         station_name: Station name
#         flood_stage: Flood threshold level
#         forecast_df: DataFrame with 7-day forecast (optional)
#         current_water_level: Current water level from API
#     """
#     fig = go.Figure()
    
#     # Load historical data
#     hist_df = load_historical_yearly_data(station_name)
    
#     if hist_df.empty:
#         fig.add_annotation(
#             text="Không có dữ liệu lịch sử",
#             xref="paper", yref="paper",
#             x=0.5, y=0.5, showarrow=False
#         )
#         return fig
    
#     # Add year and month columns
#     hist_df['year'] = hist_df['date'].dt.year
#     hist_df['month'] = hist_df['date'].dt.month
#     hist_df['day'] = hist_df['date'].dt.day
    
#     # Create "season year" - flood season runs Nov to Oct
#     # Season 2020.21 = Nov 2020 to Oct 2021
#     hist_df['season_year'] = hist_df.apply(
#         lambda row: f"{row['year']}.{str(row['year']+1)[2:]}" if row['month'] >= 11 
#         else f"{row['year']-1}.{str(row['year'])[2:]}", axis=1
#     )
    
#     # Create day of season (Nov 1 = day 1, Oct 31 = day 365)
#     def get_season_day(row):
#         month, day = row['month'], row['day']
#         # Nov=1, Dec=2, Jan=3, Feb=4, Mar=5, Apr=6, May=7, Jun=8, Jul=9, Aug=10, Sep=11, Oct=12
#         month_order = {11: 0, 12: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10, 10: 11}
#         days_in_month = [30, 31, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31]  # Nov to Oct
#         cumulative_days = [sum(days_in_month[:i]) for i in range(12)]
#         return cumulative_days[month_order[month]] + day
    
#     hist_df['season_day'] = hist_df.apply(get_season_day, axis=1)
    
#     # Get unique seasons and sort
#     seasons = sorted(hist_df['season_year'].unique())
    
#     # Color palette for seasons
#     colors = [
#         '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7', 
#         '#DDA0DD', '#98D8C8', '#F7DC6F', '#BB8FCE', '#85C1E9',
#         '#F8B500', '#00CED1', '#FF69B4', '#32CD32', '#FF4500',
#         '#9370DB', '#20B2AA', '#FFD700', '#DC143C', '#00FA9A',
#         '#1E90FF', '#FF1493'
#     ]
    
#     # Calculate statistics per season_day
#     stats_df = hist_df.groupby('season_day')['water_level'].agg(['min', 'max', 'mean']).reset_index()
    
#     # Create x-axis labels (months)
#     month_labels = ['Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct']
#     month_positions = [1, 31, 62, 93, 121, 152, 182, 213, 243, 274, 305, 335]
    
#     # 1. Add Min line (orange)
#     fig.add_trace(
#         go.Scatter(
#             x=stats_df['season_day'],
#             y=stats_df['min'],
#             mode='lines',
#             name=f"Min: {stats_df['min'].min():.2f}",
#             line=dict(color='#FF9800', width=2),
#             hovertemplate='Min: %{y:.2f}m<extra></extra>'
#         )
#     )
    
#     # 2. Add Max line (red) 
#     fig.add_trace(
#         go.Scatter(
#             x=stats_df['season_day'],
#             y=stats_df['max'],
#             mode='lines',
#             name=f"Max: {stats_df['max'].max():.2f}",
#             line=dict(color='#E53935', width=2),
#             hovertemplate='Max: %{y:.2f}m<extra></extra>'
#         )
#     )
    
#     # 3. Add AVG line (purple/magenta)
#     avg_value = stats_df['mean'].mean()
#     fig.add_trace(
#         go.Scatter(
#             x=stats_df['season_day'],
#             y=stats_df['mean'],
#             mode='lines',
#             name=f"AVG: {avg_value:.2f}",
#             line=dict(color='#9C27B0', width=2),
#             hovertemplate='AVG: %{y:.2f}m<extra></extra>'
#         )
#     )
    
#     # 4. Add each season as a separate line (last 10 seasons)
#     recent_seasons = seasons[-10:] if len(seasons) > 10 else seasons
    
#     for i, season in enumerate(recent_seasons):
#         season_data = hist_df[hist_df['season_year'] == season].sort_values('season_day')
#         if not season_data.empty:
#             peak_value = season_data['water_level'].max()
#             color = colors[i % len(colors)]
            
#             fig.add_trace(
#                 go.Scatter(
#                     x=season_data['season_day'],
#                     y=season_data['water_level'],
#                     mode='lines',
#                     name=f"{season}: {peak_value:.2f}",
#                     line=dict(color=color, width=1.5),
#                     opacity=0.7,
#                     hovertemplate=f'{season}: %{{y:.2f}}m<extra></extra>'
#                 )
#             )
    
#     # 5. Add current season (2024.25 or 2025.26) with thicker line
#     current_date = datetime.now()
#     if current_date.month >= 11:
#         current_season = f"{current_date.year}.{str(current_date.year+1)[2:]}"
#     else:
#         current_season = f"{current_date.year-1}.{str(current_date.year)[2:]}"
    
#     current_season_data = hist_df[hist_df['season_year'] == current_season].sort_values('season_day')
    
#     if not current_season_data.empty:
#         peak_value = current_season_data['water_level'].max()
#         fig.add_trace(
#             go.Scatter(
#                 x=current_season_data['season_day'],
#                 y=current_season_data['water_level'],
#                 mode='lines',
#                 name=f"{current_season}: {peak_value:.2f} (Current)",
#                 line=dict(color='#2196F3', width=3),
#                 hovertemplate=f'{current_season} (Current): %{{y:.2f}}m<extra></extra>'
#             )
#         )
    
#     # 6. Add 7-day forecast (continuing from last observed point)
#     if forecast_df is not None and not forecast_df.empty:
#         forecast_plot = forecast_df.copy()
#         forecast_plot['date'] = pd.to_datetime(forecast_plot['date'])
#         forecast_plot['month'] = forecast_plot['date'].dt.month
#         forecast_plot['day'] = forecast_plot['date'].dt.day
#         forecast_plot['season_day'] = forecast_plot.apply(get_season_day, axis=1)
        
#         # Best Model Forecast
#         fig.add_trace(
#             go.Scatter(
#                 x=forecast_plot['season_day'],
#                 y=forecast_plot['best_model_prediction'],
#                 mode='lines+markers',
#                 name='Forecast (Best)',
#                 line=dict(color='#FF9800', width=2, dash='dash'),
#                 marker=dict(size=6, symbol='diamond'),
#                 hovertemplate='Forecast Best: %{y:.2f}m<extra></extra>'
#             )
#         )
        
#         # Stacking Forecast
#         fig.add_trace(
#             go.Scatter(
#                 x=forecast_plot['season_day'],
#                 y=forecast_plot['stacking_prediction'],
#                 mode='lines+markers',
#                 name='Forecast (Stacking)',
#                 line=dict(color='#9C27B0', width=2, dash='dot'),
#                 marker=dict(size=6, symbol='square'),
#                 hovertemplate='Forecast Stacking: %{y:.2f}m<extra></extra>'
#             )
#         )
    
#     # 7. Add flood stage line
#     if flood_stage and flood_stage > 0:
#         fig.add_hline(
#             y=flood_stage,
#             line_dash="dash",
#             line_color="red",
#             annotation_text=f"Flood: {flood_stage:.1f}m",
#             annotation_position="right"
#         )
    
#     # Update layout
#     fig.update_layout(
#         title=f"📊 Observed Water Level This Season at {station_name}",
#         xaxis_title="",
#         yaxis_title="Water Level (m)",
#         xaxis=dict(
#             tickmode='array',
#             tickvals=month_positions,
#             ticktext=month_labels,
#             range=[1, 365]
#         ),
#         legend=dict(
#             orientation="h",
#             yanchor="top",
#             y=-0.15,
#             xanchor="center",
#             x=0.5,
#             font=dict(size=10)
#         ),
#         height=500,
#         margin=dict(l=50, r=50, t=80, b=120),
#         hovermode='x unified'
#     )
    
#     return fig

# def create_hydrograph(hist_df: pd.DataFrame, station_name: str,
#                       flood_stage: float, rainfall_24h: float,
#                       forecast_df: pd.DataFrame = None) -> go.Figure:
#     """Create hydrograph with water level, 7-day forecast, threshold, and rainfall"""
    
#     fig = make_subplots(specs=[[{"secondary_y": True}]])
    
#     if not hist_df.empty and 'date' in hist_df.columns:
#         df_plot = hist_df.copy()
#         df_plot['date'] = pd.to_datetime(df_plot['date'])
        
#         # Remove duplicate dates - keep the last occurrence
#         df_plot = df_plot.drop_duplicates(subset=['date'], keep='last')
#         df_plot = df_plot.sort_values('date').tail(7)
        
#         value_col = 'value' if 'value' in df_plot.columns else 'water_level'
        
#         # 1. Historical Water Level (Observed) - Blue solid line
#         fig.add_trace(
#             go.Scatter(
#                 x=df_plot['date'],
#                 y=df_plot[value_col],
#                 mode='lines+markers',
#                 name='Observed',
#                 line=dict(color='#1E88E5', width=3),
#                 marker=dict(size=8)
#             ),
#             secondary_y=False
#         )
        
#         # 2. 7-Day Forecast from forecast CSV
#         if forecast_df is not None and not forecast_df.empty:
#             forecast_plot = forecast_df.copy()
#             forecast_plot['date'] = pd.to_datetime(forecast_plot['date'])
            
#             # Best Model Forecast - Orange dashed line
#             fig.add_trace(
#                 go.Scatter(
#                     x=forecast_plot['date'],
#                     y=forecast_plot['best_model_prediction'],
#                     mode='lines+markers',
#                     name='Forecast (Best)',
#                     line=dict(color='#FF9800', width=2, dash='dash'),
#                     marker=dict(size=6, symbol='diamond')
#                 ),
#                 secondary_y=False
#             )
            
#             # Stacking Forecast - Purple dotted line
#             fig.add_trace(
#                 go.Scatter(
#                     x=forecast_plot['date'],
#                     y=forecast_plot['stacking_prediction'],
#                     mode='lines+markers',
#                     name='Forecast (Stacking)',
#                     line=dict(color='#9C27B0', width=2, dash='dot'),
#                     marker=dict(size=6, symbol='square')
#                 ),
#                 secondary_y=False
#             )
        
#         # 3. Flood Stage threshold line - Red dashed
#         if flood_stage and flood_stage > 0:
#             fig.add_hline(
#                 y=flood_stage,
#                 line_dash="dash",
#                 line_color="red",
#                 annotation_text=f"Flood Stage: {flood_stage:.1f}m",
#                 secondary_y=False
#             )
        
#         # 4. Rainfall bars (simulated for last 7 days)
#         rain_values = np.random.exponential(rainfall_24h/3 + 1, size=len(df_plot))
#         rain_values[-1] = rainfall_24h  # Today's actual
        
#         fig.add_trace(
#             go.Bar(
#                 x=df_plot['date'],
#                 y=rain_values,
#                 name='Rainfall (mm)',
#                 marker_color='rgba(100, 181, 246, 0.5)',
#                 yaxis='y2'
#             ),
#             secondary_y=True
#         )
    
#     fig.update_layout(
#         title=f"📈 7-Day Hydrograph: {station_name}",
#         xaxis_title="Date",
#         legend=dict(orientation="h", yanchor="bottom", y=1.02),
#         height=350,
#         margin=dict(l=50, r=50, t=80, b=50),
#         hovermode='x unified'
#     )
    
#     fig.update_yaxes(title_text="Water Level (m)", secondary_y=False)
#     fig.update_yaxes(title_text="Rainfall (mm)", secondary_y=True)
    
#     return fig

# # =============================================================================
# # MAIN APP
# # =============================================================================
# def main():
#     metadata_df = load_metadata()
#     station_models = load_all_station_models()
#     performance_df = load_station_performance()
    
#     if metadata_df.empty:
#         st.error("⚠️ Station metadata not found!")
#         return
    
#     metadata_hash = str(hash(tuple(metadata_df['stationId'].tolist())))
    
#     # =========================================================================
#     # SIDEBAR
#     # =========================================================================
#     with st.sidebar:
#         st.markdown("## 🌊 Mekong Forecast")
#         st.divider()
        
#         with st.spinner("Loading data..."):
#             df_all = fetch_all_stations_data(metadata_hash)
#             if df_all.empty:
#                 st.error("No data available!")
#                 return
        
#         st.session_state.last_updated = datetime.now()
        
#         station_names = df_all['name'].tolist()
#         default_idx = station_names.index('Tan Chau') if 'Tan Chau' in station_names else 0
#         selected_station = st.selectbox(
#             "📍 Select Station",
#             options=station_names,
#             index=default_idx
#         )
        
#         st.divider()
#         if st.button("🔄 Refresh Data", type="primary", use_container_width=True):
#             fetch_all_stations_data.clear()
#             st.rerun()
        
#         has_new_data, new_data_msg = check_new_data_available(df_all)
#         st.divider()
#         st.markdown("### 🔮 Forecast Update")
#         if has_new_data:
#             st.warning(f"⚠️ {new_data_msg}")
#             if st.button("🔄 Cập nhật Forecast", type="secondary", use_container_width=True):
#                 st.info("⏳ Đang chạy forecast... Vui lòng chạy notebook train3.ipynb (Cell 2) để cập nhật.")
#         else:
#             st.success(f"✅ {new_data_msg}")
        
#         st.divider()
#         st.markdown("### ℹ️ System Info")
#         if st.session_state.last_updated:
#             st.markdown(f"**Last Updated:**\n{st.session_state.last_updated.strftime('%H:%M:%S')}")
        
#         n_models_loaded = len(station_models)
#         if n_models_loaded > 0:
#             st.markdown(f"**Models Loaded:** ✅ {n_models_loaded} stations")
#         else:
#             st.markdown("**Models:** ❌ Not Found")
        
#         n_flood = len(df_all[df_all['status'] == 'FLOOD'])
#         n_alarm = len(df_all[df_all['status'] == 'ALARM'])
#         n_normal = len(df_all[df_all['status'] == 'NORMAL'])
#         n_nodata = len(df_all[df_all['status'] == 'NODATA'])
#         st.markdown(f"**Stations:** {len(df_all)} total")
#         if n_flood > 0:
#             st.markdown(f"- 🔴 Flood: {n_flood}")
#         if n_alarm > 0:
#             st.markdown(f"- 🟠 Alarm: {n_alarm}")
#         st.markdown(f"- 🟢 Normal: {n_normal}")
#         if n_nodata > 0:
#             st.markdown(f"- ⬛ No Data: {n_nodata}")
    
#     # =========================================================================
#     # MAIN DASHBOARD
#     # =========================================================================
#     st.markdown("# 🌊 Mekong River Flood Forecasting")
#     st.markdown("Real-time monitoring and ML-powered predictions for the Mekong Basin")
    
#     st.markdown("## 📡 Network Overview")
#     with st.container():
#         col_map, col_table = st.columns([0.65, 0.35])
#         with col_map:
#             network_map = create_network_map(df_all)
#             st_folium(network_map, width=None, height=450, use_container_width=True)
#         with col_table:
#             st.markdown("### 📋 Alert Table")
#             df_display = df_all[['name', 'water_level', 'last_measurement', 'status']].copy()
#             def format_date(ts):
#                 if pd.isna(ts) or ts is None:
#                     return "N/A"
#                 try:
#                     dt = pd.to_datetime(ts)
#                     return dt.strftime('%Y-%m-%d %H:%M')
#                 except:
#                     return str(ts)[:16] if ts else "N/A"
#             df_display['last_measurement'] = df_display['last_measurement'].apply(format_date)
#             df_display.columns = ['Station', 'Water Level (m)', 'Date/Time', 'Status']
#             df_display['Water Level (m)'] = df_display['Water Level (m)'].round(2)
#             status_order = {'FLOOD': 0, 'ALARM': 1, 'NORMAL': 2, 'NODATA': 3}
#             df_display['_sort'] = df_display['Status'].map(lambda x: status_order.get(x, 4))
#             df_display = df_display.sort_values('_sort').drop(columns=['_sort'])
#             st.dataframe(df_display, use_container_width=True, hide_index=True, height=400)
    
#     st.divider()
#     station_row = df_all[df_all['name'] == selected_station].iloc[0]
#     st.markdown(f"## 🔍 Analysis for: **{selected_station}**")
    
#     # Row 1: KPIs — giữ nguyên
#     kpi1, kpi2, kpi3 = st.columns(3)
#     # ... giữ nguyên ...
    
#     # Row 1.5: Model Accuracy — giữ nguyên
#     st.markdown("---")
#     # ... giữ nguyên ...
    
#     # Row 2: Seasonal Chart — giữ nguyên
#     st.markdown("---")
#     st.markdown("### 📊 Observed Water Level This Season")
#     hist_df = station_row.get('historical_df')
    
#     # ✅ SỬA: Lấy T và load forecast với T
#     T = None
#     last_meas = station_row.get('last_measurement')
#     if pd.notna(last_meas) and last_meas:
#         try:
#             T = pd.to_datetime(last_meas)
#         except:
#             T = None
    
#     forecast_df = load_station_forecast(selected_station, T=T)
    
#     fig_seasonal = create_seasonal_chart(
#         station_name=selected_station,
#         flood_stage=station_row['flood_stage'],
#         forecast_df=forecast_df,
#         current_water_level=station_row['water_level']
#     )
#     st.plotly_chart(fig_seasonal, use_container_width=True)
    
#     # Row 3: ✅ SỬA: 14-Day Forecast Chart
#     st.markdown("---")
#     st.markdown("### 🔮 14-Day Forecast Detail (T−7 → T+6)")
    
#     if not forecast_df.empty:
#         fig_forecast = create_14day_forecast_chart(
#             forecast_df=forecast_df,
#             hist_df=hist_df if hist_df is not None else pd.DataFrame(),
#             station_name=selected_station,
#             flood_stage=station_row['flood_stage'],
#             alarm_stage=station_row.get('alarm_stage', None),
#             T=T
#         )
#         st.plotly_chart(fig_forecast, use_container_width=True)
        
#         with st.expander("📋 Chi tiết dự báo 14 ngày", expanded=False):
#             display_forecast = forecast_df[['date', 'day', 'days_from_T',
#                                           'best_model_prediction', 'stacking_prediction',
#                                           'best_model_status', 'stacking_status']].copy()
#             display_forecast['date'] = pd.to_datetime(display_forecast['date'])
#             display_forecast = display_forecast.sort_values('date').drop_duplicates(subset=['date'], keep='last')
#             display_forecast['date'] = display_forecast['date'].dt.strftime('%Y-%m-%d')
#             display_forecast.columns = ['Ngày', 'Day', 'Days from T',
#                                       'Best Model (m)', 'Stacking (m)',
#                                       'Status (Best)', 'Status (Stack)']
#             display_forecast['Best Model (m)'] = display_forecast['Best Model (m)'].round(3)
#             display_forecast['Stacking (m)'] = display_forecast['Stacking (m)'].round(3)
#             st.dataframe(display_forecast, use_container_width=True, hide_index=True)
#     else:
#         st.info("📊 Chưa có dữ liệu dự báo 14 ngày. Vui lòng chạy notebook train3.ipynb để tạo forecast.")
    
#     st.divider()
#     model_info_str = f"{len(station_models)} station-specific regressors" if station_models else "Fallback mode"
#     st.markdown(
#         f"<div style='text-align: center; color: #888; font-size: 0.9em;'>"
#         f"🌊 Mekong Flood Forecasting System v3.0.1 | "
#         f"Data refreshes every {CACHE_TTL_SECONDS//60} minutes | "
#         f"ML Models: {model_info_str}"
#         f"</div>",
#         unsafe_allow_html=True
#     )

# if __name__ == "__main__":
#     main()


# ==============================================================================
# 🌊 MEKONG FLOOD FORECASTING DASHBOARD — PHẦN 1: SETUP CƠ BẢN
# ==============================================================================
import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
import requests
import time
import json
from datetime import datetime, timedelta
from typing import Dict, Optional
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import plotly.graph_objects as go
from plotly.subplots import make_subplots
# ==============================================================================
# PAGE CONFIG
# ==============================================================================
st.set_page_config(
    page_title="🌊 Mekong Flood Forecast",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==============================================================================
# CONFIGURATION PATHS
# ==============================================================================
BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "models"
REGRESSION_DIR = MODELS_DIR / "regression"
SCALERS_DIR = MODELS_DIR / "scalers"

DATA_DIR = BASE_DIR / "data"
METADATA_PATH = BASE_DIR / "station_metadata_master.csv"

TIME_SERIES_JSON = Path("E:\\HK1N3\\KHDL 2\\KHDL\\timeSeriesList_from_md.json")
BASE_DATA_DIR = Path(r"E:\HK1N3\KHDL 2\KHDL\data")
FORECAST_DIR = Path(r"E:\HK1N3\KHDL 2\KHDL\models\forecasts")
# FORECAST_DIR.mkdir(parents=True, exist_ok=True)

# ==============================================================================
# API CONFIGURATION
# ==============================================================================
MRC_API_URL = "https://api.mrcmekong.org/api/v1/time-series/telemetry/recent/stations"
# MRC_HEADERS = {
#     'accept': 'application/json, text/plain, */*',
#     'accept-language': 'en-US,en;q=0.9,vi-VN;q=0.8,vi;q=0.7',
#     'origin': 'https://monitoring.mrcmekong.org',
#     'referer': 'https://monitoring.mrcmekong.org/',
#     'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
#     'sec-ch-ua-mobile': '?0',
#     'sec-ch-ua-platform': '"Windows"',
#     'sec-fetch-dest': 'empty',
#     'sec-fetch-mode': 'cors',
#     'sec-fetch-site': 'same-site',
#     'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
# }

MRC_HEADERS = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'en-US,en;q=0.9,vi-VN;q=0.8,vi;q=0.7',
    'origin': 'https://monitoring.mrcmekong.org',
    'referer': 'https://monitoring.mrcmekong.org/',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'authorization': 'Bearer eyJhbGciOiJIUzUxMiJ9.eyJzdWIiOiJtZWl0aHV5IiwiZXhwIjoxNzY4NDg2ODA3LCJhdXRoIjoiUk9MRV9SRVNFQVJDSCBST0xFX1VTRVIiLCJpYXQiOjE3NjU4OTQ4MDd9.cDR-9Bj7ujWdNAHY40qOn7f_S_lGWq9Quq6FfuKa-ChXBMuAPrNqP_UJZ10nJVqrqCoVTtQDdqhZfzrR4N0Mig'
}

CACHE_TTL_SECONDS = 3600  # 1 giờ
# Tạo thư mục nếu chưa tồn tại
for dir_path in [MODELS_DIR, REGRESSION_DIR, SCALERS_DIR, FORECAST_DIR, DATA_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# ==============================================================================
# HELPER: LOAD METADATA
# ==============================================================================
def get_latest_forecast_file(station_name: str) -> Optional[Path]:
    """Tìm file forecast mới nhất theo định dạng: {station}_forecast_YYYYMMDD_vXXX.csv"""
    pattern = f"{station_name.replace(' ', '_')}_forecast_*.csv"
    candidates = list(FORECAST_DIR.glob(pattern))
    if not candidates:
        st.warning(f"⚠️ Không tìm thấy file forecast cho {station_name} trong {FORECAST_DIR}")
        return None
    # Sắp xếp theo ngày và version
    candidates.sort(key=lambda p: (p.stem.split('_')[-2], p.stem.split('_v')[-1]))
    return candidates[-1]
@st.cache_resource
def load_metadata() -> pd.DataFrame:
    """Load station metadata from CSV"""
    if METADATA_PATH.exists():
        df = pd.read_csv(METADATA_PATH)

        
    else:
        # Fallback: tạo DataFrame mẫu nếu thiếu file
        return pd.DataFrame({
            'stationId': [101, 102, 103],
            'name': ['Tan Chau', 'Chau Doc', 'Can Tho'],
            'latitude': [10.522, 10.708, 10.035],
            'longitude': [105.467, 105.128, 105.769],
            'floodStage': [4.5, 4.2, 2.2],
            'alarmStage': [4.0, 3.8, 1.9]
        })
    code_map = load_station_code_map()
    df["api_id"] = df["name"].astype(str).map(code_map)
    # Điền mặc định nếu thiếu (dùng stationId nếu có)
    if "stationId" in df.columns:
        df["api_id"] = df["api_id"].fillna(
            df["stationId"].astype(str).str.zfill(6)
        )
    df["api_id"] = df["api_id"].fillna("000000")

    return df


@st.cache_resource
def load_station_code_map() -> dict:
    """Tạo ánh xạ stationName → stationCode từ JSON"""
    if not TIME_SERIES_JSON.exists():
        st.warning(f"⚠️ Không tìm thấy file station code: {TIME_SERIES_JSON}")
        return {}
    
    try:
        with open(TIME_SERIES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        code_map = {}
        for item in data:
            name = str(item.get("stationName", "")).strip()
            code = str(item.get("stationCode", "")).strip().zfill(6)
            if name and code:
                code_map[name] = code
        return code_map
    except Exception as e:
        st.warning(f"⚠️ Lỗi đọc station code map: {e}")
        return {}

# ==============================================================================
# MAIN APP — PHẦN 1: KHỞI ĐỘNG
# ==============================================================================
# ==============================================================================
# CACHED FUNCTION: FETCH REAL-TIME DATA
# ==============================================================================
# ==============================================================================
# CACHED FUNCTION: FETCH REAL-TIME DATA (PHIÊN BẢN 2 - HỖN HỢP, AN TOÀN)
# ==============================================================================
@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_mrc_data(_metadata_hash: str) -> pd.DataFrame:
    """Fetch and process real-time data from MRC API with hybrid parsing and safe NaN handling"""
    metadata_df = load_metadata()
    
    try:
        with st.spinner("📡 Đang lấy dữ liệu từ MRC API..."):
            response = requests.get(
                MRC_API_URL,
                headers=MRC_HEADERS,
                timeout=(15, 30)  # (connect timeout, read timeout) = 15s connect, 30s read
            )
            response.raise_for_status()
            api_data = response.json()
            
            if not isinstance(api_data, list):
                raise ValueError("API response not a list")
            
            stations = []
            
            for item in api_data:
                if not isinstance(item, dict):
                    continue
                
                # 🔹 Bước 1: Lấy tên trạm
                station_name = str(item.get("name", "")).strip()
                if not station_name:
                    continue
                
                # 🔹 Bước 2: Tìm metadata — khớp tên không phân biệt hoa thường, khoảng trắng
                meta_match = metadata_df[
                    metadata_df["name"].astype(str).str.strip().str.lower() == station_name.lower()
                ]
                
                # 🔹 Bước 3: Lấy floodStage, alarmStage — giữ nguyên NaN nếu không có
                flood_stage_raw = meta_match["floodStage"].iloc[0] if not meta_match.empty else np.nan
                alarm_stage_raw = meta_match["alarmStage"].iloc[0] if not meta_match.empty else np.nan
                
                # Chuẩn bị hiển thị
                flood_stage_disp = "—" if pd.isna(flood_stage_raw) else f"{flood_stage_raw:.1f}"
                alarm_stage_disp = "—" if pd.isna(alarm_stage_raw) else f"{alarm_stage_raw:.1f}"
                # 🔹 Bước 4: Trích xuất water_level — ƯU TIÊN waterLevel, fallback telemetry
                water_level = None
                last_measurement = None
                
                # 4a. Thử waterLevel trực tiếp (API mới)
                wl_val = item.get("waterLevel")
                rain_val = item.get("rainFall")  # ✅ LẤY MƯA
                if wl_val is not None and not (isinstance(wl_val, str) and wl_val.lower() == "na"):
                    try:
                        water_level = float(wl_val)
                        rainfall = float(rain_val) if rain_val is not None else 0.0

                        last_measurement = item.get("lastMeasurement") or item.get("last_measurement")
                    except (ValueError, TypeError):
                        pass
                
                # 4b. Fallback: telemetry (API cũ)
                if water_level is None:
                    telemetry = item.get("telemetry", [])
                    if isinstance(telemetry, list):
                        wl_points = [
                            pt for pt in telemetry
                            if isinstance(pt, dict)
                            and pt.get("parameter") == "water_level"
                            and pt.get("value") is not None
                            and not (isinstance(pt.get("value"), str) and pt["value"].lower() == "na")
                        ]
                        if wl_points:
                            wl_points.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
                            latest = wl_points[0]
                            try:
                                water_level = float(latest["value"])
                                last_measurement = latest.get("timestamp")
                            except (ValueError, TypeError, KeyError):
                                pass
                
                # 🔹 Bước 5: Xác định trạng thái — chỉ cảnh báo nếu có ngưỡng
                status = "NODATA"
                if water_level is not None:
                    if not pd.isna(flood_stage_raw) and water_level >= flood_stage_raw:
                        status = "FLOOD"
                    elif not pd.isna(alarm_stage_raw) and water_level >= alarm_stage_raw:
                        status = "ALARM"
                    else:
                        status = "NORMAL"
                
                # 🔹 Bước 6: Thêm vào danh sách
                stations.append({
                    "stationId": int(meta_match["stationId"].iloc[0]) if not meta_match.empty else 0,
                    "name": station_name,
                    "latitude": float(meta_match["latitude"].iloc[0]) if not meta_match.empty else 0.0,
                    "longitude": float(meta_match["longitude"].iloc[0]) if not meta_match.empty else 0.0,
                    "water_level": water_level if water_level is not None else np.nan,
                    "rainfall": rainfall if 'rainfall' in locals() else 0.0,  # ✅ THÊM MƯA
                    "last_measurement": last_measurement,
                    "status": status,
                    "flood_stage": flood_stage_raw,          # giữ nguyên float/NaN
                    "alarm_stage": alarm_stage_raw,          # giữ nguyên float/NaN
                    "flood_stage_disp": flood_stage_disp,    # dùng để hiển thị
                    "alarm_stage_disp": alarm_stage_disp,    # dùng để hiển thị
                    "source": "API"
                })
            
            df = pd.DataFrame(stations)
            df["last_updated"] = datetime.now()
            return df
            
    except Exception as e:
        st.warning(f"⚠️ Lỗi gọi API MRC: {str(e)[:80]} → Dùng dữ liệu mẫu với cảnh báo rõ ràng")
        
        # 🔹 Fallback: chỉ dùng metadata, không đoán ngưỡng
        fallback_data = []
        for _, row in metadata_df.iterrows():
            station_name = str(row["name"]).strip()
            if not station_name:
                continue
                
            flood_stage_raw = row["floodStage"]
            alarm_stage_raw = row["alarmStage"]
            
            # DÙNG NaN — không điền giá trị
            fallback_data.append({
                "stationId": row["stationId"],
                "name": station_name,
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "water_level": np.nan,
                "last_measurement": None,
                "status": "NODATA",
                "flood_stage": flood_stage_raw,
                "alarm_stage": alarm_stage_raw,
                "flood_stage_disp": "Không có ngưỡng" if pd.isna(flood_stage_raw) else flood_stage_raw,
                "alarm_stage_disp": "Không có ngưỡng" if pd.isna(alarm_stage_raw) else alarm_stage_raw,
                "source": "Fallback (Metadata Only)"
            })
        
        df = pd.DataFrame(fallback_data)
        df["last_updated"] = datetime.now()
        return df

# @st.cache_data(ttl=1800, show_spinner=False)  # cache 30 phút
# def fetch_detailed_timeseries(station_name: str, days: int = 30) -> pd.DataFrame:
#     """Lấy dữ liệu 15 phút trong N ngày qua cho trạm"""
#     try:
#         # API mới của MRC hỗ trợ timeseries
#         url = f"https://api.mrcmekong.org/api/v1/time-series/station/{station_name}/recent"
#         params = {"days": days}
#         response = requests.get(url, headers=MRC_HEADERS, timeout=(10, 20))
#         response.raise_for_status()
#         data = response.json()
        
#         if not isinstance(data, list):
#             return pd.DataFrame()
        
#         records = []
#         for pt in data:
#             if pt.get("parameter") in ["water_level", "rainfall"] and pt.get("value") is not None:
#                 records.append({
#                     "timestamp": pt["timestamp"],
#                     "parameter": pt["parameter"],
#                     "value": float(pt["value"])
#                 })
        
#         if not records:
#             return pd.DataFrame()
        
#         df = pd.DataFrame(records)
#         df["timestamp"] = pd.to_datetime(df["timestamp"])
        
#         # Pivot sang dạng wide
#         wide = df.pivot_table(
#             index="timestamp",
#             columns="parameter",
#             values="value",
#             aggfunc="last"
#         ).reset_index()
        
#         # Đảm bảo đủ cột
#         for col in ["water_level", "rainfall"]:
#             if col not in wide.columns:
#                 wide[col] = np.nan
        
#         return wide[["timestamp", "water_level", "rainfall"]].sort_values("timestamp")
        
#     except Exception as e:
#         st.warning(f"⚠️ Không tải được dữ liệu chi tiết cho {station_name}: {e}")
#         return pd.DataFrame()

@st.cache_data(ttl=900, show_spinner=False)
def fetch_15min_data(station_id: str, station_name: str) -> pd.DataFrame:
    """Lấy dữ liệu 15 phút từ API MRC (đã hỗ trợ Bearer token)"""
    try:
        url = f"https://api.mrcmekong.org/api/v1/time-series/telemetry/recent/measurement/{station_id}"
        headers = {
            "origin": "https://monitoring.mrcmekong.org",
            "referer": "https://monitoring.mrcmekong.org/",
            "authorization": MRC_HEADERS["authorization"]  # ✅ DÙNG TOKEN
        }
        response = requests.get(url, headers=headers, timeout=(10, 20))
        response.raise_for_status()
        
        # Xử lý: đôi khi API trả về chuỗi JSON thay vì dict
        data = response.json() if response.headers.get("content-type", "").startswith("application/json") else json.loads(response.text)
        
        measurements = data.get("measurements", [])
        if not isinstance(measurements, list):
            st.warning(f"⚠️ measurements không phải list: {type(measurements)}")
            return pd.DataFrame()
        
        records = []
        for pt in measurements:
            if not isinstance(pt, dict):
                continue
            ts = pt.get("d")
            w = pt.get("w")
            r = pt.get("r", 0.0)
            if ts and w is not None:
                try:
                    records.append({
                        "timestamp": pd.to_datetime(ts),
                        "water_level": float(w),
                        "rainfall": float(r) if r is not None else 0.0
                    })
                except (ValueError, TypeError):
                    continue
        
        df = pd.DataFrame(records)
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df
        
    except Exception as e:
        st.warning(f"⚠️ Không tải được dữ liệu 15 phút cho {station_name}: {e}")
        return pd.DataFrame()

# ==============================================================================
# HELPER: CREATE NETWORK MAP
# ==============================================================================
def create_network_map(df: pd.DataFrame) -> folium.Map:
    """Create interactive Folium map with station markers"""
    if df.empty:
        # Bản đồ mặc định nếu không có dữ liệu
        m = folium.Map(
            location=[13.5, 105.0],  # Trung tâm Mekong
            zoom_start=6,
            tiles="CartoDB positron"
        )
        folium.Marker(
            [13.5, 105.0],
            popup="⚠️ Không có dữ liệu trạm",
            icon=folium.Icon(color="gray", icon="exclamation-triangle", prefix="fa")
        ).add_to(m)
        return m
    
    # Xác định trung tâm bản đồ: trung bình có trọng số (bỏ qua NaN)
    valid_lat = df["latitude"].replace(0, np.nan).dropna()
    valid_lon = df["longitude"].replace(0, np.nan).dropna()
    
    center_lat = valid_lat.mean() if not valid_lat.empty else 13.5
    center_lon = valid_lon.mean() if not valid_lon.empty else 105.0
    
    # Tạo bản đồ
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=7,
        tiles="CartoDB positron",
        control_scale=True
    )
    
    # Marker cluster
    marker_cluster = MarkerCluster(name="Trạm").add_to(m)
    
    # Thêm marker
    for _, row in df.iterrows():
        # Chọn màu theo trạng thái
        color_map = {
            "FLOOD": "red",
            "ALARM": "orange",
            "NORMAL": "green",
            "NODATA": "lightgray"
        }
        color = color_map.get(row["status"], "blue")
        
        # Icon
        icon = folium.Icon(
            color=color,
            icon="tint",
            prefix="fa"
        )
        
        # Popup
        popup_html = f"""
        <div style="min-width:200px;">
        <h4><b>{row['name']}</b></h4>
        <hr style="margin:5px 0;">
        <table style="width:100%; font-size:14px;">
          <tr><td><b>Mực nước:</b></td><td>{row['water_level']:.2f} m</td></tr>
          <tr><td><b>Ngưỡng lũ:</b></td><td>{row['flood_stage_disp']}</td></tr>
          <tr><td><b>Ngưỡng báo động:</b></td><td>{row['alarm_stage_disp']}</td></tr>
          <tr><td><b>Trạng thái:</b></td><td><span style="color:{color}; font-weight:bold;">{row['status']}</span></td></tr>
          <tr><td><b>Cập nhật:</b></td><td>{row['last_measurement'] or '—'}</td></tr>
          <tr><td><b>Nguồn:</b></td><td>{row['source']}</td></tr>
        </table>
        </div>
        """
        
        # Xử lý tọa độ hợp lệ
        lat = row["latitude"]
        lon = row["longitude"]
        if pd.isna(lat) or pd.isna(lon) or lat == 0 or lon == 0:
            continue  # Bỏ qua trạm không có tọa độ
        
        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{row['name']} — {row['status']}",
            icon=icon
        ).add_to(marker_cluster)
    
    # Thêm legend
    legend_html = '''
    <div style="position: fixed; 
                bottom: 50px; left: 50px; width: 180px; height: auto; 
                background-color: white; border:2px solid grey; z-index:9999; 
                font-size:14px; padding:10px;">
    <h4><b>🟢 Trạng thái trạm</b></h4>
    <i class="fa fa-tint" style="color:red"></i> FLOOD<br>
    <i class="fa fa-tint" style="color:orange"></i> ALARM<br>
    <i class="fa fa-tint" style="color:green"></i> NORMAL<br>
    <i class="fa fa-tint" style="color:lightgray"></i> NODATA<br>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(legend_html))
    
    return m

def create_hydrograph_chart(
    station_name: str,
    df_all: pd.DataFrame,
    forecast_df: pd.DataFrame,
    historical_df: Optional[pd.DataFrame] = None
) -> go.Figure:
    """Tạo biểu đồ thủy văn: thực đo + dự báo 15 ngày"""
    today = pd.Timestamp.now().normalize()
    
    # Lấy thông tin trạm
    station_row = df_all[df_all["name"] == station_name].iloc[0] if not df_all.empty else None
    flood_stage = station_row["flood_stage"] if station_row is not None and not pd.isna(station_row.get("flood_stage")) else None
    alarm_stage = station_row["alarm_stage"] if station_row is not None and not pd.isna(station_row.get("alarm_stage")) else None
    
    fig = go.Figure()
    
    # ===== 1. Dữ liệu thực đo (nếu có) =====
    if historical_df is not None and not historical_df.empty:
        hist_plot = historical_df.copy()
        hist_plot = hist_plot.drop_duplicates(subset=["timestamp"], keep="last")
        hist_plot = hist_plot.sort_values("timestamp")
        
        # Lọc 60 ngày gần nhất
        cutoff = today - timedelta(days=60)
        hist_recent = hist_plot[hist_plot["timestamp"] >= cutoff]
        
        if not hist_recent.empty:
            fig.add_trace(go.Scatter(
                x=hist_recent["timestamp"],
                y=hist_recent["value"],
                mode="lines+markers",
                name="Thực đo",
                line=dict(color="#1E88E5", width=2),
                marker=dict(size=4)
            ))
    
    # ===== 2. Dự báo 15 ngày =====
    if not forecast_df.empty and "timestamp" in forecast_df.columns:
        # Chỉ lấy 15 ngày forecast
        forecast_plot = forecast_df.head(15).copy()
        forecast_plot["timestamp"] = pd.to_datetime(forecast_plot["timestamp"])
        
        # Dự báo
        fig.add_trace(go.Scatter(
            x=forecast_plot["timestamp"],
            y=forecast_plot["predicted_water_level"],
            mode="lines+markers",
            name="Dự báo",
            line=dict(color="#FF9800", width=3, dash="dash"),
            marker=dict(size=6, symbol="diamond")
        ))
        
        # Thay thế hoàn toàn fig.add_vline(...) bằng:
        fig.add_shape(
            type="line",
            x0=today,
            x1=today,
            y0=0,
            y1=1,
            xref="x",
            yref="paper",  # y từ 0 (dưới) đến 1 (trên) — không phụ thuộc vào trục y
            line=dict(color="gray", dash="dot", width=1),
            name="Hôm nay"
        )

        # Thêm annotation riêng
        fig.add_annotation(
            x=today,
            y=1.02,
            yref="paper",
            text="Hôm nay",
            showarrow=False,
            font=dict(size=10, color="gray"),
            xanchor="center"
        )
    
    # ===== 3. Các ngưỡng =====
    if flood_stage:
        fig.add_hline(
            y=flood_stage,
            line=dict(color="red", dash="dash", width=2),
            annotation_text=f"Lũ: {flood_stage:.1f}m",
            annotation_position="right"
        )
    if alarm_stage:
        fig.add_hline(
            y=alarm_stage,
            line=dict(color="orange", dash="dash", width=2),
            annotation_text=f"Báo động: {alarm_stage:.1f}m",
            annotation_position="right"
        )
    
    # ===== 4. Layout =====
    fig.update_layout(
        title=f"📈 Thủy văn: {station_name} (60 ngày thực đo + 15 ngày dự báo)",
        xaxis_title="Ngày",
        yaxis_title="Mực nước (m)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        height=400,
        hovermode="x unified",
        margin=dict(l=50, r=50, t=80, b=50)
    )
    
    return fig

def create_dual_axis_chart(
    station_name: str,
    timeseries_df: pd.DataFrame,
    flood_stage: Optional[float] = None,
    alarm_stage: Optional[float] = None
) -> go.Figure:
    """Biểu đồ 2 trục y: mực nước (trái) + mưa (phải)"""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    if timeseries_df.empty:
        # Dữ liệu mẫu nếu không có
        now = pd.Timestamp.now()
        dates = pd.date_range(end=now, periods=192, freq="15min")  # 2 ngày
        timeseries_df = pd.DataFrame({
            "timestamp": dates,
            "water_level": np.random.normal(3.0, 0.5, len(dates)),
            "rainfall": np.random.exponential(2.0, len(dates))
        })
    
    # ===== 1. MỰC NƯỚC (trục trái) =====
    fig.add_trace(
        go.Scatter(
            x=timeseries_df["timestamp"],
            y=timeseries_df["water_level"],
            mode="lines",
            name="Mực nước",
            line=dict(color="#1E88E5", width=2),
            hovertemplate="Mực nước: %{y:.2f} m<br>Thời gian: %{x}<extra></extra>"
        ),
        secondary_y=False
    )
    
    # ===== 2. MƯA (trục phải) =====
    fig.add_trace(
        go.Bar(
            x=timeseries_df["timestamp"],
            y=timeseries_df["rainfall"],
            name="Mưa (15 phút)",
            marker=dict(color="#64B5F6", opacity=0.7),
            hovertemplate="Mưa: %{y:.1f} mm/15p<br>Thời gian: %{x}<extra></extra>"
        ),
        secondary_y=True
    )
    
    # ===== 3. CÁC NGƯỠNG =====
    if flood_stage:
        fig.add_hline(
            y=flood_stage, line=dict(color="red", dash="dash", width=2),
            annotation_text=f"Lũ: {flood_stage:.1f}m",
            annotation_position="top right",
            secondary_y=False
        )
    if alarm_stage:
        fig.add_hline(
            y=alarm_stage, line=dict(color="orange", dash="dash", width=2),
            annotation_text=f"Báo động: {alarm_stage:.1f}m",
            annotation_position="bottom right",
            secondary_y=False
        )
    
    # ===== 4. LAYOUT =====
    fig.update_layout(
        title=f"📊 Dữ liệu thời gian thực: {station_name} (30 ngày, 15 phút/lần)",
        xaxis_title="Thời gian",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=450,
        hovermode="x unified"
    )
    
    fig.update_yaxes(title_text="Mực nước [m]", secondary_y=False, color="#1E88E5")
    fig.update_yaxes(title_text="Mưa [mm/15 phút]", secondary_y=True, color="#64B5F6")
    
    return fig

def create_hydrograph_with_observed(
    station_name: str,
    observed_df: pd.DataFrame,
    forecast_df: pd.DataFrame,
    flood_stage: Optional[float] = None,
    alarm_stage: Optional[float] = None
) -> go.Figure:
    """Biểu đồ thủy văn: Observe (7 ngày) + Forecast (7 ngày)"""
    fig = go.Figure()
    
    # ===== 1. DỮ LIỆU THỰC ĐO (7 ngày gần nhất) =====
    if not observed_df.empty:
        # Lọc 7 ngày qua
        observed_df["timestamp"] = pd.to_datetime(observed_df["timestamp"], utc=True)
        cutoff = pd.Timestamp.now(tz="UTC").normalize() - timedelta(days=7)
        recent_obs = observed_df[observed_df["timestamp"] >= cutoff]
        
        if not recent_obs.empty:
            fig.add_trace(go.Scatter(
                x=recent_obs["timestamp"],
                y=recent_obs["water_level"],
                mode="lines+markers",
                name="Observe (m)",
                line=dict(color="#1E88E5", width=2),
                marker=dict(size=4),
                hovertemplate="Thực đo: %{y:.2f} m<br>%{x}<extra></extra>"
            ))
    
    # ===== 2. DỰ BÁO (15 ngày: today−7 → today+7) — màu cam thống nhất =====
    if not forecast_df.empty and "timestamp" in forecast_df.columns:
        # Lấy toàn bộ 15 ngày (day=1 → 15)
        full_forecast = forecast_df[(forecast_df["day"] >= 1) & (forecast_df["day"] <= 15)].copy()
        
        if not full_forecast.empty:
            full_forecast["timestamp"] = pd.to_datetime(full_forecast["timestamp"])
            
            fig.add_trace(go.Scatter(
                x=full_forecast["timestamp"],
                y=full_forecast["predicted_water_level"],
                mode="lines+markers",
                name="Forecast (m)",
                line=dict(color="#FF9800", width=3, dash="dash"),
                marker=dict(size=6, symbol="diamond"),
                hovertemplate="Dự báo: %{y:.2f} m<br>%{x}<extra></extra>"
            ))
    
    # ===== 3. ĐƯỜNG NGƯỠNG =====
    if flood_stage:
        fig.add_hline(
            y=flood_stage,
            line=dict(color="red", dash="dash", width=2),
            annotation_text=f"Flood Level: {flood_stage:.1f}m",
            annotation_position="top right"
        )
    if alarm_stage:
        fig.add_hline(
            y=alarm_stage,
            line=dict(color="orange", dash="dash", width=2),
            annotation_text=f"Alarm Level: {alarm_stage:.1f}m",
            annotation_position="bottom right"
        )
    
    # ===== 4. ĐƯỜNG TRUNG BÌNH (nếu có dữ liệu lịch sử) =====
    if not observed_df.empty and len(observed_df) > 30:
        avg_level = observed_df["water_level"].mean()
        fig.add_hline(
            y=avg_level,
            line=dict(color="gray", dash="dot", width=1),
            annotation_text=f"Average: {avg_level:.1f}m",
            annotation_position="bottom left"
        )
    
    # ===== 5. LAYOUT =====
    fig.update_layout(
        title=f"📊 Thủy văn: {station_name} (7 ngày thực đo + 7 ngày dự báo)",
        xaxis_title="Ngày",
        yaxis_title="Mực nước (m)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=400,
        hovermode="x unified"
    )
    
    return fig

def create_seasonal_chart(station_name: str, df_all: pd.DataFrame, historical_df: Optional[pd.DataFrame] = None) -> go.Figure:
    """Biểu đồ mùa lũ — dùng dữ liệu lịch sử nếu có"""
    station_row = df_all[df_all["name"] == station_name].iloc[0] if not df_all.empty else None
    flood_stage = station_row["flood_stage"] if station_row is not None and not pd.isna(station_row.get("flood_stage")) else None
    
    fig = go.Figure()
    
    # ===== 1. Dữ liệu lịch sử (nếu có) =====
    if historical_df is not None and not historical_df.empty:
        hist = historical_df.copy()
        hist["month"] = hist["timestamp"].dt.month
        hist["dayofyear"] = hist["timestamp"].dt.dayofyear
        
        # Nhóm theo ngày trong năm (trung bình nhiều năm)
        seasonal = hist.groupby("dayofyear")["water_level"].agg(["mean", "std"]).reset_index()
        seasonal["timestamp"] = pd.to_datetime("2023") + pd.to_timedelta(seasonal["dayofyear"] - 1, unit="D")
        
        # Vẽ đường trung bình
        fig.add_trace(go.Scatter(
            x=seasonal["timestamp"],
            y=seasonal["mean"],
            mode="lines",
            name="Trung bình nhiều năm",
            line=dict(color="#4CAF50", width=3)
        ))
        
        # Vẽ vùng tin cậy ±1σ
        fig.add_trace(go.Scatter(
            x=seasonal["timestamp"].tolist() + seasonal["timestamp"][::-1].tolist(),
            y=(seasonal["mean"] + seasonal["std"]).tolist() + (seasonal["mean"] - seasonal["std"])[::-1].tolist(),
            fill="toself",
            fillcolor="rgba(76, 175, 80, 0.2)",
            line=dict(color="rgba(0,0,0,0)"),
            name="±1σ",
            showlegend=False
        ))
    
    # ===== 2. Dữ liệu mẫu (fallback) =====
    else:
        months = pd.date_range("2023-01-01", periods=12, freq="MS")
        seasonal_avg = [1.2, 1.1, 1.0, 0.9, 1.0, 1.5, 2.5, 3.2, 3.8, 3.5, 2.8, 2.0]
        fig.add_trace(go.Scatter(
            x=months,
            y=seasonal_avg,
            mode="lines+markers",
            name="Mẫu (Mekong)",
            line=dict(color="#9E9E9E", width=2, dash="dot"),
            marker=dict(size=4)
        ))
    
    # ===== 3. Ngưỡng lũ =====
    if flood_stage:
        fig.add_hline(
            y=flood_stage,
            line=dict(color="red", dash="dash", width=2),
            annotation_text=f"Lũ: {flood_stage:.1f}m",
            annotation_position="right"
        )
    
    # ===== 4. Layout =====
    fig.update_layout(
        title=f"🌊 Mùa lũ đặc trưng: {station_name}",
        xaxis_title="Tháng",
        yaxis_title="Mực nước trung bình (m)",
        xaxis=dict(
            tickformat="%b",
            dtick="M1"
        ),
        height=300,
        margin=dict(l=50, r=50, t=60, b=50)
    )
    
    return fig

# ==============================================================================
# HELPER: LOAD LATEST FORECAST FOR STATION
# ==============================================================================
def find_latest_forecast(station_name: str) -> Optional[Path]:
    """Tìm file forecast mới nhất theo pattern: {station}_forecast_YYYYMMDD_vXXX.csv"""
    pattern = f"{station_name.replace(' ', '_').replace('’', '')}_forecast_*.csv"
    candidates = list(FORECAST_DIR.glob(pattern))
    
    if not candidates:
        return None
    
    # Sắp xếp theo date + version: mới nhất trước
    def sort_key(p: Path):
        name = p.stem  # 'Tan_Chau_forecast_20251225_v001'
        parts = name.split('_')
        if len(parts) >= 4 and parts[-2].isdigit() and parts[-1].startswith('v'):
            try:
                date_part = parts[-2]  # '20251225'
                version_part = parts[-1][1:]  # '001'
                return (date_part, int(version_part))
            except:
                pass
        return ("00000000", 0)
    
    candidates.sort(key=sort_key, reverse=True)
    return candidates[0]


def load_station_forecast(station_name: str) -> pd.DataFrame:
    """Load forecast CSV mới nhất cho trạm, trả về DataFrame có cột 'date'"""
    forecast_path = find_latest_forecast(station_name)
    today = pd.Timestamp.now().normalize()
    
    if not forecast_path or not forecast_path.exists():
        # Fallback: tạo forecast mẫu 15 ngày
        dates = [today + timedelta(days=i-7) for i in range(15)]  # −7 → +7
        return pd.DataFrame({
            "timestamp": dates,
            "day": list(range(1, 16)),
            "predicted_water_level": [np.nan] * 15,
            "status": ["NODATA"] * 15
        })
    
    try:
        df = pd.read_csv(forecast_path)
        # Tạo cột 'date' từ today
        df["timestamp"] = [today + timedelta(days=i-7) for i in range(len(df))]
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df[["timestamp", "day", "predicted_water_level", "status"]].copy()
    except Exception as e:
        st.warning(f"⚠️ Lỗi đọc forecast {station_name}: {e}")
        return pd.DataFrame()

def load_historical_data_for_seasonal(station_name: str) -> Optional[pd.DataFrame]:
    """Tải dữ liệu lịch sử từ CSV để vẽ seasonal chart"""
    try:
        # Đường dẫn dữ liệu
        BASE_DIR = Path(__file__).parent
        BASE_DATA_DIR = BASE_DIR / "data" / "historical"
        station_dir = BASE_DATA_DIR / station_name.replace(" ", "_")
        train_path = station_dir / "train.csv"
        test_path = station_dir / "test.csv"
        
        data_frames = []
        for path in [train_path, test_path]:
            if path.exists():
                df = pd.read_csv(path)
                # Chuẩn hóa cột ngày
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                elif "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                else:
                    continue
                # Chuẩn hóa cột mực nước
                if "water_level" in df.columns:
                    val_col = "water_level"
                elif "value" in df.columns:
                    val_col = "value"
                else:
                    continue
                df = df[["timestamp", val_col]].rename(columns={val_col: "water_level"})
                df = df.dropna()
                data_frames.append(df)
        
        if data_frames:
            full_hist = pd.concat(data_frames, ignore_index=True)
            full_hist = full_hist.drop_duplicates(subset=["timestamp"], keep="last")
            full_hist = full_hist.sort_values("timestamp")
            return full_hist
        return None
    except Exception as e:
        st.warning(f"⚠️ Không thể tải dữ liệu lịch sử cho {station_name}: {e}")
        return None

# ==============================================================================
# MAIN APP — PHẦN 2: CẬP NHẬT VỚI DỮ LIỆU THỰC
# ==============================================================================
def main():
    st.title("🌊 Mekong River Flood Forecasting")
    st.markdown("Real-time monitoring and ML-powered predictions for the Mekong Basin")
    
    # Load metadata & fetch data
    metadata_df = load_metadata()
    if metadata_df.empty:
        st.error("❌ Không tìm thấy dữ liệu trạm.")
        return

    # Dùng hash để cache đúng
    metadata_hash = str(hash(tuple(metadata_df["name"].tolist())))
    df_all = fetch_mrc_data(metadata_hash)

    if df_all.empty:
        st.error("❌ Không thể lấy dữ liệu từ API hoặc fallback.")
        return

    # Hiển thị tổng quan
    st.success(f"✅ Đã load {len(df_all)} trạm — Dữ liệu cập nhật: {df_all['last_updated'].iloc[0].strftime('%H:%M:%S')}")

    # Thống kê nhanh
    col1, col2, col3, col4 = st.columns(4)
    n_flood = len(df_all[df_all["status"] == "FLOOD"])
    n_alarm = len(df_all[df_all["status"] == "ALARM"])
    n_normal = len(df_all[df_all["status"] == "NORMAL"])
    n_nodata = len(df_all[df_all["status"] == "NODATA"])

    col1.metric("🔴 Flood", n_flood)
    col2.metric("🟠 Alarm", n_alarm)
    col3.metric("🟢 Normal", n_normal)
    col4.metric("⚫ No Data", n_nodata)

    # Bảng dữ liệu
    st.subheader("📋 Bảng dữ liệu thời gian thực")
    display_df = df_all[[
    "name", "water_level", "last_measurement", "status", "flood_stage_disp", "source"
    ]].copy()
    display_df.columns = ["Trạm", "Mực nước (m)", "Cập nhật lúc", "Trạng thái", "Ngưỡng lũ", "Nguồn"]
    display_df["Mực nước (m)"] = display_df["Mực nước (m)"].round(2)
    display_df["Cập nhật lúc"] = pd.to_datetime(display_df["Cập nhật lúc"]).dt.strftime("%Y-%m-%d %H:%M")
    
    # Hiển thị bản đồ + bảng
    col_map, col_table = st.columns([0.65, 0.35])
    st.divider()
    st.subheader("🔮 Dự báo mực nước 15 ngày (today−7 → today+7)")

    # Chọn trạm để xem forecast
    selected_station = st.selectbox(
        "Chọn trạm để xem dự báo",
        options=df_all["name"].tolist(),
        index=0
    )

    # Load forecast cho trạm đã chọn
    forecast_df = load_station_forecast(selected_station)

    # Hiển thị thông tin
    if not forecast_df.empty:
        st.success(f"✅ Đã load forecast cho **{selected_station}** — {len(forecast_df)} ngày")
            # Tạo biểu đồ
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
                # ===== BIỂU ĐỒ 2 TRỤC (THỜI GIAN THỰC) =====
            st.subheader("📡 Dữ liệu thời gian thực (15 phút)")
            
            # Lấy dữ liệu chi tiết
            # Lấy station_id từ metadata
            meta_df = load_metadata()
            station_meta = meta_df[meta_df["name"] == selected_station]
            station_id = station_meta["api_id"].iloc[0] if not station_meta.empty else "019803"

            # Gọi đúng hàm
            observed_df = fetch_15min_data(station_id, selected_station)
            station_row = df_all[df_all["name"] == selected_station].iloc[0] if not df_all.empty else {}
            flood_stage = station_row.get("flood_stage")
            alarm_stage = station_row.get("alarm_stage")
            
            dual_fig = create_dual_axis_chart(
                selected_station, observed_df, flood_stage, alarm_stage
            )
            st.plotly_chart(dual_fig, use_container_width=True)
            # ===== BIỂU ĐỒ THỦY VĂN (15 PHÚT - 1344 ĐIỂM) =====
            st.subheader("📊 Biểu đồ thủy văn (15 phút / đầy đủ dữ liệu)")
            
            # --- 1. DỮ LIỆU THỰC ĐO (7 ngày gần nhất) ---
            station_id = station_meta["api_id"].iloc[0] if not station_meta.empty else "019803"
            observed_df = fetch_15min_data(station_id, selected_station)
            
            # --- 2. DỮ LIỆU DỰ BÁO (1344 điểm, 15 phút) ---
            forecast_path = get_latest_forecast_file(selected_station)
            forecast_df = pd.DataFrame()
            if forecast_path and forecast_path.exists():
                forecast_df = pd.read_csv(forecast_path)
                # Chuyển 'date' → datetime (UTC → VN)
                if "timestamp" in forecast_df.columns:
                    forecast_df["timestamp"] = pd.to_datetime(forecast_df["timestamp"], utc=True)
                    forecast_df["timestamp"] = forecast_df["timestamp"].dt.tz_convert("Asia/Ho_Chi_Minh")
                else:
                    forecast_df["timestamp"] = pd.to_datetime(forecast_df["timestamp"], utc=True)
                    forecast_df["timestamp"] = forecast_df["timestamp"].dt.tz_convert("Asia/Ho_Chi_Minh")
                    st.error("❌ File forecast thiếu cột 'date'!")
            
            # --- 3. VẼ BIỂU ĐỒ ---
            fig = go.Figure()
            
            # Thực đo (7 ngày VN)
            if not observed_df.empty and "timestamp" in observed_df.columns:
                obs = observed_df.copy()
                obs["timestamp"] = pd.to_datetime(obs["timestamp"], utc=True).dt.tz_convert("Asia/Ho_Chi_Minh")
                cutoff = pd.Timestamp.now(tz="Asia/Ho_Chi_Minh").normalize() - timedelta(days=6)
                recent = obs[obs["timestamp"] >= cutoff]
                if not recent.empty:
                    fig.add_trace(go.Scatter(
                        x=recent["timestamp"],
                        y=recent["water_level"],
                        mode="lines",
                        name="Thực đo (15 phút)",
                        line=dict(color="#1E88E5", width=1),
                        hovertemplate="Thực đo: %{y:.3f} m<br>%{x}<extra></extra>"
                    ))
            
            # Dự báo (1344 điểm)
            if not forecast_df.empty and "timestamp" in forecast_df.columns:
                fig.add_trace(go.Scatter(
                    x=forecast_df["timestamp"],
                    y=forecast_df["predicted_water_level"],
                    mode="lines",
                    name="Dự báo (15 phút)",
                    line=dict(color="#FF9800", width=1.2, dash="dash"),
                    hovertemplate="Dự báo: %{y:.3f} m<br>%{x}<extra></extra>"
                ))
            
            # Ngưỡng
            flood_stage = station_row.get("flood_stage")
            alarm_stage = station_row.get("alarm_stage")
            if flood_stage:
                fig.add_hline(y=flood_stage, line=dict(color="red", dash="dash", width=2), annotation_text=f"Flood: {flood_stage:.1f}m")
            if alarm_stage:
                fig.add_hline(y=alarm_stage, line=dict(color="orange", dash="dash", width=2), annotation_text=f"Alarm: {alarm_stage:.1f}m")
            
            # Layout
            fig.update_layout(
                title=f"🌊 Tan Chau: Dữ liệu 15 phút (Thực đo + Dự báo)",
                xaxis_title="Thời gian",
                yaxis_title="Mực nước (m)",
                height=500,
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            
            st.plotly_chart(fig, use_container_width=True)
        
        with col_chart2:
            st.subheader("🌊 Mùa lũ trong năm")
            historical_df = load_historical_data_for_seasonal(selected_station)

            # Vẽ biểu đồ
            season_fig = create_seasonal_chart(selected_station, df_all, historical_df)
            st.plotly_chart(season_fig, use_container_width=True)
        # Tạo bảng chi tiết
        disp_forecast = forecast_df.copy()

        today = pd.Timestamp.now().normalize()
        # Chuyển 'date' → datetime (nếu chưa)
                # Chuyển 'date' → datetime (nếu chưa)
# Chuyển 'date' → datetime (nếu chưa)
# ✅ Sửa lỗi dứt điểm — không dùng .dt
# ✅ Sửa lỗi dứt điểm — không dùng .dt
# ✅ Sửa lần cuối — đúng cú pháp Pandas
# ✅ Sửa lỗi KeyError: 'date' — dùng 'date' thay vì 'date'
# ✅ Sửa lỗi dứt điểm — đảm bảo ts_series là datetime trước khi .dt
        if not disp_forecast.empty and "timestamp" in disp_forecast.columns:
            # 1. Ép thành datetime, ép lỗi thành NaT
            ts_series = pd.to_datetime(disp_forecast["timestamp"], errors='coerce')
            
            # 2. Lọc bỏ NaT
            valid_mask = ts_series.notna()
            
            # 3. Tạo cột days_from_today — mặc định NaN
            disp_forecast["days_from_today"] = np.nan
            
            if valid_mask.any():
                # 4. Dùng .dt.date trên Series datetime hợp lệ
                ts_dates = ts_series[valid_mask].dt.tz_localize(None).dt.date
                now_date = pd.Timestamp.now().date()
                delta_days = (pd.to_datetime(ts_dates) - pd.to_datetime(now_date)).dt.days  # ← scalar array → .days hợp lệ
                
                # 5. Gán lại
                disp_forecast.loc[valid_mask, "days_from_today"] = delta_days
            
            # 6. Phân loại
            disp_forecast["period"] = disp_forecast["days_from_today"].apply(
                lambda d: "Quá khứ" if pd.notna(d) and d < 0 
                else "Hiện tại" if pd.notna(d) and d == 0 
                else "Tương lai" if pd.notna(d) and d > 0 
                else "Unknown"
            )
            
            # 7. Tạo cột "Ngày"
            disp_forecast["Ngày"] = ts_series.dt.strftime("%Y-%m-%d")
            
            # 8. Chuẩn bị hiển thị
            disp_forecast["Mực nước dự báo (m)"] = disp_forecast["predicted_water_level"].round(3)
            disp_forecast["Trạng thái"] = disp_forecast["status"]
            
            disp_forecast = disp_forecast[["Ngày", "period", "Mực nước dự báo (m)", "Trạng thái"]]
            disp_forecast.columns = ["Ngày", "Giai đoạn", "Mực nước (m)", "Trạng thái"]
        else:
            disp_forecast = pd.DataFrame(columns=["Ngày", "Giai đoạn", "Mực nước (m)", "Trạng thái"])
       
        st.dataframe(disp_forecast, use_container_width=True, hide_index=True)
        
    else:
        st.info(f"ℹ️ Chưa có file forecast cho **{selected_station}**. Vui lòng chạy `train4.ipynb` để tạo.")
    

    with col_map:
        st.subheader("📍 Bản đồ mạng lưới")
        network_map = create_network_map(df_all)
        st_folium(network_map, width=None, height=500, use_container_width=True)

    with col_table:
        st.subheader("📋 Bảng dữ liệu thời gian thực")
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            height=500
        )

    st.divider()
    
if __name__ == "__main__":
    main()