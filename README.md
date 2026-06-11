# Tell5 — WhatsApp Business AI Platform

A WhatsApp business platform with an AI sales assistant that answers customers, tracks conversations, and helps businesses grow — all through WhatsApp.

## Features

- **WhatsApp Bot** — Connect via QR code or phone pairing (no Twilio Sandbox needed). Built on `@whiskeysockets/baileys`.
- **AI Sales Assistant** — Multi-tier AI pipeline (Gemini → Groq → OpenRouter → Mistral) with circuit breaker. Knows each business's name, services, price range, and owner.
- **Dashboard** — Real-time conversation log, knowledge base management, AI chat sandbox, stats, and bot controls.
- **Business Profile** — Set up your business name, services, pricing, hours, logo, and products. Public discover page.
- **Knowledge Base** — Add business facts the AI uses in replies. Products, policies, pricing — whatever you want the AI to know.
- **Discover Page** — Browse public business listings with search, category filters, and sort.
- **Forgot Password** — Token-based password reset flow (no email service needed).
- **Admin Panel** — Production checklist, AI provider status, pipeline logs, discovery engine sync.
- **Multi-tier AI** — Gemini (primary) with automatic fallback to Groq, OpenRouter, Mistral. Circuit breaker prevents cascading failures.
- **Conversation History** — All messages and AI replies stored with customer profiles.
- **Order Management** — Parse and track orders from WhatsApp messages.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Web Server | FastAPI (Python) + Uvicorn |
| WhatsApp Bot | Node.js + `@whiskeysockets/baileys` v7 (ESM) |
| Database | PostgreSQL via asyncpg + SQLAlchemy 2.0 |
| AI Pipeline | Google Gemini, Groq, OpenRouter, Mistral |
| Agent Framework | Google ADK (Agent Development Kit) |
| Discovery Engine | Google Cloud Discovery Engine (optional) |
| Auth | Session-based (secure cookies) + Google OAuth |
| Frontend | Vanilla JS, Tailwind CSS, Chart.js (inline) |
| Process Mgmt | `start.sh` — supervises Node + Python processes |
| Hosting | Render (single service, Dockerfile-based) |

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
cd services/whatsapp && npm install && cd ../..
```

### 2. Configure Environment

```bash
cp .env.example .env
```

**Required:**
```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/tell5
SESSION_SECRET=generate_a_long_random_secret
```

**AI (at least one):**
```env
GEMINI_API_KEY=your_gemini_key
GROQ_API_KEY=your_groq_key
OPENROUTER_API_KEY=your_openrouter_key
MISTRAL_API_KEY=your_mistral_key
```

### 3. Run Locally

```bash
# Terminal 1 — Python web server
uvicorn api.index:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Node.js WhatsApp bot
node services/whatsapp/index.js
```

Visit `http://localhost:8000` → sign up → set up business profile → connect WhatsApp.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Render Container                    │
│                                                      │
│  ┌──────────────┐      ┌──────────────────────────┐ │
│  │  Node.js Bot  │─────▶│   FastAPI (Python)       │ │
│  │  (Baileys)    │◀────│   /api/baileys/webhook    │ │
│  │               │     │                           │ │
│  │  QR/Pairing   │     │  AI Pipeline (Gemini etc) │ │
│  │  → WhatsApp   │     │  PostgreSQL CRUD          │ │
│  └──────────────┘      │  Template rendering       │ │
│                         └──────────────────────────┘ │
│                              │                       │
│                              ▼                       │
│                         ┌──────────┐                │
│                         │PostgreSQL│                │
│                         └──────────┘                │
└─────────────────────────────────────────────────────┘

WebSocket (pairing/QR)
  ↓
User's Phone ←→ WhatsApp ←→ Baileys Bot ←→ Python API ←→ DB
```

## Deployment (Render)

The app runs as a **single Render Web Service** using `Dockerfile.render`:

1. Push to GitHub
2. Create Render Web Service → connect repo
3. Set **Build Command**: (uses Dockerfile.render automatically)
4. Set **Start Command**: handled by start.sh inside container
5. Add env vars (see `.env` for all options)

**Important env vars for Render:**
- `DATABASE_URL` — Aiven PostgreSQL connection string
- `SESSION_SECRET` — Random secret for cookie signing
- `COOKIE_SECURE=True` — Required for HTTPS
- `ENVIRONMENT=production`
- At least one AI API key (GEMINI_API_KEY recommended)

The `start.sh` script boots both the Node.js bot and Python web server. The bot can access the API at `http://localhost:8000` internally.

## WhatsApp Bot

The bot in `services/whatsapp/index.js` handles:

| Feature | Detail |
|---------|--------|
| QR Code | Displayed on `/connect` page for first-time pairing |
| Pairing Code | Enter phone number on dashboard → receive 8-digit code |
| Auto-reconnect | Reconnects on disconnect (5s delay) |
| 408 Handling | Clears stale auth and re-requests pairing code |
| Logged Out | Clears auth and starts fresh |
| Message Sending | Retries with backoff on socket reconnect |
| Keep-alive | Presence update every 30s |

## API Endpoints

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/signup` | Create account |
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/auth/me` | Current user |
| POST | `/api/auth/send-reset` | Generate password reset token |
| GET | `/auth/reset/{token}` | Reset password page |
| POST | `/api/auth/reset-password` | Execute password reset |

### WhatsApp Bot
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/baileys/status` | Bot connection status |
| POST | `/api/baileys/webhook` | Webhook for bot messages |
| POST | `/api/whatsapp/restart` | Restart bot from dashboard |
| GET | `/api/csrf-token` | CSRF token (for form-based endpoints) |

### Business
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/business/profile` | Get business profile |
| POST | `/api/business/profile` | Create/update business profile |
| GET | `/api/business/products` | List products |
| POST | `/api/business/products` | Add product |
| DELETE | `/api/business/products/{id}` | Delete product |
| GET | `/api/business/discover` | List public business profiles |
| GET | `/discover` | Discover page (HTML) |
| GET | `/business-profile/{id}` | Business profile detail (HTML) |

### AI & Knowledge
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/chat/send` | Dashboard AI chat |
| GET | `/api/knowledge` | List knowledge entries |
| POST | `/api/knowledge` | Add knowledge entry |
| DELETE | `/api/knowledge/{id}` | Delete knowledge entry |
| GET | `/api/reply-templates` | List reply templates |
| POST | `/api/reply-templates` | Add reply template |
| DELETE | `/api/reply-templates/{id}` | Delete reply template |

### Admin
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/summary` | Full admin summary |
| GET | `/api/pipeline/circuit-breaker` | AI provider circuit breaker state |
| POST | `/api/discovery/sync` | Sync to Google Discovery Engine |
| POST | `/api/discovery/create-datastore` | Create Discovery Engine data store |

## AI Pipeline

Messages go through up to 4 AI tiers with automatic fallback:

| Tier | Provider | Purpose |
|------|----------|---------|
| 1 | Gemini (primary) | Main response generation |
| 2 | Groq | Fallback if Gemini fails |
| 3 | OpenRouter | Fallback if Groq fails |
| 4 | Mistral | Orchestrator / fallback |

Each tier uses a circuit breaker (3 failures → 60s cooldown). The pipeline also loads business context (name, services, knowledge base, conversation history) so the AI always knows who it's representing.

## Project Structure

```
Tell5/
├── api/index.py              # FastAPI app, all routes
├── ai.py                     # Gemini client, prompt builder
├── models.py                 # SQLAlchemy models
├── crud.py                   # Database CRUD operations
├── db.py                     # Database engine config
├── auth.py                   # Auth helpers (password, cookies)
├── csrf.py                   # CSRF token create/verify
├── config.py                 # App configuration from env
├── main.py                   # Compatibility import
├── requirements.txt
├── .env.example
├── Dockerfile.render         # Production Dockerfile (Node + Python)
├── start.sh                  # Supervises bot + web processes
├── services/
│   ├── whatsapp/
│   │   ├── index.js          # WhatsApp bot (Baileys)
│   │   ├── package.json
│   │   ├── auth/             # Stored WhatsApp credentials
│   │   └── qr-state.json     # Bot connection state
│   └── ai/
│       ├── pipeline.py       # Multi-tier AI pipeline
│       ├── personality.py    # Q&A matching, message blocking
│       ├── gemini_client.py  # Gemini integration
│       ├── groq_client.py    # Groq integration
│       ├── openrouter_client.py  # OpenRouter integration
│       ├── mistral_client.py # Mistral integration
│       ├── mcp_router.py     # MongoDB MCP router
│       ├── mongodb_tools.py  # MongoDB conversation tools
│       ├── circuit_breaker.py # Circuit breaker per provider
│       ├── metrics.py        # Provider success/fail metrics
│       ├── adk_agent.py      # Google ADK agent
│       ├── discovery_engine.py # Google Discovery Engine
│       └── mcp_router.py     # MCP server router
├── templates/
│   ├── landingpage.html      # Landing, login, signup, forgot password
│   ├── dashboard.html        # Main dashboard
│   ├── admin.html            # Admin panel
│   ├── connect.html          # WhatsApp connection page
│   ├── business_setup.html   # Business profile setup
│   ├── discover.html         # Business discover page
│   ├── business_profile.html # Public business profile
│   ├── reset_password.html   # Password reset form
│   └── help.html             # Help page
└── static/
    └── images/               # Brand assets
```
