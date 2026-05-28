# Tell5 - WhatsApp Workflow Automation Agent

A FastAPI-based backend for automating WhatsApp business workflows. Tell5 receives WhatsApp messages, categorizes them, logs interactions to a database, and sends automated responses.

## Features

- **WhatsApp Integration**: Receive and respond to messages via Twilio WhatsApp Sandbox
- **Message Categorization**: Automatically classify messages as orders, inquiries, complaints, or feedback
- **Order Management**: Log orders with customer details, items, and quantities
- **Real-time Dashboard**: Dark-themed Tailwind CSS dashboard with live conversation log and stats
- **Auto-reply System**: Intelligent auto-responses based on message category
- **Notification System**: Track new orders and important events
- **Async Architecture**: Built on FastAPI and async SQLAlchemy for high performance

## Tech Stack

- **Backend**: FastAPI, Python 3.8+
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Messaging**: Twilio WhatsApp API
- **Frontend**: Tailwind CSS, Chart.js
- **Async**: asyncpg, asyncio

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your Twilio credentials and database URL
```

**Required env vars:**
```env
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_PHONE_NUMBER=whatsapp:+1234567890
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/tell5
SESSION_SECRET=replace_with_a_long_random_secret
COOKIE_SECURE=False
```

### 3. Setup Database

```bash
# Local PostgreSQL
createdb tell5

# Or Docker
docker run -d --name postgres-tell5 -e POSTGRES_PASSWORD=password -e POSTGRES_DB=tell5 -p 5432:5432 postgres:14
```

### 4. Run Locally

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Visit: `http://localhost:8000/dashboard`

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/signup` | Create a dashboard user and session |
| POST | `/api/auth/login` | Log in and set the secure session cookie |
| POST | `/api/auth/logout` | Clear the session cookie |
| GET | `/api/auth/me` | Return the current logged-in user |
| POST | `/webhook/whatsapp` | Receive messages from Twilio |
| GET | `/api/conversations` | List all conversations |
| GET | `/api/orders` | List all orders |
| GET | `/api/stats` | Get category distribution & order count |
| GET | `/dashboard` | Real-time dashboard |

## Database Schema

**Conversations**: id, phone, message, category (order/inquiry/complaint/feedback), timestamp

**Orders**: id, phone, customer_name, item, quantity, status (pending/confirmed/shipped), timestamp

**Notifications**: id, type (new_order), payload, timestamp

**Users**: id, email, first_name, last_name, phone, password_hash, is_active, created_at

## Message Categorization

- **Order**: "order", "buy", "purchase"
- **Inquiry**: "price", "how", "info", "details", "when"
- **Complaint**: "complain", "issue", "bad", "wrong"
- **Feedback**: "thanks", "love", "good", "great"

## Auto-Reply Messages

- **Order**: "We've received your order. We'll confirm shortly."
- **Inquiry**: "Thanks for reaching out. A team member will respond soon."
- **Complaint**: "Sorry about that. We've escalated your complaint."
- **Other**: "Thanks for your message. We'll get back to you."

## Testing with Twilio

1. Go to [Twilio Console](https://console.twilio.com) → Messaging → Try it Out
2. Join WhatsApp sandbox (message the provided number)
3. Send a test message from your phone
4. Check dashboard for logged conversation

## Deployment

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Production Environment

```env
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=whatsapp:+...
DATABASE_URL=postgresql+asyncpg://prod-user:pass@prod-db:5432/tell5
SESSION_SECRET=generate-a-long-random-secret
COOKIE_SECURE=True
DEBUG=False
```

Use `AIVEN_CA_CERT_PATH=C:\path\to\ca.pem` or `PGSSLROOTCERT=C:\path\to\ca.pem` when connecting to Aiven with certificate verification.

Recommended hosting: Heroku, Railway, Render, AWS Lambda + RDS

## Project Structure

```
Tell5/
├── main.py              # FastAPI app, routes
├── models.py            # Database models
├── schemas.py           # Pydantic schemas
├── crud.py              # Database operations
├── db.py                # Database config
├── requirements.txt
├── .env.example
├── templates/dashboard.html
└── static/
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Invalid Twilio Signature | Check AUTH_TOKEN, ensure webhook is public (use ngrok locally) |
| Database connection refused | Verify PostgreSQL is running, check DATABASE_URL |
| No messages logged | Check webhook receiving requests, review logs |

## Development

### Enable Debug Logging

```bash
uvicorn main:app --reload --log-level debug
```

### Add Custom Categories

Edit `categorize_message()` in `main.py` and add your keywords.

### Database Migrations

Use Alembic for production:

```bash
pip install alembic
alembic init alembic
alembic revision --autogenerate -m "Initial"
alembic upgrade head
```

## Future Enhancements

- Customer name extraction from messages
- Sentiment analysis for complaints
- CRM system integration
- Message scheduling & delays
- Multi-workspace support
- User authentication for dashboard

## License

MIT

---

For more details, see [CONTRIBUTING.md](CONTRIBUTING.md) or contact the development team.
