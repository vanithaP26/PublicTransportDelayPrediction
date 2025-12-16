# scripts/clean_train_data.py
import pandas as pd
import os

train_path = "data/raw/train/unzipped/Train_Delay.csv"
df = pd.read_csv(train_path)

# Standardize column names
df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

# Create route name as Source → Destination
df["route_name"] = df["source"] + "→" + df["destitnation"].fillna("Unknown")

# Convert times
df["scheduled_arrival"] = pd.to_datetime(df["sc_arr__time"], errors="coerce")
df["actual_arrival"] = pd.to_datetime(df["act_arr_time"], errors="coerce")

# Compute delay
df["delay_min"] = pd.to_numeric(df["dealy_min"], errors="coerce")
df["mode"] = "Train"

train_clean = df[["route_name", "scheduled_arrival", "actual_arrival", "delay_min", "mode"]]

os.makedirs("data/processed", exist_ok=True)
train_clean.to_csv("data/processed/train_delay_dataset.csv", index=False)

print("✅ Train dataset cleaned with routes.")
print(train_clean.head())
# scripts/clean_train_data.py
import pandas as pd
import os

train_path = "data/raw/train/unzipped/Train_Delay.csv"
df = pd.read_csv(train_path)

# Standardize column names
df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

# Create route name as Source → Destination
df["route_name"] = df["source"] + "→" + df["destitnation"].fillna("Unknown")

# Convert times
df["scheduled_arrival"] = pd.to_datetime(df["sc_arr__time"], errors="coerce")
df["actual_arrival"] = pd.to_datetime(df["act_arr_time"], errors="coerce")

# Compute delay
df["delay_min"] = pd.to_numeric(df["dealy_min"], errors="coerce")
df["mode"] = "Train"

train_clean = df[["route_name", "scheduled_arrival", "actual_arrival", "delay_min", "mode"]]

os.makedirs("data/processed", exist_ok=True)
train_clean.to_csv("data/processed/train_delay_dataset.csv", index=False)

print("✅ Train dataset cleaned with routes.")
print(train_clean.head())
