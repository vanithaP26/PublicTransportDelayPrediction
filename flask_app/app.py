# app.py — updated full file (drop-in)
import os
import json
import pickle
import pathlib
import sqlite3
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone
from collections import defaultdict

from flask import (
    Flask, render_template, abort, request, redirect, url_for,
    jsonify, session, flash
)

import requests
from geopy.distance import geodesic
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from functools import wraps
from flask import session, redirect, url_for, flash
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            flash("Please login to continue", "error")
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated_function


# timezone helper (Python 3.9+). If using older Python, replace with pytz.
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

load_dotenv()

# --- Config keys
TOMTOM_KEY = os.getenv("TOMTOM_API_KEY", "").strip()
MODEL_PATH = "models/transport_delay_model.pkl"
OPENWEATHER_KEY = os.getenv("OPENWEATHER_KEY", "").strip()

MAIL_FROM = os.getenv("MAIL_FROM", "").strip()
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "").strip()
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com").strip()
MAIL_PORT = int(os.getenv("MAIL_PORT", 587))

SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")
# serializer for reset tokens
serializer = URLSafeTimedSerializer(SECRET_KEY)

# --- Flask app
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = SECRET_KEY

# --- paths & DB
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
            modes_json TEXT,
            feature TEXT DEFAULT 'public',
            user_id INTEGER
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        con.commit()

init_db()

# --- optional model load
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

# --- Geocoding helpers (OSM)
DEFAULT_CITY  = "Bengaluru"
DEFAULT_STATE = "Karnataka"
DEFAULT_COUNTRY = "India"
OSM_UA = {"User-Agent": "public-pt-delay-app (demo)"}

# --- Hard-coded fallback locations (for demo reliability)
FALLBACK_PLACES = {
    "majestic": (12.9789, 77.5715, "Majestic, Bengaluru, Karnataka, India"),
    "majestic, bengaluru": (12.9789, 77.5715, "Majestic, Bengaluru, Karnataka, India"),
    "ksr bengaluru": (12.9765, 77.5726, "KSR Bengaluru (Majestic), Karnataka, India"),
    "koppal": (15.3500, 76.1500, "Koppal, Karnataka, India"),
    "nadaprabhu kempegowda station": (12.9765, 77.5726, "Nadaprabhu Kempegowda Station (Majestic), Bengaluru, India"),
    "indiranagar": (12.9784, 77.6408, "Indiranagar, Bengaluru, Karnataka, India"),
}

# ====== Robust geocoding helpers (replace existing versions) ======
def _osm_try(query: str, prox=None):
    try:
        if not query:
            return None

        base = "https://nominatim.openstreetmap.org/search"
        params = {"format": "json", "q": query, "limit": 1}

        if prox:
            lat, lon = prox
            d = 0.3
            params.update({
                "viewbox": f"{lon-d},{lat+d},{lon+d},{lat-d}",
                "bounded": 1
            })

        r = requests.get(
            base,
            params=params,
            headers=OSM_UA,
            timeout=10,
            verify=False
        )
        r.raise_for_status()
        data = r.json()

        if not data:
            return None

        item = data[0]
        return float(item["lat"]), float(item["lon"]), item.get("display_name", "")

    except Exception as e:
        print("[geocode] OSM error:", e)
        return None

          

def _geo_strong_karnataka(q: str, prox=None):
    """Try a sequence of query forms: detailed → region → country → raw; return first match."""
    if not q:
        return None
    q = q.strip()
    attempts = [
        f"{q}, {DEFAULT_CITY}, {DEFAULT_STATE}, {DEFAULT_COUNTRY}",
        f"{q}, {DEFAULT_STATE}, {DEFAULT_COUNTRY}",
        f"{q}, {DEFAULT_COUNTRY}",
        q,
    ]
    seen = set()
    for a in attempts:
        if not a or a in seen:
            continue
        seen.add(a)
        # try the exact attempt
        res = _osm_try(a, prox=prox)
        if res:
            return res
        # also try a short form (first two parts)
        parts = [p.strip() for p in a.split(",") if p.strip()]
        if len(parts) >= 2:
            short = ", ".join(parts[:2])
            if short not in seen:
                seen.add(short)
                res2 = _osm_try(short, prox=prox)
                if res2:
                    return res2
    return None

def _geo_with_fallback(text: str, prox=None):
    """Try OSM (multiple variants), then FALLBACK_PLACES. Return (lat, lon, label) or None."""
    if not text:
        return None

    # normalize input
    try:
        text_norm = text.strip().lower()
    except Exception:
        text_norm = str(text).strip().lower()

    # remove noisy tokens that commonly appear in display names
    for trash in ["station", "stn", "bengaluru central city corporation", "city corporation", "railway", "railway station"]:
        text_norm = text_norm.replace(trash, "").strip()

    # 1) try the original user text (strong attempts)
    res = _geo_strong_karnataka(text, prox=prox)
    if res:
        return res

    # 2) try the cleaned/normalized text (if changed)
    if text_norm and text_norm != text.lower():
        res2 = _geo_strong_karnataka(text_norm, prox=prox)
        if res2:
            return res2

    # 3) fallback dictionary: ensure we compare normalized keys safely
    if isinstance(FALLBACK_PLACES, dict):
        # try exact match on normalized key
        for fk, val in FALLBACK_PLACES.items():
            if not isinstance(fk, str):
                continue
            if fk.strip().lower() == text_norm:
                return val
        # try substring matches (e.g. user typed 'majestic station')
        for fk, val in FALLBACK_PLACES.items():
            if not isinstance(fk, str):
                continue
            fk_norm = fk.strip().lower()
            if fk_norm in text_norm or text_norm in fk_norm:
                return val

    # nothing found
    print(f"[geocode] no match for text={text!r} (norm={text_norm!r})")
    return None

def geocode_pair(src_text: str, dst_text: str):
    try:
        s = _geo_with_fallback(src_text)
        d = _geo_with_fallback(dst_text)
    except Exception as e:
        print("[geocode] error:", e)
        return None, None, None

    if not s or not d:
        return None, None, None

    return (s[0], s[1]), (d[0], d[1]), None

    s_ll, d_ll = (s[0], s[1]), (d[0], d[1])

    # if very far, bias a second pass toward each other
    try:
        if geodesic(s_ll, d_ll).km > 120:
            s2 = _geo_with_fallback(src_text, prox=d_ll) or s
            d2 = _geo_with_fallback(dst_text, prox=s_ll) or d
            s_ll, d_ll = (s2[0], s2[1]), (d2[0], d2[1])
            if geodesic(s_ll, d_ll).km > 800:
                return None, None, ("Those places seem extremely far apart. Please add city/district names for clarity.")
    except Exception as e:
        print(f"[geocode] geodesic check error: {e}")

    return s_ll, d_ll, None
# ====== end replacements ======

# --- TomTom route (live traffic)
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

# --- Availability helpers
BLR_METRO_STATIONS = [
    (12.9789, 77.5715), (13.0186, 77.5560), (12.9784, 77.6408),
    (12.9780, 77.6512), (12.9951, 77.6974), (13.0097, 77.6956),
    (12.9184, 77.5735), (13.0509, 77.5304),
]
def _min_dist_km(pt, stations):
    best = 1e9
    for s in stations:
        d = geodesic(pt, s).km
        if d < best: best = d
    return best

def in_karnataka(pt):
    lat, lon = pt
    return 11.5 <= lat <= 18.5 and 74.0 <= lon <= 78.7

def available_public_modes(road_km, has_route, src_ll, dst_ll):
    modes = []

    # BUS: only if road route exists
    if has_route and road_km and road_km >= 1:
        modes.append("Bus")

    # METRO: only inside Bengaluru & near stations
    if road_km and 2 <= road_km <= 40:
        src_m = _min_dist_km(src_ll, BLR_METRO_STATIONS)
        dst_m = _min_dist_km(dst_ll, BLR_METRO_STATIONS)
        if src_m <= 2 and dst_m <= 2:
            modes.append("Metro")

    # TRAIN: only long distance
    if road_km and road_km >= 120:
        modes.append("Train")

    return modes

# --- Weather & traffic functions (use requested time)
def _unix_ts(dt):
    return int(dt.replace(tzinfo=timezone.utc).timestamp())

def get_live_weather(lat, lon, when=None, tz_name="Asia/Kolkata"):
    """
    Return: {"temperature_c":..., "humidity_pct":..., "rain_mm":...}

    Behavior:
    - If OPENWEATHER_KEY present, call 3-hour forecast (/data/2.5/forecast)
      and pick the forecast item closest to requested 'when' (future or near-past).
    - If that fails, fallback to current weather (/data/2.5/weather) or a heuristic.
    """
    def _heuristic(dt):
        hour = (dt or datetime.now()).hour
        temp = 26.0 - 3.0 * max(0, (hour - 14) / 10)
        hum = 65.0 if (6 <= hour <= 9) else 55.0
        rain = 0.0
        if 6 <= (dt or datetime.now()).month <= 9 and hour in range(15, 19):
            rain = 0.7
        return {"temperature_c": round(temp, 1), "humidity_pct": round(hum, 1), "rain_mm": round(rain, 2)}

    when_dt = when or datetime.now()
    # attach tz if ZoneInfo available and naive
    if ZoneInfo and when_dt.tzinfo is None:
        try:
            when_dt = when_dt.replace(tzinfo=ZoneInfo(tz_name))
        except Exception:
            pass

    if not OPENWEATHER_KEY:
        print("get_live_weather: OPENWEATHER_KEY not set — using heuristic")
        return _heuristic(when_dt)

    try:
        # 1) Try 3-hour forecast (5 day) which contains list[] of forecast items
        base_fc = "https://api.openweathermap.org/data/2.5/forecast"
        params_fc = {"lat": lat, "lon": lon, "appid": OPENWEATHER_KEY, "units": "metric"}
        r = requests.get(base_fc, params=params_fc, timeout=8)
        r.raise_for_status()
        fc = r.json()
        # DEBUG print optionally
        # print("DEBUG FORECAST DATA KEYS:", fc.keys())

        # If forecast list is present, find the item with dt closest to when_dt
        if "list" in fc and fc["list"]:
            target_ts = int(when_dt.timestamp())
            best = None
            best_diff = 10**18
            for item in fc["list"]:
                # item['dt'] is unix ts (UTC)
                diff = abs(item.get("dt", 0) - target_ts)
                if diff < best_diff:
                    best_diff = diff
                    best = item
            if best:
                # temperature/humidity location inside main
                temp = best.get("main", {}).get("temp", None)
                hum = best.get("main", {}).get("humidity", None)
                rain_mm = 0.0
                # rain may be under 'rain' with "3h" key for 3-hr accumulation
                if best.get("rain") and isinstance(best.get("rain"), dict):
                    # forecast rain often in '3h'
                    rain_mm = float(best["rain"].get("3h", best["rain"].get("1h", 0.0)))
                # If temp/hum missing, fallback to fc['city']['...'] or later to current
                if temp is not None and hum is not None:
                    return {"temperature_c": round(float(temp), 1),
                            "humidity_pct": round(float(hum), 1),
                            "rain_mm": round(rain_mm, 2)}

        # 2) fallback to current weather endpoint if forecast didn't help
        base_cur = "https://api.openweathermap.org/data/2.5/weather"
        params_cur = {"lat": lat, "lon": lon, "appid": OPENWEATHER_KEY, "units": "metric"}
        r2 = requests.get(base_cur, params=params_cur, timeout=6)
        r2.raise_for_status()
        cur = r2.json()
        # print("DEBUG CURRENT DATA:", cur)
        temp = cur.get("main", {}).get("temp", 24.0)
        hum = cur.get("main", {}).get("humidity", 60.0)
        rain_mm = 0.0
        # current weather sometimes has rain in 'rain' -> '1h'
        if cur.get("rain") and isinstance(cur.get("rain"), dict):
            rain_mm = float(cur["rain"].get("1h", 0.0))
        return {"temperature_c": round(temp, 1),
                "humidity_pct": round(hum, 1),
                "rain_mm": round(rain_mm, 2)}
    except Exception as e:
        print("weather fetch error:", e)
        return _heuristic(when_dt)


def base_traffic_index(lat, lon, when=None):
    """
    Simple heuristic traffic index (0-100) based on requested 'when'.
    """
    dt = when or datetime.now()
    if ZoneInfo and dt.tzinfo is None:
        try:
            dt = dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
        except Exception:
            pass
    hour = dt.hour
    dow = dt.weekday()
    if dow < 5:  # weekday
        if 8 <= hour <= 11: return 60.0
        if 17 <= hour <= 20: return 68.0
        if 12 <= hour < 17: return 36.0
        if 6 <= hour < 8: return 30.0
        return 22.0
    else:
        if 9 <= hour <= 18: return 30.0
        return 18.0

# --- Delay prediction
def traffic_for_mode(base_idx, mode):
    if mode == "Bus": return base_idx
    if mode in ("Metro", "Train"): return round(base_idx * 0.2, 1)
    return base_idx

def predict_delay_minutes(features):
    dist = max(features.get("distance_km", 0.0), 0.0)
    traffic = max(features.get("traffic_index", 0.0), 0.0)
    rain = max(features.get("rain_mm", 0.0), 0.0)
    mode = features.get("mode", "Bus")
    mode_factor = {"Bus":1.2,"Metro":0.7,"Train":0.8}.get(mode,1.0)

    if model:
        try:
            X = [[
                dist, traffic, rain,
                features.get("humidity_pct", 0.0),
                features.get("temperature_c", 0.0),
                {"Bus":1,"Metro":2,"Train":3}.get(mode,0)
            ]]
            base_pred = float(model.predict(X)[0])
            return max(base_pred * mode_factor, 0.0)
        except Exception as e:
            print("Model predict error:", e)

    base = (dist * traffic) / 200.0
    weather_factor = 1.0 + min(rain, 20.0) / 100.0
    delay = base * weather_factor * mode_factor
    return max(delay, 0.0)

# --- Email helper for reset links
def send_email(to_email, subject, body):
    if not MAIL_FROM or not MAIL_PASSWORD:
        print("send_email: mail config missing")
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = MAIL_FROM
        msg["To"] = to_email
        msg.set_content(body)
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(MAIL_FROM, MAIL_PASSWORD)
            server.send_message(msg)
        print("Email sent to", to_email)
        return True
    except Exception as e:
        print("Email send error:", repr(e))
        return False

# --- Live suggestions route (same as yours)
@app.route("/suggest")
def suggest():
    q = (request.args.get("q") or "").strip()
    if len(q) < 3:
        return jsonify([])
    try:
        base = "https://nominatim.openstreetmap.org/search"
        KA_VIEWBOX = "74.0,11.5,78.7,18.5"
        params = {
            "format":"json","q":f"{q}, {DEFAULT_STATE}, {DEFAULT_COUNTRY}",
            "addressdetails":1,"limit":12,"viewbox":KA_VIEWBOX,"bounded":1
        }
        r = requests.get(base, params=params, headers=OSM_UA, timeout=8)
        r.raise_for_status()
        data = r.json()
        out, seen = [], set()
        for d in data:
            name = d.get("display_name","")
            if not name: continue
            key = name.lower()
            if key in seen: continue
            addr = d.get("address",{})
            if "karnataka" not in (addr.get("state","") + " " + name).lower():
                continue
            seen.add(key); out.append(name)
        short_list = []
        for nm in out:
            parts = [p.strip() for p in nm.split(",")]
            short = ", ".join(parts[:2]).strip() if len(parts) >= 2 else (parts[0] if parts else "")
            if short: short_list.append(short)
        return jsonify(sorted(short_list)[:6])
    except Exception as e:
        print("suggest error:", e)
        return jsonify([])

# --- Auth (signup/login/logout)
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
            cur.execute("INSERT INTO users (name,email,password_hash,created_at) VALUES (?,?,?,?)",
                        (name,email,pw_hash,datetime.now().isoformat(timespec="seconds")))
            con.commit()
            uid = cur.lastrowid
        session["user"] = {"id": uid, "name": name, "email": email}
        flash("Account created. Please login.", "ok")
        # After registration go to login (user asked): clear session and redirect to home auth
        session.pop("user", None)
        return redirect(url_for("home") + "#auth")
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
        return redirect(url_for("plan"))

    try:
        with sqlite3.connect(DB_PATH) as con:
            cur = con.cursor()
            cur.execute("SELECT id,name,email,password_hash FROM users WHERE email=?", (email,))
            row = cur.fetchone()
        if not row:
            flash("No account found for that email.", "error")
            return redirect(url_for("plan"))
        uid, name, email_db, pw_hash = row
        if not check_password_hash(pw_hash, password):
            flash("Incorrect password.", "error")
            return redirect(url_for("plan"))
        session["user"] = {"id": uid, "name": name, "email": email_db}
        flash("Welcome back!", "ok")
    except Exception as e:
        print("login error:", e)
        flash("Something went wrong. Please try again.", "error")
    return redirect(url_for("login_page"))

@app.get("/logout")
def logout():
    session.pop("user", None)
    flash("You have been logged out.", "ok")
    return redirect(url_for("login_page"))

# show the login form (GET)
@app.get("/login")
def login_page():
    # If user already logged in, send to plan
    if session.get("user"):
        return redirect(url_for("plan"))
    return render_template("login.html")

# show the signup form (GET)
@app.get("/signup")
def signup_page():
    if session.get("user"):
        return redirect(url_for("plan"))
    return render_template("signup.html")



# --- Pages ---
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/plan")
@login_required
def plan():
    return render_template("plan.html")

@app.route("/about")
def about():
    return render_template("about.html")

# --- Predict (POST) and predict_view
@app.route("/predict", methods=["POST"])
def predict():
    road_km = None
    modes = []

    source = (request.form.get("source") or "").strip()
    destination = (request.form.get("destination") or "").strip()
    if not source or not destination:
        return "<h3 style='color:#b00020'>Please enter both Source and Destination.</h3>"

    # parse date/hour from form (plan.html uses input type=date and hour number)
    date_str = (request.form.get("date") or "").strip()
    hour_str = (request.form.get("hour") or "").strip()
    when_dt = None
    try:
        if date_str:
            # date input is yyyy-mm-dd
            parts = [int(x) for x in date_str.split("-")]
            y,m,d = parts[0], parts[1], parts[2]
            h = int(hour_str) if hour_str.isdigit() else 9
            when_dt = datetime(year=y, month=m, day=d, hour=h)
        else:
            when_dt = datetime.now()
    except Exception:
        when_dt = datetime.now()

    src_ll, dst_ll, geo_err = geocode_pair(source, destination)

    if not src_ll or not dst_ll:
        return render_template(
            "result.html",
            feature="public",
            source=source,
            destination=destination,
            weather={},
            rows=[],
            map_payload=json.dumps({}),
            distance_km=0,
            no_modes_msg="No public transport available for this route.",
            suggestions=json.dumps([])
        )

    road_poly = []
    
    route_data, route_err = tomtom_route(src_ll, dst_ll)

    road_km = None
    road_poly = []
    bus_time_min = None

    if route_data:
        road_km = route_data["distance_km"]
        road_poly = route_data["coords"]
        bus_time_min = route_data["duration_min"]

    straight_km = round(geodesic(src_ll, dst_ll).km, 2)
    display_km = road_km if road_km else straight_km


    # use weather & traffic for requested travel time
    try:
        weather_src = get_live_weather(src_ll[0], src_ll[1], when=when_dt)
    except Exception as e:
        print("weather_src error:", e); weather_src = {"temperature_c": 24.0, "humidity_pct": 60.0, "rain_mm": 0.0}
    try:
        weather_dst = get_live_weather(dst_ll[0], dst_ll[1], when=when_dt)
    except Exception as e:
        print("weather_dst error:", e); weather_dst = {"temperature_c": 24.0, "humidity_pct": 60.0, "rain_mm": 0.0}

    # Average temps/humidity and sum/average rain (rain more conservative: take max)
    temperature_c = round(((weather_src.get("temperature_c", 24.0) + weather_dst.get("temperature_c", 24.0)) / 2.0), 1)
    humidity_pct  = round(((weather_src.get("humidity_pct", 60.0) + weather_dst.get("humidity_pct", 60.0)) / 2.0), 1)
    # rain can be localized — use max so any rain along route increases delay appropriately
    rain_mm = round(max(weather_src.get("rain_mm", 0.0), weather_dst.get("rain_mm", 0.0)), 2)

    weather = {"temperature_c": temperature_c, "humidity_pct": humidity_pct, "rain_mm": rain_mm}

    # Traffic: compute for both source and destination and use a conservative index (max)
    try:
        base_tr_src = base_traffic_index(src_ll[0], src_ll[1], when=when_dt)
    except Exception as e:
        print("base_tr_src err:", e); base_tr_src = base_traffic_index(src_ll[0], src_ll[1])

    try:
        base_tr_dst = base_traffic_index(dst_ll[0], dst_ll[1], when=when_dt)
    except Exception as e:
        print("base_tr_dst err:", e); base_tr_dst = base_traffic_index(dst_ll[0], dst_ll[1])

    # Conservative: route traffic is the worse of the two ends (you can also average or weight by distance)
    base_tr = max(base_tr_src, base_tr_dst)

    has_route = route_data is not None
    modes = available_public_modes(road_km, has_route, src_ll, dst_ll)
    if not modes:
        return render_template(
            "result.html",
            feature="public",
            source=source,
            destination=destination,
            weather=weather,
            rows=[],
            map_payload=json.dumps({}),
            distance_km=display_km,
            no_modes_msg="No public transport exists between the selected locations.",
            suggestions=json.dumps([])
        )


    rows = []
    for mode in modes:
        if mode == "Bus":
            if not has_route: continue
            dist_for_mode = road_km; base_time = bus_time_min
        elif mode == "Metro":
            base_dist = road_km if road_km is not None else straight_km
            dist_for_mode = max(base_dist * 0.85, 2.0)
            base_time = (dist_for_mode / 32.0) * 60.0
        else:
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

    # Save history
    try:
        user_id = session["user"]["id"]

        with sqlite3.connect(DB_PATH) as con:
            con.execute(
            """
            INSERT INTO searches (
                ts, source, destination, road_km, modes_json, feature, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                source,
                destination,
                road_km or 0.0,
                json.dumps(rows),
                "public",
                user_id
            )
        )
        con.commit()
    except Exception as e:
        print("History insert error:", e)

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
        suggestions=json.dumps([])
    )

@app.route("/predict/view/<int:sid>")
def predict_view(sid):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("SELECT ts, source, destination, road_km, modes_json FROM searches WHERE id=?", (sid,))
        row = cur.fetchone()
    if not row:
        return "<h3>Trip not found</h3>"
    ts, source, destination, road_km, modes_json = row
    try:
        modes = json.loads(modes_json) if modes_json else []
    except Exception:
        modes = []
    src_ll, dst_ll, geo_err = geocode_pair(source, destination)
    map_payload = None
    if not geo_err and src_ll and dst_ll:
        map_payload = {"src": {"lat": src_ll[0], "lon": src_ll[1], "label": f"Source: {source}"},
                       "dst": {"lat": dst_ll[0], "lon": dst_ll[1], "label": f"Destination: {destination}"},
                       "road_polyline": []}
    weather = get_live_weather(*src_ll) if src_ll else {}
    return render_template("result.html", feature="public", source=source, destination=destination,
                           distance_km=road_km, weather=weather, rows=modes,
                           map_payload=json.dumps(map_payload), no_modes_msg=None, suggestions=json.dumps([]))

# --- Recent / view / delete / clear
@app.route("/recent")
@login_required
def recent():
    user_id = session["user"]["id"] 
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, ts, source, destination, road_km
            FROM searches
            WHERE user_id = ?
            ORDER BY id DESC
        """, (user_id,))

        rows = cur.fetchall()
    parsed_rows = []
    for rid, ts, src, dst, road_km in rows:
        try:
            ts_dt = datetime.fromisoformat(ts)
        except Exception:
            ts_dt = ts
        parsed_rows.append((rid, ts_dt, src, dst, road_km))
    return render_template("recent.html", rows=parsed_rows)

@app.post("/recent/<int:sid>/delete")
def recent_delete(sid):
    user_id = session["user"]["id"]
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
            DELETE FROM searches
            WHERE id = ? AND user_id = ?
        """, (sid, user_id))
        con.commit()
    return redirect(url_for("recent"))

@app.post("/recent/clear")
def recent_clear():
    user_id = session["user"]["id"]
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "DELETE FROM searches WHERE user_id = ?",
            (user_id,)
        )
        con.commit()
    return redirect(url_for("recent"))

@app.route("/recent/<int:sid>")
def recent_view(sid):
    user_id = session["user"]["id"]
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id, ts, source, destination, road_km, modes_json
            FROM searches
            WHERE id = ? AND user_id = ?
        """, (sid, user_id))
        row = cur.fetchone()
    if not row:
        abort(404)
    rid, ts, src, dst, road_km, modes_json = row
    try:
        ts_dt = datetime.fromisoformat(ts)
    except Exception:
        ts_dt = ts
    try:
        modes = json.loads(modes_json) if modes_json else []
    except Exception:
        modes = []
    return render_template("recent_view.html", rid=rid, ts=ts_dt, source=src, destination=dst, road_km=road_km, modes=modes)

# --- Dashboard
@app.route("/dashboard")
@login_required
def dashboard():
    feature = request.args.get("feature", "public")
    user_id = session["user"]["id"]

    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        if feature == "both":
            recs = con.execute("""
                SELECT ts, source, destination, modes_json, road_km, feature
                FROM searches
                WHERE user_id = ?               
                ORDER BY id DESC
                LIMIT 300
            """, (user_id,)).fetchall()
        else:
            recs = con.execute("""
                SELECT ts, source, destination, modes_json, road_km, feature
                FROM searches
                WHERE  user_id = ? AND feature=?
                ORDER BY id DESC
                LIMIT 300
            """, (user_id,feature)).fetchall()

    # -------------------------------
    # AGGREGATION CONTAINERS
    # -------------------------------
    mode_count   = defaultdict(int)
    mode_times   = defaultdict(list)
    mode_delays  = defaultdict(list)
    road_kms     = []
    flat_rows    = []

    def mean(arr):
        return round(sum(arr) / len(arr), 2) if arr else 0

    # -------------------------------
    # PROCESS DATABASE ROWS
    # -------------------------------
    for row in recs:
        ts  = row["ts"]
        src = row["source"]
        dst = row["destination"]
        rk  = row["road_km"]
        feat = row["feature"]

        if rk is not None:
            try:
                road_kms.append(float(rk))
            except:
                pass

        if not row["modes_json"]:
            continue

        try:
            modes = json.loads(row["modes_json"])
        except Exception:
            modes = []

        for m in modes:
            mode = m.get("mode")
            if not mode:
                continue

            mode_count[mode] += 1

            if m.get("total_time_min") is not None:
                mode_times[mode].append(float(m["total_time_min"]))

            if m.get("predicted_delay") is not None:
                mode_delays[mode].append(float(m["predicted_delay"]))

            flat_rows.append({
                "ts": ts[:10] if ts else "",
                "source": src,
                "destination": dst,
                "mode": mode,
                "delay": m.get("predicted_delay"),
                "total_time": m.get("total_time_min"),
                "feature": feat
            })

    # -------------------------------
    # KPI CALCULATIONS
    # -------------------------------
    total_trips = len(recs)

    all_times = []
    for v in mode_times.values():
        all_times.extend(v)

    avg_time = mean(all_times)

    fastest_mode = "-"
    lowest_delay_mode = "-"

    if mode_times:
        fastest_mode = min(mode_times, key=lambda k: mean(mode_times[k]) if mode_times[k] else 999)

    if mode_delays:
        lowest_delay_mode = min(mode_delays, key=lambda k: mean(mode_delays[k]) if mode_delays[k] else 999)

    # -------------------------------
    # CHART DATA
    # -------------------------------
    modes_sorted = sorted(mode_count.keys())

    chart_counts = [mode_count[m] for m in modes_sorted]
    chart_time   = [mean(mode_times[m]) for m in modes_sorted]
    chart_delay  = [mean(mode_delays[m]) for m in modes_sorted]

    # -------------------------------
    # KPI OBJECT
    # -------------------------------
    cards = {
        "total_trips": total_trips,
        "avg_time": avg_time,
        "fastest_mode": fastest_mode,
        "lowest_delay_mode": lowest_delay_mode
    }

    print("DASHBOARD KPI:", cards)

    # -------------------------------
    # RENDER TEMPLATE
    # -------------------------------
    return render_template(
        "dashboard.html",
        feature=feature,
        cards=cards,
        modes=modes_sorted,
        chart_counts=chart_counts,
        chart_time=chart_time,
        chart_delay=chart_delay,
        recent_rows=flat_rows
    )


if __name__ == "__main__":
    # helpful: print available endpoints when server starts (debug)
    print("App starting. Flask endpoints:")
    for rule in app.url_map.iter_rules():
        print(rule.endpoint, "->", rule)
    app.run(debug=True, host="127.0.0.1", port=5000)
