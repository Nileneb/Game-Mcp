# base
# sys deps
# python deps
# app
FROM python:3.11-slim
WORKDIR /app

# Ensure bash is available for startup script
RUN apt-get update && apt-get install -y --no-install-recommends bash && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x start_mining.sh

EXPOSE 8082 8083
CMD ["/bin/bash", "-lc", "./start_mining.sh"]
