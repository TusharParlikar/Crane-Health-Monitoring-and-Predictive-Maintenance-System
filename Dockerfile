FROM python:3.12-slim
# XGBoost needs the OpenMP runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY crane crane
# Models are trained at build time so the image is self-contained
RUN python -m crane.train
