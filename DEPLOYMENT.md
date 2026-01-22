# Google Cloud Deployment Guide

## Overview
This guide explains how to deploy your CXone recording fetcher to Google Cloud Platform to process 80,000+ call recordings.

## Prerequisites

✅ **You Have:**
- Working authentication script (`auth.py`)
- Recording fetcher (`fetch_recordings.py`)
- Batch processor (`main.py`)
- BigQuery source table: `your-project-id.your_dataset.your_source_table`

## Deployment Steps

### 1. Create Google Cloud Storage Bucket

Create a bucket to store the downloaded recordings:

```bash
# Set your project
gcloud config set project your-project-id

# Create storage bucket
gsutil mb -l australia-southeast1 gs://your-bucket-name

# Or use a different name and update BUCKET_NAME in main.py
```

### 2. Update Configuration

Edit [`main.py`](file:///home/waqarakbar/PythonProjects/ringcentral_callrecordings/main.py) to set your actual bucket name:

```python
BUCKET_NAME = "your-bucket-name"  # Change this to your actual bucket name
```

### 3. Set Up Service Account (for Cloud deployment)

```bash
# Create service account
gcloud iam service-accounts create cxone-recording-fetcher \
    --display-name="CXone Recording Fetcher"

# Grant necessary permissions
gcloud projects add-iam-policy-binding your-project-id \
    --member="serviceAccount:cxone-recording-fetcher@your-project-id.iam.gserviceaccount.com" \
    --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding your-project-id \
    --member="serviceAccount:cxone-recording-fetcher@your-project-id.iam.gserviceaccount.com" \
    --role="roles/storage.objectAdmin"

# Create and download key
gcloud iam service-accounts keys create ~/cxone-key.json \
    --iam-account=cxone-recording-fetcher@your-project-id.iam.gserviceaccount.com
```

### 4. Add Service Account Key to .env

Add to your `.env` file:

```bash
# CXone API Credentials
CXONE_USERNAME=your_username
CXONE_PASSWORD=your_password
CXONE_CLIENT_ID=your_client_id
CXONE_CLIENT_SECRET=your_client_secret

# Google Cloud
GOOGLE_APPLICATION_CREDENTIALS=/path/to/cxone-key.json
```

### 5. Initial Test Run (Local)

Test with a small batch first:

```bash
# Install dependencies
uv sync
# or: pip install -r requirements.txt

# Set Google credentials
export GOOGLE_APPLICATION_CREDENTIALS=~/cxone-key.json

# Run with 10 records limit (configured in main.py)
uv run main.py
```

The script is set to process **10 records** initially for testing. Check:
- ✅ Recordings download successfully
- ✅ Files upload to GCS bucket
- ✅ Tracking table gets populated

### 6. Process All Records

Once testing is successful, update [`main.py`](file:///home/waqarakbar/PythonProjects/ringcentral_callrecordings/main.py):

```python
# Change line ~108
pending_ids = get_pending_contacts(bq_client, limit=None)  # Process all records
```

### 7. Deployment Options

#### Option A: Google Compute Engine (VM)

**Best for:** Long-running batch jobs, full control

```bash
# Create VM instance
gcloud compute instances create cxone-fetcher \
    --zone=australia-southeast1-a \
    --machine-type=e2-medium \
    --service-account=cxone-recording-fetcher@your-project-id.iam.gserviceaccount.com \
    --scopes=cloud-platform \
    --image-family=ubuntu-2004-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=50GB

# SSH into the instance
gcloud compute ssh cxone-fetcher --zone=australia-southeast1-a

# On the VM:
# 1. Install Python and dependencies
sudo apt update
sudo apt install -y python3 python3-pip git

# 2. Clone your code
git clone <your-repo-url>
cd ringcentral_callrecordings

# 3. Install dependencies
pip3 install -r requirements.txt

# 4. Create .env file with credentials
nano .env

# 5. Run in background with nohup
nohup python3 main.py > processing.log 2>&1 &

# 6. Monitor progress
tail -f processing.log
```

#### Option B: Cloud Run Jobs

**Best for:** Scheduled batch processing, serverless

1. **Create Dockerfile:**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

2. **Build and deploy:**

```bash
# Build
gcloud builds submit --tag gcr.io/your-project-id/cxone-fetcher

# Deploy as Cloud Run Job
gcloud run jobs create cxone-fetcher \
    --image gcr.io/your-project-id/cxone-fetcher \
    --region australia-southeast1 \
    --service-account cxone-recording-fetcher@your-project-id.iam.gserviceaccount.com \
    --set-env-vars CXONE_USERNAME=xxx,CXONE_PASSWORD=xxx,CXONE_CLIENT_ID=xxx,CXONE_CLIENT_SECRET=xxx \
    --task-timeout 3600s \
    --max-retries 3

# Run the job
gcloud run jobs execute cxone-fetcher --region australia-southeast1
```

#### Option C: Cloud Functions (Not Recommended)

Cloud Functions have a 9-minute timeout limit, which is too short for batch processing 80K records.

### 8. Monitor Progress

Check the tracking table in BigQuery:

```sql
-- Overall progress
SELECT 
    status,
    COUNT(*) as count
FROM `your-project-id.your_dataset.recording_fetch_status`
GROUP BY status;

-- Recent activity
SELECT 
    contactId,
    recording_filename,
    gcs_uri,
    fetch_datetime,
    status
FROM `your-project-id.your_dataset.recording_fetch_status`
ORDER BY fetch_datetime DESC
LIMIT 100;

-- Failed records
SELECT 
    contactId,
    raw_response,
    fetch_datetime
FROM `your-project-id.your_dataset.recording_fetch_status`
WHERE status IN ('FAILED', 'NOT_FOUND')
ORDER BY fetch_datetime DESC;
```

### 9. Cost Optimization

**Estimated Costs for 80K recordings:**

```
- Cloud Storage: ~$2/month per 100GB
- BigQuery: ~$5/month for queries
- Compute Engine (e2-medium): ~$25/month
- Cloud Run Jobs: ~$0.50 per job run
- API Calls: Included in your CXone plan
```

**Tips:**
1. Use **Compute Engine** for one-time bulk processing, then delete the VM
2. Use **Cloud Run Jobs** for scheduled incremental processing
3. Set `SLEEP_TIME` appropriately to avoid API rate limits
4. Process in batches (e.g., 1000 at a time) and monitor

### 10. Resume After Interruption

The script automatically skips already-processed contacts by checking the tracking table. If interrupted:

```bash
# Simply run again
uv run main.py

# It will only process contacts not in the tracking table
```

## Troubleshooting

### Authentication Errors
```bash
# Verify service account has permissions
gcloud projects get-iam-policy your-project-id \
    --flatten="bindings[].members" \
    --filter="bindings.members:cxone-recording-fetcher@*"
```

### BigQuery Errors
```bash
# Test BigQuery access
bq ls -p your-project-id your_dataset
```

### Storage Errors
```bash
# Test bucket access
gsutil ls gs://your-bucket-name/
```

## Next Steps After Deployment

1. **Monitor first 100 records** to ensure everything works
2. **Check error rate** - adjust if too many NOT_FOUND
3. **Adjust rate limiting** (`SLEEP_TIME`) if hitting API limits
4. **Set up alerts** for failures
5. **Schedule regular runs** for new recordings

## File Structure

```
ringcentral_callrecordings/
├── auth.py                  # CXone authentication
├── fetch_recordings.py      # Recording fetcher class
├── main.py                  # Batch processor with GCS upload
├── .env                     # Credentials (DO NOT COMMIT)
├── requirements.txt         # Python dependencies
└── README.md               # Documentation
```

## Support

If you encounter issues:
1. Check the `raw_response` column in tracking table for error details
2. Verify credentials in `.env`
3. Ensure service account has proper permissions
4. Check API rate limits
