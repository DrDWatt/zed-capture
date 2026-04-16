# Web Server Container for ZED Control UI
FROM python:3.8-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application
COPY app /app
COPY templates /app/templates
COPY static /app/static

WORKDIR /app

# Create video directory mount point
RUN mkdir -p /mnt/videos

EXPOSE 80

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
