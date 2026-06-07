FROM node:20-slim

WORKDIR /app

COPY package*.json ./
RUN npm install --production

COPY . .

RUN groupadd -r bot && useradd -r -g bot -d /app -s /sbin/nologin bot && \
    chown -R bot:bot /app

USER bot

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD node -e "require('http').get('http://localhost:'+(process.env.BOT_PORT||3001)+'/health',r=>{process.exit(r.statusCode!==200?1:0)}).on('error',()=>process.exit(1))"

EXPOSE 3001

CMD node index.js
