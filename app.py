
from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
import sqlite3
import numpy as np
import librosa
import noisereduce as nr
import tensorflow as tf
import shutil
import hashlib
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import cv2
import base64
from PIL import Image
import io
from ultralytics import YOLO
import tempfile
import time
import uvicorn

app = FastAPI(title="PETPULSE - Pet Health Monitoring System")

EMAIL_CONFIG = {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_username": "pet2pulse",
    "smtp_password": "wnhzoodeu2454698757xj",
    "sender_email": "pet2pulse@gmail.com",
    "default_subject": "PETSTRESS Alert - Stress Detected"
}

os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)
os.makedirs("uploads", exist_ok=True)
os.makedirs("database", exist_ok=True)
os.makedirs("models", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_PATH = "database/events.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL, email TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS stress_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, stress_class TEXT NOT NULL,
        stress_intensity INTEGER, confidence FLOAT, audio_path TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS wound_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, wound_types TEXT,
        severity TEXT, confidence FLOAT, image_path TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_settings (
        user_id INTEGER PRIMARY KEY, alert_threshold INTEGER DEFAULT 3,
        email_notifications BOOLEAN DEFAULT 1, recipient_email TEXT,
        pet_name TEXT, pet_type TEXT DEFAULT 'dog', pet_age INTEGER,
        daily_report BOOLEAN DEFAULT 0, weekly_report BOOLEAN DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (id))''')
    admin_hash = hashlib.sha256("petstress123".encode()).hexdigest()
    cursor.execute('INSERT OR IGNORE INTO users (username, password_hash, email) VALUES (?, ?, ?)',
                   ("admin", admin_hash, "admin@petstress.com"))
    conn.commit()
    conn.close()

init_db()

try:
    model = tf.keras.models.load_model("models/stress_model.h5")
    print("Stress detection model loaded successfully")
except Exception as e:
    print(f"Error loading stress detection model: {e}")
    model = None

try:
    wound_model = YOLO("models/best.pt")
    print("Wound detection model loaded successfully")
except Exception as e:
    print(f"Error loading wound detection model: {e}")
    wound_model = None

SR = 16000

# ─────────────────────────────────────────────
# DB Helpers
# ─────────────────────────────────────────────

def get_current_timestamp():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def get_user_id(username):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def log_event(user_id, stress_class, stress_intensity, confidence, audio_path=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO stress_events (user_id, timestamp, stress_class, stress_intensity, confidence, audio_path) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (user_id, get_current_timestamp(), stress_class, stress_intensity, confidence, audio_path)
    )
    conn.commit()
    conn.close()

def log_wound_event(user_id, wound_types, severity, confidence, image_path=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO wound_events (user_id, timestamp, wound_types, severity, confidence, image_path) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (user_id, get_current_timestamp(),
         ",".join(wound_types) if wound_types else "none",
         severity, confidence, image_path)
    )
    conn.commit()
    conn.close()

def get_recent_events(user_id, limit=10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT timestamp, stress_class, stress_intensity, confidence '
        'FROM stress_events WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?',
        (user_id, limit)
    )
    events = cursor.fetchall()
    conn.close()
    return events

def get_user_stats(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM stress_events WHERE user_id = ?", (user_id,))
    total = cursor.fetchone()[0] or 0
    cursor.execute("SELECT COUNT(*) FROM stress_events WHERE user_id = ? AND stress_class = 'Stressed'", (user_id,))
    stressed = cursor.fetchone()[0] or 0
    cursor.execute("SELECT COUNT(*) FROM wound_events WHERE user_id = ?", (user_id,))
    wounds = cursor.fetchone()[0] or 0
    conn.close()
    health_score = max(0, 100 - (stressed / total * 100)) if total > 0 else 100

    # Get chart data for last 7 days
    chart_data = get_chart_data(user_id)

    return {
        "total_events": total,
        "stressed_events": stressed,
        "wound_events": wounds,
        "health_score": round(health_score, 1),
        "chart_data": chart_data
    }

def get_chart_data(user_id):
    """Get stress events count for the last 7 days"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get data for last 7 days
    chart_data = []
    for i in range(6, -1, -1):  # 6 days ago to today
        date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        cursor.execute(
            "SELECT COUNT(*) FROM stress_events WHERE user_id = ? AND DATE(timestamp) = ?",
            (user_id, date)
        )
        count = cursor.fetchone()[0] or 0
        chart_data.append({
            "date": (datetime.now() - timedelta(days=i)).strftime('%a'),  # Mon, Tue, etc.
            "count": count
        })

    conn.close()
    return chart_data

# ─────────────────────────────────────────────
# Email
# ─────────────────────────────────────────────

def _get_pet_info(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT pet_name, pet_type FROM user_settings WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return (row[0] or "Your pet", row[1] or "pet") if row else ("Your pet", "pet")

def send_stress_email(recipient_email, stress_data, user_id=None):
    try:
        if not recipient_email:
            return False
        pet_name, pet_type = _get_pet_info(user_id) if user_id else ("Your pet", "pet")
        si = stress_data.get("stress_intensity", 0)
        sl = "High" if si > 70 else "Moderate" if si > 40 else "Low"
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG["sender_email"]
        msg['To'] = recipient_email
        msg['Subject'] = EMAIL_CONFIG["default_subject"]
        body = f"""<html><body style="font-family:Arial,sans-serif;">
        <div style="max-width:600px;margin:0 auto;padding:20px;border:1px solid #ddd;border-radius:10px;">
        <div style="background:linear-gradient(135deg,#667eea,#764ba2);padding:20px;border-radius:10px 10px 0 0;color:white;text-align:center;">
        <h1>🚨 PETSTRESS ALERT 🚨</h1></div>
        <div style="padding:30px;"><h2 style="color:#ff6b6b;">Stress Detected in {pet_name}!</h2>
        <p><strong>Stress Level:</strong> {sl}</p>
        <p><strong>Intensity:</strong> {si}%</p>
        <p><strong>Confidence:</strong> {stress_data.get('confidence', 0) * 100:.1f}%</p>
        <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>Pet:</strong> {pet_name} ({pet_type})</p>
        </div></div></body></html>"""
        msg.attach(MIMEText(body, 'html'))
        s = smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"])
        s.starttls()
        s.login(EMAIL_CONFIG["smtp_username"], EMAIL_CONFIG["smtp_password"])
        s.send_message(msg)
        s.quit()
        return True
    except Exception as e:
        print(f"Error sending stress email: {e}")
        return False

def send_wound_email(recipient_email, wound_data, user_id=None):
    try:
        if not recipient_email:
            return False
        pet_name, pet_type = _get_pet_info(user_id) if user_id else ("Your pet", "pet")
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG["sender_email"]
        msg['To'] = recipient_email
        msg['Subject'] = "PETSTRESS Alert - Wound Detected"
        body = f"""<html><body style="font-family:Arial,sans-serif;">
        <div style="max-width:600px;margin:0 auto;padding:20px;border:1px solid #ddd;border-radius:10px;">
        <div style="background:linear-gradient(135deg,#ff6b6b,#ff8e8e);padding:20px;border-radius:10px 10px 0 0;color:white;text-align:center;">
        <h1>🩹 WOUND DETECTED 🩹</h1></div>
        <div style="padding:30px;"><h2 style="color:#c92a2a;">Wound Detected in {pet_name}!</h2>
        <p><strong>Severity:</strong> {wound_data.get('severity', 'Unknown')}</p>
        <p><strong>Wound Types:</strong> {', '.join(wound_data.get('wound_types', []))}</p>
        <p><strong>Confidence:</strong> {wound_data.get('confidence', 0) * 100:.1f}%</p>
        <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>Pet:</strong> {pet_name} ({pet_type})</p>
        </div></div></body></html>"""
        msg.attach(MIMEText(body, 'html'))
        s = smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"])
        s.starttls()
        s.login(EMAIL_CONFIG["smtp_username"], EMAIL_CONFIG["smtp_password"])
        s.send_message(msg)
        s.quit()
        return True
    except Exception as e:
        print(f"Error sending wound email: {e}")
        return False

# ─────────────────────────────────────────────
# Audio / Stress Detection
# ─────────────────────────────────────────────

def preprocess_audio(audio_data, sr=SR):
    try:
        if len(audio_data.shape) > 1:
            audio_data = librosa.to_mono(audio_data)
        if sr != SR:
            audio_data = librosa.resample(audio_data, orig_sr=sr, target_sr=SR)
        audio_data = nr.reduce_noise(y=audio_data, sr=SR)
        audio_data, _ = librosa.effects.trim(audio_data, top_db=20)
        if len(audio_data) < SR * 0.2:
            return None
        return librosa.util.normalize(audio_data)
    except Exception as e:
        print(f"Preprocess error: {e}")
        return None

# Feature extraction helper functions
MAX_FRAMES = 128

def pad_or_truncate(feature, max_len=MAX_FRAMES):
    """Pad or truncate feature to fixed length"""
    if feature.shape[1] < max_len:
        pad_width = max_len - feature.shape[1]
        return np.pad(feature, ((0, 0), (0, pad_width)), mode='constant')
    else:
        return feature[:, :max_len]

def segment_audio(audio, segment_seconds=3):
    """Segment audio into chunks"""
    segment_length = SR * segment_seconds
    segments = []
    
    for start in range(0, len(audio) - segment_length, segment_seconds * SR):
        segments.append(audio[start:start + segment_length])
    
    return segments if segments else [audio[:segment_length]] if len(audio) >= segment_length else [audio]

def extract_features(audio):
    """Extract combined features from audio matching training notebook"""
    # Extract all 4 feature types used in training
    mfcc = librosa.feature.mfcc(y=audio, sr=SR, n_mfcc=40)
    sc = librosa.feature.spectral_centroid(y=audio, sr=SR)
    zcr = librosa.feature.zero_crossing_rate(audio)
    rms = librosa.feature.rms(y=audio)
    
    # Pad or truncate all to same length
    mfcc = pad_or_truncate(mfcc)
    sc = pad_or_truncate(sc)
    zcr = pad_or_truncate(zcr)
    rms = pad_or_truncate(rms)
    
    # Stack all features together to get (43, 128) shape
    features = np.vstack([mfcc, sc, zcr, rms])
    return features

def predict_stress(audio_path=None, audio_data=None, sr=None, username=None):
    if model is None:
        raise ValueError("Stress detection model is not loaded. Cannot make a prediction.")
    try:
        if audio_path:
            audio, sr = librosa.load(audio_path, sr=SR, mono=True)
        elif audio_data is not None and sr is not None:
            audio = audio_data
            if sr != SR:
                audio = librosa.resample(audio, orig_sr=sr, target_sr=SR)
        else:
            return None, None, None, None

        audio = preprocess_audio(audio)
        if audio is None:
            return "Normal", 0, 0.0, None

        # FIXED: Segment audio and extract all features like training notebook
        segments = segment_audio(audio)
        preds = []
        
        for seg in segments:
            # Extract all 4 feature types (MFCC, spectral centroid, ZCR, RMS)
            feat = extract_features(seg)
            
            # Reshape to (1, 43, 128, 1) for model
            feat = feat[np.newaxis, ..., np.newaxis]
            
            # Make prediction
            pred = model.predict(feat, verbose=0)[0][0]
            preds.append(pred)
            print(f"Segment prediction: {pred}")
        
        # Average predictions across all segments (like training)
        raw_pred = float(np.mean(preds)) if preds else 0.3
        print(f"Mean prediction across {len(preds)} segments: {raw_pred}")

        stress_class     = "Stressed" if raw_pred > 0.5 else "Normal"
        stress_intensity = int(raw_pred * 100)
        confidence       = raw_pred
        alert_message    = None

        if username and stress_class == "Stressed":
            uid = get_user_id(username)
            if uid:
                conn   = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT alert_threshold, email_notifications, recipient_email '
                    'FROM user_settings WHERE user_id = ?', (uid,)
                )
                settings = cursor.fetchone()
                if settings:
                    thresh, email_on, recipient = settings[0] or 3, settings[1], settings[2]
                    cursor.execute(
                        "SELECT COUNT(*) FROM stress_events WHERE user_id = ? "
                        "AND stress_class = 'Stressed' AND timestamp > datetime('now', '-30 minutes')",
                        (uid,)
                    )
                    recent = cursor.fetchone()[0]
                    conn.close()
                    if email_on and recipient and (recent + 1 >= thresh):
                        alert_message = f"ALERT: {recent + 1} stress events in the last 30 minutes!"
                        ok = send_stress_email(
                            recipient,
                            {"stress_intensity": stress_intensity, "confidence": confidence, "stress_class": stress_class},
                            uid
                        )
                        alert_message += " Email notification sent." if ok else " Failed to send email."
                else:
                    conn.close()

        return stress_class, stress_intensity, confidence, alert_message

    except ValueError:
        raise
    except Exception as e:
        print(f"Prediction error: {e}")
        import traceback; traceback.print_exc()
        return "Error", 0, 0.0, None

# ─────────────────────────────────────────────
# Wound Detection Helpers
# ─────────────────────────────────────────────

def normalize_wound_class(raw_class):
    # Accept both old underscore format and new hyphen format.
    normalize_map = {
        "minor_wound": "minor-wound",
        "minor-wound": "minor-wound",
        "moderate_wound": "no-wound",
        "moderate-wound": "no-wound",
        "severe_wound": "severe-wound",
        "severe-wound": "severe-wound",
        "no_wound": "no-wound",
        "no-wound": "no-wound",
        "normal": "no-wound"
    }
    return normalize_map.get(raw_class, raw_class)


def get_wound_severity(class_name, confidence):
    mapping = {
        "minor-wound": "Low",
        "no-wound":    "None",
        "severe-wound": "High",
        "normal":      "None"
    }
    base = mapping.get(class_name, "Unknown")
    if base not in ("None", "Unknown"):
        if confidence > 0.8:
            return f"{base} (High Confidence)"
        elif confidence > 0.5:
            return base
        else:
            return f"{base} (Low Confidence)"
    return base

def determine_overall_severity(detections):
    if not detections:
        return "No wounds detected"
    sevs = [d["severity"] for d in detections if d["class"] != "normal"]
    if not sevs:
        return "No wounds detected"
    if any("High" in s for s in sevs):
        return "High Severity"
    elif any("Medium" in s for s in sevs):
        return "Medium Severity"
    return "Low Severity"

def get_wound_recommendations(overall_severity, wound_types):
    recs = []
    if overall_severity == "High Severity":
        recs += [
            "🚨 URGENT: Immediate veterinary attention required!",
            "Keep the wound clean",
            "Apply gentle pressure if bleeding",
            "Do not treat serious wounds at home"
        ]
    elif overall_severity == "Medium Severity":
        recs += [
            "⚠️ Vet consultation recommended within 24 hours",
            "Clean with mild antiseptic",
            "Monitor for infection",
            "Prevent licking"
        ]
    elif overall_severity == "Low Severity":
        recs += [
            "✅ Minor wound - monitor closely",
            "Clean with warm water and mild soap",
            "Apply pet-safe antiseptic"
        ]
    else:
        recs += [
            "✅ No wounds detected - your pet appears healthy",
            "Continue regular monitoring"
        ]
    if wound_types:
        if "severe_wound"   in wound_types: recs.append("🩹 Deep wounds may require stitches")
        if "moderate_wound" in wound_types: recs.append("🩸 May need pressure bandages")
        if "minor_wound"    in wound_types: recs.append("💊 Minor abrasions usually heal within a few days")
    return recs

def run_wound_detection_on_image(image_input):
    """
    Run YOLO wound detection on a single image.
    `image_input` can be a file path (str) or a numpy array (BGR).
    Returns (detections, wound_types, overall_severity, highest_confidence).
    """
    if wound_model is None:
        return [], [], "No wounds detected", 0.0

    if isinstance(image_input, str):
        image = cv2.imread(image_input)
        if image is None:
            print(f"Cannot read image: {image_input}")
            return [], [], "No wounds detected", 0.0
    else:
        image = image_input

    results      = wound_model.predict(source=image, conf=0.25, verbose=False)
    detections   = []
    wound_types  = []
    highest_conf = 0.0
    # YOLO model classes should match your dataset: minor-wound, no-wound, severe-wound
    class_names  = ["minor-wound", "no-wound", "severe-wound"]

    for result in results:
        if len(result.boxes) > 0:
            for box in result.boxes:
                cls         = int(box.cls[0])
                conf        = float(box.conf[0])
                raw_class   = class_names[cls] if cls < len(class_names) else f"class_{cls}"
                class_name  = normalize_wound_class(raw_class)
                severity    = get_wound_severity(class_name, conf)
                detections.append({"class": class_name, "confidence": conf, "severity": severity})
                if conf > highest_conf:
                    highest_conf = conf
                if class_name != "no-wound" and class_name not in wound_types:
                    wound_types.append(class_name)

    overall_severity = determine_overall_severity(detections)
    return detections, wound_types, overall_severity, highest_conf

def run_wound_detection_on_video(video_path):
    """
    Run YOLO wound detection on evenly sampled frames from a video file.
    Samples up to 20 frames spread across the full duration.
    Returns (detections_list, wound_types, overall_severity, max_confidence).
    """
    if wound_model is None:
        return [], [], "No wounds detected", 0.0

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Cannot open video: {video_path}")
        return [], [], "No wounds detected", 0.0

    total_frames   = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    target_samples = min(20, total_frames)
    sample_every   = max(1, total_frames // target_samples)

    all_detections = []
    max_conf       = 0.0
    frame_count    = 0
    class_names    = ["minor_wound", "moderate_wound", "severe_wound", "normal"]

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_count % sample_every == 0:
            results = wound_model.predict(source=frame, conf=0.25, verbose=False)
            for result in results:
                if len(result.boxes) > 0:
                    for box in result.boxes:
                        cls         = int(box.cls[0])
                        conf        = float(box.conf[0])
                        raw_class   = class_names[cls] if cls < len(class_names) else f"class_{cls}"
                        class_name  = normalize_wound_class(raw_class)
                        if class_name != "normal":
                            all_detections.append({
                                "class":      class_name,
                                "confidence": conf,
                                "severity":   get_wound_severity(class_name, conf),
                                "frame":      frame_count
                            })
                            if conf > max_conf:
                                max_conf = conf
        frame_count += 1
        if frame_count > 150:
            break

    cap.release()

    # Unique wound types in order of first appearance
    seen        = set()
    wound_types = []
    for d in all_detections:
        if d["class"] not in seen:
            seen.add(d["class"])
            wound_types.append(d["class"])

    overall_severity = determine_overall_severity(all_detections)
    print(f"Video wound detection: {frame_count} frames scanned, "
          f"{len(all_detections)} detections, severity={overall_severity}")
    return all_detections, wound_types, overall_severity, max_conf

# ─────────────────────────────────────────────
# Routes — Pages
@app.get("/", response_class=HTMLResponse)
async def root_page(request: Request, success: str = None):
    return templates.TemplateResponse("login.html", {"request": request, "success": success})

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("username")
    return response

@app.get("/signin")
async def signin_redirect():
    return RedirectResponse(url="/", status_code=302)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    if result is None or hashlib.sha256(password.encode()).hexdigest() != result[0]:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid username or password"}
        )
    response = RedirectResponse(url="/dashboard", status_code=302)
    response.set_cookie(key="username", value=username)
    return response

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    username = request.cookies.get("username")
    if not username:
        return templates.TemplateResponse("login.html", {"request": request})
    user_id       = get_user_id(username)
    recent_events = get_recent_events(user_id, 5) if user_id else []
    stats         = get_user_stats(user_id) if user_id else {
        "total_events": 0, "stressed_events": 0, "wound_events": 0, "health_score": 100
    }
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "username": username, "recent_events": recent_events, "stats": stats}
    )

@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@app.post("/signup")
async def signup(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...)
):
    # Validate input
    if password != confirm_password:
        return templates.TemplateResponse(
            "signup.html", {"request": request, "error": "Passwords do not match"}
        )

    if len(password) < 6:
        return templates.TemplateResponse(
            "signup.html", {"request": request, "error": "Password must be at least 6 characters long"}
        )

    if len(username) < 3:
        return templates.TemplateResponse(
            "signup.html", {"request": request, "error": "Username must be at least 3 characters long"}
        )

    # Check if username already exists
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cursor.fetchone():
        conn.close()
        return templates.TemplateResponse(
            "signup.html", {"request": request, "error": "Username already exists"}
        )

    # Check if email already exists
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    if cursor.fetchone():
        conn.close()
        return templates.TemplateResponse(
            "signup.html", {"request": request, "error": "Email already registered"}
        )

    # Create new user
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    cursor.execute(
        "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
        (username, password_hash, email)
    )
    conn.commit()
    conn.close()

    # Redirect to login with success message
    response = RedirectResponse(url="/?success=Account created successfully! Please log in.", status_code=302)
    return response

# ─────────────────────────────────────────────
# Routes — Stress Detection (Upload)
# ─────────────────────────────────────────────

@app.post("/upload-audio")
async def upload_audio(
    request:    Request,
    audio_file: UploadFile = File(...),
    username:   str        = Form(...)
):
    """
    Accept an uploaded audio file, run stress prediction with the CNN model,
    log the result and return it as JSON.
    """
    if not audio_file or not audio_file.filename:
        return JSONResponse({"success": False, "error": "No audio file provided"}, status_code=400)

    # Validate MIME type loosely (browsers may send application/octet-stream for some audio)
    content_type = audio_file.content_type or ""
    if content_type and not (content_type.startswith("audio/") or content_type == "application/octet-stream"):
        return JSONResponse({"success": False, "error": "Please upload an audio file"}, status_code=400)

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Preserve original extension so librosa can pick the right decoder
    orig_ext = os.path.splitext(audio_file.filename)[-1].lower() or ".wav"
    filepath = f"uploads/audio_{ts}{orig_ext}"

    with open(filepath, "wb") as buf:
        shutil.copyfileobj(audio_file.file, buf)

    try:
        sc, si, conf, alert = predict_stress(audio_path=filepath, username=username)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=503)

    if sc == "Error":
        return JSONResponse({"success": False, "error": "Error processing audio file"}, status_code=500)

    uid = get_user_id(username)
    if uid:
        log_event(uid, sc, si, conf, filepath)

    return JSONResponse({
        "success":          True,
        "stress_class":     sc,
        "stress_intensity": si,
        "confidence":       conf,
        "alert":            alert,
        "timestamp":        get_current_timestamp()
    })


@app.post("/record-audio")
async def record_audio(
    request:    Request,
    audio_data: str = Form(...),
    username:   str = Form(...)
):
    """Legacy endpoint — accepts base64 audio data from the old record-in-browser flow."""
    try:
        header, encoded = audio_data.split(',', 1) if ',' in audio_data else ('', audio_data)
        audio_bytes = base64.b64decode(encoded)
        suffix = '.webm'
        if 'wav' in header.lower():  suffix = '.wav'
        elif 'ogg' in header.lower(): suffix = '.ogg'
        elif 'mp4' in header.lower(): suffix = '.mp4'

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(audio_bytes)
        tmp.close()

        try:
            sc, si, conf, alert = predict_stress(audio_path=tmp.name, username=username)
        except ValueError as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=503)
        finally:
            try: os.unlink(tmp.name)
            except: pass

        uid = get_user_id(username)
        if uid:
            log_event(uid, sc, si, conf)

        return JSONResponse({
            "success":          True,
            "stress_class":     sc,
            "stress_intensity": si,
            "confidence":       conf,
            "alert":            alert,
            "timestamp":        get_current_timestamp()
        })
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)

# ─────────────────────────────────────────────
# Routes — Wound Detection (Upload)
# ─────────────────────────────────────────────

@app.post("/upload-wound-image")
async def upload_wound_image(
    request:    Request,
    image_file: UploadFile = File(...),
    username:   str        = Form(...)
):
    """
    Accept an uploaded image, run YOLO wound detection,
    log the result and return it as JSON.
    """
    if not image_file or not image_file.filename:
        return JSONResponse({"success": False, "error": "No image file provided"}, status_code=400)

    content_type = image_file.content_type or ""
    if content_type and not (content_type.startswith("image/") or content_type == "application/octet-stream"):
        return JSONResponse({"success": False, "error": "Please upload an image file"}, status_code=400)

    if wound_model is None:
        return JSONResponse({"success": False, "error": "Wound detection model is not loaded"}, status_code=503)

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    orig_ext = os.path.splitext(image_file.filename)[-1].lower() or ".jpg"
    filepath = f"uploads/wound_img_{ts}{orig_ext}"

    with open(filepath, "wb") as buf:
        shutil.copyfileobj(image_file.file, buf)

    try:
        detections, wound_types, overall_severity, highest_conf = run_wound_detection_on_image(filepath)
        recs = get_wound_recommendations(overall_severity, wound_types)

        uid             = get_user_id(username)
        alert_triggered = False
        if uid:
            log_wound_event(uid, wound_types, overall_severity, highest_conf, filepath)
            # Send e-mail only for severe wounds (High Severity)
            if wound_types and overall_severity == "High Severity":
                conn = sqlite3.connect(DB_PATH)
                cur  = conn.cursor()
                cur.execute(
                    'SELECT email_notifications, recipient_email FROM user_settings WHERE user_id = ?', (uid,)
                )
                s = cur.fetchone()
                conn.close()
                if s and s[0] and s[1]:
                    ok = send_wound_email(
                        s[1],
                        {"severity": overall_severity, "wound_types": wound_types, "confidence": highest_conf},
                        uid
                    )
                    if ok:
                        alert_triggered = True

        return JSONResponse({
            "success":            True,
            "detections":         detections,
            "wound_types":        wound_types,
            "overall_severity":   overall_severity,
            "recommendations":    recs,
            "highest_confidence": highest_conf,
            "alert":              "Wound alert email sent!" if alert_triggered else None,
            "timestamp":          get_current_timestamp()
        })
    except Exception as e:
        print(f"Error processing wound image: {e}")
        import traceback; traceback.print_exc()
        return JSONResponse({"success": False, "error": "Error processing image"}, status_code=500)


@app.post("/process-wound-video")
async def process_wound_video(
    request:    Request,
    video_file: UploadFile = File(...),
    username:   str        = Form(...)
):
    """
    Accept an uploaded video, run YOLO wound detection on sampled frames,
    log the result and return it as JSON.
    """
    if not video_file or not video_file.filename:
        return JSONResponse({"success": False, "error": "No video file provided"}, status_code=400)

    content_type = video_file.content_type or ""
    if content_type and not (content_type.startswith("video/") or content_type == "application/octet-stream"):
        return JSONResponse({"success": False, "error": "Please upload a video file"}, status_code=400)

    if wound_model is None:
        return JSONResponse({"success": False, "error": "Wound detection model is not loaded"}, status_code=503)

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    orig_ext = os.path.splitext(video_file.filename)[-1].lower() or ".mp4"
    filepath = f"uploads/wound_vid_{ts}{orig_ext}"

    with open(filepath, "wb") as buf:
        shutil.copyfileobj(video_file.file, buf)

    try:
        dets, wound_types, overall_severity, max_conf = run_wound_detection_on_video(filepath)
        recs = get_wound_recommendations(overall_severity, wound_types)

        uid             = get_user_id(username)
        alert_triggered = False
        if uid:
            log_wound_event(uid, wound_types, overall_severity, max_conf, filepath)
            if wound_types and overall_severity in ("High Severity", "Medium Severity"):
                conn = sqlite3.connect(DB_PATH)
                cur  = conn.cursor()
                cur.execute(
                    'SELECT email_notifications, recipient_email FROM user_settings WHERE user_id = ?', (uid,)
                )
                s = cur.fetchone()
                conn.close()
                if s and s[0] and s[1]:
                    ok = send_wound_email(
                        s[1],
                        {"severity": overall_severity, "wound_types": wound_types, "confidence": max_conf},
                        uid
                    )
                    if ok:
                        alert_triggered = True

        avg_conf = (sum(d["confidence"] for d in dets) / len(dets)) if dets else 0.0

        return JSONResponse({
            "success":          True,
            "detections":       dets[:10],
            "wound_types":      wound_types,
            "overall_severity": overall_severity,
            "recommendations":  recs,
            "avg_confidence":   avg_conf,
            "max_confidence":   max_conf,
            "alert":            "Wound alert email sent!" if alert_triggered else None,
            "timestamp":        get_current_timestamp()
        })
    except Exception as e:
        print(f"Error processing wound video: {e}")
        import traceback; traceback.print_exc()
        return JSONResponse({"success": False, "error": f"Error processing video: {str(e)}"}, status_code=500)

# ─────────────────────────────────────────────
# Route — Live Detection
# ─────────────────────────────────────────────

@app.post("/live-detect")
async def live_detect(
    request:    Request,
    audio_data: str        = Form(...),   # base64 data-URL (WAV or WebM)
    video_file: UploadFile = File(...),   # combined WebM blob from MediaRecorder
    username:   str        = Form(...)
):
    """
    Unified live detection:
      • audio_data  → stress prediction via CNN model
      • video_file  → wound detection via YOLO on sampled frames
    Both blobs cover exactly the user-selected recording duration.
    """
    user_id = get_user_id(username)
    if not user_id:
        return JSONResponse({"success": False, "error": "User not found"}, status_code=404)

    stress_result   = {}
    wound_result    = {}
    alert_messages  = []

    # ── Stress: decode audio data-URL → temp file → CNN model ──
    try:
        header, encoded = audio_data.split(',', 1) if ',' in audio_data else ('', audio_data)
        audio_bytes = base64.b64decode(encoded)

        # Choose file suffix from data-URL MIME hint
        suffix = '.webm'
        if 'wav' in header.lower():   suffix = '.wav'
        elif 'ogg' in header.lower(): suffix = '.ogg'
        elif 'mp4' in header.lower(): suffix = '.mp4'

        tmp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp_audio.write(audio_bytes)
        tmp_audio.close()

        try:
            sc, si, conf, alert_msg = predict_stress(audio_path=tmp_audio.name, username=username)
            if sc == "Error":
                stress_result = {"success": False, "error": "Audio processing returned an error"}
            else:
                stress_result = {
                    "success":          True,
                    "stress_class":     sc,
                    "stress_intensity": si,
                    "confidence":       conf,
                    "alert":            alert_msg
                }
                log_event(user_id, sc, si, conf, "live_detection")
                if alert_msg:
                    alert_messages.append(alert_msg)
        except ValueError as e:
            stress_result = {"success": False, "error": str(e)}
        finally:
            try: os.unlink(tmp_audio.name)
            except: pass

    except Exception as e:
        stress_result = {"success": False, "error": f"Audio processing error: {str(e)}"}

    # ── Wound: save video blob → YOLO on sampled frames ──
    try:
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = '.webm'
        if video_file.filename and '.' in video_file.filename:
            ext = '.' + video_file.filename.rsplit('.', 1)[-1].lower()

        video_path = f"uploads/live_{ts}{ext}"
        with open(video_path, "wb") as f:
            shutil.copyfileobj(video_file.file, f)

        dets, wound_types, overall_severity, max_conf = run_wound_detection_on_video(video_path)
        recs = get_wound_recommendations(overall_severity, wound_types)

        wound_result = {
            "wound_detected": len(dets) > 0,
            "wound_types":    wound_types,
            "severity":       overall_severity,
            "confidence":     max_conf,
            "detections":     dets[:10],
            "recommendations": recs
        }

        if dets:
            log_wound_event(user_id, wound_types, overall_severity, max_conf, video_path)

        if wound_types and overall_severity in ("High Severity", "Medium Severity"):
            conn = sqlite3.connect(DB_PATH)
            cur  = conn.cursor()
            cur.execute(
                'SELECT email_notifications, recipient_email FROM user_settings WHERE user_id = ?', (user_id,)
            )
            s = cur.fetchone()
            conn.close()
            if s and s[0] and s[1]:
                ok = send_wound_email(
                    s[1],
                    {"severity": overall_severity, "wound_types": wound_types, "confidence": max_conf},
                    user_id
                )
                if ok:
                    alert_messages.append("Wound alert email sent!")

    except Exception as e:
        print(f"Wound video error in live-detect: {e}")
        import traceback; traceback.print_exc()
        wound_result = {"wound_detected": False, "error": f"Video processing error: {str(e)}"}

    return JSONResponse({
        "success":        True,
        "stress_results": stress_result,
        "wound_results":  wound_result,
        "alerts":         alert_messages,
        "timestamp":      get_current_timestamp()
    })

# ─────────────────────────────────────────────
# Routes — Settings
# ─────────────────────────────────────────────

@app.post("/update-settings")
async def update_settings(
    request:             Request,
    username:            str  = Form(...),
    alert_threshold:     int  = Form(3),
    email_notifications: bool = Form(True),
    recipient_email:     str  = Form(None),
    pet_name:            str  = Form(None),
    pet_type:            str  = Form("dog"),
    pet_age:             int  = Form(None)
):
    uid = get_user_id(username)
    if not uid:
        return JSONResponse({"error": "User not found"}, status_code=404)
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        'INSERT OR REPLACE INTO user_settings '
        '(user_id, alert_threshold, email_notifications, recipient_email, pet_name, pet_type, pet_age) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        (uid, alert_threshold, email_notifications, recipient_email, pet_name, pet_type, pet_age)
    )
    conn.commit()
    conn.close()
    return JSONResponse({"success": True, "message": "Settings updated successfully"})

@app.post("/test-email")
async def test_email(username: str = Form(...)):
    uid = get_user_id(username)
    if not uid:
        return JSONResponse({"error": "User not found"}, status_code=404)
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute('SELECT recipient_email, email_notifications FROM user_settings WHERE user_id = ?', (uid,))
    s = cur.fetchone()
    conn.close()
    if not s or not s[0]:
        return JSONResponse({"error": "Recipient email not configured"}, status_code=400)
    if not s[1]:
        return JSONResponse({"error": "Email notifications are disabled"}, status_code=400)
    ok = send_stress_email(s[0], {"stress_intensity": 75, "confidence": 0.92, "stress_class": "Stressed"}, uid)
    if ok:
        return JSONResponse({"success": True, "message": "Test email sent successfully"})
    return JSONResponse({"error": "Failed to send test email."})

@app.get("/get-settings")
async def get_settings(username: str):
    uid = get_user_id(username)
    if not uid:
        return JSONResponse({"error": "User not found"}, status_code=404)
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        'SELECT alert_threshold, email_notifications, recipient_email, pet_name, pet_type, pet_age '
        'FROM user_settings WHERE user_id = ?', (uid,)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        s = {
            "alert_threshold":     row[0] or 3,
            "email_notifications": bool(row[1]) if row[1] is not None else True,
            "recipient_email":     row[2] or "",
            "pet_name":            row[3] or "",
            "pet_type":            row[4] or "dog",
            "pet_age":             row[5]
        }
    else:
        s = {
            "alert_threshold":     3,
            "email_notifications": True,
            "recipient_email":     "",
            "pet_name":            "",
            "pet_type":            "dog",
            "pet_age":             None
        }
    return JSONResponse({"settings": s})

# ─────────────────────────────────────────────
# Routes — Event History / Stats
# ─────────────────────────────────────────────

@app.get("/recent-events")
async def get_events(username: str):
    uid = get_user_id(username)
    if not uid:
        return JSONResponse({"error": "User not found"}, status_code=404)
    events = get_recent_events(uid, 10)
    return JSONResponse({
        "events": [
            {
                "timestamp":        e[0],
                "stress_class":     e[1],
                "stress_intensity": e[2],
                "confidence":       e[3]
            } for e in events
        ]
    })

@app.get("/stats")
async def get_stats(username: str):
    uid = get_user_id(username)
    if not uid:
        return JSONResponse({"error": "User not found"}, status_code=404)
    return JSONResponse(get_user_stats(uid))

@app.get("/wound-history")
async def get_wound_history(username: str):
    uid = get_user_id(username)
    if not uid:
        return JSONResponse({"error": "User not found"}, status_code=404)
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute(
        'SELECT timestamp, wound_types, severity, confidence '
        'FROM wound_events WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20',
        (uid,)
    )
    events = cur.fetchall()
    conn.close()
    return JSONResponse({
        "events": [
            {
                "timestamp":   e[0],
                "wound_types": e[1].split(",") if e[1] else [],
                "severity":    e[2],
                "confidence":  e[3]
            } for e in events
        ]
    })

# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
