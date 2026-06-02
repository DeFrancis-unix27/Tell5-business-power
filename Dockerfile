FROM python:3.12-slim

WORKDIR /app

# Install curl (needed for nvm)
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Install Node.js via nvm (much faster than apt-get + nodesource)
ENV NVM_DIR=/root/.nvm
RUN curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
RUN bash -c "source $NVM_DIR/nvm.sh && nvm install 20 && nvm use 20 && npm install -g npm"
ENV PATH="$NVM_DIR/versions/node/v20.18.0/bin:$PATH"

# Copy dependency files first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/whatsapp/package.json services/whatsapp/package.json
RUN cd services/whatsapp && npm install

# Copy application code
COPY . .

EXPOSE 8000 3001

CMD node services/whatsapp/index.js & uvicorn api.index:app --host 0.0.0.0 --port ${PORT:-8000}
