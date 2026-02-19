#!/usr/bin/env python3
"""
Classify Calls - Gemini AI Call Classification Pipeline

Reads transcribed calls from BigQuery (recording_fetch_status), sends
transcripts to Gemini 2.0 Flash Thinking via Vertex AI for classification,
and saves structured results to the call_classifications BigQuery table.

Step 3 of the pipeline:
  1. main.py         → Fetch recordings → GCS + BigQuery
  2. transcribe_v2.py → Transcribe + Analyse → BigQuery  
  3. classify_calls.py → Gemini classification → BigQuery
"""

import os
import sys
import time
import json
from datetime import datetime, timezone
from google.cloud import bigquery
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
PROJECT_ID = os.getenv("GCP_PROJECT_ID")
DATASET_ID = os.getenv("GCP_DATASET_ID")
TRACKING_TABLE_NAME = os.getenv("GCP_TRACKING_TABLE")
VERTEX_AI_LOCATION = os.getenv("VERTEX_AI_LOCATION", "australia-southeast1")

# Validate required environment variables
required_vars = {
    "GCP_PROJECT_ID": PROJECT_ID,
    "GCP_DATASET_ID": DATASET_ID,
    "GCP_TRACKING_TABLE": TRACKING_TABLE_NAME,
}

missing_vars = [name for name, value in required_vars.items() if not value]
if missing_vars:
    raise ValueError(
        f"Missing required environment variables: {', '.join(missing_vars)}\n"
        f"Please set these in your .env file. See .env.example for reference."
    )

TRACKING_TABLE = f"{PROJECT_ID}.{DATASET_ID}.{TRACKING_TABLE_NAME}"
CLASSIFICATIONS_TABLE = f"{PROJECT_ID}.{DATASET_ID}.call_classifications"

# Gemini config
GEMINI_MODEL = "gemini-2.0-flash-thinking-exp"
GEMINI_FALLBACK_MODEL = "gemini-2.0-flash"

# Rate limiting
SLEEP_BETWEEN_CALLS = 1.0  # seconds between Gemini API calls


# --- GEMINI CLIENT (lazy loaded) ---
_genai_client = None


def get_genai_client():
    """Lazy-load the Google GenAI client with Vertex AI backend."""
    global _genai_client
    if _genai_client is None:
        try:
            from google import genai
            _genai_client = genai.Client(
                vertexai=True,
                project=PROJECT_ID,
                location=VERTEX_AI_LOCATION,
            )
            print(f"✓ Gemini client initialized (Vertex AI @ {VERTEX_AI_LOCATION})")
        except ImportError:
            raise RuntimeError(
                "google-genai package not installed. Run: uv add google-genai"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Gemini client: {e}")
    return _genai_client


# --- BIGQUERY FUNCTIONS ---


def init_bq_client():
    """Initialize BigQuery client."""
    return bigquery.Client(project=PROJECT_ID)


def get_pending_classifications(bq_client, limit=None):
    """
    Fetch records that have been transcribed but not yet classified by Gemini.
    Returns list of dicts with contactId and transcription.
    """
    limit_clause = f"LIMIT {limit}" if limit else ""

    query = f"""
        SELECT contactId, transcription
        FROM `{TRACKING_TABLE}`
        WHERE transcribed = 1
          AND transcription IS NOT NULL
          AND LENGTH(TRIM(transcription)) > 0
          AND (gemini_analysed IS NULL OR gemini_analysed = 0)
        ORDER BY fetch_datetime ASC
        {limit_clause}
    """

    print("Fetching pending classifications from BigQuery...")
    rows = bq_client.query(query).result()
    results = [
        {"contactId": row.contactId, "transcription": row.transcription}
        for row in rows
    ]
    return results


def build_classification_prompt(transcript_text):
    """Build the Gemini classification prompt with the transcript."""
    return f"""You are analyzing a customer service call transcript for an Australian outdoor power equipment parts business (chainsawspares.com.au).

Classify the call using the following structure. Think through the classification step-by-step, then return ONLY valid JSON with no markdown formatting.

**A. CALL TYPE** (select up to 2 that apply):
- product_enquiry: Customer researching products or asking what to buy
- parts_identification: Customer needs help identifying the correct part number or compatible part
- order_placement: Customer ready to place an order
- order_support: Customer asking about existing order (tracking, changes, cancellation)
- technical_support: Customer needs help with installation, usage, or troubleshooting
- warranty_or_return: Customer reporting defect, wrong item, or requesting refund/return
- complaint: Customer unhappy with product quality or service
- general_enquiry: Delivery timeframes, opening hours, policies, payment methods

**B. SALE RESULT** (choose exactly ONE):
- sale_completed: Order was placed during this call, payment taken, order ID exists
- sale_intended: Customer stated they will purchase but did not complete order on this call
- no_sale_customer_declined: Customer decided not to buy
- no_sale_business_unable: We couldn't fulfill (out of stock, don't carry item, can't confirm compatibility)
- not_sales_call: Call was support/service, not a purchase opportunity

**C. NO SALE REASONS** (select ALL that apply, ONLY if B = no_sale_customer_declined OR no_sale_business_unable):

Customer Reasons:
- price_objection: Customer said price was too high
- freight_objection: Customer concerned about delivery/shipping cost
- customer_undecided: Customer needs time to think or compare options
- competitor_mention: Customer mentioned buying elsewhere or checking competitor
- technical_uncertainty: Customer not confident this is the right part/product
- other_customer_reason: Clear customer reason but not covered by above

Business Reasons:
- out_of_stock: Item unavailable
- not_in_range: We don't carry/stock that item
- cannot_confirm_compatibility: Staff unable to confirm if part fits customer's equipment
- other_business_reason: Clear business reason but not covered by above

**D. PRODUCT FAMILY** (choose exactly ONE):
- chainsaw_related: Chainsaws, chainsaw parts, chainsaw accessories, protective equipment, milling equipment
- outdoor_power_equipment: Brushcutters, lawn mowers, multi-tools, post hole diggers, pressure washers, rotary hoes, tillers
- engines_generators: Stationary engines (horizontal/vertical shaft), generators, engine parts
- pumps_water_equipment: Water pumps, hoses, fittings, water troughs
- fencing: Electric fence energisers and all fencing equipment
- weed_sprayers: All weed sprayer products and parts
- log_equipment: Log splitters and swing saws
- power_tools: Zomax 58v tools and battery equipment
- other

**D2. PRODUCT CATEGORY DETAIL** (select up to 3 that apply):
- chainsaws_complete_units
- chainsaw_spare_parts
- chainsaw_accessories
- protective_clothing_equipment
- chainsaw_milling_equipment
- generators
- lawn_mower_parts
- log_splitter_swing_saw
- petrol_multi_tool
- post_hole_digger
- pressure_washer_rotary_hoe_tiller
- weed_sprayers
- electric_fence_energisers
- electric_fence_equipment_other
- stationary_engines
- zomax_58v_tools
- honda_copy_engine_parts
- water_pumps_hoses_accessories
- water_troughs
- other

**E. PROBLEMS DETECTED** (select ALL that apply):
- customer_frustrated: Customer expressed frustration, annoyance, or anger
- wrong_part_supplied: Customer received incorrect part previously
- quality_concern: Customer raised concerns about part quality or durability
- staff_knowledge_gap: Staff member unable to answer customer question
- call_transferred: Call transferred to another person or department
- other: Clear problem but not covered by above categories

**F. DELIVERY TRACKING ENQUIRY** (ONLY complete if call_type includes order_support AND call is about tracking):

Carrier (choose ONE):
- startrack
- auspost
- other_carrier
- unknown_carrier

Customer Action (choose ONE):
- checked_tracking_needs_help: Checked tracking themselves, want more info/escalation
- cant_find_tracking: Don't have tracking number, need us to provide it
- hasnt_checked_tracking: Have tracking number but haven't looked it up yet
- parcel_overdue: Tracking shows delivered but they don't have it, or significantly delayed
- unclear: Cannot determine what customer has done

Reason for Call (select ALL that apply):
- no_movement_on_tracking: Tracking hasn't updated in days
- delivery_timeframe_concern: Want to know when it'll arrive
- failed_delivery_attempt: Missed delivery, need redelivery arranged
- wrong_address_supplied: Customer realizes they gave wrong address
- parcel_damaged_lost: Tracking shows issue or customer suspects loss
- general_tracking_question: Just want status update
- other: Clear reason but not covered by above categories

**G. AGENT INFORMATION**:
Extract the staff member's name if they introduce themselves at the start of the call (e.g., "Hi, this is Sarah speaking", "John here, how can I help?", "You're speaking with Mike"). Return the first name only as a string. If no name is mentioned or unclear, return null.

**H. ESCALATION & FOLLOW-UP ACTIONS** (select ALL that apply):
- mechanic_callback_promised: Staff said a mechanic, technician, or expert will call the customer back
- mechanic_consult_then_callback: Staff will get advice from mechanic/technician/expert and then call customer back themselves
- manager_escalation: Staff said a manager will speak to the customer or call them back
- general_callback_promised: Staff promised to call back (not mechanic/manager specific)
- other_escalation: Other escalation mentioned but not covered above
- none: No escalation or callback promised

**I. CONFIDENCE SCORES**:
For each major classification section, provide a confidence score from 0.0 to 1.0 indicating how certain you are about your classification:
- call_type_confidence: How confident are you in the call type classification?
- sale_result_confidence: How confident are you in the sale result?
- product_classification_confidence: How confident are you in the product family and categories?
- overall_confidence: Overall confidence in the entire classification

Return your classification as JSON with this exact structure:
{{
  "classification_version": "v1.0",
  "call_type": [...],
  "sale_result": "...",
  "no_sale_reasons": [...],
  "product_family": "...",
  "product_category_detail": [...],
  "problems_detected": [...],
  "delivery_tracking": {{
    "carrier": "...",
    "customer_action": "...",
    "reason_for_call": [...]
  }},
  "agent_name": "...",
  "escalation_actions": [...],
  "confidence_scores": {{
    "call_type_confidence": 0.0,
    "sale_result_confidence": 0.0,
    "product_classification_confidence": 0.0,
    "overall_confidence": 0.0
  }}
}}

If the call is NOT about delivery tracking, set "delivery_tracking" to null.
If agent name is not identified, set "agent_name" to null.
If no escalation or callback was mentioned, use ["none"] for escalation_actions.

TRANSCRIPT:
{transcript_text}"""


def call_gemini(transcript_text):
    """
    Send transcript to Gemini for classification.
    
    Tries the primary model first, falls back to stable model if needed.
    Returns parsed JSON dict or raises an exception.
    """
    client = get_genai_client()
    prompt = build_classification_prompt(transcript_text)

    # Try primary model, then fallback
    models_to_try = [GEMINI_MODEL, GEMINI_FALLBACK_MODEL]

    for model_name in models_to_try:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            response_text = response.text.strip()

            # Strip markdown code fences if present
            if response_text.startswith("```"):
                # Remove ```json or ``` at start and ``` at end
                lines = response_text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                response_text = "\n".join(lines).strip()

            # Parse JSON
            classification = json.loads(response_text)
            print(f"  ✓ Gemini response received (model: {model_name})")
            return classification, model_name

        except json.JSONDecodeError as e:
            print(f"  ⚠ JSON parse error with {model_name}: {e}")
            print(f"    Raw response (first 200 chars): {response_text[:200]}")
            if model_name == models_to_try[-1]:
                raise ValueError(f"All models returned invalid JSON: {e}")
            print(f"  ↳ Trying fallback model...")

        except Exception as e:
            print(f"  ⚠ Error with {model_name}: {e}")
            if model_name == models_to_try[-1]:
                raise
            print(f"  ↳ Trying fallback model...")

    raise RuntimeError("All Gemini models failed")


def save_classification(bq_client, contact_id, classification, model_name, transcript_text):
    """
    Insert classification results into call_classifications table
    and update gemini_analysed flag in recording_fetch_status.
    """
    # Extract fields from classification JSON
    call_type = classification.get("call_type", [])
    sale_result = classification.get("sale_result")
    no_sale_reasons = classification.get("no_sale_reasons", [])
    product_family = classification.get("product_family")
    product_category_detail = classification.get("product_category_detail", [])
    problems_detected = classification.get("problems_detected", [])
    escalation_actions = classification.get("escalation_actions", [])
    agent_name = classification.get("agent_name")
    confidence_scores = classification.get("confidence_scores", {})
    delivery_tracking = classification.get("delivery_tracking")
    version = classification.get("classification_version", "v1.0")

    def sql_str(val):
        """Escape a string for SQL, returns NULL if None."""
        if val is None:
            return "NULL"
        # BigQuery uses doubled single quotes for escaping, not backslashes
        escaped = str(val).replace("'", "''")
        return f"'{escaped}'"

    def sql_array(arr):
        """Convert a list to a SQL array literal."""
        if not arr:
            return "[]"
        items = ", ".join(sql_str(v) for v in arr)
        return f"[{items}]"

    # Build delivery_tracking STRUCT or NULL
    if delivery_tracking and isinstance(delivery_tracking, dict):
        dt_carrier = sql_str(delivery_tracking.get("carrier"))
        dt_action = sql_str(delivery_tracking.get("customer_action"))
        dt_reasons = sql_array(delivery_tracking.get("reason_for_call", []))
        dt_sql = f"STRUCT({dt_carrier} AS carrier, {dt_action} AS customer_action, {dt_reasons} AS reason_for_call)"
    else:
        dt_sql = "NULL"

    # Build confidence_scores STRUCT
    cs = confidence_scores or {}
    ct_conf = cs.get("call_type_confidence", 0.0)
    sr_conf = cs.get("sale_result_confidence", 0.0)
    pc_conf = cs.get("product_classification_confidence", 0.0)
    ov_conf = cs.get("overall_confidence", 0.0)
    cs_sql = f"STRUCT({ct_conf} AS call_type_confidence, {sr_conf} AS sale_result_confidence, {pc_conf} AS product_classification_confidence, {ov_conf} AS overall_confidence)"

    insert_query = f"""
        INSERT INTO `{CLASSIFICATIONS_TABLE}` (
            call_id, contactId, call_date, transcript,
            classification_version, classification_timestamp, llm_model,
            call_type, sale_result, product_family, agent_name,
            no_sale_reasons, product_category_detail, problems_detected, escalation_actions,
            delivery_tracking, confidence_scores
        ) VALUES (
            {sql_str(contact_id)}, {sql_str(contact_id)}, CURRENT_DATE(), @transcript,
            {sql_str(version)}, CURRENT_TIMESTAMP(), {sql_str(model_name)},
            {sql_array(call_type)}, {sql_str(sale_result)}, {sql_str(product_family)}, {sql_str(agent_name)},
            {sql_array(no_sale_reasons)}, {sql_array(product_category_detail)}, {sql_array(problems_detected)}, {sql_array(escalation_actions)},
            {dt_sql}, {cs_sql}
        )
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("transcript", "STRING", transcript_text),
        ]
    )
    bq_client.query(insert_query, job_config=job_config).result()
    print(f"  ✓ Classification saved to call_classifications")

    # UPDATE gemini_analysed flag
    update_query = f"""
        UPDATE `{TRACKING_TABLE}`
        SET gemini_analysed = 1
        WHERE contactId = @contact_id
    """
    update_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("contact_id", "STRING", contact_id),
        ]
    )
    bq_client.query(update_query, job_config=update_config).result()
    print(f"  ✓ recording_fetch_status updated (gemini_analysed=1)")


def save_classification_error(bq_client, contact_id, error_msg):
    """Mark a record as failed classification (gemini_analysed = 0) to retry later."""
    # We don't insert into call_classifications on error — just leave gemini_analysed as 0
    # so it gets retried on next run. Log the error.
    print(f"  ✗ Classification failed for {contact_id}: {error_msg}")


# --- MAIN ---


def main():
    print("=" * 70)
    print("CXone Call Classification Pipeline (Gemini AI)")
    print("=" * 70)
    print(f"Model: {GEMINI_MODEL} (fallback: {GEMINI_FALLBACK_MODEL})")
    print(f"Vertex AI: {VERTEX_AI_LOCATION}")
    print(f"Tracking: {TRACKING_TABLE}")
    print(f"Output:   {CLASSIFICATIONS_TABLE}")
    print()

    # Initialize clients
    bq_client = init_bq_client()

    # Initialize Gemini (fail fast if misconfigured)
    get_genai_client()

    # Get pending classifications
    pending = get_pending_classifications(bq_client, limit=10)

    print(f"\n✓ Found {len(pending)} calls to classify.\n")

    if not pending:
        print("No pending classifications. Exiting.")
        return

    processed = 0
    success_count = 0
    failed_count = 0

    for record in pending:

        # for testing lets do only 1 call
        # if processed >= 1:
        #     break

        processed += 1
        contact_id = record["contactId"]
        transcription = record["transcription"]

        print(f"\n{'=' * 70}")
        print(f"[{processed}/{len(pending)}] Contact: {contact_id}")
        print(f"  Transcript length: {len(transcription)} chars")
        print("=" * 70)

        try:
            # Step 1: Call Gemini API
            print("  ⏳ Sending to Gemini for classification...")
            classification, model_used = call_gemini(transcription)

            # Show preview
            print(f"  📋 Call type: {classification.get('call_type', [])}")
            print(f"  💰 Sale result: {classification.get('sale_result', 'N/A')}")
            print(f"  🏷️ Product: {classification.get('product_family', 'N/A')}")
            print(f"  👤 Agent: {classification.get('agent_name', 'N/A')}")
            confidence = classification.get("confidence_scores", {})
            print(f"  🎯 Confidence: {confidence.get('overall_confidence', 'N/A')}")

            # Step 2: Save to BigQuery
            print("  ⏳ Saving to BigQuery...")
            save_classification(bq_client, contact_id, classification, model_used, transcription)

            success_count += 1
            print(f"  ✅ Done!")

        except Exception as e:
            save_classification_error(bq_client, contact_id, str(e))
            failed_count += 1

        # Rate limiting
        if processed < len(pending):
            time.sleep(SLEEP_BETWEEN_CALLS)

    # Final Summary
    print(f"\n{'=' * 70}")
    print("CLASSIFICATION COMPLETE")
    print("=" * 70)
    print(f"Total Processed:    {processed}")
    print(f"✓ Successful:       {success_count}")
    print(f"✗ Failed:           {failed_count}")
    print("=" * 70)


if __name__ == "__main__":
    main()
