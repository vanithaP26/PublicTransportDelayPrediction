import pandas as pd
import requests
import os

# --- Function to fetch hourly weather data ---
def get_weather_data(lat, lon, date):
    url = (
        f"https://archive-api.open-meteo.com/v1/archive?"
        f"latitude={lat}&longitude={lon}&start_date={date}&end_date={date}"
        f"&hourly=temperature_2m,precipitation,relative_humidity_2m,wind_speed_10m"
    )
    r = requests.get(url)
    data = r.json()
    df = pd.DataFrame(data["hourly"])
    df["time"] = pd.to_datetime(df["time"])
    return df

# --- Bengaluru coordinates ---
lat, lon = 12.9716, 77.5946
date = "2024-01-01"

weather = get_weather_data(lat, lon, date)
weather.rename(columns={
    "temperature_2m": "temperature",
    "precipitation": "precipitation",
    "relative_humidity_2m": "humidity",
    "wind_speed_10m": "windspeed"
}, inplace=True)

os.makedirs("data/processed", exist_ok=True)
weather.to_csv("data/processed/weather_data.csv", index=False)

print("✅ Weather data downloaded and saved!")
print(weather.head())
