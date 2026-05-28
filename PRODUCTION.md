# Production Deployment Guide

This guide covers deploying Tell5 to production safely and securely.

## Pre-Deployment Checklist

### Security

- [ ] **Environment Variables**: Generate strong, random values for all required variables:
  - `SESSION_SECRET`: At least 32 characters, generated with `python -c "import secrets; print(secrets.token_urlsafe(32))"`
  - `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`: Stored securely, never in version control
  - All API keys for third-party services

- [ ] **COOKIE_SECURE**: Set to `True` (only send cookies over HTTPS)
  - This requires a valid SSL/TLS certificate

- [ ] **DEBUG**: Set to `False`

- [ ] **Database**: Use a managed PostgreSQL service (Aiven, AWS RDS, Heroku Postgres, etc.)
  - Enable SSL connections
  - Use strong passwords
  - Regular backups enabled

- [ ] **Secrets Management**: Use your platform's secret management:
  - Heroku Config Vars
  - AWS Secrets Manager
  - Railway Secrets
  - Docker secrets for Swarm/Kubernetes

### Infrastructure

- [ ] **HTTPS/TLS**: Valid certificate from Let's Encrypt or your provider
- [ ] **Database Backups**: Automated daily backups to separate storage
- [ ] **Monitoring**: Set up error tracking and logging (Sentry, DataDog, etc.)
- [ ] **DNS**: Configure custom domain with HTTPS
- [ ] **Load Balancer**: If scaling beyond single instance

### Code

- [ ] **Tests**: Run full test suite
- [ ] **Database Migrations**: Test migrations on production-like database
  ```bash
  alembic upgrade head
  ```
- [ ] **Dependencies**: All pinned to specific versions in `requirements.txt`
- [ ] **Logs**: Configured to rotate and not fill disk

## Deployment Options

### Option 1: Heroku (Easiest)

```bash
# Install Heroku CLI
brew tap heroku/brew && brew install heroku

# Login
heroku login

# Create app
heroku create your-app-name

# Add PostgreSQL addon
heroku addons:create heroku-postgresql:standard-0

# Set environment variables
heroku config:set \
  TWILIO_ACCOUNT_SID=your_sid \
  TWILIO_AUTH_TOKEN=your_token \
  SESSION_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))") \
  DEBUG=False \
  COOKIE_SECURE=True \
  ENVIRONMENT=production

# Deploy
git push heroku main

# Run migrations
heroku run alembic upgrade head

# View logs
heroku logs --tail
```

### Option 2: Docker + Railway

```bash
# Push to GitHub first
git push origin main

# Login to Railway
railway login

# Initialize project
railway init

# Link to GitHub repo
railway link

# Set environment variables in Railway dashboard

# Deploy (automatic on push to main)
git push origin main

# View logs
railway logs
```

### Option 3: AWS ECS + RDS

1. Create RDS PostgreSQL instance
2. Create ECR repository
3. Build and push Docker image:
   ```bash
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <your-ecr-uri>
   docker build -t tell5:latest .
   docker tag tell5:latest <your-ecr-uri>/tell5:latest
   docker push <your-ecr-uri>/tell5:latest
   ```
4. Create ECS cluster and task definition
5. Configure task definition with environment variables from Secrets Manager
6. Deploy service

### Option 4: Docker Compose + VPS

```bash
# On production server
git clone https://github.com/your-username/Tell5.git
cd Tell5

# Create production .env
cat > .env.prod << EOF
ENVIRONMENT=production
DEBUG=False
COOKIE_SECURE=True
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
SESSION_SECRET=your_generated_secret
DATABASE_URL=postgresql+asyncpg://user:pass@prod-db:5432/tell5
# ... other vars
EOF

# Run with docker-compose
docker-compose -f docker-compose.yml --env-file .env.prod up -d

# Run migrations
docker-compose exec tell5-app alembic upgrade head

# Setup reverse proxy (nginx)
# Configure SSL certificate
```

## Post-Deployment

### Verify

```bash
# Check health endpoint
curl https://your-domain.com/healthz
# Should return {"ok": true}

# Check admin dashboard (login required)
curl https://your-domain.com/admin

# Verify Twilio webhook is accessible
# In Twilio Console → Messaging → Settings → WhatsApp Sandbox
# Update callback URL to: https://your-domain.com/webhook/whatsapp
```

### Monitoring

Set up monitoring for:
- Application errors (Sentry)
- Database performance
- API response times
- Disk usage
- Memory usage
- Failed database connections

### Logging

Configure log aggregation:
- Send logs to CloudWatch, DataDog, or similar
- Set up alerts for ERROR level logs
- Archive logs after 30 days
- Monitor log file disk usage

### Scaling

If traffic increases:
- **Horizontal**: Add more application instances behind load balancer
- **Vertical**: Increase instance size/resources
- **Database**: Upgrade to higher tier PostgreSQL
- **Caching**: Add Redis for session/cache layer

## Backup & Recovery

### Automated Backups

- Database: Daily automated backups (7-14 day retention)
- Application code: Git repository (essential)
- Secrets: Never backup plaintext secrets

### Recovery Plan

1. **Database Recovery**: Use managed backup restore
2. **Application Recovery**: 
   ```bash
   git clone https://github.com/your-username/Tell5.git
   cd Tell5
   # Set env variables
   docker-compose up
   alembic upgrade head
   ```
3. **Test Recovery**: Quarterly disaster recovery drill

## Updating Production

### Safe Update Process

```bash
# 1. Create feature branch
git checkout -b production-update

# 2. Make changes and test locally
# 3. Commit and create PR

# 4. After PR review is approved
git checkout main
git pull origin main

# 5. Test migrations in staging
docker-compose -f docker-compose.staging.yml exec app alembic upgrade head

# 6. Deploy to production (different per platform)
# Heroku: git push heroku main
# Railway: git push origin main (auto-deploys)
# AWS/VPS: docker-compose up

# 7. Verify health
curl https://your-domain.com/healthz
```

### Zero-Downtime Updates

For critical updates, use blue-green deployment:
1. Deploy new version to separate instance
2. Run migrations on new instance
3. Health check new instance
4. Switch load balancer to new instance
5. Keep old instance as rollback

## Troubleshooting

### App won't start
```bash
# Check logs
heroku logs --tail  # Heroku
railway logs        # Railway
docker-compose logs # Docker
```

### Database connection fails
- Verify DATABASE_URL is correct
- Check database credentials
- Ensure SSL certificates are valid
- Check security group/firewall rules

### Migrations fail
- Backup database first
- Check migration files for SQL errors
- Roll back: `alembic downgrade -1`
- Fix issue and create new migration

## Performance Optimization

- Enable database query caching
- Use CDN for static files
- Set HTTP cache headers appropriately
- Monitor and optimize slow queries
- Consider database connection pooling (PgBouncer)

## Security Hardening

- Keep dependencies updated: `pip install --upgrade -r requirements.txt`
- Enable database encryption at rest
- Use VPC/security groups to restrict access
- Implement IP whitelisting for admin endpoints
- Regular security audits of dependencies
- Enable audit logging in database

---

For help, see [README.md](README.md) and [MIGRATIONS.md](MIGRATIONS.md)
