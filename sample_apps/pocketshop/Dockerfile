# PocketShop — production-style image for Hull's Docker Compose deploy path.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install Python deps first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App source.
COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8000

# The entrypoint migrates (idempotent; seeds catalog) then serves on $PORT.
CMD ["./entrypoint.sh"]
