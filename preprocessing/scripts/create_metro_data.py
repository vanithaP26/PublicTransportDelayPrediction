import pandas as pd
from datetime import datetime, timedelta
import numpy as np
import os

# --- Create a fake metro delay dataset with routes ---

# Define routes
routes = [
    "Purple Line: Kengeri → Whitefield",
    "Green Line: Nagasandra → Silk Institute",
    "Yellow Line: R V Road → Bommasandra",
    "Pink Line: Kalena Agrahara → Nagawara",
]

# Generate synthetic data
num_records = 5000
data = []

for i in range(num_records):
    route = np.random.choice(routes)
    base_time = datetime(2025, 10, 20, 6, 0) + timedelta(minutes=int(np.random.randint(0, 600)))
    delay = np.random.randint(0, 15)  # delay in minutes
    scheduled_time = base_time
    actual_time = scheduled_time + timedelta(minutes=int(delay))  # cast to int

    data.append({
        "route_name": route,
        "scheduled_arrival": scheduled_time,
        "actual_arrival": actual_time,
        "delay_min": delay,
        "mode": "Metro"
    })

# Convert to DataFrame
df = pd.DataFrame(data)

# Save to processed data folder
output_path = "data/processed/metro_delay_dataset.csv"
os.makedirs(os.path.dirname(output_path), exist_ok=True)
df.to_csv(output_path, index=False)

print(f"✅ Metro delay dataset created successfully with routes!")
print(f"Rows: {len(df)}")
print(df.head())
