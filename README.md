# 🏠 Real Estate Voice Agent — Azure

An AI-powered telephony system that automatically calls real estate leads, conducts qualifying conversations over the phone using GPT-4, and scores them — all without a human agent.

> **Live system:** A prospect fills out a web form → the system immediately calls them → an AI agent conducts a full qualifying conversation → lead data is extracted, scored, and stored.

---

## Demo Flow

```
Prospect fills form
        ↓
Twilio places outbound call (< 5 seconds)
        ↓
Answering machine? → Hang up + schedule retry
        ↓
Human answers → Personalized AI greeting
        ↓
GPT-4 conducts qualifying conversation
  (property type, bedrooms, budget, location, timeline, financing)
        ↓
Azure Speech transcribes responses (Whisper fallback)
        ↓
Lead scored: 🔥 Hot / 🌤 Warm / 🧊 Cold
        ↓
Matched properties fetched from Redis
        ↓
Lead + transcript saved to database
        ↓
No answer? → Retry scheduler (up to 4 attempts, respects 9AM–9PM window)
```

---

## Architecture

```
┌─────────────────┐     POST /api/submit-lead     ┌──────────────────────┐
│   Web Form      │ ───────────────────────────► │   FastAPI Backend     │
│  (static/HTML)  │                               │   (main.py)          │
└─────────────────┘                               └──────────┬───────────┘
                                                             │
                              ┌──────────────────────────────┼──────────────────────────┐
                              │                              │                          │
                    ┌─────────▼────────┐        ┌───────────▼────────┐     ┌───────────▼──────────┐
                    │  Twilio Voice    │        │  Azure OpenAI      │     │  Redis               │
                    │  - Outbound call │        │  GPT-4             │     │  - Property listings │
                    │  - AMD detection │        │  - Conversation    │     │  - Bedroom indexing  │
                    │  - Recording     │        │  - Data extraction │     └──────────────────────┘
                    │  - Status hooks  │        │  - Lead scoring    │
                    └─────────┬────────┘        └────────────────────┘
                              │
                    ┌─────────▼────────┐        ┌────────────────────┐
                    │  Transcription   │        │  SQLite / SQLAlch. │
                    │  Azure Speech    │        │  - Lead records    │
                    │  + Whisper (fbk) │        │  - Transcripts     │
                    └──────────────────┘        │  - Appointments    │
                                                └────────────────────┘
                    ┌──────────────────┐
                    │ Callback         │
                    │ Scheduler        │
                    │ (async bg loop)  │
                    └──────────────────┘
```

---

## Key Features

**Telephony Pipeline**
- Outbound calls triggered instantly on form submission via Twilio
- Answering machine detection (AMD) — voicemails are detected and hung up, not wasted
- Up to 4 retry attempts with exponential backoff (30min → 2hr → 4hr → 24hr)
- Quiet hours enforcement: no calls placed between 9 PM and 9 AM

**AI Conversation**
- GPT-4 (Azure OpenAI) conducts natural qualifying conversations
- Gathers: property type, bedrooms, budget, location, timeline, financing status
- One question at a time, short responses optimized for phone calls
- Graceful call ending detection

**Transcription — Dual Layer**
- Primary: Azure Cognitive Services Speech-to-Text (low latency, high accuracy)
- Fallback: OpenAI Whisper (local, runs if Azure Speech fails)
- Audio conversion via `ffmpeg` (MP3 → 16kHz mono WAV)

**Lead Intelligence**
- Automatic lead scoring: Hot / Warm / Cold based on financing status + data completeness
- GPT-4 extracts structured JSON from raw conversation transcripts
- Property matching against Redis-indexed listings (by bedroom count + budget)
- Full conversation transcripts saved to database
- 24-hour duplicate detection prevents repeat calls

**Security & Reliability**
- Twilio webhook signature validation
- Pydantic input validation with regex (name, phone, email, budget)
- Rate limiting: 3 lead submissions per IP per hour
- CORS restricted to configured origins

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web Framework | FastAPI + Uvicorn |
| Voice/Telephony | Twilio Programmable Voice |
| AI Conversation | Azure OpenAI (GPT-4) |
| Speech-to-Text | Azure Cognitive Services + OpenAI Whisper |
| Property Cache | Redis |
| Database | SQLite + SQLAlchemy ORM |
| Deployment | Docker + Azure App Service |
| Dependency Mgmt | `uv` + `pyproject.toml` |

---

## Project Structure

```
.
├── main.py                  # FastAPI app — all routes and core logic
├── database.py              # SQLAlchemy models (Lead schema)
├── callback_scheduler.py    # Async retry loop for missed calls
├── load_properties_redis.py # Seed script for Redis property data
├── view_leads.py            # CLI utility to inspect leads
├── view_redis.py            # CLI utility to inspect Redis cache
├── static/
│   └── index.html           # Lead capture web form
├── Dockerfile               # Container config
├── startup.sh               # Azure App Service entrypoint
└── .azure/                  # Azure deployment config
```

---

## Local Setup

### Prerequisites

- Python 3.11+
- Redis running locally
- `ffmpeg` installed (`brew install ffmpeg` / `apt install ffmpeg`)
- Twilio account with a phone number
- Azure OpenAI deployment (GPT-4)
- Azure Speech Services resource

### 1. Clone and install

```bash
git clone https://github.com/parvarora2001/Real-Estate-Voice-Agent-Azure.git
cd Real-Estate-Voice-Agent-Azure

# Using uv (recommended)
pip install uv
uv sync

# Or pip
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.envu` to `.env` and fill in your credentials:

```env
# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1xxxxxxxxxx

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_KEY=your_key
AZURE_OPENAI_DEPLOYMENT=gpt-4
AZURE_OPENAI_API_VERSION=2024-08-01-preview

# Azure Speech
AZURE_SPEECH_KEY=your_key
AZURE_SPEECH_REGION=eastus

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_SSL=false

# App
BASE_URL=https://your-ngrok-or-domain.com
FRONTEND_URL=http://localhost:8000
```

### 3. Seed property data

```bash
python load_properties_redis.py
```

### 4. Run

```bash
python main.py
# Server starts at http://localhost:8000
```

### 5. Expose to Twilio (local dev)

Twilio webhooks need a public URL. Use ngrok:

```bash
ngrok http 8000
# Copy the https URL into BASE_URL in your .env
```

---

## Docker / Azure Deployment

```bash
# Build
docker build -t real-estate-voice-agent .

# Run
docker run -p 8000:8000 --env-file .env real-estate-voice-agent
```

The `.azure/` directory contains the Azure App Service deployment configuration. The `startup.sh` script handles process startup in the container environment.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Lead capture web form |
| `POST` | `/api/submit-lead` | Submit new lead (triggers call) |
| `GET` | `/api/status` | System health + active call count |
| `GET` | `/health` | Load balancer health check |
| `POST` | `/voice/incoming` | Twilio inbound call webhook |
| `POST` | `/voice/outbound` | Twilio outbound call webhook |
| `POST` | `/voice/process` | Process recorded caller response |
| `POST` | `/voice/status` | Twilio call status callback |

---

## Lead Scoring Logic

| Score | Criteria |
|---|---|
| 🔥 **Hot** | Financing pre-approved + immediate timeline |
| 🌤 **Warm** | Budget and bedroom count both captured |
| 🧊 **Cold** | Incomplete qualification data |

---

## Callback Retry Schedule

| Attempt | Delay | Notes |
|---|---|---|
| 1 | 30 minutes | First retry |
| 2 | 2 hours | — |
| 3 | 4 hours | — |
| 4 | 24 hours | Final attempt |
| 5+ | — | Marked `failed_max_attempts` |

All callbacks respect quiet hours (9 AM – 9 PM). Calls that would fall outside this window are automatically pushed to 10 AM the next day.

---

## Utilities

```bash
# View all leads in database
python view_leads.py

# Inspect Redis property cache
python view_redis.py

# Manually trigger callback queue
python callback_scheduler.py
```

---

## Known Limitations / Roadmap

- [ ] Move conversation state from in-memory dict to Redis (needed for horizontal scaling)
- [ ] Replace PID-based temp audio files with `tempfile.NamedTemporaryFile` (concurrent call safety)
- [ ] Swap SQLite for PostgreSQL for production persistence
- [ ] Add GitHub Actions CI pipeline
- [ ] Webhook signature validation enforced on all voice endpoints

---

## License

MIT