# Quick Start Guide - CXone Recording Batch Processor

## What This Does
Automatically fetches call recordings from CXone API for 80,000+ contacts and uploads them to Google Cloud Storage, with full tracking in BigQuery.

## Architecture

```
BigQuery Source Table (80K+ contacts)
          ↓
    [main.py] Batch Processor
          ↓
    CXone API → Download Recordings
          ↓
    Upload to GCS Bucket
          ↓
    Track in BigQuery Table
```

## Quick Start (5 Steps)

### 1. Install Dependencies
```bash
# Using uv (recommended)
uv sync

# OR using pip
pip install -r requirements.txt
```

### 2. Configure Environment
```bash
# Copy example env file
cp .env.example .env

# Edit with your credentials
nano .env
```

Add your credentials:
```bash
CXONE_USERNAME=your_username
CXONE_PASSWORD=your_password
CXONE_CLIENT_ID=your_client_id
CXONE_CLIENT_SECRET=your_client_secret
```

### 3. Set Up Google Cloud

**Create GCS Bucket:**
```bash
gsutil mb -l australia-southeast1 gs://your-bucket-name
```

**Update bucket name in `main.py`:**
```python
BUCKET_NAME = "your-bucket-name"  # Line 18
```

### 4. Test Locally (First 10 Records)
```bash
# Set Google credentials
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

# Run with 10-record limit (default)
uv run main.py
```

**Expected output:**
```
✓ Tracking table found
✓ Found 10 records to process

[1/10] Processing contact: 693159199085
  ✓ Found voice-only file URL
  ✓ Uploaded to GCS: gs://your-bucket-name/recordings/693159199085_voice-only.mp4
  ✓ Logged to BigQuery
  ✓ Cleaned up local file
```

### 5. Deploy to Production

See [`DEPLOYMENT.md`](file:///home/waqarakbar/PythonProjects/ringcentral_callrecordings/DEPLOYMENT.md) for full deployment options:
- **Option A:** Google Compute Engine (VM) - Best for bulk processing
- **Option B:** Cloud Run Jobs - Best for scheduled runs
- **Option C:** Local processing with tmux/screen

## Project Structure

```
ringcentral_callrecordings/
├── auth.py                  # CXone authentication
├── fetch_recordings.py      # Recording downloader
├── main.py                  # Batch processor (GCS + BigQuery)
├── .env                     # Your credentials (gitignored)
├── requirements.txt         # Python dependencies
├── DEPLOYMENT.md           # Full deployment guide
└── README.md               # API documentation
```

## Key Features

✅ **Automatic Batch Processing**
- Reads contacts from BigQuery source table
- Skips already-processed records
- Handles errors gracefully

✅ **Smart Tracking**
- Logs every contact processed
- Stores success/failure status
- Saves raw API response for debugging
- Tracks GCS file location

✅ **Error Handling**
- Handles missing recordings (404)
- API failures logged to BigQuery
- Rate limiting to avoid API throttling
- Resumable - just restart if interrupted

✅ **Cost Efficient**
- Cleans up local files after upload
- Processes in batches
- Uses standard storage class

## Database Schema

### Source Table
```sql
your-project-id.your_dataset.your_source_table
  - contactId (STRING)
  - [other call metadata...]
```

### Tracking Table (auto-created)
```sql
your-project-id.your_dataset.recording_fetch_status
  - contactId (STRING)            # Contact ID
  - recording_filename (STRING)   # e.g., "693159199085_voice-only.mp4"
  - gcs_uri (STRING)             # GCS path to file
  - fetch_datetime (TIMESTAMP)   # When processed
  - status (STRING)              # SUCCESS/FAILED/NOT_FOUND/NO_RECORDING
  - raw_response (STRING)        # Full API response JSON
```

## Monitoring Progress

```sql
-- Check overall status
SELECT status, COUNT(*) as count
FROM `your-project-id.your_dataset.recording_fetch_status`
GROUP BY status;

-- View recent successes
SELECT contactId, recording_filename, gcs_uri, fetch_datetime
FROM `your-project-id.your_dataset.recording_fetch_status`
WHERE status = 'SUCCESS'
ORDER BY fetch_datetime DESC
LIMIT 10;
```

## Configuration Options

In [`main.py`](file:///home/waqarakbar/PythonProjects/ringcentral_callrecordings/main.py):

```python
# Process all or limit for testing
pending_ids = get_pending_contacts(bq_client, limit=10)  # Line ~108

# API rate limiting
SLEEP_TIME = 1.5  # Seconds between API calls (Line 22)

# Your GCS bucket
BUCKET_NAME = "your-bucket-name"  # Line 18
```

## Troubleshooting

**"Recording not found" (404):**
- Normal for contacts without recordings
- Logged with status `NOT_FOUND`
- Will not be retried

**Authentication errors:**
```bash
# Verify credentials
cat .env

# Test CXone auth
uv run -c "from auth import CXoneAuthenticator; auth = CXoneAuthenticator(); print('✓ Auth works!')"
```

**BigQuery permission errors:**
```bash
# Verify service account permissions
gcloud projects get-iam-policy your-project-id \
    --flatten="bindings[].members" \
    --filter="bindings.members:*@your-project-id*"
```

## Next Steps

1. ✅ Test with 10 records locally
2. ✅ Verify files in GCS bucket
3. ✅ Check tracking table in BigQuery
4. ✅ Increase limit or remove for full processing
5. ✅ Deploy to Compute Engine for bulk run

See [`DEPLOYMENT.md`](file:///home/waqarakbar/PythonProjects/ringcentral_callrecordings/DEPLOYMENT.md) for detailed deployment instructions!
