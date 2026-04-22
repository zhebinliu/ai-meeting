# Meeting AI

AI-powered meeting transcription and requirement extraction system.

## Features

- **Audio Transcription**: Convert meeting audio to text using Whisper or Xiaomi ASR
- **AI Processing Pipeline**:
  - Transcript polishing
  - Meeting minutes generation
  - Requirement extraction
- **Feishu Integration**: Export meeting results to Feishu documents and Bitable

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy (async) + SQLite
- **AI**: OpenAI compatible API (MiMo-V2-Pro, MiMo-V2-Omni)
- **ASR**: Whisper, Xiaomi, iFlytek
- **Frontend**: Vanilla JS

## Project Structure

```
backend/
├── main.py              # FastAPI application entry
├── config.py            # Configuration management
├── database.py          # Database setup
├── models/              # SQLAlchemy models
│   ├── meeting.py
│   └── requirement.py
├── routes/              # API endpoints
│   ├── meeting.py
│   └── websocket.py
└── services/
    ├── ai/              # AI processing
    ├── asr/             # ASR clients
    └── feishu/          # Feishu integration

frontend/
├── index.html
├── css/
├── js/
└── lib/
```

## Setup

### 1. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Key variables:
- `OPENAI_API_KEY` - API key for AI processing
- `OPENAI_BASE_URL` - API base URL
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` - Feishu app credentials (optional)

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the Application

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Or use Docker:

```bash
docker-compose up --build
```

## API Endpoints

### Meetings

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/meetings` | Create meeting |
| GET | `/api/meetings` | List all meetings |
| GET | `/api/meetings/{id}` | Get meeting details |
| PATCH | `/api/meetings/{id}` | Update meeting |
| DELETE | `/api/meetings/{id}` | Delete meeting |
| POST | `/api/meetings/upload` | Upload audio file |
| POST | `/api/meetings/{id}/process` | Trigger AI processing |
| POST | `/api/meetings/{id}/resume` | Resume failed meeting |

### Export & Sync

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/meetings/{id}/export-feishu` | Export to Feishu doc |
| POST | `/api/meetings/{id}/sync-requirements` | Sync to Feishu Bitable |

### Manual Actions

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/meetings/{id}/actions/polish` | Polish transcript |
| POST | `/api/meetings/{id}/actions/summarize` | Generate minutes |
| POST | `/api/meetings/{id}/actions/extract_requirements` | Extract requirements |

## License

MIT
