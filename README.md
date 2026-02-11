# 🎙️ CXone Call Recording Pipeline

**End-to-end cloud pipeline for fetching, storing, transcribing, and analyzing call center recordings at scale.**

Built with Python · NICE CXone API · Google Cloud Platform · Deepgram AI

---

## 🔥 What This Does

This production-ready pipeline processes **80,000+ call recordings** automatically:

1. **Fetches** recording metadata from the NICE CXone (inContact) API
2. **Downloads** audio files and uploads them to Google Cloud Storage
3. **Transcribes** recordings using Deepgram's Nova-3 speech-to-text model
4. **Identifies speakers** with AI-powered diarization (Speaker 1, Speaker 2, etc.)
5. **Analyzes** each call for sentiment, topics, intents, and generates summaries
6. **Tracks** everything in BigQuery with full audit trail and resume capability

All processing is idempotent — the pipeline can be stopped and restarted at any point without reprocessing completed records.

---

## 🏗️ Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  BigQuery    │     │  CXone API   │     │  Google Cloud    │
│  Source      │────▶│  Recording   │────▶│  Storage (GCS)   │
│  Table       │     │  Download    │     │  Audio Bucket    │
└─────────────┘     └──────────────┘     └────────┬─────────┘
                                                   │
                    ┌──────────────┐                │
                    │  Deepgram    │◀───────────────┘
                    │  Nova-3 AI   │   (Signed URL)
                    └──────┬───────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
    │Transcribe │   │ Speaker   │   │  Audio    │
    │ Speech    │   │ Diarize   │   │  Intel    │
    │ to Text   │   │ (who said │   │ Sentiment │
    │           │   │  what)    │   │ Topics    │
    │           │   │           │   │ Intents   │
    │           │   │           │   │ Summary   │
    └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                    ┌──────▼───────┐
                    │  BigQuery    │
                    │  Tracking    │
                    │  Table       │
                    └──────────────┘
```

---

## ✨ Key Features

### Recording Pipeline (`main.py`)
- **Batch processing** — Handles 80,000+ contacts with configurable batch sizes
- **Automatic token refresh** — CXone tokens refresh transparently before each API call
- **GCS upload** — Recordings stored in organized bucket paths
- **Smart resumption** — LEFT JOIN query skips already-processed contacts
- **Rate limiting** — Configurable delays to respect API quotas
- **Full audit trail** — Every contact logged with status, timestamp, and raw API response

### Transcription & Analysis (`transcribe_v2.py`)
- **Deepgram Nova-3** — State-of-the-art speech-to-text accuracy
- **Speaker diarization** — Identifies and labels different speakers in the conversation
- **Multichannel detection** — Auto-detects stereo audio for perfect Agent/Customer separation
- **Dual transcript storage** — Both raw text and diarized conversation format
- **Audio Intelligence** (single API call):
  - 📋 **Summarization** — AI-generated call summary
  - 🏷️ **Topic Detection** — Identifies discussion topics with confidence scores
  - 🎯 **Intent Recognition** — Detects caller intent (complaint, inquiry, etc.)
  - 💬 **Sentiment Analysis** — Per-segment and overall sentiment scoring

### Cloud Deployment
- **Dockerized** — Optimized multi-layer Dockerfile with `uv` package manager
- **Cloud Run Jobs** — Two independent jobs from a single Docker image
- **Secret Manager** — API credentials secured via Google Secret Manager
- **Cost-effective** — Pay-per-execution pricing, no idle costs

---

## 📊 Sample Output

### Diarized Transcription
```
Speaker 1: Good afternoon. John and John online sales. Dallas speaking. How can I help you today?
Speaker 2: Hi. Good day. It's Rod Sanderson. How are you?
Speaker 1: Good, thank you. How can I assist?
Speaker 2: Can I speak to one of the technicians, please?
Speaker 3: Afternoon, John and John. It's Simon speaking.
Speaker 2: Hey, Simon. I've got a question about my Honda engine...
```

### Audio Intelligence Results
| Feature | Sample Output |
|---------|--------------|
| **Summary** | "Customer called to speak with a technician about a Honda engine issue. Call was transferred from reception to the service department." |
| **Topics** | `Honda engine`, `service department`, `technician request` |
| **Intents** | `request_transfer`, `technical_inquiry` |
| **Sentiment** | Overall: `neutral` (score: 0.12) |

---

## 🗃️ BigQuery Schema

The tracking table stores the complete lifecycle of each recording:

| Column | Type | Description |
|--------|------|-------------|
| `contactId` | STRING | CXone contact identifier |
| `recording_filename` | STRING | Original audio filename |
| `gcs_uri` | STRING | Cloud Storage path (`gs://bucket/path`) |
| `fetch_datetime` | TIMESTAMP | When the recording was fetched |
| `status` | STRING | `SUCCESS`, `FAILED`, `NOT_FOUND`, `NO_RECORDING` |
| `raw_response` | STRING | Full CXone API response (JSON) |
| `transcription` | STRING | Diarized conversation transcript |
| `transcription_raw` | STRING | Plain text transcript |
| `summary` | STRING | AI-generated call summary |
| `topics` | STRING | Detected topics (JSON) |
| `intents` | STRING | Detected intents (JSON) |
| `sentiment` | STRING | Sentiment analysis (JSON) |
| `transcribed` | INTEGER | Transcription flag (0/1) |
| `analysed` | INTEGER | Analysis flag (0/1) |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- Google Cloud project with BigQuery & Cloud Storage
- NICE CXone API credentials
- Deepgram API key ([free tier available](https://console.deepgram.com))

### Setup

```bash
# Clone the repository
git clone <repo-url>
cd ringcentral_callrecordings

# Install dependencies
uv sync --locked

# Configure credentials
cp .env.example .env
# Edit .env with your actual credentials
```

### Run Locally

```bash
# Step 1: Fetch recordings & upload to GCS
uv run python main.py

# Step 2: Transcribe & analyze recordings
uv run python transcribe_v2.py
```

### Deploy to Google Cloud

```bash
# Build Docker image
docker build -t gcr.io/$PROJECT_ID/cxone-recording-fetcher .

# Push to Container Registry
docker push gcr.io/$PROJECT_ID/cxone-recording-fetcher

# Create Cloud Run Job — Recording Fetcher
gcloud run jobs create cxone-recording-fetcher \
  --image gcr.io/$PROJECT_ID/cxone-recording-fetcher \
  --region $REGION \
  --memory 4Gi --cpu 2

# Create Cloud Run Job — Transcriber (same image, different entrypoint)
gcloud run jobs create cxone-transcriber \
  --image gcr.io/$PROJECT_ID/cxone-recording-fetcher \
  --command "uv,run,python,transcribe_v2.py" \
  --region $REGION \
  --memory 4Gi --cpu 2
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for full deployment guide with secret management.

---

## 📁 Project Structure

```
├── auth.py              # CXone OAuth 2.0 authentication
├── fetch_recordings.py  # Recording metadata & download logic
├── main.py              # Batch recording fetcher pipeline
├── transcribe_v2.py     # Deepgram transcription & analysis pipeline
├── transcribe.py        # Local transcription (Whisper, for testing)
├── Dockerfile           # Optimized container with uv
├── .env.example         # Environment variable template
├── DEPLOYMENT.md        # GCP deployment guide
├── QUICKSTART.md        # Local setup & testing guide
└── pyproject.toml       # Python dependencies
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Language** | Python 3.10+ |
| **Package Manager** | uv (Astral) |
| **CXone API** | OAuth 2.0, Media Playback API |
| **Speech-to-Text** | Deepgram Nova-3 |
| **Audio Intelligence** | Deepgram (Summarization, Topics, Intents, Sentiment) |
| **Cloud Storage** | Google Cloud Storage |
| **Data Warehouse** | Google BigQuery |
| **Containerization** | Docker |
| **Deployment** | Google Cloud Run Jobs |
| **Secrets** | Google Secret Manager |

---

## 🔒 Security

- All API credentials stored in environment variables (`.env`)
- `.gitignore` configured to exclude secrets, credentials, and local recordings
- Google Secret Manager integration for cloud deployment
- GCS signed URLs with 15-minute expiry for Deepgram access
- Service account with least-privilege IAM roles

---

## 📈 Monitoring

### BigQuery — Processing Status
```sql
SELECT status, COUNT(*) as count
FROM `project.dataset.recording_fetch_status`
GROUP BY status;
```

### BigQuery — Transcription Progress
```sql
SELECT
  COUNTIF(transcribed = 1) AS transcribed,
  COUNTIF(transcribed IS NULL OR transcribed = 0) AS pending,
  COUNT(*) AS total
FROM `project.dataset.recording_fetch_status`
WHERE status = 'SUCCESS';
```

### Cloud Run — Job Logs
```bash
gcloud logging read "resource.type=cloud_run_job" --limit 50
```

---

## 📄 License

This project is provided as-is for use with NICE inContact CXone API and Deepgram.
