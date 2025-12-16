import pandas as pd
import os

print("📂 Loading BMTC GTFS data (memory optimized, route fix)...")

# Paths
base_path = r"data/raw/bmtc_gtfs/unzipped"

# Load essential data
stop_times = pd.read_csv(
    os.path.join(base_path, "stop_times.txt"),
    usecols=["trip_id", "arrival_time"],
    nrows=5000
)

trips = pd.read_csv(
    os.path.join(base_path, "trips.txt"),
    usecols=["trip_id", "route_id"],
    nrows=5000
)

routes = pd.read_csv(
    os.path.join(base_path, "routes.txt"),
    usecols=["route_id", "route_desc"],
    dtype=str
)

# ✅ Merge step-by-step
bus_df = stop_times.merge(trips, on="trip_id", how="left")
bus_df = bus_df.merge(routes, on="route_id", how="left")

# ✅ Assign readable route name
bus_df["route_name"] = bus_df["route_desc"].fillna("Unknown")

# ✅ Convert times safely
bus_df["scheduled_arrival"] = pd.to_datetime(bus_df["arrival_time"], errors="coerce")

# ✅ Simulate actual arrival and delay (temporary for model training)
bus_df["actual_arrival"] = bus_df["scheduled_arrival"] + pd.to_timedelta(
    (bus_df.index % 15), unit="m"
)
bus_df["delay_min"] = (
    (bus_df["actual_arrival"] - bus_df["scheduled_arrival"]).dt.total_seconds() / 60
).fillna(0)

# ✅ Keep final clean columns
bus_df = bus_df[["route_name", "scheduled_arrival", "actual_arrival", "delay_min"]]
bus_df["mode"] = "Bus"

# ✅ Save output
os.makedirs("data/processed", exist_ok=True)
output_path = "data/processed/bus_delay_dataset.csv"
bus_df.to_csv(output_path, index=False, chunksize=5000)

print(f"✅ Cleaned Bus dataset saved: {output_path}")
print("Rows:", len(bus_df))
bus_df.to_parquet("data/processed/bus_delay_dataset.parquet", index=False)
print("💾 Also saved a faster version: bus_delay_dataset.parquet")

print(bus_df.head(10))
