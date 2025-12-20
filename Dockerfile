# base
FROM python:3.11-slim
WORKDIR /app

# sys deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && rm -rf /var/lib/apt/lists/*

# python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# app
COPY server.py ./server.py
COPY simulate_iot_device.py ./simulate_iot_device.py

ENV FASTMCP_HOST=0.0.0.0 \
    FASTMCP_PORT=8082 \
    SSE_PATH=/sse-paperstream \
    RESULT_PATH=/paper-result

EXPOSE 8082
CMD ["python","-u","/app/server.py"]
