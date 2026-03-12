import time
import os
import psutil
from fastapi import FastAPI
from prometheus_client import make_asgi_app, Counter, Gauge
import uvicorn

app = FastAPI()

# Prometheus Metrics
# Create an ASGI app for Prometheus metrics scraping
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Custom Metrics
MEMORY_USAGE = Gauge('dummy_service_memory_bytes', 'Curent memory usage in bytes')
REQUEST_COUNT = Counter('dummy_service_requests_total', 'Total HTTP Requests', ['endpoint'])

# A list to hold garbage memory
memory_hog = []

def update_memory_metric():
    process = psutil.Process(os.getpid())
    MEMORY_USAGE.set(process.memory_info().rss)

@app.get("/")
def read_root():
    REQUEST_COUNT.labels(endpoint='/').inc()
    update_memory_metric()
    return {"status": "ok", "message": "Dummy Service is running normally."}

@app.get("/memory-leak")
def trigger_leak():
    """
    Intentionally consumes ~50MB of RAM every time it is called.
    We will use this to trigger the Prometheus OOM alert during the live Hackathon demo.
    """
    REQUEST_COUNT.labels(endpoint='/memory-leak').inc()
    
    # Append 50MB of garbage string to the list
    memory_hog.append("A" * 50 * 1024 * 1024) 
    
    update_memory_metric()
    return {"status": "leaking", "message": f"Consumed 50MB. Total hogs: {len(memory_hog)}"}

@app.get("/clear")
def clear_leak():
    """Rescue endpoint just in case."""
    global memory_hog
    memory_hog = []
    update_memory_metric()
    return {"status": "cleared"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
