import os
import time
import random
import requests
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
TARGET_URL = os.getenv("TARGET_URL", "http://proxy-service:8080")

# Production microservice endpoints with realistic distribution
endpoints = [
    # Health & Status endpoints (15% combined)
    ("/health", 0.08),
    ("/ready", 0.07),
    
    # CRUD operations (25% combined)
    ("/list", 0.06),
    ("/create", 0.06),
    ("/search", 0.06),
    ("/get/resource-1", 0.04),
    ("/update/resource-1", 0.03),
    
    # Multi-service orchestration (20% combined)
    ("/process", 0.05),
    ("/validate", 0.05),
    ("/verify", 0.05),
    ("/check", 0.05),
    
    # Data operations (15% combined)
    ("/fetch-data", 0.06),
    ("/metrics", 0.05),
    ("/sync", 0.04),
    
    # Status & Operation tracking (10% combined)
    ("/status/op-1", 0.05),
    ("/status/op-2", 0.05),
    
    # Error scenarios (10% combined)
    ("/error", 0.04),
    ("/warn", 0.04),
    ("/simulate-cpu", 0.015),
    ("/simulate-oom", 0.005),
    
    # Latency simulation (5% combined)
    ("/delay/1", 0.03),
    ("/delay/2", 0.02),
]

def get_random_endpoint():
    """Weighted random endpoint selection."""
    rand = random.random()
    cumulative = 0
    for ep, prob in endpoints:
        cumulative += prob
        if rand < cumulative:
            return ep
    return "/health"

def run_load():
    """Run continuous load test with random endpoint selection."""
    call_count = 0
    while True:
        endpoint = get_random_endpoint()
        url = f"{TARGET_URL}{endpoint}"
        try:
            resp = requests.get(url, timeout=20)
            call_count += 1
            if call_count % 10 == 0:
                logging.info(f"[{call_count}] Called {url} - Status: {resp.status_code}")
            else:
                logging.debug(f"Called {url} - Status: {resp.status_code}")
        except requests.Timeout:
            logging.warning(f"Timeout calling {url}")
        except Exception as e:
            logging.error(f"Failed to call {url}: {e}")
        
        # Random delay between requests
        time.sleep(random.uniform(0.3, 1.5))

if __name__ == "__main__":
    logging.info(f"Starting load tester targeting {TARGET_URL}")
    logging.info(f"Testing {len(endpoints)} endpoints with realistic distribution")
    logging.info(f"Endpoints: {[ep for ep, _ in endpoints]}")
    run_load()
