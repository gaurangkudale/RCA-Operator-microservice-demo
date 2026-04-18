from fastapi import FastAPI, HTTPException, Body, Header
import os
import requests
import time
import json
import random
import uuid
from datetime import datetime
from typing import Any, Dict, List
from common.logging_setup import setup_logging


E_COMMERCE_PRODUCTS = [
    {"id": "sku-1001", "name": "Wireless Headphones", "price": 129.0, "category": "electronics", "stock": 52},
    {"id": "sku-1002", "name": "Gaming Mouse", "price": 49.0, "category": "electronics", "stock": 18},
    {"id": "sku-1003", "name": "Coffee Grinder", "price": 89.0, "category": "home", "stock": 7},
    {"id": "sku-1004", "name": "Travel Backpack", "price": 110.0, "category": "outdoor", "stock": 34},
]

def parse_service_urls(env_var_name: str) -> list:
    """Parse comma-separated service URLs from environment variable."""
    urls = os.getenv(env_var_name, "")
    return [url.strip() for url in urls.split(",") if url.strip()]

def call_downstream_service(urls: list, endpoint: str, logger) -> list:
    """Call multiple downstream services and collect responses."""
    responses = []
    for url in urls:
        try:
            logger.info(f"Calling downstream service {url}{endpoint}")
            resp = requests.get(f"{url}{endpoint}", timeout=5)
            resp.raise_for_status()
            responses.append({"url": url, "status": resp.status_code, "data": resp.json()})
        except Exception as e:
            logger.error(f"Failed to call {url}{endpoint}: {e}", exc_info=True)
            responses.append({"url": url, "status": "failed", "error": str(e)})
    return responses


def resolve_request_id(x_request_id: str) -> str:
    return x_request_id.strip() if x_request_id and x_request_id.strip() else f"req-{uuid.uuid4().hex[:12]}"


def ensure_service_role(service_name: str, allowed_services: List[str], operation: str, logger, request_id: str):
    if service_name not in allowed_services:
        logger.warning(
            json.dumps(
                {
                    "event": "invalid_service_route",
                    "request_id": request_id,
                    "operation": operation,
                    "service": service_name,
                    "allowed_services": allowed_services,
                }
            )
        )
        raise HTTPException(status_code=404, detail=f"{operation} is not exposed by {service_name}")

def create_app(service_name: str):
    app = FastAPI(title=service_name)
    logger = setup_logging(service_name)
    
    # Mock in-memory storage for resources
    resources_db = {}
    operation_status = {}
    carts_db: Dict[str, List[Dict[str, Any]]] = {}
    orders_db: Dict[str, Dict[str, Any]] = {}
    payments_db: Dict[str, Dict[str, Any]] = {}
    shipments_db: Dict[str, Dict[str, Any]] = {}
    ledger_db: List[Dict[str, Any]] = []
    
    # Optional downstream service to call (for backward compatibility)
    next_service_url = os.getenv("NEXT_SERVICE_URL")
    
    # Parse multi-service URLs for new endpoints (DAG pattern - no cycles)
    validate_services = parse_service_urls("VALIDATE_SERVICES_URL")
    fetch_services = parse_service_urls("FETCH_SERVICES_URL")
    verify_services = parse_service_urls("VERIFY_SERVICES_URL")
    check_services = parse_service_urls("CHECK_SERVICES_URL")
    sync_services = parse_service_urls("SYNC_SERVICES_URL")

    @app.get("/api/frontend/home")
    def frontend_home(x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["frontend"], "frontend_home", logger, request_id)
        logger.info(json.dumps({"event": "frontend_home_requested", "request_id": request_id, "service": service_name}))

        catalog_data = call_downstream_service(fetch_services, "/api/products?limit=5", logger)
        ad_data = call_downstream_service(validate_services, "/api/ads/placements", logger)
        recommendation_data = call_downstream_service(verify_services, "/api/recommendations/guest-user", logger)

        return {
            "service": service_name,
            "request_id": request_id,
            "hero_banner": "Spring Sale - Up to 40% Off",
            "catalog": catalog_data,
            "ads": ad_data,
            "recommendations": recommendation_data,
        }

    @app.get("/api/products")
    def list_products(limit: int = 10, x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["product-catalog-service", "frontend"], "list_products", logger, request_id)
        low_stock_items = [p["id"] for p in E_COMMERCE_PRODUCTS if p["stock"] < 10]
        if low_stock_items:
            logger.warning(
                json.dumps(
                    {
                        "event": "inventory_low_stock",
                        "request_id": request_id,
                        "service": service_name,
                        "skus": low_stock_items,
                    }
                )
            )

        return {
            "service": service_name,
            "request_id": request_id,
            "products": E_COMMERCE_PRODUCTS[: max(1, min(limit, len(E_COMMERCE_PRODUCTS)))],
            "count": min(limit, len(E_COMMERCE_PRODUCTS)),
        }

    @app.get("/api/products/{product_id}")
    def get_product(product_id: str, x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["product-catalog-service", "frontend"], "get_product", logger, request_id)
        product = next((p for p in E_COMMERCE_PRODUCTS if p["id"] == product_id), None)
        if not product:
            logger.warning(
                json.dumps(
                    {
                        "event": "product_not_found",
                        "request_id": request_id,
                        "service": service_name,
                        "product_id": product_id,
                    }
                )
            )
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

        return {"service": service_name, "request_id": request_id, "product": product}

    @app.get("/api/reviews/{product_id}")
    def get_product_reviews(product_id: str, x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["product-reviews-service"], "get_product_reviews", logger, request_id)
        sentiment = random.choice(["positive", "neutral", "negative"])
        if sentiment == "negative":
            logger.warning(
                json.dumps(
                    {
                        "event": "negative_review_trend",
                        "request_id": request_id,
                        "service": service_name,
                        "product_id": product_id,
                    }
                )
            )

        return {
            "service": service_name,
            "request_id": request_id,
            "product_id": product_id,
            "reviews": [
                {"review_id": f"rev-{product_id}-1", "rating": 5, "comment": "Great quality and delivery speed."},
                {"review_id": f"rev-{product_id}-2", "rating": 3, "comment": "Packaging could be better."},
            ],
            "trend": sentiment,
        }

    @app.get("/api/recommendations/{user_id}")
    def get_recommendations(user_id: str, x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["recommendation-service", "frontend"], "get_recommendations", logger, request_id)
        if random.random() < 0.1:
            logger.error(
                json.dumps(
                    {
                        "event": "recommendation_model_timeout",
                        "request_id": request_id,
                        "service": service_name,
                        "user_id": user_id,
                    }
                )
            )
            raise HTTPException(status_code=504, detail="Recommendation model timeout")

        return {
            "service": service_name,
            "request_id": request_id,
            "user_id": user_id,
            "recommendations": random.sample(E_COMMERCE_PRODUCTS, k=2),
        }

    @app.post("/api/cart/{cart_id}/items")
    def add_cart_item(cart_id: str, payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["cart-service"], "add_cart_item", logger, request_id)

        product_id = payload.get("product_id", "sku-1001")
        quantity = int(payload.get("quantity", 1))
        carts_db.setdefault(cart_id, []).append({"product_id": product_id, "quantity": quantity})
        logger.info(
            json.dumps(
                {
                    "event": "cart_item_added",
                    "request_id": request_id,
                    "service": service_name,
                    "cart_id": cart_id,
                    "product_id": product_id,
                    "quantity": quantity,
                }
            )
        )

        return {
            "service": service_name,
            "request_id": request_id,
            "cart_id": cart_id,
            "items": carts_db[cart_id],
            "item_count": len(carts_db[cart_id]),
        }

    @app.get("/api/cart/{cart_id}")
    def get_cart(cart_id: str, x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["cart-service", "checkout-service"], "get_cart", logger, request_id)
        items = carts_db.get(cart_id, [])
        if not items:
            logger.warning(
                json.dumps(
                    {
                        "event": "cart_empty",
                        "request_id": request_id,
                        "service": service_name,
                        "cart_id": cart_id,
                    }
                )
            )
        return {"service": service_name, "request_id": request_id, "cart_id": cart_id, "items": items}

    @app.post("/api/checkout/{cart_id}")
    def checkout_cart(cart_id: str, payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["checkout-service", "frontend"], "checkout_cart", logger, request_id)

        if random.random() < 0.08:
            logger.error(
                json.dumps(
                    {
                        "event": "checkout_dependency_failure",
                        "request_id": request_id,
                        "service": service_name,
                        "cart_id": cart_id,
                    }
                )
            )
            raise HTTPException(status_code=503, detail="Checkout dependency unavailable")

        order_id = f"ord-{uuid.uuid4().hex[:8]}"
        orders_db[order_id] = {
            "order_id": order_id,
            "cart_id": cart_id,
            "email": payload.get("email", "shopper@example.com"),
            "status": "placed",
            "created_at": datetime.utcnow().isoformat(),
        }
        logger.info(
            json.dumps(
                {
                    "event": "order_placed",
                    "request_id": request_id,
                    "service": service_name,
                    "order_id": order_id,
                    "cart_id": cart_id,
                }
            )
        )

        return {"service": service_name, "request_id": request_id, "order": orders_db[order_id]}

    @app.post("/api/payments/authorize")
    def authorize_payment(payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["payment-service"], "authorize_payment", logger, request_id)

        payment_id = f"pay-{uuid.uuid4().hex[:8]}"
        amount = float(payload.get("amount", 99.0))
        if random.random() < 0.15:
            logger.warning(
                json.dumps(
                    {
                        "event": "payment_declined",
                        "request_id": request_id,
                        "service": service_name,
                        "payment_id": payment_id,
                        "amount": amount,
                        "reason": "insufficient_funds",
                    }
                )
            )
            raise HTTPException(status_code=402, detail="Payment declined")

        payments_db[payment_id] = {"payment_id": payment_id, "amount": amount, "status": "authorized"}
        return {"service": service_name, "request_id": request_id, "payment": payments_db[payment_id]}

    @app.get("/api/ads/placements")
    def get_ads(x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["ad-service", "frontend"], "get_ads", logger, request_id)
        if random.random() < 0.05:
            logger.warning(
                json.dumps(
                    {
                        "event": "ad_engine_degraded",
                        "request_id": request_id,
                        "service": service_name,
                        "fallback": True,
                    }
                )
            )

        return {
            "service": service_name,
            "request_id": request_id,
            "placements": [
                {"slot": "hero", "campaign_id": "camp-summer-01", "cpc": 1.2},
                {"slot": "sidebar", "campaign_id": "camp-gadgets-09", "cpc": 0.8},
            ],
        }

    @app.post("/api/quotes/{cart_id}")
    def create_quote(cart_id: str, payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["quote-service"], "create_quote", logger, request_id)
        destination = payload.get("destination", "US")
        shipping_cost = round(random.uniform(4.5, 19.0), 2)
        tax = round(random.uniform(1.5, 7.5), 2)
        return {
            "service": service_name,
            "request_id": request_id,
            "cart_id": cart_id,
            "quote": {"shipping": shipping_cost, "tax": tax, "destination": destination, "currency": "USD"},
        }

    @app.post("/api/shipping/label")
    def create_shipping_label(payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["shipping-service"], "create_shipping_label", logger, request_id)

        order_id = payload.get("order_id", "ord-unknown")
        if random.random() < 0.1:
            logger.error(
                json.dumps(
                    {
                        "event": "carrier_api_error",
                        "request_id": request_id,
                        "service": service_name,
                        "order_id": order_id,
                    }
                )
            )
            raise HTTPException(status_code=502, detail="Carrier API error")

        shipment_id = f"shp-{uuid.uuid4().hex[:8]}"
        shipments_db[shipment_id] = {"shipment_id": shipment_id, "order_id": order_id, "status": "label_created"}
        return {"service": service_name, "request_id": request_id, "shipment": shipments_db[shipment_id]}

    @app.post("/api/email/send")
    def send_email(payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["email-service"], "send_email", logger, request_id)
        recipient = payload.get("to", "customer@example.com")
        template = payload.get("template", "order_confirmation")

        if random.random() < 0.07:
            logger.error(
                json.dumps(
                    {
                        "event": "email_provider_throttled",
                        "request_id": request_id,
                        "service": service_name,
                        "recipient": recipient,
                    }
                )
            )
            raise HTTPException(status_code=429, detail="Email provider throttled")

        return {
            "service": service_name,
            "request_id": request_id,
            "message_id": f"mail-{uuid.uuid4().hex[:8]}",
            "recipient": recipient,
            "template": template,
            "status": "queued",
        }

    @app.post("/api/accounting/ledger")
    def post_ledger_entry(payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        ensure_service_role(service_name, ["accounting-service"], "post_ledger_entry", logger, request_id)
        entry = {
            "entry_id": f"led-{uuid.uuid4().hex[:8]}",
            "order_id": payload.get("order_id", "ord-unknown"),
            "amount": float(payload.get("amount", 0.0)),
            "currency": payload.get("currency", "USD"),
            "created_at": datetime.utcnow().isoformat(),
        }
        ledger_db.append(entry)
        logger.info(json.dumps({"event": "ledger_entry_posted", "request_id": request_id, "service": service_name, "entry_id": entry["entry_id"]}))
        return {"service": service_name, "request_id": request_id, "entry": entry}

    @app.get("/health")
    def health():
        logger.info(f"{service_name} health check ok")
        return {"status": "ok", "service": service_name, "timestamp": datetime.utcnow().isoformat()}

    @app.get("/ready")
    def ready():
        """Kubernetes readiness probe - checks if service is ready to accept traffic."""
        logger.info(f"{service_name} readiness check")
        return {"ready": True, "service": service_name, "resources_count": len(resources_db)}

    @app.get("/process")
    def process():
        logger.info(f"{service_name} processing request")
        if next_service_url:
            try:
                logger.info(f"Calling downstream service {next_service_url}")
                resp = requests.get(f"{next_service_url}/process", timeout=5)
                resp.raise_for_status()
                return {"status": "success", "service": service_name, "downstream": resp.json()}
            except Exception as e:
                logger.error(f"Failed to call downstream service: {e}", exc_info=True)
                raise HTTPException(status_code=502, detail="Bad Gateway")
        return {"status": "success", "service": service_name, "message": "processing done"}

    @app.get("/list")
    def list_resources():
        """Get list of all resources."""
        logger.info(f"{service_name} listing all resources")
        return {
            "status": "success",
            "service": service_name,
            "count": len(resources_db),
            "resources": list(resources_db.values()),
            "timestamp": datetime.utcnow().isoformat()
        }

    @app.get("/get/{resource_id}")
    def get_resource(resource_id: str):
        """Get a specific resource by ID."""
        logger.info(f"{service_name} fetching resource {resource_id}")
        if resource_id not in resources_db:
            logger.warning(f"Resource {resource_id} not found in {service_name}")
            raise HTTPException(status_code=404, detail=f"Resource {resource_id} not found")
        
        return {
            "status": "success",
            "service": service_name,
            "resource": resources_db[resource_id]
        }

    @app.post("/create")
    def create_resource():
        """Create a new resource."""
        logger.info(f"{service_name} creating new resource")
        resource_id = f"res_{int(time.time() * 1000)}"
        resources_db[resource_id] = {
            "id": resource_id,
            "service": service_name,
            "created_at": datetime.utcnow().isoformat(),
            "status": "active"
        }
        operation_status[resource_id] = {"operation": "create", "status": "completed"}
        logger.info(f"Created resource {resource_id} in {service_name}")
        
        return {
            "status": "success",
            "service": service_name,
            "resource_id": resource_id,
            "message": "Resource created successfully"
        }

    @app.put("/update/{resource_id}")
    def update_resource(resource_id: str):
        """Update an existing resource."""
        logger.info(f"{service_name} updating resource {resource_id}")
        if resource_id not in resources_db:
            logger.warning(f"Resource {resource_id} not found for update in {service_name}")
            raise HTTPException(status_code=404, detail=f"Resource {resource_id} not found")
        
        resources_db[resource_id]["updated_at"] = datetime.utcnow().isoformat()
        resources_db[resource_id]["status"] = "updated"
        operation_status[resource_id] = {"operation": "update", "status": "completed"}
        
        return {
            "status": "success",
            "service": service_name,
            "resource_id": resource_id,
            "message": "Resource updated successfully"
        }

    @app.delete("/delete/{resource_id}")
    def delete_resource(resource_id: str):
        """Delete a resource."""
        logger.info(f"{service_name} deleting resource {resource_id}")
        if resource_id not in resources_db:
            logger.warning(f"Resource {resource_id} not found for deletion in {service_name}")
            raise HTTPException(status_code=404, detail=f"Resource {resource_id} not found")
        
        deleted_resource = resources_db.pop(resource_id)
        operation_status[resource_id] = {"operation": "delete", "status": "completed", "timestamp": datetime.utcnow().isoformat()}
        logger.info(f"Deleted resource {resource_id} from {service_name}")
        
        return {
            "status": "success",
            "service": service_name,
            "resource_id": resource_id,
            "deleted_resource": deleted_resource,
            "message": "Resource deleted successfully"
        }

    @app.get("/search")
    def search_resources(query: str = ""):
        """Search resources by query."""
        logger.info(f"{service_name} searching resources with query: {query}")
        if not query:
            return {"status": "success", "service": service_name, "results": list(resources_db.values())}
        
        # Simple search matching on id
        results = [r for r in resources_db.values() if query.lower() in r.get("id", "").lower()]
        logger.info(f"Found {len(results)} results for query '{query}' in {service_name}")
        
        return {
            "status": "success",
            "service": service_name,
            "query": query,
            "result_count": len(results),
            "results": results
        }

    @app.get("/status/{operation_id}")
    def get_operation_status(operation_id: str):
        """Get status of a previously executed operation."""
        logger.info(f"{service_name} checking status of operation {operation_id}")
        if operation_id not in operation_status:
            logger.warning(f"Operation {operation_id} not found in {service_name}")
            return {
                "status": "unknown",
                "service": service_name,
                "operation_id": operation_id,
                "message": "Operation not found"
            }
        
        return {
            "status": "success",
            "service": service_name,
            "operation_id": operation_id,
            "operation_status": operation_status[operation_id]
        }

    @app.get("/metrics")
    def get_metrics():
        """Get service metrics."""
        logger.info(f"{service_name} collecting metrics")
        return {
            "service": service_name,
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": {
                "total_resources": len(resources_db),
                "total_operations": len(operation_status),
                "active_carts": len(carts_db),
                "orders": len(orders_db),
                "payments": len(payments_db),
                "shipments": len(shipments_db),
                "ledger_entries": len(ledger_db),
                "uptime_check": True,
                "memory_healthy": True
            }
        }

    @app.get("/sync")
    def sync_state():
        """Sync state with downstream services."""
        logger.info(f"{service_name} syncing state with downstream services")
        if not sync_services:
            return {
                "status": "synced",
                "service": service_name,
                "message": "Local state synchronized",
                "resources_synced": len(resources_db)
            }
        
        responses = call_downstream_service(sync_services, "/sync", logger)
        
        return {
            "status": "synced",
            "service": service_name,
            "local_resources": len(resources_db),
            "downstream_sync": responses
        }

    @app.post("/rollback/{operation_id}")
    def rollback_operation(operation_id: str):
        """Rollback a previous operation."""
        logger.info(f"{service_name} rolling back operation {operation_id}")
        
        if operation_id not in operation_status:
            logger.warning(f"Cannot rollback unknown operation {operation_id} in {service_name}")
            raise HTTPException(status_code=404, detail=f"Operation {operation_id} not found")
        
        original_status = operation_status[operation_id]
        operation_status[operation_id]["status"] = "rolled_back"
        operation_status[operation_id]["rolled_back_at"] = datetime.utcnow().isoformat()
        
        logger.info(f"Successfully rolled back operation {operation_id} in {service_name}")
        
        return {
            "status": "success",
            "service": service_name,
            "operation_id": operation_id,
            "original_status": original_status,
            "message": "Operation rolled back successfully"
        }

    @app.get("/validate")
    def validate():
        """Validate through multiple downstream services (for verification workflows)."""
        logger.info(f"{service_name} validation request")
        if not validate_services:
            return {"status": "validated", "service": service_name, "message": "local validation passed"}
        
        responses = call_downstream_service(validate_services, "/validate", logger)
        all_passed = all(r.get("status") == 200 for r in responses if r.get("status") != "failed")
        
        return {
            "status": "validated" if all_passed else "validation_failed",
            "service": service_name,
            "responses": responses
        }

    @app.get("/fetch-data")
    def fetch_data():
        """Fetch aggregated data from multiple downstream services."""
        logger.info(f"{service_name} fetching aggregated data")
        if not fetch_services:
            return {"status": "success", "service": service_name, "data": []}
        
        responses = call_downstream_service(fetch_services, "/fetch-data", logger)
        
        return {
            "status": "success",
            "service": service_name,
            "aggregated_data": responses
        }

    @app.get("/verify")
    def verify():
        """Cross-service verification."""
        logger.info(f"{service_name} performing verification")
        if not verify_services:
            return {"status": "verified", "service": service_name, "message": "local verification passed"}
        
        responses = call_downstream_service(verify_services, "/verify", logger)
        
        return {
            "status": "verified",
            "service": service_name,
            "verification_results": responses
        }

    @app.get("/check")
    def check():
        """Check status across multiple downstream services."""
        logger.info(f"{service_name} performing health check across services")
        if not check_services:
            return {"status": "healthy", "service": service_name, "dependencies": []}
        
        responses = call_downstream_service(check_services, "/check", logger)
        
        return {
            "status": "healthy",
            "service": service_name,
            "dependency_status": responses
        }

    @app.get("/warn")
    def warn():
        logger.warning(f"This is a warning log from {service_name}. Something might be wrong.")
        return {"status": "warning_logged", "service": service_name}

    @app.get("/error")
    def error():
        logger.error(f"This is a deliberate error log from {service_name}.")
        raise HTTPException(status_code=500, detail="Internal Server Error triggered")

    @app.get("/simulate-oom")
    def simulate_oom():
        try:
            # Simulate OOM log
            raise MemoryError("java.lang.OutOfMemoryError: Java heap space")
        except MemoryError as e:
            logger.error(f"Out of memory error in {service_name}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Simulated OOM Error")

    @app.get("/simulate-cpu")
    def simulate_cpu():
        logger.info(f"Simulating CPU load in {service_name}")
        start = time.time()
        while time.time() - start < 2:
            _ = [i * i for i in range(1000)]
        return {"status": "cpu_load_done", "service": service_name}

    @app.get("/delay/{seconds}")
    def simulate_delay(seconds: int):
        """Simulate network latency/processing delay."""
        logger.info(f"Simulating {seconds}s delay in {service_name}")
        if seconds > 30:
            logger.warning(f"Requested delay {seconds}s exceeds max (30s) in {service_name}")
            seconds = 30
        
        time.sleep(min(seconds, 30))
        return {
            "status": "success",
            "service": service_name,
            "delay_simulated_seconds": seconds,
            "timestamp": datetime.utcnow().isoformat()
        }

    return app
