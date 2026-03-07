import logging
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict

from agent.orchestrator import AgentOrchestrator
from agent.pir_generator import PIRGenerator
from api.slack_notifier import SlackNotifier
from api.history_db import IncidentHistoryDB

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Autonomous Incident Agent Webhook API")

# Allow local dashboard to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup components for Production (Live K8s & Nova LLM)
agent = AgentOrchestrator(mock_sensors=False)
notifier = SlackNotifier(use_mock=False)
db = IncidentHistoryDB()
pir_gen = PIRGenerator()

class AlertPayload(BaseModel):
    alert_name: str
    service_name: str
    namespace: str = "default"
    incident_id: str
    description: str

def trigger_agent_loop(payload: AlertPayload):
    """
    Background Task to run the ReAct Loop asynchronously 
    so the PagerDuty webhook doesn't timeout.
    """
    logger.info(f"==== Starting Incident Resolution for {payload.incident_id} ====")
    
    try:
        result = agent.run_incident_resolution(
            alert_name=payload.alert_name,
            service_name=payload.service_name,
            namespace=payload.namespace
        )
        
        if result.get("status") == "plan_ready":
            # Log the incident to the Dashboard Database
            db.log_incident(
                incident_id=payload.incident_id,
                service_name=payload.service_name,
                alert_name=payload.alert_name,
                analysis=result.get("analysis"),
                proposed_action=result.get("proposed_action")
            )
            
            # Hand off to Ghost Mode Slack to get human approval
            notifier.send_incident_plan(
                incident_id=payload.incident_id,
                analysis=result.get("analysis"),
                proposed_action=result.get("proposed_action")
            )
        else:
            logger.error(f"Agent failed to formulate a plan: {result.get('reason')}")
            
    except Exception as e:
        logger.critical(f"FATAL: Agent Orchestrator crashed entirely. Reason: {str(e)}")
        # DEAD MAN'S SNITCH: AI is offline. Page humans.
        notifier.send_incident_plan(
            incident_id=payload.incident_id,
            analysis=f"⚠️ CRITICAL INFRASTRUCTURE ALERT ⚠️\nThe Autonomous AI Agent has suffered a fatal crash or the Amazon Nova LLM API is unreachable.\n\nException: {str(e)}\n\nThe self-healing pipeline is OFFLINE. Human SRE intervention is required immediately.",
            proposed_action={"tool": "noop_require_human", "parameters": {}}
        )
        
@app.get("/api/incidents")
def get_incident_history():
    """
    Returns the recent history of all AI handled incidents for the Web Dashboard.
    """
    history = db.get_recent_incidents(limit=50)
    return {"status": "success", "count": len(history), "data": history}
        
@app.post("/webhook/pagerduty")
async def pagerduty_webhook(payload: AlertPayload, background_tasks: BackgroundTasks):
    """
    Webhook receiver for OpsGenie/PagerDuty alerts.
    """
    logger.info(f"Received webhook for {payload.service_name}")
    # Add agent execution to background queue
    background_tasks.add_task(trigger_agent_loop, payload)
    
    return {"status": "accepted", "message": "Incident assigned to Agent"}

@app.post("/api/incidents/{incident_id}/report")
def generate_pir(incident_id: str):
    """
    Generates a Post-Incident Report (PIR) for a given incident using Amazon Nova.
    """
    incident = db.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    report = pir_gen.generate(incident)
    db.save_pir(incident_id, report)
    return {"status": "success", "incident_id": incident_id, "report": report}


@app.get("/api/incidents/{incident_id}/report")
def get_pir(incident_id: str):
    """
    Returns an existing PIR for a given incident.
    """
    incident = db.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    if not incident.get("pir_report"):
        raise HTTPException(status_code=404, detail="No PIR has been generated for this incident yet")
    return {"status": "success", "incident_id": incident_id, "report": incident["pir_report"]}


@app.get("/health")
def health_check():
    return {"status": "healthy"}
