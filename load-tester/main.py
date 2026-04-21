import os
import time
import random
import requests
import logging
import uuid
from itertools import cycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def env_url(name, default):
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


SERVICE_URLS = {
    "frontend": env_url("FRONTEND_URL", "http://frontend:8080"),
    "product-catalog": env_url("PRODUCT_CATALOG_URL", "http://product-catalog:8080"),
    "cart": env_url("CART_URL", "http://cart:8080"),
    "checkout": env_url("CHECKOUT_URL", "http://checkout:8080"),
    "quote": env_url("QUOTE_URL", "http://quote:8080"),
    "payment": env_url("PAYMENT_URL", "http://payment:8080"),
    "shipping": env_url("SHIPPING_URL", "http://shipping:8080"),
    "email": env_url("EMAIL_URL", "http://email:8080"),
    "ad-service": env_url("AD_SERVICE_URL", "http://ad-service:8080"),
}

# Realistic workflows: sequences that trigger complex internal calls
WORKFLOWS = [
    # Workflow 1: Browse -> Add to Cart -> Checkout (full e-commerce flow)
    [
        {"service": "frontend", "method": "GET", "endpoint": "/products", "name": "Browse"},
        {"service": "cart", "method": "POST", "endpoint": "/cart/add", "json": {"userId": "user-100", "productId": "sku-1001", "quantity": 1}, "name": "AddCart"},
        {"service": "frontend", "method": "POST", "endpoint": "/checkout", "json": {"userId": "user-100", "paymentMethod": "card", "email": "buyer@example.com"}, "name": "Checkout"},
    ],
    # Workflow 2: Browse catalog and query discounts
    [
        {"service": "product-catalog", "method": "GET", "endpoint": "/products", "name": "CatalogBrowse"},
        {"service": "ad-service", "method": "GET", "endpoint": "/discounts?userId=user-200", "name": "GetDiscounts"},
    ],
    # Workflow 3: Quote calculation with dependencies
    [
        {"service": "quote", "method": "POST", "endpoint": "/quote", "json": {"userId": "user-300", "items": [{"productId": "sku-1002", "quantity": 2}]}, "name": "GetQuote"},
    ],
    # Workflow 4: Payment + Shipping sequence
    [
        {"service": "payment", "method": "POST", "endpoint": "/payment/charge", "json": {"amount": 299.0}, "name": "Payment"},
        {"service": "shipping", "method": "POST", "endpoint": "/shipping/create", "json": {"orderId": "ord-test-wf4"}, "name": "Shipping"},
    ],
    # Workflow 5: Multi-user cart operations
    [
        {"service": "cart", "method": "POST", "endpoint": "/cart/add", "json": {"userId": "user-400", "productId": "sku-1003", "quantity": 1}, "name": "User400Cart"},
        {"service": "cart", "method": "GET", "endpoint": "/cart/user-400", "name": "FetchCart"},
    ],
]

# Common health/diagnostics endpoints run by all services
HEALTH_CHECK_ENDPOINTS = [
    {"service": "frontend", "endpoint": "/health", "method": "GET"},
    {"service": "product-catalog", "endpoint": "/ready", "method": "GET"},
    {"service": "cart", "endpoint": "/health", "method": "GET"},
    {"service": "checkout", "endpoint": "/ready", "method": "GET"},
    {"service": "quote", "endpoint": "/health", "method": "GET"},
    {"service": "payment", "endpoint": "/dependencies/health", "method": "GET"},
    {"service": "shipping", "endpoint": "/dependencies/health", "method": "GET"},
    {"service": "email", "endpoint": "/health", "method": "GET"},
    {"service": "ad-service", "endpoint": "/ready", "method": "GET"},
]

# Fault injection endpoints for chaos/resilience testing
FAULT_ENDPOINTS = [
    {"service": "frontend", "endpoint": "/warn", "method": "GET", "weight": 0.02},
    {"service": "checkout", "endpoint": "/error", "method": "GET", "weight": 0.01},
    {"service": "payment", "endpoint": "/warn", "method": "GET", "weight": 0.02},
    {"service": "shipping", "endpoint": "/simulate-cpu", "method": "GET", "weight": 0.01},
    {"service": "ad-service", "endpoint": "/delay/1", "method": "GET", "weight": 0.01},
]

# Mesh fanout: all services call all other services
MESH_ENDPOINTS = [
    {"service": s, "endpoint": "/mesh/ping-all", "method": "POST"}
    for s in SERVICE_URLS.keys()
]

def run_load():
    """Run continuous realistic workflows with mixed traffic patterns."""
    call_count = 0
    workflow_cycle = cycle(WORKFLOWS)
    health_cycle = cycle(HEALTH_CHECK_ENDPOINTS)
    fault_cycle = cycle(FAULT_ENDPOINTS)
    mesh_cycle = cycle(MESH_ENDPOINTS)

    # Distribute traffic: 70% workflows, 20% health, 10% mesh.
    # Fault endpoints (/error, /warn, /simulate-cpu, /delay) are removed from
    # the steady-state mix so the demo is clean by default — errors only come
    # from the chaos-runner Job, which flips failure knobs per scenario.
    # Set LOAD_TESTER_INCLUDE_FAULTS=true to bring them back for ad-hoc chaos.
    include_faults = os.getenv("LOAD_TESTER_INCLUDE_FAULTS", "false").lower() == "true"
    if include_faults:
        distribution = (
            ["workflow"] * 12 +
            ["health"] * 4 +
            ["fault"] * 2 +
            ["mesh"] * 2
        )
    else:
        distribution = (
            ["workflow"] * 14 +
            ["health"] * 4 +
            ["mesh"] * 2
        )
    distribution_cycle = cycle(distribution)

    while True:
        traffic_type = next(distribution_cycle)
        
        if traffic_type == "workflow":
            # Execute a complete workflow (sequence of calls)
            workflow = next(workflow_cycle)
            workflow_name = "_".join([step.get("name", step["endpoint"]) for step in workflow])
            request_id = f"lg-wf-{workflow_name}-{uuid.uuid4().hex[:8]}"

            for i, step in enumerate(workflow):
                service = step["service"]
                base_url = SERVICE_URLS.get(service, "")
                method = step.get("method", "GET")
                endpoint = step["endpoint"]
                url = f"{base_url}{endpoint}"
                payload = step.get("json")

                try:
                    resp = requests.request(
                        method=method,
                        url=url,
                        headers={"x-request-id": request_id},
                        json=payload,
                        timeout=20,
                    )
                    call_count += 1
                    status_level = "info" if 200 <= resp.status_code < 300 else "warning" if 400 <= resp.status_code < 500 else "error"
                    step_id = f"[{call_count}] {step.get('name', 'step-' + str(i))}"
                    
                    if status_level == "error":
                        logging.error(f"{step_id} | {method} {url} -> {resp.status_code} | {request_id}")
                    elif status_level == "warning":
                        logging.warning(f"{step_id} | {method} {url} -> {resp.status_code} | {request_id}")
                    else:
                        logging.info(f"{step_id} | {method} {url} -> {resp.status_code} | {request_id}")

                except Exception as e:
                    call_count += 1
                    logging.error(f"[{call_count}] Workflow error: {e} | {request_id}")

                time.sleep(random.uniform(0.05, 0.15))  # Stagger steps within workflow

        elif traffic_type == "health":
            # Health check from a random service
            check = next(health_cycle)
            base_url = SERVICE_URLS.get(check["service"], "")
            url = f"{base_url}{check['endpoint']}"
            request_id = f"lg-health-{uuid.uuid4().hex[:8]}"

            try:
                resp = requests.request(
                    method=check.get("method", "GET"),
                    url=url,
                    headers={"x-request-id": request_id},
                    timeout=10,
                )
                call_count += 1
                if resp.status_code == 200:
                    logging.info(f"[{call_count}] HEALTH {check['service']} -> {resp.status_code}")
                else:
                    logging.warning(f"[{call_count}] HEALTH {check['service']} -> {resp.status_code}")
            except Exception as e:
                call_count += 1
                logging.error(f"[{call_count}] HEALTH {check['service']} failed: {e}")

        elif traffic_type == "fault":
            # Inject fault/chaos for observability
            if random.random() < 0.5:  # 50% of fault slots trigger
                fault = next(fault_cycle)
                base_url = SERVICE_URLS.get(fault["service"], "")
                url = f"{base_url}{fault['endpoint']}"
                request_id = f"lg-fault-{uuid.uuid4().hex[:8]}"

                try:
                    resp = requests.request(
                        method=fault.get("method", "GET"),
                        url=url,
                        headers={"x-request-id": request_id},
                        timeout=15,
                    )
                    call_count += 1
                    logging.warning(f"[{call_count}] FAULT {fault['service']}{fault['endpoint']} -> {resp.status_code} (injected)")
                except Exception as e:
                    call_count += 1
                    logging.warning(f"[{call_count}] FAULT {fault['service']}{fault['endpoint']} failed: {e} (injected)")

        elif traffic_type == "mesh":
            # Mesh fanout: service calls all other services
            mesh = next(mesh_cycle)
            base_url = SERVICE_URLS.get(mesh["service"], "")
            url = f"{base_url}{mesh['endpoint']}"
            request_id = f"lg-mesh-{mesh['service']}-{uuid.uuid4().hex[:8]}"

            try:
                resp = requests.request(
                    method=mesh.get("method", "GET"),
                    url=url,
                    headers={"x-request-id": request_id},
                    json={},
                    timeout=30,
                )
                call_count += 1
                if resp.status_code == 200:
                    result = resp.json()
                    fanout_count = result.get("fanout_calls", 0)
                    logging.info(f"[{call_count}] MESH {mesh['service']} fanout={fanout_count} -> {resp.status_code}")
                else:
                    logging.warning(f"[{call_count}] MESH {mesh['service']} -> {resp.status_code}")
            except Exception as e:
                call_count += 1
                logging.error(f"[{call_count}] MESH {mesh['service']} failed: {e}")

        # Adaptive delay: keep traffic bursty but sustainable
        time.sleep(random.uniform(0.1, 0.35))

if __name__ == "__main__":
    logging.info("Starting production-ready load generator with realistic workflows")
    logging.info(f"Workflows: {len(WORKFLOWS)} | Health checks: {len(HEALTH_CHECK_ENDPOINTS)} | Fault injection: {len(FAULT_ENDPOINTS)} | Mesh fanout: {len(MESH_ENDPOINTS)}")
    run_load()
