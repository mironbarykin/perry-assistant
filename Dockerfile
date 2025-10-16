FROM python:3.11-slim

RUN apt-get update && apt-get upgrade -y && apt-get clean

WORKDIR /app

COPY . /app

# Create log directory for persistent logging
RUN mkdir -p /data/logs

# Set up /data as a volume for persistent data (logs, etc.)
VOLUME ["/data"]

RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
