import pandas as pd
import pickle
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

# === Load dataset ===
data_path = "data/processed/final_dataset.csv"
print("📂 Loading dataset...")
df = pd.read_csv(data_path, low_memory=False)

print(f"✅ Dataset loaded successfully!\nRows: {len(df)} Columns: {len(df.columns)}")

# === Clean & prepare ===
df = df.dropna(subset=["delay_min"])
df["delay_min"] = pd.to_numeric(df["delay_min"], errors="coerce")
df = df.dropna(subset=["delay_min"])

# === Sample to avoid huge memory load ===
if len(df) > 200000:
    df = df.sample(200000, random_state=42)
    print("⚙️ Using a 200k-row sample for faster training...")

# === Feature selection ===
features = ["hour", "temperature_C", "rain_mm", "humidity_%", "traffic_index", "event_day"]
X = df[features]
y = df["delay_min"]

# === Train/Test split ===
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# === Train model ===
print("🚀 Training Random Forest model...")
model = RandomForestRegressor(n_estimators=50, random_state=42, n_jobs=-1)
model.fit(X_train, y_train)

# === Evaluate ===
y_pred = model.predict(X_test)
mae = mean_absolute_error(y_test, y_pred)
r2 = r2_score(y_test, y_pred)
print(f"✅ Model trained successfully!\nMAE: {mae:.2f} minutes\nR² Score: {r2:.3f}")

# === Save model ===
output_path = "models/transport_delay_model.pkl"
with open(output_path, "wb") as f:
    pickle.dump(model, f)
print(f"💾 Model saved as: {output_path}")
