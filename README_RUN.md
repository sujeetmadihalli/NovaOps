# NovaOps — How to Run

## Prerequisites

- Python 3.x installed at `E:\VirtualEnvs\apiapp-YRc1n0Op\`
- AWS credentials set in `.env` (see step 0)

---

## Step 0 — Set Up `.env`

Create a file called `.env` in the project root with:

```
AWS_ACCESS_KEY_ID=your_key_here
AWS_SECRET_ACCESS_KEY=your_secret_here
AWS_DEFAULT_REGION=us-east-1
```

---

## Step 1 — Allow PowerShell Scripts (one-time)

Open PowerShell as Administrator and run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

---

## Step 2 — Install Dependencies (one-time)

```powershell
& "E:\VirtualEnvs\apiapp-YRc1n0Op\Scripts\Activate.ps1"
cd "e:\Nova Hackathon\NovaOps"
pip install -r requirements.txt
```
(Deactivate the virtual env created by Activate.ps1 run the command "deactivate")
---

## Step 3 — Start the API Backend

Open **Terminal 1** and run:

```powershell
& "E:\VirtualEnvs\apiapp-YRc1n0Op\Scripts\Activate.ps1"
cd "e:\Nova Hackathon\NovaOps"
$env:PYTHONPATH = "."
uvicorn api.server:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

---

## Step 4 — Start the Dashboard

Open **Terminal 2** and run:

```powershell
& "E:\VirtualEnvs\apiapp-YRc1n0Op\Scripts\Activate.ps1"
cd "e:\Nova Hackathon\NovaOps"
python -m http.server 8081 --directory dashboard
```

---

## Step 5 — Open the App

| URL | What |
|-----|------|
| `http://localhost:8081` | Dashboard UI |
| `http://localhost:8000/docs` | FastAPI Swagger docs |
| `http://localhost:8000/health` | Health check |

---

## Step 6 — Trigger a Test Incident

In a third terminal, send a mock alert to the agent:

```powershell
& "E:\VirtualEnvs\apiapp-YRc1n0Op\Scripts\Activate.ps1"
cd "e:\Nova Hackathon\NovaOps"
$env:PYTHONPATH = "."
python evaluation_harness/multi_scenario_test.py
```

Or fire a single webhook manually:

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/webhook/pagerduty" `
  -Method POST `
  -ContentType "application/json" `
  -Body '{"alert_name":"HighMemoryUsage","service_name":"redis-cache","namespace":"default","incident_id":"INC-001","description":"Memory spike detected"}'
```

---

## Step 7 — Generate a Post-Incident Report

1. Open the dashboard at `http://localhost:8081`
2. Click **"Post-Incident Report"** on any incident card
3. Nova will generate a structured PIR and display it in a modal
4. Click **"Copy Report"** to copy it to clipboard

---

## Stopping the App

Press `Ctrl+C` in both Terminal 1 and Terminal 2.
