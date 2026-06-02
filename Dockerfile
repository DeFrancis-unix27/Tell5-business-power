FROM python:3.12-slim

WORKDIR /app

# Install Node.js 20
RUN apt-get update && \
    apt-get install -y curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/whatsapp/package.json services/whatsapp/
RUN cd services/whatsapp && npm install

# Copy application code
COPY . .

# Expose ports
EXPOSE 8000 3001

# Start both services
CMD node services/whatsapp/index.js & uvicorn api.index:app --host 0.0.0.0 --port ${PORT:-8000}
