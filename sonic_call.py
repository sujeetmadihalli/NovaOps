#!/usr/bin/env python3
import os
import sys
import json
import requests
import boto3
import io

try:
    import numpy as np
    import soundfile as sf
    import sounddevice as sd
except ImportError:
    print("❌ ERROR: sounddevice or soundfile missing. Run: pip install sounddevice numpy soundfile")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configuration
API_URL = "http://localhost:8082"
SONIC_MODEL_ID = os.environ.get("NOVA_MODEL_ID", "us.amazon.nova-2-lite-v1:0")

# Audio Config
SAMPLE_RATE = 16000
CHANNELS = 1

def record_audio(duration: int = 5) -> bytes:
    """Record audio from the microphone for the given duration."""
    print(f"\n🎙️  Listening for {duration} seconds... Speak now!")
    # Record at 16kHz, mono
    try:
        recording = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16')
        sd.wait()
        print("✅ Recording complete.")
        
        # Convert numpy array to WAV bytes memory buffer
        with io.BytesIO() as io_buffer:
            sf.write(io_buffer, recording, SAMPLE_RATE, format='WAV', subtype='PCM_16')
            return io_buffer.getvalue()
    except Exception as e:
        print(f"⚠️ Microphone access failed ({e}). Falling back to text mode.")
        return None

def play_audio(audio_bytes: bytes):
    """Play a WAV audio bytestream through the speakers."""
    with io.BytesIO(audio_bytes) as io_buffer:
        data, fs = sf.read(io_buffer)
        sd.play(data, fs)
        sd.wait()

def load_incident(incident_id: str):
    """Fetch the incident details from the backend."""
    try:
        resc = requests.get(f"{API_URL}/api/incidents/{incident_id}", timeout=10)
        if resc.status_code != 200:
            return None
        return resc.json().get("data")
    except Exception as e:
        print(f"Error fetching incident: {e}")
    return None

def trigger_approval(incident_id: str):
    """Hits the NovaOps API to approve the incident."""
    try:
        print("\n[System] Sending approval to NovaOps API...")
        headers = {}
        token = os.environ.get("NOVAOPS_APPROVAL_TOKEN", "").strip()
        if token:
            headers["X-NovaOps-Approval-Token"] = token
        resc = requests.post(
            f"{API_URL}/api/incidents/{incident_id}/approve",
            headers=headers,
            timeout=10,
        )
        if resc.status_code == 200:
            print(f"[System] Successfully approved incident {incident_id}!")
            return True
        else:
            print(f"[System] Approval failed: {resc.text}")
    except Exception as e:
        print(f"[System] Error sending approval: {e}")
    return False


def trigger_rejection(incident_id: str):
    """Hits the NovaOps API to reject (deny) the incident."""
    try:
        print("\n[System] Sending rejection to NovaOps API...")
        headers = {}
        token = os.environ.get("NOVAOPS_APPROVAL_TOKEN", "").strip()
        if token:
            headers["X-NovaOps-Approval-Token"] = token
        resc = requests.post(
            f"{API_URL}/api/incidents/{incident_id}/reject",
            headers=headers,
            timeout=10,
        )
        if resc.status_code == 200:
            print(f"[System] Successfully rejected incident {incident_id}.")
            return True
        else:
            print(f"[System] Rejection failed: {resc.text}")
    except Exception as e:
        print(f"[System] Error sending rejection: {e}")
    return False

def simulated_voice_call(incident_id: str):
    incident = load_incident(incident_id)
    if not incident:
        print(f"❌ Cannot find incident {incident_id} in the database. Start the system and trigger an alert first.")
        return

    service = incident.get("service_name", "unknown service")
    alert = incident.get("alert_name", "unknown alert")
    
    print("=" * 60)
    print(f"📞 INCOMING CALL FROM: NovaOps Automated SRE (Nova Sonic)")
    print(f"   Regarding Incident: {incident_id}")
    print("=" * 60)
    
    system_prompt = f"""You are Amazon Nova Sonic, an AI voice assistant for the NovaOps SRE team.
You are calling the on-call engineer (the user) on the phone.

Incident Details:
- ID: {incident_id}
- Affected Service: {service}
- Alert: {alert}

Your Goal:
1. Explain the incident briefly.
2. Tell them the AI war room has proposed a remediation plan.
3. Ask if they want to approve the automated remediation.

Rules:
- Speak casually and conversationally, like a real phone call. Do not use markdown.
- Be robust: If the user tries to talk about unrelated topics, politely steer the conversation back to the incident and the remediation plan.
- If they ask for details, explain it simply.
- If they explicitly approve or say yes (e.g., "I approve", "go ahead", "yes do it", "sounds good"), you MUST output the exact token: [ACTION_APPROVED]
- If they reject, say no, ask to hang up, or abort (e.g., "no", "reject", "hang up", "stop", "abort"), you MUST output the exact token: [ACTION_REJECTED]
- Keep your responses under 3 sentences so it feels like a real voice conversation.
"""

    messages = []
    
    # We use bedrock runtime to simulate the conversational loop
    bedrock = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

    # Initial greeting
    try:
        response = bedrock.converse(
            modelId=SONIC_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": "Hello? (Start the phone call)"}]}],
            system=[{"text": system_prompt}]
        )
        first_reply = response["output"]["message"]["content"][0]["text"]
        print(f"\n🔊 Nova Sonic: {first_reply}")
        messages.append({"role": "user", "content": [{"text": "Hello? (Start the phone call)"}]})
        messages.append({"role": "assistant", "content": [{"text": first_reply}]})
    except Exception as e:
        print(f"Failed to connect to Bedrock: {e}")
        return

    while True:
        try:
            print("\nPress ENTER when you are ready to speak, or type 'exit' to hang up.")
            cmd = input("> ")
            if cmd.lower() in ['exit', 'quit', 'hang up']:
                print("\n📵 Call disconnected.")
                break

            wav_bytes = record_audio(duration=6)
            
            if wav_bytes is None:
                # Text fallback if audio is not working
                fallback_cmd = input("\n🎙️  You (text fallback): ")
                if not fallback_cmd.strip():
                    fallback_cmd = "(silence)"
                messages.append({"role": "user", "content": [{"text": fallback_cmd}]})
            else:
                # Send the audio stream as an attachment block in Converse API
                messages.append({
                    "role": "user", 
                    "content": [
                        {
                            "document": {
                                "name": "voice_input",
                                "format": "wav",
                                "source": {"bytes": wav_bytes}
                            }
                        }
                    ]
                })

            # For real Nova Sonic, we request that the model replies with an audio clip
            response = bedrock.converse(
                modelId=SONIC_MODEL_ID,
                messages=messages,
                system=[{"text": system_prompt}]
            )
            
            # Since we are using nova-2-lite in the code config fallback, it will return text.
            # If Nova 2 Sonic is active, we can parse the audio.
            content_blocks = response["output"]["message"]["content"]
            reply_text = ""
            
            for block in content_blocks:
                if "text" in block:
                    reply_text += block["text"]
                elif "document" in block:
                    # Parse binary audio returned by Sonic
                    doc_bytes = block["document"]["source"]["bytes"]
                    try:
                        play_audio(doc_bytes)
                    except Exception as e:
                        print(f"⚠️ Audio playback failed ({e}). Attempting to stream text logs instead.")
            
            if "[ACTION_APPROVED]" in reply_text:
                clean_reply = reply_text.replace("[ACTION_APPROVED]", "").strip()
                if clean_reply:
                    print(f"\n🔊 Nova Sonic: {clean_reply}")
                
                print(f"\n🔊 Nova Sonic: Initiating remediation sequence now. Goodbye!")
                trigger_approval(incident_id)
                print("\n📵 Call disconnected.")
                break
            elif "[ACTION_REJECTED]" in reply_text:
                clean_reply = reply_text.replace("[ACTION_REJECTED]", "").strip()
                if clean_reply:
                    print(f"\n🔊 Nova Sonic: {clean_reply}")
                
                print(f"\n🔊 Nova Sonic: Understood, remediation aborted. Goodbye!")
                trigger_rejection(incident_id)
                print("\n📵 Call disconnected.")
                break
            else:
                if reply_text:
                    print(f"\n🔊 Nova Sonic: {reply_text}")
                # We save the model's response back to context
                messages.append({"role": "assistant", "content": content_blocks})
                
        except KeyboardInterrupt:
            print("\n📵 Call disconnected.")
            break
        except Exception as e:
            print(f"\n❌ Audio Stream Interrupted: {e}")
            break

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sonic_call.py <incident_id>")
        sys.exit(1)
        
    incident_id_arg = sys.argv[1]
    simulated_voice_call(incident_id_arg)
