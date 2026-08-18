# SmartLib — Automatic Webcam Library Gate

MCA mini-project for automatic library entry/exit using a webcam, OpenCV YuNet face detection and SFace face recognition.

## Features
- Live webcam gate at `/gate`
- Automatic face recognition
- Automatic ENTRY/EXIT toggle
- 10-second duplicate protection
- SQLite database
- Student registration
- Dashboard and attendance logs
- Unknown-person detection
- Library item database foundation for RFID/barcode integration

## Windows setup

Open PowerShell inside the SmartLib folder:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe download_models.py
.venv\Scripts\python.exe app.py
```

Then open:

- Dashboard: http://127.0.0.1:5000/
- Live gate: http://127.0.0.1:5000/gate

You do NOT need to activate PowerShell's virtual environment. Directly calling `.venv\Scripts\python.exe` avoids the ExecutionPolicy problem.

## First use

1. Open Dashboard.
2. Register a student using one clear photo containing exactly one face.
3. Open Live Gate.
4. Allow browser/camera access if prompted.
5. The webcam continuously scans.
6. First recognized appearance records ENTRY.
7. After the cooldown and a later appearance, the next recognition records EXIT.

## Important

This is an academic prototype. Do not use face recognition alone as a high-stakes security decision. Obtain appropriate consent and protect biometric data.

For physical book exit control, integrate RFID/barcodes. A camera alone should not be treated as a reliable proof that a particular book is authorized to leave.

The `MATCH_THRESHOLD` in `app.py` is a starting value and should be evaluated on representative consented test data before real use.

Do not commit `smartlib.db`, real student photos, biometric embeddings, or model files to GitHub.


## Deploy on Render

This version uses the browser webcam on `/gate`, so the camera is accessed by the visitor's device rather than the Render server.

1. Push this folder to GitHub.
2. In Render, create a **Web Service** from the GitHub repository.
3. Use build command: `pip install -r requirements.txt && python download_models.py`
4. Use start command: `gunicorn --workers 1 --threads 4 --timeout 120 app:app`
5. Set `PYTHON_VERSION=3.13.5`.
6. Open the HTTPS `/gate` URL and allow camera permission.

The SQLite database is suitable for a demo, but Render's default filesystem is ephemeral. For real production data, migrate attendance/users to PostgreSQL or attach a persistent disk.
