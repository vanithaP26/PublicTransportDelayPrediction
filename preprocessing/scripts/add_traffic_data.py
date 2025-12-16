import pandas as pd
import numpy as np
import os

np.random.seed(42)

times = pd.date_range("2024-01-01 06:00", "2024-01-01 22:00", freq="H")
traffic = []

for t in times:
    base = np.random.normal(50, 15)          # average congestion
    if 7 <= t.hour <= 10 or 17 <= t.hour <= 20:
        base += np.random.randint(20, 40)    # add peak-hour congestion
    traffic.append(min(max(base, 0), 100))

traffic_df = pd.DataFrame({
    "time": times,
    "traffic_intensity": traffic
})

os.makedirs("data/processed", exist_ok=True)
traffic_df.to_csv("data/processed/traffic_data.csv", index=False)

print("✅ Traffic intensity data created successfully!")
print(traffic_df.head())
