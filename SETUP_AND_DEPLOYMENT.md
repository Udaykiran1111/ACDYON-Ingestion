# Task 1 Job Ingestion — Laptop Setup and Deployment Guide

## 1. Package layout

This ZIP is intentionally split into two deployable parts:

| Folder | Purpose | Deployment target |
|---|---|---|
| `frontend/` | Static reviewer dashboard | Vercel or any static host |
| `backend/` | FastAPI API, ingestion runner, SQLite persistence, tests, and Dockerfile | Render or another container host |

The original Node/tRPC scaffold is not included in this release package. Confirmed unused template UI files were removed. The reviewer documentation and audit report are included at the package root.

> **Hosting note:** Vercel and Render are external hosting providers. The active managed project preview uses a different runtime path. The split deployment below is an independent release arrangement and must be smoke-tested after deployment.

## 2. Requirements on your laptop

Install Python 3.11 or newer, Git, and a modern browser. Node.js is not required for this split package because the frontend is a plain static HTML page. Docker is optional for local container testing.

Check the installations:

```bash
python --version
pip --version
git --version
```

## 3. Backend local setup

Open a terminal in the extracted package and move into the backend folder:

```bash
cd backend
python -m venv .venv
```

Activate the environment. On macOS or Linux:

```bash
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Set the local reviewer token. On macOS or Linux:

```bash
export REVIEWER_TOKEN=local-reviewer-token
export ALLOWED_ORIGINS=http://localhost:5500,http://127.0.0.1:5500
```

On Windows PowerShell:

```powershell
$env:REVIEWER_TOKEN="local-reviewer-token"
$env:ALLOWED_ORIGINS="http://localhost:5500,http://127.0.0.1:5500"
```

Start the backend from the `backend` folder:

```bash
uvicorn python_app.main:app --reload --port 8000
```

Keep this terminal running. The API is now available at `http://localhost:8000`.

The service creates `jobs.sqlite3` automatically. This file is intentionally ignored by Git because it contains local runtime data. Do not commit it.

## 4. Frontend local setup

Open a second terminal. Move into the frontend folder and serve it with Python’s static server:

```bash
cd frontend
python -m http.server 5500
```

Open `http://localhost:5500` in your browser. The included `config.js` already points to `http://localhost:8000`.

When the page asks for the reviewer token, enter the same value used for `REVIEWER_TOKEN`. The browser stores it locally for later requests.

## 5. Local verification

The backend tests run from the `backend` folder:

```bash
pytest -q
python -m compileall -q python_app
```

A successful test run should report the current Python test count shown in the project audit report. Then verify the browser flow:

1. Open the frontend.
2. Enter the reviewer token.
3. Confirm the dashboard loads.
4. Click **Trigger Run Now**.
5. Confirm the red progress bar appears during the run.
6. Wait for the run to finish.
7. Confirm the progress animation disappears and the latest totals refresh.
8. Open Run history and confirm entries are ingestion runs, not tests.
9. Schedule and delete a schedule only if you want to verify the schedule controls.

## 6. Render backend deployment

Create a new Render Web Service from the `backend` folder. You can use the included `render.yaml` as a Blueprint, or configure the service manually.

Recommended settings:

| Render field | Value |
|---|---|
| Runtime | Docker |
| Dockerfile | `backend/Dockerfile` if deploying from the repository root; `Dockerfile` if the Render root directory is set to `backend` |
| Health check path | `/` |
| Port | Use the platform-provided `PORT`; the container already reads it |
| Build context | The `backend` directory |

Set these environment variables in Render:

| Variable | Example | Purpose |
|---|---|---|
| `REVIEWER_TOKEN` | Use a strong random secret | Protects dashboard and trigger endpoints |
| `ALLOWED_ORIGINS` | Your Vercel URL, for example `https://your-frontend.vercel.app` | Allows the Vercel browser to call the API |
| `SQLITE_PATH` | `/var/data/jobs.sqlite3` | Local SQLite path inside the service |

Do not commit the real reviewer token. Do not place it in `config.js` on the frontend. The frontend token is entered by the reviewer in the browser; the backend validates it.

After Render deploys, test the backend root URL in a browser. It should return a small API message. A 403 response from a protected endpoint without the token is expected.

Important persistence limitation: SQLite inside a normal autoscaled or ephemeral service is not a production durability guarantee. Use a managed PostgreSQL/MySQL-compatible database or a persistent disk before treating the deployment as production-ready.

## 7. Vercel frontend deployment

Create a new Vercel project from the `frontend` folder. Select **Other** or a static deployment. No build command is required. Set the output directory to the project root, or leave the framework preset blank if Vercel asks.

Before deploying, edit `frontend/config.js`:

```javascript
window.APP_CONFIG = {
  API_BASE: "https://your-render-backend.onrender.com"
};
```

For a team workflow, copy `config.example.js` to `config.js` during deployment preparation and replace the placeholder URL. The `config.js` file is ignored by Git so it should be supplied through your deployment workflow rather than committed as a secret-bearing file.

Deploy the static frontend. Then update the Render `ALLOWED_ORIGINS` value to the exact Vercel URL, redeploy or restart Render, and reload the Vercel page.

## 8. Cross-host verification

After both services are deployed, perform this sequence:

1. Open the Vercel URL.
2. Enter the same `REVIEWER_TOKEN` configured on Render.
3. Confirm the dashboard request succeeds.
4. Click **Trigger Run Now**.
5. Confirm the progress panel updates and eventually stops.
6. Confirm fetched and inserted totals refresh.
7. Open Run history and verify that records are labeled as ingestion runs.
8. Confirm browser developer tools show no CORS error.
9. Call the Render root URL directly to confirm the backend is healthy.
10. Call the scheduled endpoint only from your authorized scheduler with `X-Cron-Token` set to the same secret.

If the browser shows a CORS error, check `ALLOWED_ORIGINS` first. If it shows 403, check that the browser token exactly matches `REVIEWER_TOKEN`. If the dashboard loads but has no data, check the Render logs and the SQLite persistence limitation.

## 9. What is intentionally not included

The package does not include the original Node/tRPC preview scaffold, Manus-only runtime metadata, local SQLite files, Python caches, dependency folders, build directories, logs, editor settings, or generated archives. The `.gitignore` documents these exclusions. The active chatbot component and confirmed unused template UI files were removed because this product does not use them.

## 10. Final submission checklist

Before sharing the project, confirm that the ZIP contains `frontend/index.html`, `frontend/config.example.js`, `backend/python_app/main.py`, `backend/python_app/ingestion.py`, `backend/requirements.txt`, `backend/Dockerfile`, `backend/render.yaml`, the Python tests, `.gitignore`, `README.md`, `AUDIT_REPORT.md`, and this guide.

Before claiming deployment completion, record the actual Vercel URL, Render URL, test result, manual-trigger result, scheduled-callback result, and database choice. Do not claim that a feature worked in production based only on local tests.
