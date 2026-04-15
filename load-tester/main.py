import os
import time
import random
import requests
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
TARGET_URL = os.getenv("TARGET_URL", "http://proxy-service:8080")

# Original endpoints + new multi-service endpoints
endpoints = [
    ("/health", 0.15),          # 15% chance
    ("/process", 0.15),         # 15% chance (original chain)
    ("/validate", 0.15),        # 15% chance (new multi-service)
    ("/fetch-data", 0.15),      # 15% chance (new multi-service)
    ("/verify", 0.15),          # 15% chance (new multi-service)
    ("/check", 0.15),           # 15% chance (new multi-service)
    ("/warn", 0.05),            # 5% chance
    ("/error", 0.05),           # 5% chance
    ("/simulate-oom", 0.005),   # 0.5% chance
    ("/simulate-cpu", 0.005),   # 0.5% chance
]

def get_random_endpoint():
    rand = random.random()
    cumulative = 0
    for ep, prob in endpoints:
        cumulative += prob
        if rand < cumulative:
            return ep
    return "/health"

def run_load():
    while True:
        endpoint = get_random_endpoint()
        url = f"{TARGET_URL}{endpoint}"
        try:
            resp = requests.get(url, timeout=15)
            logging.info(f"Called {url} - Status: {resp.status_code}")
        except Exception as e:
            logging.error(f"Failed to call {url}: {e}")
        time.sleep(random.uniform(0.5, 2.0))

if __name__ == "__main__":
    logging.info(f"Starting load tester targeting {TARGET_URL}")
    logging.info(f"Testing endpoints: {[ep for ep, _ in endpoints]}")
    run_load()
