FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY python_app ./python_app
COPY python_tests ./python_tests

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn python_app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
