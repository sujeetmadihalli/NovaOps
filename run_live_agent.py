import os
import subprocess
from dotenv import load_dotenv

# Load real AWS credentials for Bedrock to use, but keep DYNAMO and S3 pointing to LocalStack
load_dotenv()
os.environ["DYNAMODB_ENDPOINT"] = "http://localhost:4566"
os.environ["S3_ENDPOINT"] = "http://localhost:4566"
os.environ["NOVAOPS_USE_MOCK"] = "0"

from agents.main import run
from tools.executor import RemediationExecutor
from tools.k8s_actions import KubernetesActions

def main():
    print("="*60)
    print("🚀 Triggering Live NovaOps Incident Agent")
    print("="*60)
    
    # K8s Actions with use_mock=False will use the local ~/.kube/config created by Minikube
    executor = RemediationExecutor(KubernetesActions(use_mock=False))
    
    # We trigger the exact alert that should match dummy-service-oom.md in TF-IDF
    alert = "OOM detected on dummy-service"
    metadata = {
        "service_name": "dummy-service",
        "namespace": "default",
        "alert_name": "dummy-service OOM"
    }

    # Run the entire War Room + Jury + Governance pipeline live against Minikube and Bedrock!
    result = run(alert, executor=executor, metadata=metadata)
    
    print(f"\n✅ Live Incident Output saved in simulated DynamoDB under ID: {result['incident_id']}")
    print("Check out the Dashboard UI to see the decision and execution trace!")
    print("\n📞 Initiating Sonic Voice Call for SRE Approval...")
    
    # Launch Sonic call automatically
    try:
        subprocess.run(["python3", "sonic_call.py", result["incident_id"]])
    except Exception as e:
        print(f"Failed to trigger sonic call: {e}")

if __name__ == "__main__":
    main()
