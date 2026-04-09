import os
import time
import random
import requests
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
TARGET_URL = os.getenv("TARGET_URL", "http://proxy-service:8080")

endpoints = [
    ("/health", 0.2),       # 20% chance
    ("/process", 0.2),      # 20% chance
    ("/warn", 0.08),        # 8% chance
    ("/error", 0.5),        # 50% chance (increased for error testing)
    ("/simulate-oom", 0.01),# 1% chance
    ("/simulate-cpu", 0.01),# 1% chance
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
            resp = requests.get(url, timeout=10)
            logging.info(f"Called {url} - Status: {resp.status_code}")
        except Exception as e:
            logging.error(f"Failed to call {url}: {e}")
        time.sleep(random.uniform(0.5, 2.0))

if __name__ == "__main__":
    logging.info(f"Starting load tester targeting {TARGET_URL}")
    run_load()
