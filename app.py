# app.py — Karnataka coverage, Bengaluru-first geocoding, strict PT availability,
# fast short suggestions (A2, max 6), Public PT with smart Walk/Cab hints,
# optional separate Cab/Walk features, Login/Signup (SQLite, hashed),
# always-save history (even "no direct PT"), and interactive dashboard.

import os, json, pickle, pathlib, sqlite3
from datetime import datetime
from collections import defaultdict
from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, session, flash
)
import requests
from geopy.distance import geodesic
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

TOMTOM_KEY = os.getenv("TOMTOM_API_KEY", "").strip()
MODEL_PATH = "models/transport_delay_model.pkl"

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

# ------------ Data dir / DB ------------
APP_DIR = pathlib.Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "app.db"

def init_db():
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT,
            source TEXT,
            destination TEXT,
            road_km REAL,
            modes_json TEXT
        )""")
        con.commit()
init_db()

def ensure_feature_column():
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("PRAGMA table_info(searches)")
        cols = [c[1] for c in cur.fetchall()]
        if "feature" not in cols:
            cur.execute("ALTER TABLE searches ADD COLUMN feature TEXT DEFAULT 'public'")
            con.commit()
ensure_feature_column()

def init_users_table():
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        con.commit()
init_users_table()

# ------------ Optional ML model ------------
model = None
try:
    if os.path.exists(MODEL_PATH):
        with open(MODEL_PATH, "rb") as f:
            model = pickle.load(f)
        print(f"[OK] Loaded model: {MODEL_PATH}")
    else:
        print(f"[WARN] Model not found; using heuristic fallback.")
except Exception as e:
    print(f"[WARN] Model load error: {e}. Using heuristic fallback.")

# ------------ Geocoding (Karnataka coverage, Bengaluru-first) ------------
DEFAULT_CITY  = "Bengaluru"
DEFAULT_STATE = "Karnataka"
DEFAULT_COUNTRY = "India"
OSM_UA = {"User-Agent": "public-pt-delay-app (demo)"}

def _osm_try(query: str, prox=None):
    try:
        base = "https://nominatim.openstreetmap.org/search"
        params = {"format": "json", "q": query, "limit": 1, "addressdetails": 1}
        if prox:
            lat, lon = prox; d = 0.25  # ~25–30 km bias box
            params.update({"viewbox": f"{lon-d},{lat+d},{lon+d},{lat-d}", "bounded": 1})
        r = requests.get(base, params=params, headers=OSM_UA, timeout=12)
        r.raise_for_status()
        data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", "")
    except Exception as e:
        print("OSM geocode err:", e)
    return None

def _geo_strong_karnataka(q: str, prox=None):
    """Bengaluru-first → Karnataka → India → raw."""
    attempts = [
        f"{q}, {DEFAULT_CITY}, {DEFAULT_STATE}, {DEFAULT_COUNTRY}",
        f"{q}, {DEFAULT_STATE}, {DEFAULT_COUNTRY}",
        f"{q}, {DEFAULT_COUNTRY}",
        q,
    ]
    seen = set()
    for a in attempts:
        if a in seen:
            continue
        seen.add(a)
        res = _osm_try(a, prox=prox)
        if res:
            return res
    return None

# ------------ Hard-coded fallback locations (for demo reliability) ------------
FALLBACK_PLACES = {
    "majestic": (12.9789, 77.5715, "Majestic, Bengaluru, Karnataka, India"),
    "majestic, bengaluru": (12.9789, 77.5715, "Majestic, Bengaluru, Karnataka, India"),
    "ksr bengaluru": (12.9765, 77.5726, "KSR Bengaluru (Majestic), Karnataka, India"),
    "koppal": (15.3500, 76.1500, "Koppal, Karnataka, India"),
}

def _geo_with_fallback(text: str, prox=None):
    """Try OSM first, then fallback dictionary for known demo places."""
    res = _geo_strong_karnataka(text, prox=prox)
    if res:
        return res
    key = (text or "").strip().lower()
    if key in FALLBACK_PLACES:
        lat, lon, label = FALLBACK_PLACES[key]
        return lat, lon, label
    return None

def geocode_pair(src_text: str, dst_text: str):
    s = _geo_with_fallback(src_text)
    d = _geo_with_fallback(dst_text)
    if not s or not d:
        return None, None, ("We couldn’t locate one of those places. "
                            "Try a more specific name (e.g., ‘Majestic, Bengaluru’).")
    s_ll, d_ll = (s[0], s[1]), (d[0], d[1])

    # If very far, bias a second pass toward each other
    if geodesic(s_ll, d_ll).km > 120:
        s2 = _geo_with_fallback(src_text, prox=d_ll) or s
        d2 = _geo_with_fallback(dst_text, prox=s_ll) or d
        s_ll, d_ll = (s2[0], s2[1]), (d2[0], d2[1])
        if geodesic(s_ll, d_ll).km > 800:
            return None, None, ("Those places seem extremely far apart. "
                                "Please add city/district names for clarity.")
    return s_ll, d_ll, None

# ------------ TomTom routing (for Bus/Cab road path) ------------
def tomtom_route(src_ll, dst_ll):
    if not TOMTOM_KEY:
        return None, "TomTom API key missing."
    lat1, lon1 = src_ll; lat2, lon2 = dst_ll
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{lat1},{lon1}:{lat2},{lon2}/json"
    params = {"key": TOMTOM_KEY, "traffic": "true", "routeType": "fastest", "travelMode": "car"}
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if not data.get("routes"):
            return None, "No road route found."
        route = data["routes"][0]
        length_m   = route["summary"].get("lengthInMeters", 0)
        duration_s = route["summary"].get("travelTimeInSeconds", 0)
        coords = []
        for leg in route.get("legs", []):
            for p in leg.get("points", []):
                coords.append([p["latitude"], p["longitude"]])
        return {
            "distance_km": round(length_m/1000.0, 2),
            "duration_min": round(duration_s/60.0, 1),
            "coords": coords
        }, None
    except Exception as e:
        return None, f"TomTom route error: {e}"

# ------------ Helpers for availability / regions ------------
BLR_METRO_STATIONS = [
    (12.9789, 77.5715),  # Majestic
    (13.0186, 77.5560),  # Yeshwanthpur
    (12.9784, 77.6408),  # MG Road
    (12.9780, 77.6512),  # Indiranagar
    (12.9951, 77.6974),  # Baiyappanahalli
    (13.0097, 77.6956),  # KR Puram
    (12.9184, 77.5735),  # Banashankari
    (13.0509, 77.5304),  # Jalahalli
]
KA_RAIL_STATIONS = [
    (13.0097, 77.6956),  # KR Puram
    (13.0188, 77.5560),  # Yeshwanthpur
    (12.9981, 77.5920),  # Bengaluru Cantonment
    (12.9765, 77.5726),  # KSR Bengaluru (Majestic)
    (12.3135, 76.6499),  # Mysuru Jn
    (13.3419, 77.1010),  # Tumakuru
    (13.0076, 76.1026),  # Hassan
    (12.5223, 76.8962),  # Mandya
    (13.9299, 75.5681),  # Shivamogga
    (12.8700, 74.8426),  # Mangaluru Central
    (15.3647, 75.1240),  # Hubballi Jn
    (13.3409, 74.7421),  # Udupi
]

def _min_dist_km(pt, stations):
    best = 1e9
    for s in stations:
        d = geodesic(pt, s).km
        if d < best:
            best = d
    return best

def in_karnataka(pt):
    """Simple bbox check used for generic Bus/Train availability."""
    lat, lon = pt
    return 11.5 <= lat <= 18.5 and 74.0 <= lon <= 78.7

# ------------ Mode availability (Public PT, generic Karnataka rules) ------------
def available_public_modes(road_km, has_route, src_ll, dst_ll):
    """
    PUBLIC MODES (generic Karnataka logic)

    - Bus  : Any valid road route inside Karnataka (1–800 km)
    - Metro: Only if both ends near BLR metro (<= 3.5 km) and trip <= 40 km
    - Train: Any long intercity trip (>= 120 km) inside Karnataka
    """
    avail = []
    if road_km is None:
        return avail

    # BUS – generic within Karnataka
    if has_route and in_karnataka(src_ll) and in_karnataka(dst_ll) and 1 <= road_km <= 800:
        avail.append("Bus")

    # METRO – strict Bengaluru logic
    src_metro_km = _min_dist_km(src_ll, BLR_METRO_STATIONS)
    dst_metro_km = _min_dist_km(dst_ll, BLR_METRO_STATIONS)
    if src_metro_km <= 3.5 and dst_metro_km <= 3.5 and road_km <= 40:
        avail.append("Metro")

    # TRAIN – heuristic for long intercity routes in Karnataka
    if road_km >= 120 and in_karnataka(src_ll) and in_karnataka(dst_ll):
        avail.append("Train")

    # unique
    out, seen = [], set()
    for m in avail:
        if m not in seen:
            out.append(m)
            seen.add(m)
    return out

# ------------ Weather / Traffic / Delay ------------
def get_live_weather(lat, lon):
    # stub (plug real API later if needed)
    return {"temperature_c": 24.0, "humidity_pct": 70.0, "rain_mm": 0.0}

def base_traffic_index(lat, lon, when=None):
    hour = (when or datetime.now()).hour
    return 40.0 if (8 <= hour <= 11 or 17 <= hour <= 20) else 28.0

def traffic_for_mode(base_idx, mode):
    if mode == "Bus":
        return base_idx
    if mode in ("Metro", "Train"):
        return round(base_idx * 0.2, 1)
    return base_idx

def predict_delay_minutes(features):
    dist = max(features.get("distance_km", 0.0), 0.0)
    traffic = max(features.get("traffic_index", 0.0), 0.0)
    rain = max(features.get("rain_mm", 0.0), 0.0)
    mode = features.get("mode", "Bus")
    # heuristic if model missing
    mode_factor = {"Bus": 6.0, "Metro": 3.0, "Train": 3.5, "Cab": 6.0, "Walk": 1.0}.get(mode, 5.0)
    delay = dist * (traffic / 30.0) * (1.0 + min(rain, 20.0) / 50.0) * mode_factor
    if model:
        try:
            X = [[
                dist, traffic, rain,
                features.get("humidity_pct", 0.0),
                features.get("temperature_c", 0.0),
                {"Bus": 1, "Metro": 2, "Train": 3, "Cab": 4, "Walk": 5}.get(mode, 0)
            ]]
            pred = float(model.predict(X)[0])
            return max(pred, 0.0)
        except Exception as e:
            print("Model predict error:", e)
    return max(delay, 0.0)

# ------------ Live suggestions (fast & short) ------------
@app.route("/suggest")
def suggest():
    q = (request.args.get("q") or "").strip()
    if len(q) < 3:
        return jsonify([])

    try:
        base = "https://nominatim.openstreetmap.org/search"
        KA_VIEWBOX = "74.0,11.5,78.7,18.5"  # Karnataka bbox: lonW,latS,lonE,latN

        params = {
            "format": "json",
            "q": f"{q}, {DEFAULT_STATE}, {DEFAULT_COUNTRY}",  # single call
            "addressdetails": 1,
            "limit": 12,              # we'll trim after filtering/formatting
            "viewbox": KA_VIEWBOX,    # Karnataka only
            "bounded": 1
        }
        r = requests.get(base, params=params, headers=OSM_UA, timeout=8)
        r.raise_for_status()
        data = r.json()

        out, seen = [], set()
        for d in data:
            name = d.get("display_name", "")
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            addr = d.get("address", {})
            if "karnataka" not in (addr.get("state", "") + " " + name).lower():
                continue
            seen.add(key)
            out.append(name)

        # short label A2 → first two comma parts only + cap 6
        short_list = []
        for nm in out:
            parts = [p.strip() for p in nm.split(",")]
            short = ", ".join(parts[:2]).strip() if len(parts) >= 2 else (parts[0] if parts else "")
            if short:
                short_list.append(short)

        return jsonify(sorted(short_list)[:6])
    except Exception as e:
        print("suggest error:", e)
        return jsonify([])

# ------------ Auth (Signup/Login/Logout) ------------
@app.post("/signup")
def signup():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()

    if not name or not email or not password:
        flash("Please fill all fields.", "error")
        return redirect(url_for("home") + "#auth")

    pw_hash = generate_password_hash(password)
    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?,?,?,?)",
                (name, email, pw_hash, datetime.now().isoformat(timespec="seconds"))
            )
            con.commit()
            uid = cur.lastrowid
        session["user"] = {"id": uid, "name": name, "email": email}
        flash("Account created. You are now logged in.", "ok")
    except sqlite3.IntegrityError:
        flash("That email is already registered.", "error")
    except Exception as e:
        print("signup error:", e)
        flash("Something went wrong. Please try again.", "error")

    return redirect(url_for("home") + "#auth")

@app.post("/login")
def login():
    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()
    if not email or not password:
        flash("Please enter email and password.", "error")
        return redirect(url_for("home") + "#auth")

    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            cur.execute("SELECT id, name, email, password_hash FROM users WHERE email=?", (email,))
            row = cur.fetchone()
        if not row:
            flash("No account found for that email.", "error")
            return redirect(url_for("home") + "#auth")

        uid, name, email_db, pw_hash = row
        if not check_password_hash(pw_hash, password):
            flash("Incorrect password.", "error")
            return redirect(url_for("home") + "#auth")

        session["user"] = {"id": uid, "name": name, "email": email_db}
        flash("Welcome back!", "ok")
    except Exception as e:
        print("login error:", e)
        flash("Something went wrong. Please try again.", "error")

    return redirect(url_for("home") + "#auth")

@app.get("/logout")
def logout():
    session.pop("user", None)
    flash("You have been logged out.", "ok")
    return redirect(url_for("home") + "#auth")

# ------------ Pages ------------
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/plan")
def plan():
    return render_template("plan.html")

@app.route("/about")
def about():
    return render_template("about.html")

# ------------ Public PT predict (separate page result + smart suggestions) ------------
@app.route("/predict", methods=["POST"])
def predict():
    source = (request.form.get("source") or "").strip()
    destination = (request.form.get("destination") or "").strip()
    if not source or not destination:
        return "<h3 style='color:#b00020'>Please enter both Source and Destination.</h3>"

    src_ll, dst_ll, geo_err = geocode_pair(source, destination)
    if geo_err:
        # still save attempt (empty rows)
        try:
            with sqlite3.connect(DB_PATH) as con:
                con.execute(
                    "INSERT INTO searches (ts, source, destination, road_km, modes_json, feature) VALUES (?,?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"),
                     source, destination, 0.0, json.dumps([]), "public")
                )
                con.commit()
        except Exception as e:
            print("History insert (geocode_err) error:", e)
        return f"<h3 style='color:#b00020'>{geo_err}</h3>"

    # Road route (for Bus distance/time; also helps Cab suggestion)
    route_data, route_err = tomtom_route(src_ll, dst_ll)
    road_km = None; road_poly = []; bus_time_min = None
    if not route_err and route_data:
        road_km = route_data["distance_km"]
        road_poly = route_data["coords"]
        bus_time_min = route_data["duration_min"]

    # Distances
    straight_km = round(geodesic(src_ll, dst_ll).km, 2)
    display_km = road_km if road_km is not None else straight_km

    # Live context
    weather = get_live_weather(*src_ll)
    base_tr = base_traffic_index(*src_ll)

    # Public modes (generic availability)
    has_route = route_data is not None
    modes = available_public_modes(road_km, has_route, src_ll, dst_ll)

    # Build Public rows (may be empty)
    rows = []
    for mode in modes:
        if mode == "Bus":
            if not has_route:
                continue
            dist_for_mode = road_km
            base_time = bus_time_min
        elif mode == "Metro":
            base_dist = road_km if road_km is not None else straight_km
            dist_for_mode = max(base_dist * 0.85, 2.0)
            base_time = (dist_for_mode / 32.0) * 60.0
        else:  # Train
            base_dist = road_km if road_km is not None else straight_km
            dist_for_mode = max(base_dist * 0.90, 10.0)
            base_time = (dist_for_mode / 40.0) * 60.0

        tr_idx = traffic_for_mode(base_tr, mode)
        feats = {
            "distance_km": dist_for_mode,
            "traffic_index": tr_idx,
            "rain_mm": weather["rain_mm"],
            "humidity_pct": weather["humidity_pct"],
            "temperature_c": weather["temperature_c"],
            "mode": mode
        }
        delay_min = round(predict_delay_minutes(feats), 2)
        total_time = round(max(base_time + delay_min, 1.0), 2)

        # simple fares
        if mode == "Bus":
            fare = round(5 + 2.5 * dist_for_mode, 2)
        elif mode == "Metro":
            fare = round(10 + 3.0 * dist_for_mode, 2)
        else:
            fare = round(8 + 2.0 * dist_for_mode, 2)

        delay_note = "No significant delay" if delay_min < 3 else f"~{delay_min} min delay"

        rows.append({
            "mode": mode,
            "traffic_index": tr_idx,
            "predicted_delay": delay_min,
            "total_time_min": total_time,
            "fare": fare,
            "delay_note": delay_note
        })

    # Save (even if rows == [])
    try:
        with sqlite3.connect(DB_PATH) as con:
            con.execute(
                "INSERT INTO searches (ts, source, destination, road_km, modes_json, feature) VALUES (?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"),
                 source, destination, road_km or 0.0, json.dumps(rows), "public")
            )
            con.commit()
    except Exception as e:
        print("History insert error:", e)

    # ---------- SMART SUGGESTIONS (inline cards) ----------
    suggestions = []

    # Walk suggestion (assume path factor 1.35 & speed 4.5 km/h)
    path_km = straight_km * 1.35
    walk_time_min = (path_km / 4.5) * 60.0
    # Rule: suggest walk if short OR clearly competitive
    min_public_time = min([r["total_time_min"] for r in rows], default=float("inf"))
    if path_km <= 2.5 or walk_time_min <= (min_public_time * 0.8):
        # walking delay very low impact
        feats_walk = {
            "distance_km": path_km,
            "traffic_index": base_tr * 0.1,
            "rain_mm": weather["rain_mm"],
            "humidity_pct": weather["humidity_pct"],
            "temperature_c": weather["temperature_c"],
            "mode": "Walk"
        }
        walk_delay = round(predict_delay_minutes(feats_walk) * 0.2, 2)
        walk_total = round(max(walk_time_min + walk_delay, 1.0), 2)
        suggestions.append({
            "type": "Walk",
            "title": "Walkable distance",
            "detail": f"~{round(path_km,2)} km · ~{round(walk_total)} min",
            "note": "Good option for nearby places."
        })

    # Cab suggestion (if near & faster or when no PT)
    if road_km is not None:
        cab_time_min = bus_time_min if bus_time_min is not None else (road_km / 28.0) * 60.0
        feats_cab = {
            "distance_km": road_km,
            "traffic_index": base_tr,
            "rain_mm": weather["rain_mm"],
            "humidity_pct": weather["humidity_pct"],
            "temperature_c": weather["temperature_c"],
            "mode": "Cab"
        }
        cab_delay = round(predict_delay_minutes(feats_cab), 2)
        cab_total = round(max(cab_time_min + cab_delay, 1.0), 2)
        cab_fare  = round(40 + 14.0 * road_km + 0.5 * cab_delay, 2)

        faster_than_public = cab_total < (min_public_time * 0.85 if min_public_time != float("inf") else cab_total)
        near_distance = road_km <= 20
        if (near_distance and faster_than_public) or not rows:  # show if faster OR no PT
            suggestions.append({
                "type": "Cab",
                "title": "Nearby — Cab could save time",
                "detail": f"{road_km} km · ETA ~{round(cab_total)} min",
                "note": f"Est. fare ₹{cab_fare}"
            })

    # ---------- Map payload ----------
    map_payload = {
        "src": {"lat": src_ll[0], "lon": src_ll[1], "label": f"Source: {source}"},
        "dst": {"lat": dst_ll[0], "lon": dst_ll[1], "label": f"Destination: {destination}"},
        "road_polyline": road_poly
    }

    no_modes_msg = None
    if not rows:
        no_modes_msg = "No direct Public Transport available for this route. Try nearest major bus stop / metro station nearby."

    return render_template(
        "result.html",
        feature="public",
        source=source, destination=destination,
        weather=weather, rows=rows,
        map_payload=json.dumps(map_payload),
        distance_km=display_km,
        no_modes_msg=no_modes_msg,
        suggestions=json.dumps(suggestions)  # <— pass to template
    )

# ------------ Cab (optional separate feature) ------------
@app.route("/cab")
def cab():
    return render_template("cab.html")

@app.route("/cab_predict", methods=["POST"])
def cab_predict():
    source = (request.form.get("source") or "").strip()
    destination = (request.form.get("destination") or "").strip()
    if not source or not destination:
        return "<h3 style='color:#b00020'>Please enter both Source and Destination.</h3>"

    src_ll, dst_ll, geo_err = geocode_pair(source, destination)
    if geo_err:
        try:
            with sqlite3.connect(DB_PATH) as con:
                con.execute(
                    "INSERT INTO searches (ts, source, destination, road_km, modes_json, feature) VALUES (?,?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"),
                     source, destination, 0.0, json.dumps([]), "cab")
                )
                con.commit()
        except Exception as e:
            print("History insert (cab geocode_err):", e)
        return f"<h3 style='color:#b00020'>{geo_err}</h3>"

    route_data, route_err = tomtom_route(src_ll, dst_ll)
    road_km = None; road_poly = []; base_time_min = None
    if not route_err and route_data:
        road_km = route_data["distance_km"]
        road_poly = route_data["coords"]
        base_time_min = route_data["duration_min"]

    straight_km = round(geodesic(src_ll, dst_ll).km, 2)
    display_km = road_km if road_km is not None else straight_km

    weather = get_live_weather(*src_ll)
    base_tr = base_traffic_index(*src_ll)

    rows = []
    if road_km is not None and base_time_min is not None:
        mode = "Cab"
        tr_idx = base_tr
        feats = {
            "distance_km": road_km,
            "traffic_index": tr_idx,
            "rain_mm": weather["rain_mm"],
            "humidity_pct": weather["humidity_pct"],
            "temperature_c": weather["temperature_c"],
            "mode": mode
        }
        delay_min = round(predict_delay_minutes(feats), 2)
        total_time = round(max(base_time_min + delay_min, 1.0), 2)
        fare = round(40 + 14.0 * road_km + 0.5 * delay_min, 2)
        delay_note = "No significant delay" if delay_min < 3 else f"~{delay_min} min delay"

        rows.append({
            "mode": mode,
            "traffic_index": tr_idx,
            "predicted_delay": delay_min,
            "total_time_min": total_time,
            "fare": fare,
            "delay_note": delay_note
        })

    try:
        with sqlite3.connect(DB_PATH) as con:
            con.execute(
                "INSERT INTO searches (ts, source, destination, road_km, modes_json, feature) VALUES (?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"),
                 source, destination, road_km or 0.0, json.dumps(rows), "cab")
            )
            con.commit()
    except Exception as e:
        print("History insert (cab):", e)

    map_payload = {
        "src": {"lat": src_ll[0], "lon": src_ll[1], "label": f"Source: {source}"},
        "dst": {"lat": dst_ll[0], "lon": dst_ll[1], "label": f"Destination: {destination}"},
        "road_polyline": road_poly
    }

    no_modes_msg = None if rows else "No road route found for Cab. Try a nearby landmark."
    return render_template(
        "result.html",
        feature="cab",
        source=source, destination=destination,
        weather=weather, rows=rows,
        map_payload=json.dumps(map_payload),
        distance_km=display_km,
        no_modes_msg=no_modes_msg
    )

# ------------ Walk (optional separate feature, 4.5 km/h) ------------
WALK_SPEED_KMPH = 4.5  # chosen

@app.route("/walk")
def walk():
    return render_template("walk.html")

@app.route("/walk_predict", methods=["POST"])
def walk_predict():
    source = (request.form.get("source") or "").strip()
    destination = (request.form.get("destination") or "").strip()
    if not source or not destination:
        return "<h3 style='color:#b00020'>Please enter both Source and Destination.</h3>"

    src_ll, dst_ll, geo_err = geocode_pair(source, destination)
    if geo_err:
        try:
            with sqlite3.connect(DB_PATH) as con:
                con.execute(
                    "INSERT INTO searches (ts, source, destination, road_km, modes_json, feature) VALUES (?,?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"),
                     source, destination, 0.0, json.dumps([]), "walk")
                )
                con.commit()
        except Exception as e:
            print("History insert (walk geocode_err):", e)
        return f"<h3 style='color:#b00020'>{geo_err}</h3>"

    straight_km = geodesic(src_ll, dst_ll).km
    path_km = min(straight_km * 1.35, 50.0)  # approximate path factor
    base_time_min = (path_km / WALK_SPEED_KMPH) * 60.0

    weather = get_live_weather(*src_ll)
    base_tr = base_traffic_index(*src_ll)  # minimal impact

    feats = {
        "distance_km": path_km,
        "traffic_index": base_tr * 0.1,
        "rain_mm": weather["rain_mm"],
        "humidity_pct": weather["humidity_pct"],
        "temperature_c": weather["temperature_c"],
        "mode": "Walk"
    }
    delay_min = round(predict_delay_minutes(feats) * 0.2, 2)
    total_time = round(max(base_time_min + delay_min, 1.0), 2)

    rows = [{
        "mode": "Walk",
        "traffic_index": feats["traffic_index"],
        "predicted_delay": delay_min,
        "total_time_min": total_time,
        "fare": 0.0,
        "delay_note": "Walk time varies by signals & footpaths"
    }]

    try:
        with sqlite3.connect(DB_PATH) as con:
            con.execute(
                "INSERT INTO searches (ts, source, destination, road_km, modes_json, feature) VALUES (?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"),
                 source, destination, path_km, json.dumps(rows), "walk")
            )
            con.commit()
    except Exception as e:
        print("History insert (walk):", e)

    map_payload = {
        "src": {"lat": src_ll[0], "lon": src_ll[1], "label": f"Source: {source}"},
        "dst": {"lat": dst_ll[0], "lon": dst_ll[1], "label": f"Destination: {destination}"},
        "road_polyline": []  # draw straight segment on map
    }

    return render_template(
        "result.html",
        feature="walk",
        source=source, destination=destination,
        weather=weather, rows=rows,
        map_payload=json.dumps(map_payload),
        distance_km=round(path_km, 2),
        no_modes_msg=None
    )

# ------------ Recent (with feature, delete/clear) ------------
@app.route("/recent")
def recent():
    rows = []
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT id, ts, source, destination, road_km, feature FROM searches ORDER BY id DESC LIMIT 300")
        rows = cur.fetchall()
    return render_template("recent.html", rows=rows)

@app.route("/recent/<int:sid>/delete", methods=["POST"])
def recent_delete(sid):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("DELETE FROM searches WHERE id=?", (sid,))
        con.commit()
    return redirect(url_for("recent"))

@app.route("/recent/clear", methods=["POST"])
def recent_clear():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM searches")
        con.commit()
    return redirect(url_for("recent"))

# ------------ Dashboard (feature filter) ------------
@app.route("/dashboard")
def dashboard():
    feature = request.args.get("feature", "public")  # 'public', 'cab', 'walk', or 'both'
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        if feature == "both":
            cur.execute("SELECT ts, source, destination, modes_json, road_km, feature FROM searches ORDER BY id DESC LIMIT 300")
        else:
            cur.execute("SELECT ts, source, destination, modes_json, road_km, feature FROM searches WHERE feature=? ORDER BY id DESC LIMIT 300", (feature,))
        recs = cur.fetchall()

    count = defaultdict(int)
    times = defaultdict(list)
    delays = defaultdict(list)
    fares = defaultdict(list)
    road_kms = []
    flat_rows = []

    def mean(arr): return (sum(arr)/len(arr)) if arr else 0

    for ts, src, dst, modes_json, rk, feat in recs:
        if rk is not None:
            try:
                road_kms.append(float(rk))
            except:
                pass
        if not modes_json:
            continue
        try:
            rows = json.loads(modes_json)
        except Exception:
            rows = []
        for r in rows:
            m = r.get("mode")
            if not m:
                continue
            count[m] += 1
            if "total_time_min" in r:
                times[m].append(float(r["total_time_min"]))
            if "predicted_delay" in r:
                delays[m].append(float(r["predicted_delay"]))
            if "fare" in r:
                fares[m].append(float(r["fare"]))
            flat_rows.append({
                "ts": ts, "source": src, "destination": dst,
                "mode": m,
                "total_time": r.get("total_time_min", 0),
                "delay": r.get("predicted_delay", 0),
                "fare": r.get("fare", 0),
                "feature": feat
            })

    modes_sorted = sorted(count.keys())
    chart_counts = [count[m] for m in modes_sorted]
    chart_time   = [round(mean(times[m]), 1)  for m in modes_sorted]
    chart_delay  = [round(mean(delays[m]), 1) for m in modes_sorted]

    # simple cards (fastest & lowest delay)
    fastest_mode = "-"
    lowest_delay_mode = "-"
    if modes_sorted:
        avg_time_by_mode = {m: mean(times[m]) for m in modes_sorted if times[m]}
        avg_delay_by_mode = {m: mean(delays[m]) for m in modes_sorted if delays[m]}
        if avg_time_by_mode:
            fastest_mode = min(avg_time_by_mode, key=avg_time_by_mode.get)
        if avg_delay_by_mode:
            lowest_delay_mode = min(avg_delay_by_mode, key=avg_delay_by_mode.get)

    cards = {
        "total_trips": len(recs),
        "avg_road_km": round(mean(road_kms), 1) if road_kms else 0,
        "fastest_mode": fastest_mode,
        "lowest_delay_mode": lowest_delay_mode
    }

    return render_template("dashboard.html",
        modes=modes_sorted,
        chart_counts=chart_counts,
        chart_time=chart_time,
        chart_delay=chart_delay,
        cards=cards,
        recent_rows=json.dumps(flat_rows),
        feature=feature
    )

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
