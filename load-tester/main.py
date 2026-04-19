import os
import time
import random
import requests
import logging
import uuid
from itertools import cycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
FRONTEND_URL = os.getenv("FRONTEND_URL", os.getenv("TARGET_URL", "http://frontend:8080"))


def env_url(name, default):
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


SERVICE_URLS = {
    "frontend": env_url("FRONTEND_URL", FRONTEND_URL),
    "product-catalog": env_url("PRODUCT_CATALOG_URL", os.getenv("CATALOG_URL", "http://product-catalog:8080")),
    "cart": env_url("CART_URL", "http://cart:8080"),
    "checkout": env_url("CHECKOUT_URL", "http://checkout:8080"),
    "quote": env_url("QUOTE_URL", "http://quote:8080"),
    "payment": env_url("PAYMENT_URL", "http://payment:8080"),
    "shipping": env_url("SHIPPING_URL", "http://shipping:8080"),
    "email": env_url("EMAIL_URL", "http://email:8080"),
    "ad-service": env_url("AD_SERVICE_URL", os.getenv("AD_URL", "http://ad-service:8080")),
}

COMMON_ENDPOINTS = [
    {"method": "GET", "endpoint": "/health"},
    {"method": "GET", "endpoint": "/ready"},
    {"method": "GET", "endpoint": "/warn"},
    {"method": "GET", "endpoint": "/error"},
    {"method": "GET", "endpoint": "/simulate-cpu"},
    {"method": "GET", "endpoint": "/delay/1"},
]

SERVICE_SPECIFIC = {
    "frontend": [
        {"method": "GET", "endpoint": "/products"},
        {
            "method": "POST",
            "endpoint": "/cart/add",
            "json": {"userId": "user-100", "productId": "sku-1002", "quantity": 1},
        },
        {
            "method": "POST",
            "endpoint": "/checkout",
            "json": {"userId": "user-100", "paymentMethod": "card", "email": "buyer@example.com"},
        },
    ],
    "product-catalog": [
        {"method": "GET", "endpoint": "/products"},
        {"method": "GET", "endpoint": "/products/sku-1001"},
    ],
    "cart": [
        {
            "method": "POST",
            "endpoint": "/cart/add",
            "json": {"userId": "user-100", "productId": "sku-1001", "quantity": 1},
        },
        {"method": "GET", "endpoint": "/cart/user-100"},
    ],
    "checkout": [
        {
            "method": "POST",
            "endpoint": "/checkout",
            "json": {"userId": "user-100", "paymentMethod": "card", "email": "buyer@example.com"},
        }
    ],
    "quote": [
        {
            "method": "POST",
            "endpoint": "/quote",
            "json": {"userId": "user-100", "items": [{"productId": "sku-1002", "quantity": 1}]},
        }
    ],
    "payment": [
        {"method": "POST", "endpoint": "/payment/charge", "json": {"amount": 149.0}},
        {"method": "POST", "endpoint": "/payment/refund", "json": {"paymentId": "pay-missing"}},
    ],
    "shipping": [
        {"method": "POST", "endpoint": "/shipping/create", "json": {"orderId": "ord-test-100"}},
        {"method": "GET", "endpoint": "/shipping/ord-test-100"},
    ],
    "email": [
        {
            "method": "POST",
            "endpoint": "/email/send",
            "json": {"to": "buyer@example.com", "template": "order_confirmation"},
        }
    ],
    "ad-service": [
        {"method": "GET", "endpoint": "/discounts?userId=user-100"},
    ],
}


def build_scenarios():
    scenarios = []
    for service in SERVICE_URLS.keys():
        for item in COMMON_ENDPOINTS:
            scenarios.append({"service": service, "method": item["method"], "endpoint": item["endpoint"]})

        for item in SERVICE_SPECIFIC.get(service, []):
            scenario = {"service": service, "method": item["method"], "endpoint": item["endpoint"]}
            if "json" in item:
                scenario["json"] = item["json"]
            scenarios.append(scenario)

        # Triggers all-to-all calls from each service to every other service.
        scenarios.append({"service": service, "method": "POST", "endpoint": "/mesh/ping-all"})

    return scenarios


SCENARIOS = build_scenarios()

def run_load():
    """Run continuous all-services endpoint sweeps."""
    call_count = 0
    scenario_stream = cycle(SCENARIOS)

    while True:
        scenario = next(scenario_stream)
        base_url = SERVICE_URLS[scenario["service"]]
        url = f"{base_url}{scenario['endpoint']}"
        method = scenario.get("method", "GET")
        request_id = f"lg-{uuid.uuid4().hex[:12]}"
        headers = {"x-request-id": request_id}

        try:
            resp = requests.request(method=method, url=url, headers=headers, json=scenario.get("json"), timeout=20)
            call_count += 1
            if resp.status_code >= 500:
                logging.error(f"[{call_count}] {method} {url} status={resp.status_code} request_id={request_id}")
            elif resp.status_code >= 400:
                logging.warning(f"[{call_count}] {method} {url} status={resp.status_code} request_id={request_id}")
            else:
                logging.info(f"[{call_count}] {method} {url} status={resp.status_code} request_id={request_id}")
        except requests.Timeout:
            logging.warning(f"Timeout calling {method} {url}")
        except Exception as e:
            logging.error(f"Failed to call {method} {url}: {e}")
        
        # Keep traffic bursty but bounded to avoid overloading the cluster.
        time.sleep(random.uniform(0.15, 0.45))

if __name__ == "__main__":
    logging.info(f"Starting load generator with frontend target {FRONTEND_URL}")
    logging.info(f"Loaded {len(SCENARIOS)} all-services endpoint scenarios")
    run_load()
