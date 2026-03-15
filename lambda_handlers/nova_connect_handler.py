"""Lambda handler for Amazon Connect + Lex voice escalation.

This Lambda is invoked by an Amazon Lex bot that is wired into the
Amazon Connect Contact Flow. It receives the caller's speech as text
(transcribed by Lex), sends it to Bedrock Nova for a real-time AI
conversation, and returns Nova's response for Lex/Polly to speak back.

Conversation state is carried in Lex session attributes so multi-turn
context is preserved across Lambda invocations.

When Nova emits [ACTION_APPROVED] or [ACTION_REJECTED], the Lambda
triggers the NovaOps API accordingly and ends the conversation.

Environment variables (set on the Lambda):
  NOVA_MODEL_ID             — Bedrock model ID (default: us.amazon.nova-2-lite-v1:0)
  NOVAOPS_API_CALLBACK_URL  — NovaOps server URL for approval callback
  AWS_DEFAULT_REGION        — Bedrock region
"""

import os
import json
import logging
import urllib.request
import urllib.error
import urllib.parse

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

NOVA_MODEL_ID = os.environ.get("NOVA_MODEL_ID", "us.amazon.nova-2-lite-v1:0")
CALLBACK_URL = os.environ.get("NOVAOPS_API_CALLBACK_URL", "http://localhost:8082")

# Lazy-init Bedrock client
_bedrock_client = None


def get_bedrock():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        )
    return _bedrock_client


def handler(event, context):
    """Lex V2 fulfillment handler.

    Expected event structure (Lex V2 format):
    {
        "sessionState": {
            "sessionAttributes": { ... },
            "intent": { "name": "...", "state": "..." }
        },
        "inputTranscript": "what the caller said",
        "invocationSource": "FulfillmentCodeHook",
        ...
    }
    """
    logger.info(f"Lambda invoked: {json.dumps(event, default=str)[:2000]}")

    session_attrs = event.get("sessionState", {}).get("sessionAttributes", {}) or {}
    user_utterance = event.get("inputTranscript", "").strip()
    intent_name = event.get("sessionState", {}).get("intent", {}).get("name", "")

    # Retrieve incident context from session (set by Contact Flow on call start)
    incident_id = session_attrs.get("incident_id", "unknown")
    system_prompt = session_attrs.get("system_prompt", "")
    callback_url = _resolve_callback_url(session_attrs.get("callback_url", ""))

    # Rebuild conversation history from session
    messages = _load_messages(session_attrs)

    # Append the new user utterance
    if user_utterance:
        messages.append({"role": "user", "content": [{"text": user_utterance}]})

    # If this is the first turn and no user utterance, generate initial greeting
    if not messages:
        messages.append({"role": "user", "content": [{"text": "Hello? (Start the phone call)"}]})

    # Call Bedrock Nova
    try:
        reply_text = _call_nova(messages, system_prompt)
    except Exception as e:
        logger.error(f"Bedrock call failed: {e}")
        return _build_response(
            session_attrs, intent_name,
            "I'm having trouble connecting to the AI system. "
            "Please check your Slack for incident details.",
            close=True,
        )

    # Check for approval/rejection tokens
    if "[ACTION_APPROVED]" in reply_text:
        clean_reply = reply_text.replace("[ACTION_APPROVED]", "").strip()
        _trigger_approval(callback_url, incident_id)
        farewell = clean_reply or "Approved. Initiating remediation now. Goodbye."
        return _build_response(session_attrs, intent_name, farewell, close=True)

    if "[ACTION_REJECTED]" in reply_text:
        clean_reply = reply_text.replace("[ACTION_REJECTED]", "").strip()
        _trigger_rejection(callback_url, incident_id)
        logger.info(f"Incident {incident_id} rejected by on-call engineer")
        farewell = clean_reply or "Understood, remediation aborted. Goodbye."
        return _build_response(session_attrs, intent_name, farewell, close=True)

    # Continue conversation — save updated history
    messages.append({"role": "assistant", "content": [{"text": reply_text}]})
    _save_messages(session_attrs, messages)

    return _build_response(session_attrs, intent_name, reply_text, close=False)


def _call_nova(messages: list, system_prompt: str) -> str:
    """Call Bedrock Nova with the conversation history."""
    bedrock = get_bedrock()

    system = [{"text": system_prompt}] if system_prompt else []

    response = bedrock.converse(
        modelId=NOVA_MODEL_ID,
        messages=messages,
        system=system,
    )

    content_blocks = response["output"]["message"]["content"]
    reply_text = ""
    for block in content_blocks:
        if "text" in block:
            reply_text += block["text"]

    logger.info(f"Nova response: {reply_text[:500]}")
    return reply_text


def _trigger_approval(callback_url: str, incident_id: str):
    """Call the NovaOps API to approve the incident."""
    url = f"{callback_url}/api/incidents/{incident_id}/approve"
    logger.info(f"Triggering approval: POST {url}")

    try:
        req = urllib.request.Request(url, method="POST", data=b"")
        req.add_header("Content-Type", "application/json")
        token = os.environ.get("NOVAOPS_APPROVAL_TOKEN", "").strip()
        if token:
            req.add_header("X-NovaOps-Approval-Token", token)
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info(f"Approval response: {resp.status}")
    except urllib.error.URLError as e:
        logger.error(f"Approval callback failed: {e}")
    except Exception as e:
        logger.error(f"Approval callback error: {e}")


def _trigger_rejection(callback_url: str, incident_id: str):
    """Call the NovaOps API to reject (deny) the incident."""
    url = f"{callback_url}/api/incidents/{incident_id}/reject"
    logger.info(f"Triggering rejection: POST {url}")

    try:
        req = urllib.request.Request(url, method="POST", data=b"")
        req.add_header("Content-Type", "application/json")
        token = os.environ.get("NOVAOPS_APPROVAL_TOKEN", "").strip()
        if token:
            req.add_header("X-NovaOps-Approval-Token", token)
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info(f"Rejection response: {resp.status}")
    except urllib.error.URLError as e:
        logger.error(f"Rejection callback failed: {e}")
    except Exception as e:
        logger.error(f"Rejection callback error: {e}")


def _load_messages(session_attrs: dict) -> list:
    """Load conversation history from Lex session attributes."""
    raw = session_attrs.get("conversation_history", "")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse conversation history, starting fresh")
        return []


def _save_messages(session_attrs: dict, messages: list):
    """Save conversation history to Lex session attributes.

    Lex session attributes have a size limit (~12KB), so we keep
    only the last 6 turns to stay within bounds.
    """
    # Keep last 6 message pairs (12 messages) to stay under session limit
    trimmed = messages[-12:] if len(messages) > 12 else messages
    session_attrs["conversation_history"] = json.dumps(trimmed)


def _resolve_callback_url(session_value: str) -> str:
    """Avoid SSRF by only allowing the session callback URL when it matches our configured base."""
    if not session_value:
        return CALLBACK_URL

    try:
        expected = urllib.parse.urlparse(CALLBACK_URL)
        provided = urllib.parse.urlparse(session_value)
        if provided.scheme in {"http", "https"} and provided.netloc == expected.netloc:
            return session_value.rstrip("/")
    except Exception:
        pass

    logger.warning("Ignoring unexpected callback_url from session attributes")
    return CALLBACK_URL.rstrip("/")


def _build_response(
    session_attrs: dict,
    intent_name: str,
    message_text: str,
    close: bool = False,
) -> dict:
    """Build a Lex V2 fulfillment response.

    Args:
        session_attrs: Updated session attributes.
        intent_name: The Lex intent name.
        message_text: Text for Polly to speak to the caller.
        close: If True, fulfills the intent and ends the conversation.
              If False, elicits another turn via the same intent.
    """
    if close:
        return {
            "sessionState": {
                "sessionAttributes": session_attrs,
                "dialogAction": {"type": "Close"},
                "intent": {"name": intent_name, "state": "Fulfilled"},
            },
            "messages": [
                {"contentType": "PlainText", "content": message_text}
            ],
        }

    return {
        "sessionState": {
            "sessionAttributes": session_attrs,
            "dialogAction": {
                "type": "ElicitIntent",
            },
            "intent": {"name": intent_name, "state": "InProgress"},
        },
        "messages": [
            {"contentType": "PlainText", "content": message_text}
        ],
    }
