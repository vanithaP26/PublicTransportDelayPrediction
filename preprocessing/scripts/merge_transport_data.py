# scripts/merge_transport_data.py
import pandas as pd
import os

bus = pd.read_csv("data/processed/bus_delay_dataset.csv")
train = pd.read_csv("data/processed/train_delay_dataset.csv")
metro = pd.read_csv("data/processed/metro_delay_dataset.csv")

combined = pd.concat([bus, train, metro], ignore_index=True)

# Add date and hour columns
combined["date"] = pd.to_datetime(combined["scheduled_arrival"], errors="coerce").dt.date
combined["hour"] = pd.to_datetime(combined["scheduled_arrival"], errors="coerce").dt.hour

combined.to_csv("data/processed/combined_transport.csv", index=False)

print("✅ Combined dataset created successfully!")
print("Rows:", combined.shape[0])
print(combined.head())
