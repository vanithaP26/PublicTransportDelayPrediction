import pandas as pd
from datetime import datetime

# ==============================
# 🧼 Clean Metro Data Script
# ==============================

print("📂 Cleaning Metro dataset...")

# Path to your created metro CSV
input_path = "data/processed/metro_delay_dataset.csv"
output_path = "data/processed/metro_delay_dataset.csv"

# Load the data
df = pd.read_csv(input_path)

# Ensure the main columns exist
expected_cols = ["route_name", "scheduled_arrival", "actual_arrival", "delay_min", "mode"]
missing = [c for c in expected_cols if c not in df.columns]
if missing:
    raise ValueError(f"❌ Missing columns in metro dataset: {missing}")

# Convert times safely
df["scheduled_arrival"] = pd.to_datetime(df["scheduled_arrival"], errors="coerce")
df["actual_arrival"] = pd.to_datetime(df["actual_arrival"], errors="coerce")

# Compute delay in minutes if missing or invalid
df["delay_min"] = df.apply(
    lambda row: (row["actual_arrival"] - row["scheduled_arrival"]).total_seconds() / 60
    if pd.notnull(row["actual_arrival"]) and pd.notnull(row["scheduled_arrival"])
    else row["delay_min"],
    axis=1
)

# Replace NaN or negative delays with 0
df["delay_min"] = df["delay_min"].fillna(0)
df.loc[df["delay_min"] < 0, "delay_min"] = 0

# Ensure the mode is correctly labeled
df["mode"] = "Metro"

# Keep relevant columns only
df = df[["route_name", "scheduled_arrival", "actual_arrival", "delay_min", "mode"]]

# Save cleaned version
df.to_csv(output_path, index=False)
print(f"✅ Cleaned Metro dataset saved: {output_path}")
print(f"Rows: {len(df)}")
print(df.head())
