FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot/ ./
ENV PYTHONUNBUFFERED=1 DATA_DIR=/app/data GOOGLE_CREDENTIALS=/app/secrets/service-account.json
CMD ["python", "main.py"]
