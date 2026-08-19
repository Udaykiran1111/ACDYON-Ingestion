# Task 1 Job Ingestion — Split Deployment Package

This release contains a clean two-part package for the Task 1 reviewer dashboard.

The `frontend/` folder is a static dashboard intended for Vercel. The `backend/` folder contains the Python FastAPI API, ingestion runner, tests, Dockerfile, and Render Blueprint. The frontend calls the backend through `frontend/config.js`.

Read [SETUP_AND_DEPLOYMENT.md](SETUP_AND_DEPLOYMENT.md) before running the project. It covers laptop setup, environment variables, local testing, Vercel deployment, Render deployment, CORS, scheduling, and final verification.

Read [AUDIT_REPORT.md](AUDIT_REPORT.md) for the honest implementation audit, verification evidence, and remaining production limitations.

The package intentionally excludes the original Node/tRPC scaffold, local SQLite data, logs, caches, build output, dependency folders, secrets, archives, and unused chatbot/template UI files. See `.gitignore` for the complete exclusion list.
