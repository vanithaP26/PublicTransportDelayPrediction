import pandas as pd
import os

events = [
    ["2024-01-01", "New Year Celebration", "High"],
    ["2024-01-14", "Makar Sankranti", "Medium"],
    ["2024-03-08", "Maha Shivaratri", "Medium"],
    ["2024-03-25", "Holi Festival", "High"],
    ["2024-04-10", "Election Rally", "Very High"],
    ["2024-08-15", "Independence Day", "High"],
    ["2024-10-02", "Gandhi Jayanti", "Low"],
    ["2024-10-12", "Dasara Festival", "Very High"],
    ["2024-11-01", "Kannada Rajyotsava", "High"],
    ["2024-12-25", "Christmas", "High"]
]

df = pd.DataFrame(events, columns=["date", "event_name", "impact_level"])
df["date"] = pd.to_datetime(df["date"])

impact_map = {"Low": 1, "Medium": 2, "High": 3, "Very High": 4}
df["impact_score"] = df["impact_level"].map(impact_map)

os.makedirs("data/processed", exist_ok=True)
df.to_csv("data/processed/event_calendar.csv", index=False)

print("✅ Event Calendar Dataset Created Successfully!")
print(df.head())
