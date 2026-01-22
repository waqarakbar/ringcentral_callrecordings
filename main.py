import os
import time
import json
import pandas as pd
from google.cloud import bigquery
from google.cloud import storage
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import your existing classes
from auth import CXoneAuthenticator
from fetch_recordings import RecordingFetcher, RecordingNotFoundException

# --- CONFIGURATION FROM ENVIRONMENT ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("GCP_DATASET_ID")
SOURCE_TABLE_NAME = os.getenv("GCP_SOURCE_TABLE")
TRACKING_TABLE_NAME = os.getenv("GCP_TRACKING_TABLE")
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

# Validate required environment variables
required_vars = {
    "GCP_PROJECT_ID": PROJECT_ID,
    "GCP_DATASET_ID": DATASET_ID,
    "GCP_SOURCE_TABLE": SOURCE_TABLE_NAME,
    "GCP_TRACKING_TABLE": TRACKING_TABLE_NAME,
    "GCS_BUCKET_NAME": BUCKET_NAME
}

missing_vars = [var_name for var_name, var_value in required_vars.items() if not var_value]
if missing_vars:
    raise ValueError(
        f"Missing required environment variables: {', '.join(missing_vars)}\n"
        f"Please set these in your .env file. See .env.example for reference."
    )

# Construct full table names
SOURCE_TABLE = f"{PROJECT_ID}.{DATASET_ID}.{SOURCE_TABLE_NAME}"
TRACKING_TABLE = f"{PROJECT_ID}.{DATASET_ID}.{TRACKING_TABLE_NAME}"

# API Rate Limit Buffer (Seconds)
SLEEP_TIME = 1.5  # Adjust based on your API tier

def init_clients():
    """Initialize BigQuery and Cloud Storage clients."""
    bq_client = bigquery.Client(project=PROJECT_ID)
    gcs_client = storage.Client(project=PROJECT_ID)
    bucket = gcs_client.bucket(BUCKET_NAME)
    return bq_client, bucket

def ensure_tracking_table(bq_client):
    """Creates the tracking table if it doesn't exist."""
    schema = [
        bigquery.SchemaField("contactId", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("recording_filename", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("gcs_uri", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("fetch_datetime", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("status", "STRING", mode="NULLABLE"),  # SUCCESS, FAILED, NOT_FOUND, NO_RECORDING
        bigquery.SchemaField("raw_response", "STRING", mode="NULLABLE"),
    ]
    table_ref = bigquery.Table(TRACKING_TABLE, schema=schema)
    try:
        bq_client.get_table(table_ref)
        print(f"✓ Tracking table {TRACKING_TABLE} found.")
    except Exception:
        print(f"Creating tracking table {TRACKING_TABLE}...")
        bq_client.create_table(table_ref)
        print(f"✓ Tracking table created.")

def get_pending_contacts(bq_client, limit=None):
    """
    Fetches contacts from source that are NOT in the tracking table.
    
    Args:
        bq_client: BigQuery client
        limit: Optional limit for testing (e.g., 10 for first batch)
    """
    limit_clause = f"LIMIT {limit}" if limit else ""
    
    # Cast contactId to STRING to match tracking table type
    query = f"""
        SELECT CAST(src.contactId AS STRING) as contactId
        FROM `{SOURCE_TABLE}` src
        LEFT JOIN `{TRACKING_TABLE}` trk
        ON CAST(src.contactId AS STRING) = trk.contactId
        WHERE trk.contactId IS NULL
        order by src.startDate desc
        {limit_clause}
    """
    print("Fetching pending records from BigQuery...")
    df = bq_client.query(query).to_dataframe()
    return df['contactId'].tolist()

def save_to_bq(bq_client, row_data):
    """Stream a single result row to BigQuery."""
    errors = bq_client.insert_rows_json(TRACKING_TABLE, [row_data])
    if errors:
        print(f"  ✗ Error inserting into BigQuery: {errors}")
    else:
        print(f"  ✓ Logged to BigQuery")

def upload_to_gcs(bucket, blob_name, local_file_path):
    """Upload a file from local path to GCS."""
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_file_path)
    gcs_uri = f"gs://{bucket.name}/{blob_name}"
    print(f"  ✓ Uploaded to GCS: {gcs_uri}")
    return gcs_uri

def main():
    print("="*70)
    print("CXone Recording Batch Processor")
    print("="*70)
    
    # Initialize clients
    bq_client, bucket = init_clients()
    ensure_tracking_table(bq_client)

    # Initialize CXone authentication and fetcher
    print("\nInitializing CXone API...")
    auth = CXoneAuthenticator()
    fetcher = RecordingFetcher(auth)
    
    # Get list of pending contacts (use limit for testing)
    # Remove limit parameter or set to None to process all
    pending_ids = get_pending_contacts(bq_client, limit=10000)  # Start with 10 for testing
    
    # pending_ids.append(693159199085)

    print(f"\n✓ Found {len(pending_ids)} records to process.\n")

    if len(pending_ids) == 0:
        print("No pending contacts to process. Exiting.")
        return

    processed_count = 0
    success_count = 0
    failed_count = 0

    for contact_id in pending_ids:
        processed_count += 1
        print(f"\n{'='*70}")
        print(f"[{processed_count}/{len(pending_ids)}] Processing contact: {contact_id}")
        print('='*70)
        
        try:
            # Ensure token is valid (refresh if expired)
            # The get_access_token() method automatically checks expiry and refreshes
            auth.get_access_token()
            
            # Fetch recording metadata
            metadata = fetcher.get_recording_metadata(str(contact_id))
            
            # Store raw response as JSON
            raw_response_text = json.dumps(metadata, indent=2)
            
            # Extract file URLs
            file_urls = fetcher.extract_file_urls(metadata)
            
            if not file_urls:
                print(f"  ⚠ No recording files found for {contact_id}")
                error_row = {
                    "contactId": str(contact_id),
                    "recording_filename": None,
                    "gcs_uri": None,
                    "fetch_datetime": datetime.now(timezone.utc).isoformat(),
                    "status": "NO_RECORDING",
                    "raw_response": "No recording files found in metadata"
                }
                save_to_bq(bq_client, error_row)
                failed_count += 1
                continue
            
            # Download the recording (usually first one is voice-only)
            file_info = file_urls[0]
            local_filepath = fetcher.download_recording(
                file_info["url"],
                str(contact_id),
                file_info["media_type"]
            )
            
            # Get just the filename
            file_name = local_filepath.name
            
            # Upload to GCS bucket
            gcs_blob_path = f"recordings/{file_name}"
            gcs_uri = upload_to_gcs(bucket, gcs_blob_path, str(local_filepath))
            
            # Log Success to BigQuery
            success_row = {
                "contactId": str(contact_id),
                "recording_filename": file_name,
                "gcs_uri": gcs_uri,
                "fetch_datetime": datetime.now(timezone.utc).isoformat(),
                "status": "SUCCESS",
                "raw_response": raw_response_text
            }
            save_to_bq(bq_client, success_row)
            success_count += 1
            
            # Clean up local file to save disk space
            if local_filepath.exists():
                local_filepath.unlink()
                print(f"  ✓ Cleaned up local file")

        except RecordingNotFoundException as e:
            print(f"  ⚠ Recording not found for contact: {contact_id}")
            error_row = {
                "contactId": str(contact_id),
                "recording_filename": None,
                "gcs_uri": None,
                "fetch_datetime": datetime.now(timezone.utc).isoformat(),
                "status": "NOT_FOUND",
                "raw_response": str(e)
            }
            save_to_bq(bq_client, error_row)
            failed_count += 1

        except Exception as e:
            print(f"  ✗ Failed to process {contact_id}")
            print(f"  Error: {str(e)}")
            error_row = {
                "contactId": str(contact_id),
                "recording_filename": None,
                "gcs_uri": None,
                "fetch_datetime": datetime.now(timezone.utc).isoformat(),
                "status": "FAILED",
                "raw_response": str(e)
            }
            save_to_bq(bq_client, error_row)
            failed_count += 1

        # Rate limiting sleep
        time.sleep(SLEEP_TIME)
    
    # Final Summary
    print("\n" + "="*70)
    print("PROCESSING COMPLETE")
    print("="*70)
    print(f"Total Processed:    {processed_count}")
    print(f"✓ Successful:       {success_count}")
    print(f"✗ Failed/Not Found: {failed_count}")
    print("="*70)

if __name__ == "__main__":
    main()