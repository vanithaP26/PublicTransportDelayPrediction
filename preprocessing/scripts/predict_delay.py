import joblib
import numpy as np
import pandas as pd

# --- Load trained model ---
model = joblib.load("models/transport_delay_model.pkl")
print("✅ Model loaded successfully!\n")

# --- User input section ---
print("Enter details to predict transport delay:")
hour = int(input("🕒 Hour of day (0-23): "))
temperature = float(input("🌡️ Temperature (°C): "))
rain = float(input("🌧️ Rainfall (mm): "))
humidity = float(input("💧 Humidity (%): "))
traffic = float(input("🚗 Traffic Index (0.0 to 1.0): "))
event_day = int(input("🎉 Event Day (1 for yes, 0 for no): "))

# --- Prepare data for prediction ---
data = pd.DataFrame([{
    "hour": hour,
    "temperature_C": temperature,
    "rain_mm": rain,
    "humidity_%": humidity,
    "traffic_index": traffic,
    "event_day": event_day
}])

# --- Predict delay ---
pred_delay = model.predict(data)[0]
print(f"\n🚌 Predicted Transport Delay: {pred_delay:.2f} minutes")
