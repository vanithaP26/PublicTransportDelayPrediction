import pandas as pd

# Load your final dataset
df = pd.read_csv("data/processed/final_dataset.csv")

# Convert delay_min column to minutes if it's in HH:MM:SS format
def to_minutes(x):
    try:
        if isinstance(x, str) and ":" in x:
            h, m, s = map(int, x.split(":"))
            return h * 60 + m + s / 60
        else:
            return float(x)
    except:
        return 0.0

df["delay_min"] = df["delay_min"].apply(to_minutes)

# Save fixed version
df.to_csv("data/processed/final_dataset.csv", index=False)

print("✅ Fixed delay_min column successfully! Example values:")
print(df["delay_min"].head())
print("Saved corrected file: data/processed/final_dataset.csv")
