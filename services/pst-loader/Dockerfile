FROM python:3.11-slim

RUN pip install --no-cache-dir boto3 psycopg2-binary

WORKDIR /app
COPY load_emails.py /app/load_emails.py

ENTRYPOINT ["python", "/app/load_emails.py"]

