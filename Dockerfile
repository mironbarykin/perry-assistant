FROM python:3.11-slim

RUN apt-get update && apt-get upgrade -y && apt-get clean

WORKDIR /app

COPY . /app

# Create data and log directories for persistent storage
RUN mkdir -p /data/logs

# Set DATA_DIR env so app uses it
ENV DATA_DIR=/data

# Set up /data as a volume for persistent data (logs, json, credentials)
VOLUME ["/data"]

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
