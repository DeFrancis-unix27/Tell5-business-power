FROM python:3.12-slim
WORKDIR /app

# Install Node.js 20 for Baileys bot
RUN apt-get update && apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Google credentials on Cloud Run
ENV GOOGLE_APPLICATION_CREDENTIALS=/app/json/tell5-498219-460db9f7fe24.json

# Fix credentials path in .env
RUN sed -i 's|/json/tell5|/app/json/tell5|g' .env 2>/dev/null || true

CMD ["bash", "render-start.sh"]
