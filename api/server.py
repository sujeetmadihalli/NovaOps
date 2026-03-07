import logging
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict

from agent.orchestrator import AgentOrchestrator
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

# Setup components (using MOCK for safe local testing)
agent = AgentOrchestrator(mock_sensors=True)
notifier = SlackNotifier(use_mock=True)
db = IncidentHistoryDB()

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

@app.get("/health")
def health_check():
    return {"status": "healthy"}
