# Tell5

**Your AI sales team works WhatsApp while you sleep.**

---

Small businesses using WhatsApp struggle to manage customers efficiently. Orders, complaints, inquiries, and feedback all mix together in one inbox. Customers get ignored. Sales get lost. Business owners burn out trying to reply 24/7.

Tell5 fixes this. It connects to your WhatsApp number, learns your business, and answers every customer automatically — like a salesperson who knows your prices, your policies, and never sleeps.

---

## How It Works

**1. Connect your WhatsApp** — QR code or phone pairing. No Twilio, no sandbox, no third-party number. Your existing WhatsApp works.

**2. Tell the AI about your business** — Name, services, prices, hours, policies. The AI introduces itself as from YOUR business, never as Tell5.

**3. It starts selling** — Customers message your number. The AI answers questions, recommends products, gives estimates, takes orders. All in natural WhatsApp conversation.

**4. You stay in control** — Every conversation logged. Add knowledge from your dashboard. Turn AI on/off. Watch everything in real time.

---

## Features

- **WhatsApp Bot** — Connect via QR or pairing code. Auto-reconnects on disconnect. Your existing number.
- **AI Sales Assistant** — Multi-tier AI (Gemini → Groq → OpenRouter → Mistral) with automatic fallback. Knows your business name, owner, services, price range, and policies. Never pitches Tell5 unless asked.
- **Business Profile** — Name, description, category, services, pricing, hours, logo, products. The AI reads it before every reply.
- **Knowledge Base** — Add facts, policies, product details. The AI uses them naturally. Update anytime from the dashboard.
- **Dashboard** — Live conversation log, AI chat sandbox, bot controls, conversation stats, knowledge & template management.
- **Conversation Log** — Every message and AI reply stored with customer name and profile. See who's asking what.
- **Order Tracking** — Parse orders from messages. Track status. Get notified on new orders.
- **Discover Page** — Customers browse public business profiles. Search, filter by category.
- **Admin Panel** — AI provider health, circuit breaker status, pipeline logs, recent contacts, system health checks.
- **Forgot Password** — Self-service reset, no email service required.
- **Google OAuth** — Sign in with Google.
- **Multi-tier Reliability** — If Gemini fails, Groq takes over. If Groq fails, OpenRouter. Circuit breaker prevents cascading failures.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| WhatsApp | Baileys v7 (Node.js, ESM) — QR + pairing code |
| Web Server | FastAPI (Python) + Uvicorn |
| Database | PostgreSQL + asyncpg + SQLAlchemy 2.0 |
| AI (Tier 1) | Google Gemini |
| AI (Tier 2) | Groq (Llama 3) |
| AI (Tier 3) | OpenRouter (Gemini fallback) |
| AI (Tier 4) | Mistral Large (orchestrator) |
| Agents | Google ADK |
| Auth | Session cookies + Google OAuth |
| Frontend | Vanilla JS, Tailwind CSS, Chart.js |
| Process Mgmt | start.sh — Node.js + Python in one container |
| Hosting | Render (single service, Dockerfile) |
| Discovery | Google Cloud Discovery Engine (optional) |

---

## Quick Start

```bash
# Install
pip install -r requirements.txt
cd services/whatsapp && npm install && cd ../..

# Configure
cp .env.example .env
# Edit .env — set DATABASE_URL, SESSION_SECRET, GEMINI_API_KEY

# Run (two terminals)
uvicorn api.index:app --reload --host 0.0.0.0 --port 8000
node services/whatsapp/index.js
```

Open `http://localhost:8000` → sign up → set up business → connect WhatsApp.

---

## API Endpoints

### Auth
| POST | `/api/auth/signup` | Create account |
| POST | `/api/auth/login` | Login |
| POST | `/api/auth/logout` | Logout |
| GET | `/api/auth/me` | Current user |
| POST | `/api/auth/send-reset` | Generate reset token |
| POST | `/api/auth/reset-password` | Reset password |

### WhatsApp Bot
| GET | `/api/baileys/status` | Bot connection status |
| POST | `/api/baileys/webhook` | Bot message webhook |
| POST | `/api/whatsapp/restart` | Restart bot |

### Business
| GET/POST | `/api/business/profile` | Get/update business profile |
| GET/POST/DELETE | `/api/business/products` | Product CRUD |
| GET | `/api/business/discover` | List public profiles |

### AI & Knowledge
| POST | `/api/chat/send` | Dashboard AI chat |
| GET/POST/DELETE | `/api/knowledge` | Knowledge base CRUD |
| GET/POST/DELETE | `/api/reply-templates` | Reply template CRUD |

### Admin
| GET | `/api/admin/summary` | Full admin summary |
| GET | `/api/pipeline/circuit-breaker` | Circuit breaker states |
| POST | `/api/discovery/sync` | Sync to Discovery Engine |

---

## Deployment (Render)

Single Web Service using `Dockerfile.render`:

1. Push to GitHub
2. Create Render Web Service → connect repo
3. Set env vars in Render dashboard
4. Deploy — `start.sh` runs both Node bot and Python server

The bot accesses the API at `http://localhost:8000` inside the container.

---

## Project Structure

```
Tell5/
├── api/index.py              # FastAPI routes
├── ai.py                     # Gemini client + prompt builder
├── models.py                 # 12 SQLAlchemy models
├── crud.py                   # Database operations
├── auth.py / csrf.py         # Auth + CSRF
├── config.py                 # Env var config
├── start.sh                  # Boots Node + Python
├── Dockerfile.render         # Production image
├── services/
│   ├── whatsapp/index.js     # WhatsApp bot (Baileys)
│   └── ai/                   # Multi-tier AI pipeline
│       ├── pipeline.py       # Orchestrator
│       ├── personality.py    # Q&A matching + blocking
│       ├── groq_client.py
│       ├── openrouter_client.py
│       ├── mistral_client.py
│       ├── circuit_breaker.py
│       ├── adk_agent.py
│       └── discovery_engine.py
├── templates/                # 10 HTML pages
└── requirements.txt
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `SESSION_SECRET` | Yes | Random secret for cookies |
| `GEMINI_API_KEY` | Recommended | Google Gemini |
| `GROQ_API_KEY` | No | Groq fallback |
| `OPENROUTER_API_KEY` | No | OpenRouter fallback |
| `MISTRAL_API_KEY` | No | Mistral fallback |
| `ADMIN_EMAIL` | No | Auto-assign admin |
| `COOKIE_SECURE` | No | `True` on HTTPS (Render) |

---

## LICENSE

MIT
