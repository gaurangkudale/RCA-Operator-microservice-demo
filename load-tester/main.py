import os
import time
import random
import requests
import logging
import uuid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
FRONTEND_URL = os.getenv("FRONTEND_URL", os.getenv("TARGET_URL", "http://frontend:8080"))

SERVICE_URLS = {
    "frontend": FRONTEND_URL,
    "cart": os.getenv("CART_URL", "http://cart:8080"),
    "checkout": os.getenv("CHECKOUT_URL", "http://checkout:8080"),
    "payment": os.getenv("PAYMENT_URL", "http://payment:8080"),
    "shipping": os.getenv("SHIPPING_URL", "http://shipping:8080"),
    "email": os.getenv("EMAIL_URL", "http://email:8080"),
    "catalog": os.getenv("CATALOG_URL", "http://product-catalog:8080"),
    "quote": os.getenv("QUOTE_URL", "http://quote:8080"),
    "ad": os.getenv("AD_URL", "http://ad-service:8080"),
}

SCENARIOS = [
    {"service": "frontend", "method": "GET", "endpoint": "/products", "weight": 0.18},
    {"service": "frontend", "method": "POST", "endpoint": "/cart/add", "weight": 0.16, "json": {"userId": "user-100", "productId": "sku-1002", "quantity": 1}},
    {"service": "frontend", "method": "POST", "endpoint": "/checkout", "weight": 0.12, "json": {"userId": "user-100", "paymentMethod": "card", "email": "buyer@example.com"}},
    {"service": "catalog", "method": "GET", "endpoint": "/products", "weight": 0.07},
    {"service": "catalog", "method": "GET", "endpoint": "/products/sku-1001", "weight": 0.05},
    {"service": "cart", "method": "GET", "endpoint": "/cart/user-100", "weight": 0.06},
    {"service": "quote", "method": "POST", "endpoint": "/quote", "weight": 0.06, "json": {"userId": "user-100", "items": [{"productId": "sku-1002", "quantity": 1}] }},
    {"service": "payment", "method": "POST", "endpoint": "/payment/charge", "weight": 0.05, "json": {"amount": 149.0}},
    {"service": "shipping", "method": "POST", "endpoint": "/shipping/create", "weight": 0.05, "json": {"orderId": "ord-test-100"}},
    {"service": "email", "method": "POST", "endpoint": "/email/send", "weight": 0.03, "json": {"to": "buyer@example.com", "template": "order_confirmation"}},
    {"service": "ad", "method": "GET", "endpoint": "/discounts?userId=user-100", "weight": 0.03},
    {"service": "frontend", "method": "GET", "endpoint": "/warn", "weight": 0.04},
    {"service": "checkout", "method": "GET", "endpoint": "/error", "weight": 0.03},
    {"service": "payment", "method": "GET", "endpoint": "/simulate-cpu", "weight": 0.03},
    {"service": "shipping", "method": "GET", "endpoint": "/delay/2", "weight": 0.03},
    {"service": "frontend", "method": "GET", "endpoint": "/health", "weight": 0.02},
    {"service": "frontend", "method": "GET", "endpoint": "/ready", "weight": 0.02},
]

def pick_scenario():
    """Weighted random scenario selection."""
    rand = random.random()
    cumulative = 0
    for scenario in SCENARIOS:
        cumulative += scenario["weight"]
        if rand < cumulative:
            return scenario
    return SCENARIOS[0]

def run_load():
    """Run continuous load test with random endpoint selection."""
    call_count = 0
    while True:
        scenario = pick_scenario()
        base_url = SERVICE_URLS[scenario["service"]]
        url = f"{base_url}{scenario['endpoint']}"
        method = scenario.get("method", "GET")
        request_id = f"lg-{uuid.uuid4().hex[:12]}"
        headers = {"x-request-id": request_id}

        try:
            resp = requests.request(method=method, url=url, headers=headers, json=scenario.get("json"), timeout=20)
            call_count += 1
            if call_count % 10 == 0:
                logging.info(
                    f"[{call_count}] {method} {url} status={resp.status_code} request_id={request_id}"
                )
            else:
                logging.debug(f"{method} {url} status={resp.status_code} request_id={request_id}")
        except requests.Timeout:
            logging.warning(f"Timeout calling {method} {url}")
        except Exception as e:
            logging.error(f"Failed to call {method} {url}: {e}")
        
        # Random delay between requests
        time.sleep(random.uniform(0.3, 1.5))

if __name__ == "__main__":
    logging.info(f"Starting load generator with frontend target {FRONTEND_URL}")
    logging.info(f"Loaded {len(SCENARIOS)} realistic e-commerce scenarios")
    run_load()
