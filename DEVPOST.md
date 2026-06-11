# Tell5

**Your AI sales team works WhatsApp while you sleep.**

---

## Inspiration

Small business owners in Africa are accessible 24/7 through WhatsApp — their customers message them directly. But the business owner can't reply at 2 AM, or while driving, or when serving another customer face-to-face. Messages pile up. Sales slip away. Some hire receptionists, which costs money and still doesn't solve overnight coverage.

We built Tell5 so every small business can have an AI sales assistant that lives on their WhatsApp — answering questions, recommending products, taking orders, and never sleeping. The customer texts like they're talking to a real person. The business owner wakes up to orders already captured and customers already served.

## What it does

Tell5 connects to any WhatsApp number via QR code or phone pairing code — no Twilio, no sandbox, no third-party number. Once connected, the business owner sets up a profile (business name, services, prices, hours, policies) and optionally adds knowledge base entries (product details, FAQ, pricing rules).

When a customer messages the business on WhatsApp, Tell5's AI pipeline processes the message through multiple AI providers (Gemini primary, with automatic fallback to Groq, OpenRouter, and Mistral). The AI knows exactly which business it represents — it introduces itself naturally, answers questions about services and pricing, recommends products, and takes orders. Every conversation is logged on a real-time dashboard where the owner can read, manage knowledge, and control the bot.

The dashboard also includes an AI chat sandbox for testing replies, a business profile editor, product management, conversation stats, and an admin panel showing AI provider health and pipeline logs.

## How we built it

- **WhatsApp connection**: Node.js bot using `@whiskeysockets/baileys` v7 (ESM) — handles QR code registration, phone pairing, auto-reconnection on disconnect, and stale session cleanup.
- **Web server**: FastAPI (Python) with async SQLAlchemy + asyncpg for PostgreSQL — handles all API routes, authentication, template rendering, and AI orchestration.
- **AI pipeline**: Multi-tier architecture with circuit breaker. Tier 1 is Google Gemini (temperature 0.7, max 300 tokens). If Gemini fails, fallback to Groq (Llama 3), then OpenRouter, then Mistral as orchestrator. Each provider has its own client wrapper with retry logic and cooldown.
- **Frontend**: Vanilla JavaScript with Tailwind CSS — no framework. All pages are server-rendered Jinja2 templates. Dashboard has live conversation log, AI chat sandbox, bot status, and knowledge base CRUD.
- **Deployment**: Single Render Web Service using a Dockerfile that installs both Python deps and Node.js, then `start.sh` supervises both processes.
- **Auth**: Session-based with secure cookies, CSRF protection for form endpoints, and Google OAuth option.

### Google Cloud Products Used

| Product | What we use it for |
|---------|-------------------|
| **Gemini API** (`google-genai`) | Primary AI engine — handles message classification, reply generation, and confidence checking. Runs at temperature 0.7, max 300 tokens. First tier in our multi-provider pipeline. |
| **Discovery Engine / Agent Builder** (`google-cloud-discoveryengine`) | Knowledge base search — businesses can upload product details, FAQ, and policies. Discovery Engine indexes them and the AI searches them during conversations to give accurate, business-specific answers. |
| **ADK (Agent Development Kit)** (`google-adk`) | Builds a structured customer support agent with function-calling tools for business lookup, product listing, and conversation retrieval. |
| **Google OAuth / Identity Platform** (via `authlib`) | Social login — users can sign in with their Google account. |
| **Cloud IAM / Service Accounts** (`google-auth`) | Authenticates Discovery Engine API calls using a service account JSON key. Credentials can be provided as file path or raw JSON env var. |

## Challenges we ran into

- **Baileys ESM on Node 20**: `@whiskeysockets/baileys` v7 is pure ESM, which crashes `require()`. We had to use dynamic `import()` throughout the bot, and handle the async initialization carefully before setting up event handlers.
- **Pairing code vs QR race conditions**: `requestPairingCode()` sets `creds.me` internally, which causes Baileys' `validateConnection()` to call `generateLoginNode()` instead of `generateRegistrationNode()` on reconnection. This meant every 408 timeout during pairing required full auth directory cleanup and fresh pairing request — not just a reconnect.
- **WhatsApp WebSocket reliability**: The connection drops frequently on Render containers (ephemeral network). The bot's `sendMessage` function would hold a stale socket reference while the API had already processed the message. This caused duplicate conversations (from retries re-calling the webhook) and messages that were processed but never delivered.
- **CSRF protection blocking JSON APIs**: The CSRF middleware was designed for form submissions but was also blocking JSON API fetch calls from the dashboard. We had to exempt `application/json` requests since they can't be forged by browser forms.
- **Google GenAI import hanging**: The Gemini client library (`google-genai`) hangs on import when not installed or misconfigured. Since `ai.py` was imported at module level by the pipeline, every request to the AI pipeline would hang. Fixed with lazy imports inside function bodies.

## Accomplishments that we're proud of

- A WhatsApp bot that reliably stays connected for days, survives disconnects, and re-pairs automatically when the connection drops with 408 timeout during pairing.
- A multi-tier AI pipeline with circuit breakers — if Gemini goes down, Groq picks up. If Groq fails, OpenRouter takes over. The business keeps running.
- An AI that knows each business personally — introduces itself by the business name, mentions the owner, talks about their specific services and prices. It never pitches Tell5 unless asked.
- End-to-end WhatsApp messaging working through a single Render container — no external services beyond PostgreSQL and AI APIs.
- Forgot password flow that works without email — useful in markets where email is less common than phone.
- The bot survived 7 rounds of debugging, 12+ deployments, and a database wipe.

## What we learned

- Baileys internals are undocumented and break in surprising ways. `requestPairingCode()` modifies auth state that persists across reconnections. Debugging required reading the library source code.
- WebSocket-based WhatsApp connections on cloud containers are inherently unstable. The bot must be designed for frequent disconnection and reconnection — every message path needs to handle stale socket references.
- Multi-tier AI providers require careful circuit breaker design. A single failing provider should never cascade into total system failure. Each tier needs its own timeout, retry count, and cooldown.
- Server-side template rendering with vanilla JS is faster to develop than React/Vue for a project of this scope. No build step, no npm in the frontend, no hydration issues.
- CSRF protection needs different rules for form-based vs JSON API requests. One size does not fit all.

## What's next for Tell5

- **Persistent message queue**: Store failed-to-send messages and retry via background scheduler instead of relying on synchronous retries.
- **Multiple WhatsApp numbers per account**: Let one dashboard manage multiple business profiles, each with its own WhatsApp bot instance.
- **Analytics dashboard**: Customer response rates, popular products, peak messaging hours, conversion tracking.
- **Multilingual replies**: Detect customer language and reply in the same language.
- **Voice message transcription**: Convert voice notes to text so the AI can respond to voice messages too.
- **WhatsApp Business API integration**: For businesses that qualify, offer the official Business API as an alternative to Baileys.
- **Inventory management**: Track stock levels and let the AI inform customers when items are out of stock.
