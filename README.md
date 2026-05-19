# 🚍 Public Transport Delay Prediction System

A Flask-based Machine Learning web application that predicts public transport delays using transportation datasets, weather conditions, traffic analysis, and route-based features.

This project provides an intelligent delay prediction system with user authentication, admin dashboard, search history tracking, feedback management, and real-time route-based analysis.

---

# 📌 Project Overview

The **Public Transport Delay Prediction System** is designed to analyze and predict delays in public transportation systems such as buses and metro services.

The system combines:

* Machine Learning prediction models
* Flask web development
* Transportation data preprocessing
* Weather and traffic integration
* Route distance analysis
* User management system
* Admin dashboard functionalities

The application helps users estimate transport delays based on different travel conditions and route parameters.

---

# ✨ Key Features

## 👤 User Features

✅ User Registration & Login System

✅ Public Transport Delay Prediction

✅ Route-based distance analysis

✅ Transport mode selection

✅ Search history tracking

✅ Feedback submission system

✅ Responsive web interface

---

## 🔐 Admin Features

✅ Admin Login Dashboard

✅ View User Search Records

✅ Monitor Application Usage

✅ Manage Feedback Data

---

## 🤖 Machine Learning Features

✅ Trained ML Model Integration (`transport_delay_model.pkl`)

✅ Heuristic fallback prediction system

✅ Data preprocessing pipeline

✅ Multi-dataset transport analysis

---

# 🛠️ Tech Stack

## Frontend

* HTML5
* CSS3
* JavaScript
* Bootstrap

## Backend

* Python
* Flask

## Machine Learning & Data Processing

* Pandas
* NumPy
* Scikit-learn
* Pickle

## APIs & Libraries

* OpenStreetMap (Nominatim API)
* TomTom Traffic API
* OpenWeather API
* Geopy

## Database

* SQLite

---

# 📂 Project Structure

```bash
transport_delay_flask/
│
├── flask_app/
│   ├── data/
│   │   ├── app.db
│   │   ├── final_dataset.csv
│   │   └── settings.json
│   │
│   ├── models/
│   │   └── transport_delay_model.pkl
│   │
│   ├── static/
│   │   └── hero.png
│   │
│   ├── templates/
│   │   ├── about.html
│   │   ├── admin_dashboard.html
│   │   ├── admin_login.html
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── forgot_password.html
│   │   ├── home.html
│   │   ├── login.html
│   │   ├── profile.html
│   │   ├── register.html
│   │   └── reset_password.html
│   │
│   ├── .env
│   ├── app.py
│   └── requirements.txt
│
├── preprocessing/
│   ├── processed/
│   │   ├── bus_delay_dataset.csv
│   │   ├── combined_transport.csv
│   │   ├── event_calendar.csv
│   │   ├── final_dataset.csv
│   │   └── metro_delay_dataset.csv
│   │
│   ├── raw/
│   └── scripts/
│       ├── add_event_calendar.py
│       ├── add_traffic_data.py
│       ├── add_weather_data.py
│       ├── clean_bus_data.py
│       └── clean_metro_data.py
│
├── .gitignore
└── README.md
```

---

# ⚙️ System Workflow

## 1️⃣ Data Collection

Transportation datasets for buses and metro systems are collected and stored.

---

## 2️⃣ Data Preprocessing

The preprocessing pipeline includes:

* Cleaning raw transport data
* Merging multiple datasets
* Weather data integration
* Traffic data integration
* Event calendar generation
* Feature engineering

Scripts used:

```bash
add_weather_data.py
add_traffic_data.py
add_event_calendar.py
clean_bus_data.py
clean_metro_data.py
```

---

## 3️⃣ Machine Learning Model

A trained machine learning model (`transport_delay_model.pkl`) is used to predict delays.

If the model is unavailable, the system automatically switches to a heuristic fallback prediction method.

---

## 4️⃣ Prediction System

The application predicts delays using:

* Source & destination
* Distance between locations
* Weather conditions
* Traffic conditions
* Transport mode

---

# 🔐 Authentication System

The application includes:

* User registration
* Secure password hashing
* Login authentication
* Password reset functionality
* Session management
* Admin authentication

---

# 🌍 External API Integrations

## OpenStreetMap API

Used for geocoding and location handling.

## TomTom Traffic API

Used for traffic-based route analysis.

## OpenWeather API

Used for weather condition analysis.

---

# ⚙️ Installation & Setup

## 1️⃣ Clone the Repository

```bash
git clone https://github.com/vanithaP26/PublicTransportDelayPrediction.git
```

---

## 2️⃣ Navigate to Project Folder

```bash
cd PublicTransportDelayPrediction
```

---

## 3️⃣ Create Virtual Environment

### Windows

```bash
python -m venv venv
venv\Scripts\activate
```

### Linux / Mac

```bash
python3 -m venv venv
source venv/bin/activate
```

---

## 4️⃣ Install Dependencies

```bash
pip install -r flask_app/requirements.txt
```

---

## 5️⃣ Configure Environment Variables

Create a `.env` file inside `flask_app/`.

Example:

```env
TOMTOM_API_KEY=your_api_key
OPENWEATHER_KEY=your_api_key
FLASK_SECRET_KEY=your_secret_key
MAIL_FROM=your_email
MAIL_PASSWORD=your_password
```

---

## 6️⃣ Run the Application

```bash
python flask_app/app.py
```

---

# 🌐 Application Access

Open your browser and visit:

```bash
http://127.0.0.1:5000
```

---

# 📊 Database Tables

The SQLite database includes:

* `users`
* `admins`
* `searches`
* `feedback`

---

# 📈 Future Enhancements

* Real-time GPS integration
* Live transport tracking
* Cloud deployment
* Advanced analytics dashboard
* Deep learning prediction models
* Mobile application support
* Smart city integration

---

# 🧪 Sample Use Cases

* Predicting bus delays
* Metro delay analysis
* Transportation analytics
* Traffic-aware route estimation
* Smart mobility solutions

---

# 🔒 .gitignore Configuration

Large datasets, virtual environments, and database files are ignored using `.gitignore`.

```gitignore
venv/
*.db
*.csv
__pycache__/
.env
```

---

# 👩‍💻 Author

## Vanitha P

GitHub:

[https://github.com/vanithaP26](https://github.com/vanithaP26)

---

# 📜 License

This project is developed for educational, academic, and learning purposes.

---

# ⭐ Support

If you like this project:

⭐ Star the repository

🍴 Fork the project

📢 Share with others

---

# 🚀 Conclusion

The Public Transport Delay Prediction System demonstrates the practical implementation of Machine Learning, Flask web development, transportation analytics, and intelligent prediction systems. The project integrates real-world APIs, preprocessing pipelines, database management, authentication systems, and ML-based prediction into a complete end-to-end smart transportation solution.
