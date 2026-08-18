
import os, sqlite3, time
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response, g
import cv2
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "smartlib.db")
MODELS = os.path.join(BASE, "models")
YUNET = os.path.join(MODELS, "face_detection_yunet_2023mar.onnx")
SFACE = os.path.join(MODELS, "face_recognition_sface_2021dec.onnx")

MATCH_THRESHOLD = 0.55
CONFIRM_SECONDS = 1.5
EVENT_LOCK_SECONDS = 30
ABSENCE_SECONDS = 2.5
MAX_REG_PHOTOS = 8

app = Flask(__name__)
detector = None
recognizer = None
camera = None
gate_state = {}

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        student_id TEXT UNIQUE NOT NULL,
        role TEXT NOT NULL,
        department TEXT,
        email TEXT,
        phone TEXT,
        embedding BLOB NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS user_embeddings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        embedding BLOB NOT NULL,
        source TEXT DEFAULT 'upload',
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS attendance(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('ENTRY','EXIT')),
        timestamp TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS library_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_code TEXT UNIQUE NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'AVAILABLE'
    );
    CREATE TABLE IF NOT EXISTS alerts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_type TEXT NOT NULL,
        message TEXT NOT NULL,
        timestamp TEXT NOT NULL
    );
    """)
    # Safe migration for an older database.
    try: db.execute("ALTER TABLE users ADD COLUMN photo_count INTEGER DEFAULT 1")
    except sqlite3.OperationalError: pass
    db.commit(); db.close()

def load_models():
    global detector, recognizer
    if not os.path.exists(YUNET) or not os.path.exists(SFACE):
        print("Models not found. Run download_models.py")
        return False
    detector = cv2.FaceDetectorYN.create(YUNET, "", (320,320), 0.85, 0.3, 5000)
    recognizer = cv2.FaceRecognizerSF.create(SFACE, "")
    return True

def extract_face(image):
    if detector is None or recognizer is None or image is None:
        return None, 0
    h, w = image.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(image)
    if faces is None: return None, 0
    faces = sorted(faces, key=lambda x: x[2]*x[3], reverse=True)
    aligned = recognizer.alignCrop(image, faces[0])
    feature = recognizer.feature(aligned).astype(np.float32)
    return feature, len(faces)

def normalize_feature(feature):
    feature = np.asarray(feature, dtype=np.float32).reshape(1, -1)
    norm = np.linalg.norm(feature)
    return feature / norm if norm else feature

def find_match(feature):
    feature = normalize_feature(feature)
    db = get_db()
    rows = db.execute("""
        SELECT u.id,u.name,u.student_id,u.role,u.department,u.email,u.phone,
               COALESCE(e.embedding,u.embedding) AS embedding
        FROM users u
        LEFT JOIN user_embeddings e ON e.user_id=u.id
    """).fetchall()
    best, best_score = None, -1
    for row in rows:
        if row["embedding"] is None: continue
        emb = np.frombuffer(row["embedding"], dtype=np.float32).reshape(1,-1)
        score = float(recognizer.match(feature, emb, cv2.FaceRecognizerSF_FR_COSINE))
        if score > best_score:
            best_score, best = score, row
    return best, best_score

def last_action(user_id):
    row = get_db().execute(
        "SELECT action FROM attendance WHERE user_id=? ORDER BY id DESC LIMIT 1",(user_id,)
    ).fetchone()
    return row["action"] if row else "EXIT"

def record_action(user_id, action):
    now = datetime.now().isoformat(timespec="seconds")
    db = get_db()
    db.execute("INSERT INTO attendance(user_id,action,timestamp) VALUES(?,?,?)",
               (user_id,action,now)); db.commit()
    return now

def add_alert(kind, message):
    db=get_db()
    db.execute("INSERT INTO alerts(alert_type,message,timestamp) VALUES(?,?,?)",
               (kind,message,datetime.now().isoformat(timespec="seconds"))); db.commit()

def process_frame(frame):
    feature, count = extract_face(frame)
    result = {"name":"Unknown","student_id":"","action":"","status":"No face","color":(0,200,255)}
    now = time.time()

    if feature is None:
        for state in gate_state.values():
            if state["present"] and now - state["last_seen"] >= ABSENCE_SECONDS:
                state["present"] = False
                state["candidate_since"] = None
        return frame, result

    user, score = find_match(feature)
    if user is None or score < MATCH_THRESHOLD:
        result["status"] = "UNKNOWN PERSON"
        result["color"] = (0,0,255)
        return frame, result

    result["name"] = user["name"]
    result["student_id"] = user["student_id"]
    key = user["id"]
    state = gate_state.setdefault(key, {
        "candidate_since": None, "last_seen": 0.0,
        "last_event": 0.0, "present": False
    })
    state["last_seen"] = now

    if state["present"]:
        result["action"] = last_action(user["id"])
        result["status"] = "Already processed"
        result["color"] = (0,200,0)
        return frame, result

    if state["last_event"] and now - state["last_event"] < EVENT_LOCK_SECONDS:
        remaining = EVENT_LOCK_SECONDS - (now - state["last_event"])
        result["action"] = last_action(user["id"])
        result["status"] = f"Gate locked... {remaining:.0f}s"
        result["color"] = (0,200,255)
        return frame, result

    if state["candidate_since"] is None:
        state["candidate_since"] = now
        result["status"] = "Confirming face..."
        return frame, result

    elapsed = now - state["candidate_since"]
    if elapsed < CONFIRM_SECONDS:
        result["status"] = f"Confirming face... {CONFIRM_SECONDS-elapsed:.1f}s"
        return frame, result

    action = "EXIT" if last_action(user["id"]) == "ENTRY" else "ENTRY"
    timestamp = record_action(user["id"], action)
    state["last_event"] = now
    state["present"] = True
    state["candidate_since"] = None
    result["action"] = action
    result["status"] = f"{action}  {timestamp[11:]}"
    result["color"] = (0,200,0)
    return frame, result

def open_camera():
    global camera
    # Try the Windows DirectShow camera first, then other indexes/backends.
    candidates = [
        (0, cv2.CAP_DSHOW), (1, cv2.CAP_DSHOW), (2, cv2.CAP_DSHOW),
        (0, cv2.CAP_MSMF), (1, cv2.CAP_MSMF)
    ]
    for index, backend in candidates:
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
        # Confirm that the selected device can actually return a frame.
        ok, frame = cap.read()
        if ok and frame is not None and frame.size:
            print(f"SmartLib camera opened: index={index}, backend={backend}")
            return cap
        cap.release()
    return None

def camera_stream():
    # Flask's `g` and get_db() require an application context.
    # A streaming generator runs after the route function has returned, so
    # explicitly keep an application context alive for the whole stream.
    global camera
    with app.app_context():
        yield from _camera_stream_impl()

def _camera_stream_impl():
    global camera
    if camera is None or not camera.isOpened():
        camera = open_camera()
    if camera is None:
        # Return a visible diagnostic frame instead of a blank/failed stream.
        frame = np.zeros((540, 960, 3), dtype=np.uint8)
        cv2.putText(frame, "CAMERA NOT AVAILABLE", (250, 245),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 80, 255), 3, cv2.LINE_AA)
        cv2.putText(frame, "Close Windows Camera/Zoom/Teams and reload", (185, 290),
                    cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 2, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", frame)
        if ok:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
        return

    while True:
        ok,frame=camera.read()
        if not ok or frame is None:
            # Re-open once if the webcam disconnects.
            camera.release()
            camera = open_camera()
            if camera is None:
                break
            continue
        frame,result=process_frame(frame)
        label=("UNKNOWN PERSON" if result["status"]=="UNKNOWN PERSON"
               else f'{result["name"]} | {result["student_id"]}' if result["name"]!="Unknown"
               else result["status"])
        cv2.putText(frame,label,(25,40),cv2.FONT_HERSHEY_SIMPLEX,.85,result["color"],2,cv2.LINE_AA)
        cv2.putText(frame,result["status"],(25,78),cv2.FONT_HERSHEY_SIMPLEX,.75,result["color"],2,cv2.LINE_AA)
        ok,buf=cv2.imencode(".jpg",frame)
        if ok: yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"+buf.tobytes()+b"\r\n"

@app.post("/api/frame")
def api_frame():
    if "frame" not in request.files:
        return jsonify(error="Frame is required."), 400
    raw = request.files["frame"].read()
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return jsonify(error="Invalid image."), 400
    frame, result = process_frame(image)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return jsonify(error="Could not encode frame."), 500
    import base64
    return jsonify(
        image=base64.b64encode(buf.tobytes()).decode("ascii"),
        name=result["name"],
        student_id=result["student_id"],
        action=result["action"],
        status=result["status"]
    )

@app.route("/")
def index(): return render_template("index.html")
@app.route("/gate")
def gate(): return render_template("gate.html")
@app.route("/video_feed")
def video_feed(): return Response(camera_stream(),mimetype="multipart/x-mixed-replace; boundary=frame")

@app.get("/api/stats")
def stats():
    db=get_db()
    total=db.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
    present=db.execute("""SELECT COUNT(*) n FROM users u WHERE COALESCE(
      (SELECT action FROM attendance a WHERE a.user_id=u.id ORDER BY a.id DESC LIMIT 1),'EXIT')='ENTRY'""").fetchone()["n"]
    entries=db.execute("SELECT COUNT(*) n FROM attendance WHERE action='ENTRY' AND date(timestamp)=date('now')").fetchone()["n"]
    exits=db.execute("SELECT COUNT(*) n FROM attendance WHERE action='EXIT' AND date(timestamp)=date('now')").fetchone()["n"]
    alerts=db.execute("SELECT COUNT(*) n FROM alerts").fetchone()["n"]
    books=db.execute("SELECT COUNT(*) n FROM library_items").fetchone()["n"]
    return jsonify(total=total,present=present,entries=entries,exits=exits,alerts=alerts,books=books)

@app.get("/api/analytics")
def analytics():
    db=get_db()
    daily=db.execute("""
      SELECT substr(timestamp,1,10) day, action, COUNT(*) count
      FROM attendance WHERE timestamp >= datetime('now','-6 days')
      GROUP BY day,action ORDER BY day
    """).fetchall()
    roles=db.execute("SELECT role,COUNT(*) count FROM users GROUP BY role ORDER BY count DESC").fetchall()
    recent=db.execute("""
      SELECT u.name,u.student_id,a.action,a.timestamp FROM attendance a
      JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 8
    """).fetchall()
    return jsonify(daily=[dict(x) for x in daily],roles=[dict(x) for x in roles],
                   recent=[dict(x) for x in recent])

@app.post("/api/register")
def register():
    form=request.form
    if not form.get("name") or not form.get("student_id") or not form.get("role"):
        return jsonify(error="Name, Student ID and Role are required."),400

    photos=[p for p in request.files.getlist("photos") if p and p.filename]
    if not photos and request.files.get("photo"): photos=[request.files.get("photo")]
    if not photos: return jsonify(error="Capture or upload at least one face photo."),400
    if len(photos)>MAX_REG_PHOTOS: return jsonify(error=f"Maximum {MAX_REG_PHOTOS} photos allowed."),400

    features=[]
    for photo in photos:
        image=cv2.imdecode(np.frombuffer(photo.read(),np.uint8),cv2.IMREAD_COLOR)
        if image is None: continue
        feature,count=extract_face(image)
        if feature is not None and count==1:
            features.append(normalize_feature(feature).astype(np.float32))
    if not features:
        return jsonify(error="No valid face found. Use clear photos with exactly one face."),400

    # Average several enrollment images for a more stable primary template.
    avg=normalize_feature(np.mean(np.vstack(features),axis=0))
    try:
        db=get_db()
        cur=db.execute("""INSERT INTO users
          (name,student_id,role,department,email,phone,embedding,created_at,photo_count)
          VALUES(?,?,?,?,?,?,?,?,?)""",
          (form["name"].strip(),form["student_id"].strip(),form["role"].strip(),
           form.get("department","").strip(),form.get("email","").strip(),
           form.get("phone","").strip(),avg.tobytes(),
           datetime.now().isoformat(timespec="seconds"),len(features)))
        user_id=cur.lastrowid
        for feature in features:
            db.execute("INSERT INTO user_embeddings(user_id,embedding,source,created_at) VALUES(?,?,?,?)",
                       (user_id,feature.tobytes(),"camera/upload",datetime.now().isoformat(timespec="seconds")))
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return jsonify(error="Student ID already exists."),409
    return jsonify(message=f"Registered successfully with {len(features)} face photo(s).")

@app.get("/api/users")
def users():
    rows=get_db().execute("""SELECT name,student_id,role,department,email,phone,photo_count,created_at
                             FROM users ORDER BY id DESC""").fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/attendance")
def attendance():
    rows=get_db().execute("""SELECT u.name,u.student_id,a.action,a.timestamp
                             FROM attendance a JOIN users u ON u.id=a.user_id
                             ORDER BY a.id DESC LIMIT 100""").fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/alerts")
def alerts():
    rows=get_db().execute("SELECT alert_type,message,timestamp FROM alerts ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/items")
def items():
    rows=get_db().execute("SELECT item_code,title,status FROM library_items ORDER BY id DESC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/items")
def add_item():
    data=request.get_json(force=True); code=str(data.get("item_code","")).strip(); title=str(data.get("title","")).strip()
    if not code or not title: return jsonify(error="Item code and title are required."),400
    try:
        db=get_db(); db.execute("INSERT INTO library_items(item_code,title) VALUES(?,?)",(code,title)); db.commit()
    except sqlite3.IntegrityError: return jsonify(error="Item code already exists."),409
    return jsonify(message="Library item added.")

if __name__=="__main__":
    init_db(); load_models(); app.run(host="0.0.0.0",port=int(os.environ.get("PORT",5000)),debug=False)
