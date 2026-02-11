#!/usr/bin/env python3
"""
Transcribe V2 - Deepgram Transcription & Audio Intelligence Pipeline

Reads recordings from BigQuery (recording_fetch_status), generates signed URLs
for GCS files, calls Deepgram API for transcription + analysis (summarization,
topic detection, intent recognition, sentiment analysis), and saves results
back to BigQuery.
"""

import os
import sys
import time
import json
import requests
from datetime import datetime, timezone, timedelta
from google.cloud import bigquery, storage
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("GCP_DATASET_ID")
TRACKING_TABLE_NAME = os.getenv("GCP_TRACKING_TABLE")
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

# Validate required environment variables
required_vars = {
    "GCP_PROJECT_ID": PROJECT_ID,
    "GCP_DATASET_ID": DATASET_ID,
    "GCP_TRACKING_TABLE": TRACKING_TABLE_NAME,
    "GCS_BUCKET_NAME": BUCKET_NAME,
    "DEEPGRAM_API_KEY": DEEPGRAM_API_KEY,
}

missing_vars = [name for name, value in required_vars.items() if not value]
if missing_vars:
    raise ValueError(
        f"Missing required environment variables: {', '.join(missing_vars)}\n"
        f"Please set these in your .env file. See .env.example for reference."
    )

TRACKING_TABLE = f"{PROJECT_ID}.{DATASET_ID}.{TRACKING_TABLE_NAME}"

# Deepgram API config
DEEPGRAM_API_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_MODEL = "nova-3"

# Rate limiting
SLEEP_BETWEEN_CALLS = 1.0  # seconds between Deepgram API calls

# Signed URL expiry
SIGNED_URL_EXPIRY_MINUTES = 15


def init_clients():
    """Initialize BigQuery and GCS clients."""
    bq_client = bigquery.Client(project=PROJECT_ID)
    gcs_client = storage.Client(project=PROJECT_ID)
    return bq_client, gcs_client


def ensure_new_columns(bq_client):
    """Add new columns to the tracking table if they don't exist."""
    new_columns = [
        bigquery.SchemaField("transcribed", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("analysed", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("transcription", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("transcription_raw", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("summary", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("topics", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("intents", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("sentiment", "STRING", mode="NULLABLE"),
    ]

    table = bq_client.get_table(TRACKING_TABLE)
    existing_field_names = {field.name for field in table.schema}

    columns_to_add = [col for col in new_columns if col.name not in existing_field_names]

    if columns_to_add:
        print(f"Adding {len(columns_to_add)} new column(s) to {TRACKING_TABLE}...")
        updated_schema = list(table.schema) + columns_to_add
        table.schema = updated_schema
        bq_client.update_table(table, ["schema"])
        print(f"✓ Added columns: {', '.join(c.name for c in columns_to_add)}")
    else:
        print("✓ All required columns already exist.")


def get_pending_transcriptions(bq_client, limit=None):
    """
    Fetch records that have a GCS URI but haven't been transcribed yet.
    Returns list of dicts with contactId and gcs_uri.
    """
    limit_clause = f"LIMIT {limit}" if limit else ""

    query = f"""
        SELECT contactId, gcs_uri
        FROM `{TRACKING_TABLE}`
        WHERE gcs_uri IS NOT NULL
          AND status = 'SUCCESS'
          AND (transcribed IS NULL OR transcribed = 0)
        ORDER BY fetch_datetime ASC
        {limit_clause}
    """

    print("Fetching pending transcriptions from BigQuery...")
    rows = bq_client.query(query).result()
    results = [{"contactId": row.contactId, "gcs_uri": row.gcs_uri} for row in rows]
    return results


def generate_signed_url(gcs_client, gcs_uri):
    """
    Generate a signed URL from a gs:// URI so Deepgram can access the file.
    
    Args:
        gcs_client: GCS client
        gcs_uri: gs://bucket-name/path/to/file
    
    Returns:
        Signed URL string
    """
    # Parse gs:// URI
    # gs://bucket-name/path/to/file -> bucket-name, path/to/file
    path = gcs_uri.replace("gs://", "")
    bucket_name = path.split("/")[0]
    blob_path = "/".join(path.split("/")[1:])

    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    signed_url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(minutes=SIGNED_URL_EXPIRY_MINUTES),
        method="GET",
    )

    return signed_url


def call_deepgram_api(audio_url):
    """
    Call Deepgram API with transcription + all audio intelligence features.
    
    Single API call handles:
    - Transcription (nova-3 model)
    - Speaker Diarization (speaker identification)
    - Utterances (conversation turns)
    - Multichannel (if stereo audio: Ch1=Agent, Ch2=Customer)
    - Summarization
    - Topic Detection
    - Intent Recognition
    - Sentiment Analysis
    
    Returns:
        dict: Full API response
    """
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/json",
    }

    params = {
        "model": DEEPGRAM_MODEL,
        "smart_format": "true",
        "diarize": "true",       # Speaker identification
        "utterances": "true",    # Group into conversation turns
        "multichannel": "true",  # If stereo: separate channels per speaker
        "summarize": "v2",
        "topics": "true",
        "intents": "true",
        "sentiment": "true",
    }

    payload = {"url": audio_url}

    response = requests.post(
        DEEPGRAM_API_URL,
        headers=headers,
        params=params,
        json=payload,
        timeout=300,  # 5 minute timeout for large files
    )

    response.raise_for_status()
    return response.json()


def format_conversation(utterances):
    """
    Format utterances into a readable conversation transcript.
    
    Uses numbered Speaker labels (Speaker 1, Speaker 2, Speaker 3...)
    since we can't reliably determine Agent vs Customer roles,
    especially in multi-party calls with transfers.
    
    Example output:
        Speaker 1: Hello, and thank you for calling. How can I help you today?
        Speaker 2: Hi, I need to check on my order status.
        Speaker 1: Sure, may I have your order number?
    
    Args:
        utterances: List of utterance dicts from Deepgram response
    
    Returns:
        str: Formatted conversation string
    """
    lines = []
    for utt in utterances:
        # Deepgram uses 0-indexed speaker IDs, we display as 1-indexed
        speaker_id = utt.get("speaker", 0)
        speaker_name = f"Speaker {speaker_id + 1}"
        transcript = utt.get("transcript", "").strip()
        if transcript:
            lines.append(f"{speaker_name}: {transcript}")
    return "\n".join(lines)


def format_multichannel_conversation(channels):
    """
    Format multichannel (stereo) audio into a conversation transcript.
    
    In call center stereo recordings:
    - Channel 0 = Agent
    - Channel 1 = Customer
    
    Merges both channels' words by timestamp to produce a natural
    conversation order.
    
    Returns:
        str: Formatted conversation string
    """
    CHANNEL_LABELS = {0: "Agent", 1: "Customer"}
    
    # Collect all words from all channels with their channel info
    all_words = []
    for ch_idx, channel in enumerate(channels):
        alternatives = channel.get("alternatives", [])
        if not alternatives:
            continue
        for word_info in alternatives[0].get("words", []):
            all_words.append({
                "word": word_info.get("word", ""),
                "start": word_info.get("start", 0),
                "end": word_info.get("end", 0),
                "channel": ch_idx,
            })
    
    # Sort all words by start time
    all_words.sort(key=lambda w: w["start"])
    
    # Group consecutive words by the same channel into utterances
    if not all_words:
        return ""
    
    utterances = []
    current_channel = all_words[0]["channel"]
    current_words = [all_words[0]["word"]]
    
    for word in all_words[1:]:
        if word["channel"] == current_channel:
            current_words.append(word["word"])
        else:
            # Speaker changed — save current utterance
            utterances.append({
                "channel": current_channel,
                "text": " ".join(current_words),
            })
            current_channel = word["channel"]
            current_words = [word["word"]]
    
    # Don't forget the last utterance
    if current_words:
        utterances.append({
            "channel": current_channel,
            "text": " ".join(current_words),
        })
    
    # Format as conversation
    lines = []
    for utt in utterances:
        label = CHANNEL_LABELS.get(utt["channel"], f"Channel {utt['channel'] + 1}")
        text = utt["text"].strip()
        if text:
            lines.append(f"{label}: {text}")
    
    return "\n".join(lines)


def parse_deepgram_response(response):
    """
    Parse the Deepgram API response to extract transcription and analysis.
    
    Supports two modes:
    - Multichannel (stereo): Agent/Customer labels from channels
    - Mono with diarization: Speaker 1/2/3 labels from utterances
    
    Returns:
        dict with keys: transcription, summary, topics, intents, sentiment
    """
    result = {
        "transcription": "",
        "transcription_raw": "",
        "summary": "",
        "topics": "[]",
        "intents": "[]",
        "sentiment": "{}",
    }

    try:
        channels = response.get("results", {}).get("channels", [])
        num_channels = len(channels)
        
        # Extract raw transcript (plain text without speaker labels)
        if channels:
            alternatives = channels[0].get("alternatives", [])
            if alternatives:
                result["transcription_raw"] = alternatives[0].get("transcript", "")
        
        # Extract diarized/conversation-style transcript
        if num_channels >= 2:
            # MULTICHANNEL: stereo recording — use channel-based labeling
            print(f"  🔊 Detected {num_channels}-channel audio (stereo) — using Agent/Customer labels")
            result["transcription"] = format_multichannel_conversation(channels)
        else:
            # MONO: use diarization-based utterances
            utterances = response.get("results", {}).get("utterances", [])
            if utterances:
                # Count unique speakers
                speakers = set(u.get("speaker", 0) for u in utterances)
                print(f"  🎙️ Detected {len(speakers)} speaker(s) in mono audio — using Speaker labels")
                result["transcription"] = format_conversation(utterances)
            else:
                # Fallback: use plain transcript
                result["transcription"] = result["transcription_raw"]

        # Extract summary
        summary_data = response.get("results", {}).get("summary", {})
        if summary_data:
            result["summary"] = summary_data.get("short", "")

        # Extract topics
        topics_data = response.get("results", {}).get("topics", {})
        if topics_data:
            segments = topics_data.get("segments", [])
            all_topics = []
            for seg in segments:
                for topic_item in seg.get("topics", []):
                    all_topics.append({
                        "topic": topic_item.get("topic", ""),
                        "confidence": topic_item.get("confidence_score", 0),
                        "text": seg.get("text", ""),
                    })
            result["topics"] = json.dumps(all_topics)

        # Extract intents
        intents_data = response.get("results", {}).get("intents", {})
        if intents_data:
            segments = intents_data.get("segments", [])
            all_intents = []
            for seg in segments:
                for intent_item in seg.get("intents", []):
                    all_intents.append({
                        "intent": intent_item.get("intent", ""),
                        "confidence": intent_item.get("confidence_score", 0),
                        "text": seg.get("text", ""),
                    })
            result["intents"] = json.dumps(all_intents)

        # Extract sentiment
        sentiments_data = response.get("results", {}).get("sentiments", {})
        if sentiments_data:
            segments = sentiments_data.get("segments", [])
            average = sentiments_data.get("average", {})

            sentiment_result = {
                "average": {
                    "sentiment": average.get("sentiment", "neutral"),
                    "sentiment_score": average.get("sentiment_score", 0),
                },
                "segments": [],
            }
            for seg in segments:
                sentiment_result["segments"].append({
                    "text": seg.get("text", ""),
                    "sentiment": seg.get("sentiment", "neutral"),
                    "sentiment_score": seg.get("sentiment_score", 0),
                })
            result["sentiment"] = json.dumps(sentiment_result)

    except Exception as e:
        print(f"  ⚠ Warning parsing response: {e}")

    return result


def update_bigquery_row(bq_client, contact_id, parsed_data, success=True):
    """
    Update the BigQuery row with transcription and analysis results.
    Uses DML UPDATE statement.
    """
    if success:
        query = f"""
            UPDATE `{TRACKING_TABLE}`
            SET
                transcribed = 1,
                analysed = 1,
                transcription = @transcription,
                transcription_raw = @transcription_raw,
                summary = @summary,
                topics = @topics,
                intents = @intents,
                sentiment = @sentiment
            WHERE contactId = @contact_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("transcription", "STRING", parsed_data["transcription"]),
                bigquery.ScalarQueryParameter("transcription_raw", "STRING", parsed_data["transcription_raw"]),
                bigquery.ScalarQueryParameter("summary", "STRING", parsed_data["summary"]),
                bigquery.ScalarQueryParameter("topics", "STRING", parsed_data["topics"]),
                bigquery.ScalarQueryParameter("intents", "STRING", parsed_data["intents"]),
                bigquery.ScalarQueryParameter("sentiment", "STRING", parsed_data["sentiment"]),
                bigquery.ScalarQueryParameter("contact_id", "STRING", contact_id),
            ]
        )
    else:
        # On failure, mark as attempted but not successful
        query = f"""
            UPDATE `{TRACKING_TABLE}`
            SET
                transcribed = 0,
                analysed = 0,
                transcription = @error_msg
            WHERE contactId = @contact_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("error_msg", "STRING", parsed_data.get("error", "Unknown error")),
                bigquery.ScalarQueryParameter("contact_id", "STRING", contact_id),
            ]
        )

    bq_client.query(query, job_config=job_config).result()
    print(f"  ✓ BigQuery updated (transcribed={'1' if success else '0'})")


def main():
    print("=" * 70)
    print("CXone Transcription & Analysis Pipeline (Deepgram)")
    print("=" * 70)
    print(f"Model: {DEEPGRAM_MODEL}")
    print(f"Table: {TRACKING_TABLE}")
    print()

    # Initialize clients
    bq_client, gcs_client = init_clients()

    # Ensure new columns exist
    ensure_new_columns(bq_client)

    # Get pending transcriptions
    # Set limit for testing, remove or set to None for full processing
    pending = get_pending_transcriptions(bq_client, limit=5)

    print(f"\n✓ Found {len(pending)} recordings to transcribe.\n")

    if not pending:
        print("No pending transcriptions. Exiting.")
        return

    processed = 0
    success_count = 0
    failed_count = 0

    for record in pending:

        # for testing lets do only 1 call
        if processed >= 4:
            break
        
        processed += 1
        contact_id = record["contactId"]
        gcs_uri = record["gcs_uri"]

        print(f"\n{'=' * 70}")
        print(f"[{processed}/{len(pending)}] Contact: {contact_id}")
        print(f"  GCS: {gcs_uri}")
        print("=" * 70)

        try:
            # Step 1: Generate signed URL
            print("  ⏳ Generating signed URL...")
            signed_url = generate_signed_url(gcs_client, gcs_uri)
            print("  ✓ Signed URL generated")

            # Step 2: Call Deepgram API
            print("  ⏳ Calling Deepgram API (transcription + analysis)...")
            api_response = call_deepgram_api(signed_url)
            print("  ✓ Deepgram API response received")

            # Step 3: Parse response
            parsed = parse_deepgram_response(api_response)

            # Show preview
            transcript_preview = parsed["transcription"][:100]
            print(f"  📝 Transcript: {transcript_preview}{'...' if len(parsed['transcription']) > 100 else ''}")
            print(f"  📋 Summary: {parsed['summary'][:100]}{'...' if len(parsed['summary']) > 100 else ''}")

            # Step 4: Update BigQuery
            print("  ⏳ Updating BigQuery...")
            update_bigquery_row(bq_client, contact_id, parsed, success=True)

            success_count += 1
            print(f"  ✅ Done!")

        except requests.exceptions.HTTPError as e:
            print(f"  ✗ Deepgram API error: {e}")
            error_data = {"error": f"Deepgram API error: {str(e)}"}
            update_bigquery_row(bq_client, contact_id, error_data, success=False)
            failed_count += 1

        except Exception as e:
            print(f"  ✗ Error: {e}")
            error_data = {"error": str(e)}
            update_bigquery_row(bq_client, contact_id, error_data, success=False)
            failed_count += 1

        # Rate limiting
        if processed < len(pending):
            time.sleep(SLEEP_BETWEEN_CALLS)

    # Final Summary
    print(f"\n{'=' * 70}")
    print("TRANSCRIPTION COMPLETE")
    print("=" * 70)
    print(f"Total Processed:    {processed}")
    print(f"✓ Successful:       {success_count}")
    print(f"✗ Failed:           {failed_count}")
    print("=" * 70)


if __name__ == "__main__":
    main()
