from fastapi import FastAPI, HTTPException, Body, Header
import os
import requests
import time
import json
import random
import uuid
import threading
from datetime import datetime
from typing import Any, Dict, Optional
from common.logging_setup import setup_logging
from common.production_utils import ResilientHTTPSession


E_COMMERCE_PRODUCTS = [
    {"id": "sku-1001", "name": "Wireless Headphones", "price": 129.0, "category": "electronics", "stock": 52},
    {"id": "sku-1002", "name": "Gaming Mouse", "price": 49.0, "category": "electronics", "stock": 18},
    {"id": "sku-1003", "name": "Coffee Grinder", "price": 89.0, "category": "home", "stock": 7},
    {"id": "sku-1004", "name": "Travel Backpack", "price": 110.0, "category": "outdoor", "stock": 34},
]


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return default


# Runtime chaos overrides. Scenario runners POST to /chaos/config to flip
# failure probabilities without restarting pods. Keys mirror env var names
# (PAYMENT_FAILURE_RATE, CATALOG_ERROR_PROB, ...). Values override env defaults
# for the lifetime of the pod or until /chaos/reset is called.
CHAOS_OVERRIDES: Dict[str, float] = {}
_chaos_lock = threading.Lock()


def chaos_float(name: str, env_default_value: float) -> float:
    """Return the runtime chaos override for `name` if set, else env default."""
    with _chaos_lock:
        if name in CHAOS_OVERRIDES:
            return CHAOS_OVERRIDES[name]
    return env_default_value


def resolve_request_id(x_request_id: str) -> str:
    return x_request_id.strip() if x_request_id and x_request_id.strip() else f"req-{uuid.uuid4().hex[:12]}"


def canonical_service(name: str) -> str:
    if name.endswith("-service"):
        return name[:-8]
    return name


def env_url(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def is_service(service_name: str, *allowed: str) -> bool:
    candidate = canonical_service(service_name)
    return candidate in {canonical_service(s) for s in allowed}


def log_event(logger, level: str, service_name: str, endpoint: str, request_id: str, message: str, dependency: Optional[str] = None, **extra):
    payload = {
        "service_name": service_name,
        "endpoint": endpoint,
        "request_id": request_id,
        "dependency": dependency or "",
        "message": message,
        "timestamp": datetime.utcnow().isoformat(),
    }
    payload.update(extra)
    line = json.dumps(payload)
    if level == "error":
        logger.error(line)
    elif level == "warning":
        logger.warning(line)
    else:
        logger.info(line)


def call_service(base_url: str, method: str, endpoint: str, logger, service_name: str, request_id: str, dependency: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 6):
    if not base_url:
        raise RuntimeError(f"Missing URL for dependency {dependency}")

    started_at = time.time()
    response = requests.request(
        method=method,
        url=f"{base_url}{endpoint}",
        headers={"x-request-id": request_id},
        json=payload,
        timeout=timeout,
    )
    latency_ms = int((time.time() - started_at) * 1000)
    return response, latency_ms


def create_app(service_name: str):
    app = FastAPI(title=service_name)
    logger = setup_logging(service_name)

    # Production-ready HTTP session with resilience patterns
    http_session = ResilientHTTPSession(service_name, logger)

    # Dependency health status
    dependency_health: Dict[str, Dict[str, Any]] = {}

    carts_db: Dict[str, list] = {}
    orders_db: Dict[str, Dict[str, Any]] = {}
    payments_db: Dict[str, Dict[str, Any]] = {}
    shipments_db: Dict[str, Dict[str, Any]] = {}

    product_catalog_url = os.getenv("PRODUCT_CATALOG_URL", "")
    cart_url = os.getenv("CART_URL", "")
    checkout_url = os.getenv("CHECKOUT_URL", "")
    quote_url = os.getenv("QUOTE_URL", "")
    payment_url = os.getenv("PAYMENT_URL", "")
    shipping_url = os.getenv("SHIPPING_URL", "")
    email_url = os.getenv("EMAIL_URL", "")
    ad_service_url = os.getenv("AD_SERVICE_URL", "")

    # Keep defaults aligned with in-cluster service DNS names for all deployments.
    service_urls = {
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

    payment_failure_rate = env_float("PAYMENT_FAILURE_RATE", 0.15)
    payment_slow_prob = env_float("PAYMENT_SLOW_PROB", 0.2)
    shipping_failure_rate = env_float("SHIPPING_FAILURE_RATE", 0.1)
    shipping_warning_rate = env_float("SHIPPING_WARNING_RATE", 0.2)
    catalog_latency_prob = env_float("CATALOG_LATENCY_PROB", 0.2)
    catalog_error_prob = env_float("CATALOG_ERROR_PROB", 0.05)
    ad_delay_prob = env_float("AD_DELAY_PROB", 0.2)
    ad_error_prob = env_float("AD_ERROR_PROB", 0.03)
    quote_mismatch_rate = env_float("QUOTE_MISMATCH_RATE", 0.05)
    email_warning_rate = env_float("EMAIL_WARNING_RATE", 0.1)

    def call_service_resilient(
        base_url: str,
        method: str,
        endpoint: str,
        request_id: str,
        dependency: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: int = 6,
    ) -> tuple:
        """Call a service with resilience patterns (retry, circuit breaker, bulkhead)."""
        return http_session.call_service_resilient(
            base_url=base_url,
            method=method,
            endpoint=endpoint,
            request_id=request_id,
            dependency=dependency,
            payload=payload,
            timeout=timeout,
            on_log=log_event,
        )

    def execute_checkout(payload: Dict[str, Any], request_id: str):
        user_id = payload.get("userId", "user-100")
        payment_method = payload.get("paymentMethod", "card")
        email = payload.get("email", "buyer@example.com")

        # Fetch cart with resilience
        try:
            response, latency_ms, success, reason = call_service_resilient(
                cart_url, "GET", f"/cart/{user_id}", request_id, "cart"
            )
            if not success or not response:
                log_event(logger, "error", service_name, "/checkout", request_id, f"Failed to fetch cart: {reason}", dependency="cart")
                raise HTTPException(status_code=502, detail="Cart unavailable")
            items = response.json().get("items", [])
            if not items:
                log_event(logger, "warning", service_name, "/checkout", request_id, "Checkout requested with empty cart", dependency="cart")
                raise HTTPException(status_code=400, detail="Cart is empty")
            log_event(logger, "info", service_name, "/checkout", request_id, "Cart loaded", dependency="cart", latency_ms=latency_ms)
        except HTTPException:
            raise
        except Exception as exc:
            log_event(logger, "error", service_name, "/checkout", request_id, "Cart fetch exception", dependency="cart", error=str(exc))
            raise HTTPException(status_code=502, detail="Cart unavailable")

        # Fetch quote with resilience
        try:
            response, latency_ms, success, reason = call_service_resilient(
                quote_url, "POST", "/quote", request_id, "quote", payload={"userId": user_id, "items": items}
            )
            if not success or not response:
                log_event(logger, "error", service_name, "/checkout", request_id, f"Quote failed: {reason}", dependency="quote")
                raise HTTPException(status_code=502, detail="Quote unavailable")
            if latency_ms > 500:
                log_event(logger, "warning", service_name, "/checkout", request_id, "Quote service slow", dependency="quote", latency_ms=latency_ms)
            quote_data = response.json()
        except HTTPException:
            raise
        except Exception as exc:
            log_event(logger, "error", service_name, "/checkout", request_id, "Quote exception", dependency="quote", error=str(exc))
            raise HTTPException(status_code=502, detail="Quote unavailable")

        order_id = f"ord-{uuid.uuid4().hex[:8]}"

        # Process payment with resilience
        try:
            response, latency_ms, success, reason = call_service_resilient(
                payment_url,
                "POST",
                "/payment/charge",
                request_id,
                "payment",
                payload={"amount": quote_data.get("total", 0.0), "paymentMethod": payment_method, "orderId": order_id},
            )
            if not success or not response:
                log_event(logger, "error", service_name, "/checkout", request_id, f"Payment failed: {reason}", dependency="payment")
                raise HTTPException(status_code=502, detail="Payment failed")
            payment_data = response.json().get("payment", {})
        except HTTPException:
            raise
        except Exception as exc:
            log_event(logger, "error", service_name, "/checkout", request_id, "Payment exception", dependency="payment", error=str(exc))
            raise HTTPException(status_code=502, detail="Payment failed")

        # Process shipping with resilience and graceful degradation
        shipping_failed = False
        shipping_error = ""
        shipment_data: Dict[str, Any] = {}
        try:
            response, latency_ms, success, reason = call_service_resilient(
                shipping_url, "POST", "/shipping/create", request_id, "shipping", payload={"orderId": order_id}
            )
            if success and response:
                shipment_data = response.json().get("shipment", {})
            else:
                shipping_failed = True
                shipping_error = reason
                log_event(logger, "error", service_name, "/checkout", request_id, f"Shipping failed (graceful degradation): {reason}", dependency="shipping")
        except Exception as exc:
            shipping_failed = True
            shipping_error = str(exc)
            log_event(logger, "error", service_name, "/checkout", request_id, "Shipping exception (graceful degradation)", dependency="shipping", error=shipping_error)

        # Send email with resilience (non-critical side-effect)
        email_status = "skipped"
        try:
            response, latency_ms, success, reason = call_service_resilient(
                email_url,
                "POST",
                "/email/send",
                request_id,
                "email",
                payload={"to": email, "template": "order_confirmation", "orderId": order_id},
            )
            if success and response:
                email_status = "sent"
            else:
                log_event(logger, "warning", service_name, "/checkout", request_id, f"Email side-effect failed: {reason}", dependency="email")
        except Exception as exc:
            log_event(logger, "warning", service_name, "/checkout", request_id, "Email exception (non-critical)", dependency="email", error=str(exc))

        orders_db[order_id] = {
            "orderId": order_id,
            "userId": user_id,
            "total": quote_data.get("total", 0.0),
            "payment": payment_data,
            "shipment": shipment_data,
            "emailStatus": email_status,
            "status": "partial_failure" if shipping_failed else "completed",
        }

        if shipping_failed:
            return {
                "service": service_name,
                "request_id": request_id,
                "status": "partial_failure",
                "order": orders_db[order_id],
                "error": "shipping_failure",
                "details": shipping_error,
            }

        log_event(logger, "info", service_name, "/checkout", request_id, "Checkout completed successfully")
        return {"service": service_name, "request_id": request_id, "status": "success", "order": orders_db[order_id]}

    @app.get("/health")
    def health(x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        log_event(logger, "info", service_name, "/health", request_id, "Health check ok")
        return {"status": "ok", "service": service_name, "timestamp": datetime.utcnow().isoformat()}

    @app.get("/ready")
    def ready(x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        log_event(logger, "info", service_name, "/ready", request_id, "Readiness check ok")
        return {"ready": True, "service": service_name}

    @app.get("/products")
    def products(x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)

        if is_service(service_name, "frontend"):
            try:
                response, latency_ms = call_service(
                    product_catalog_url,
                    "GET",
                    "/products",
                    logger,
                    service_name,
                    request_id,
                    dependency="product-catalog",
                )
                if latency_ms > 500:
                    log_event(logger, "warning", service_name, "/products", request_id, "Catalog response slow (>500ms)", dependency="product-catalog", latency_ms=latency_ms)
                response.raise_for_status()
                log_event(logger, "info", service_name, "/products", request_id, "Products fetched from catalog", dependency="product-catalog", latency_ms=latency_ms)
                return response.json()
            except Exception as exc:
                log_event(logger, "error", service_name, "/products", request_id, "Failed to fetch products", dependency="product-catalog", error=str(exc))
                raise HTTPException(status_code=502, detail="Catalog unavailable")

        if is_service(service_name, "product-catalog"):
            if random.random() < chaos_float("CATALOG_ERROR_PROB", catalog_error_prob):
                log_event(logger, "error", service_name, "/products", request_id, "DB timeout while fetching products")
                raise HTTPException(status_code=504, detail="Catalog DB timeout")

            if random.random() < chaos_float("CATALOG_LATENCY_PROB", catalog_latency_prob):
                time.sleep(random.uniform(0.55, 1.1))
                log_event(logger, "warning", service_name, "/products", request_id, "Slow DB response")

            log_event(logger, "info", service_name, "/products", request_id, "Product list fetched")
            return {"service": service_name, "products": E_COMMERCE_PRODUCTS}

        raise HTTPException(status_code=404, detail="Endpoint is not exposed by this service")

    @app.post("/cart/add")
    def cart_add(payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)

        user_id = payload.get("userId", "user-100")
        product_id = payload.get("productId", "sku-1001")
        quantity = int(payload.get("quantity", 1))

        if is_service(service_name, "frontend"):
            try:
                response, latency_ms = call_service(
                    cart_url,
                    "POST",
                    "/cart/add",
                    logger,
                    service_name,
                    request_id,
                    dependency="cart",
                    payload={"userId": user_id, "productId": product_id, "quantity": quantity},
                )
                response.raise_for_status()
                log_event(logger, "info", service_name, "/cart/add", request_id, "Cart item added successfully", dependency="cart", latency_ms=latency_ms)
                return response.json()
            except Exception as exc:
                log_event(logger, "error", service_name, "/cart/add", request_id, "Cart add failed", dependency="cart", error=str(exc))
                raise HTTPException(status_code=502, detail="Cart service unavailable")

        if is_service(service_name, "cart"):
            try:
                response, latency_ms = call_service(
                    product_catalog_url,
                    "GET",
                    f"/products/{product_id}",
                    logger,
                    service_name,
                    request_id,
                    dependency="product-catalog",
                )
                if latency_ms > 500:
                    log_event(logger, "warning", service_name, "/cart/add", request_id, "Product service response slow (>500ms)", dependency="product-catalog", latency_ms=latency_ms)
                response.raise_for_status()
            except Exception as exc:
                log_event(logger, "error", service_name, "/cart/add", request_id, "Product unavailable for cart add", dependency="product-catalog", error=str(exc))
                raise HTTPException(status_code=502, detail="Product unavailable")

            item = {"productId": product_id, "quantity": quantity}
            carts_db.setdefault(user_id, []).append(item)
            log_event(logger, "info", service_name, "/cart/add", request_id, "Cart item added successfully", dependency="product-catalog")
            return {"service": service_name, "userId": user_id, "items": carts_db[user_id]}

        raise HTTPException(status_code=404, detail="Endpoint is not exposed by this service")

    @app.post("/checkout")
    def checkout(payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)

        if is_service(service_name, "frontend"):
            user_id = payload.get("userId", "user-100")
            payment_method = payload.get("paymentMethod", "card")
            email = payload.get("email", "buyer@example.com")
            try:
                response, latency_ms = call_service(
                    checkout_url,
                    "POST",
                    "/checkout",
                    logger,
                    service_name,
                    request_id,
                    dependency="checkout",
                    payload={"userId": user_id, "paymentMethod": payment_method, "email": email},
                    timeout=12,
                )
                if response.status_code >= 500:
                    log_event(logger, "error", service_name, "/checkout", request_id, "Checkout failed", dependency="checkout", status_code=response.status_code)
                    raise HTTPException(status_code=502, detail="Checkout failed")

                if response.status_code == 207:
                    log_event(logger, "warning", service_name, "/checkout", request_id, "Checkout partial failure", dependency="checkout", latency_ms=latency_ms)
                else:
                    log_event(logger, "info", service_name, "/checkout", request_id, "Checkout completed", dependency="checkout", latency_ms=latency_ms)
                return response.json()
            except HTTPException:
                raise
            except Exception as exc:
                log_event(logger, "error", service_name, "/checkout", request_id, "Checkout call failed", dependency="checkout", error=str(exc))
                raise HTTPException(status_code=502, detail="Checkout unavailable")

        if is_service(service_name, "checkout"):
            return execute_checkout(payload, request_id)

        raise HTTPException(status_code=404, detail="Endpoint is not exposed by this service")

    @app.get("/products/{product_id}")
    def catalog_product(product_id: str, x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        if not is_service(service_name, "product-catalog"):
            raise HTTPException(status_code=404, detail="Endpoint is only exposed by product-catalog")

        if random.random() < chaos_float("CATALOG_ERROR_PROB", catalog_error_prob):
            log_event(logger, "error", service_name, f"/products/{product_id}", request_id, "DB timeout while fetching product")
            raise HTTPException(status_code=504, detail="Catalog DB timeout")

        if random.random() < chaos_float("CATALOG_LATENCY_PROB", catalog_latency_prob):
            time.sleep(random.uniform(0.55, 1.0))
            log_event(logger, "warning", service_name, f"/products/{product_id}", request_id, "Slow DB response")

        product = next((item for item in E_COMMERCE_PRODUCTS if item["id"] == product_id), None)
        if not product:
            log_event(logger, "error", service_name, f"/products/{product_id}", request_id, "Product not found")
            raise HTTPException(status_code=404, detail="Product not found")

        log_event(logger, "info", service_name, f"/products/{product_id}", request_id, "Product fetched")
        return {"service": service_name, "product": product}

    @app.get("/cart/{user_id}")
    def cart_get(user_id: str, x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        if not is_service(service_name, "cart", "checkout"):
            raise HTTPException(status_code=404, detail="Endpoint is only exposed by cart")

        items = carts_db.get(user_id, [])
        if not items:
            log_event(logger, "warning", service_name, f"/cart/{user_id}", request_id, "Cart is empty")
        else:
            log_event(logger, "info", service_name, f"/cart/{user_id}", request_id, "Cart fetched")
        return {"service": service_name, "userId": user_id, "items": items}

    @app.get("/discounts")
    def discounts(userId: str = "user-100", x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        if not is_service(service_name, "ad-service", "ad"):
            raise HTTPException(status_code=404, detail="Endpoint is only exposed by ad-service")

        if random.random() < chaos_float("AD_ERROR_PROB", ad_error_prob):
            log_event(logger, "error", service_name, "/discounts", request_id, "Invalid discount rule", user_id=userId)
            raise HTTPException(status_code=500, detail="Invalid discount rule")

        if random.random() < chaos_float("AD_DELAY_PROB", ad_delay_prob):
            time.sleep(random.uniform(0.4, 0.9))
            log_event(logger, "warning", service_name, "/discounts", request_id, "Discount service delayed", user_id=userId)

        discount_pct = random.choice([0, 5, 10, 15])
        log_event(logger, "info", service_name, "/discounts", request_id, "Discount rule computed", user_id=userId)
        return {"service": service_name, "userId": userId, "discountPercent": discount_pct}

    @app.post("/quote")
    def quote(payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        if not is_service(service_name, "quote"):
            raise HTTPException(status_code=404, detail="Endpoint is only exposed by quote")

        user_id = payload.get("userId", "user-100")
        items = payload.get("items", [])
        subtotal = 0.0

        for item in items:
            product_id = item.get("productId", "")
            quantity = int(item.get("quantity", 1))
            try:
                response, latency_ms = call_service(
                    product_catalog_url,
                    "GET",
                    f"/products/{product_id}",
                    logger,
                    service_name,
                    request_id,
                    dependency="product-catalog",
                )
                if latency_ms > 500:
                    log_event(logger, "warning", service_name, "/quote", request_id, "Catalog lookup slow", dependency="product-catalog", latency_ms=latency_ms)
                response.raise_for_status()
                subtotal += float(response.json()["product"]["price"]) * quantity
            except Exception as exc:
                log_event(logger, "error", service_name, "/quote", request_id, "Failed to fetch product for quote", dependency="product-catalog", error=str(exc))
                raise HTTPException(status_code=502, detail="Unable to calculate quote")

        try:
            discount_resp, discount_latency = call_service(
                ad_service_url,
                "GET",
                f"/discounts?userId={user_id}",
                logger,
                service_name,
                request_id,
                dependency="ad-service",
            )
            if discount_latency > 500:
                log_event(logger, "warning", service_name, "/quote", request_id, "Discount service slow", dependency="ad-service", latency_ms=discount_latency)
            discount_resp.raise_for_status()
            discount_pct = float(discount_resp.json().get("discountPercent", 0.0))
        except Exception as exc:
            log_event(logger, "warning", service_name, "/quote", request_id, "Discount unavailable, continuing without discount", dependency="ad-service", error=str(exc))
            discount_pct = 0.0

        discount_amount = round(subtotal * discount_pct / 100.0, 2)
        total = round(subtotal - discount_amount, 2)
        if random.random() < chaos_float("QUOTE_MISMATCH_RATE", quote_mismatch_rate):
            log_event(logger, "error", service_name, "/quote", request_id, "Price mismatch detected", dependency="ad-service", subtotal=subtotal, discount_percent=discount_pct)
            raise HTTPException(status_code=500, detail="Price mismatch")

        log_event(logger, "info", service_name, "/quote", request_id, "Price calculated", dependency="ad-service", subtotal=subtotal, discount_percent=discount_pct, total=total)
        return {
            "service": service_name,
            "userId": user_id,
            "subtotal": round(subtotal, 2),
            "discountPercent": discount_pct,
            "discountAmount": discount_amount,
            "total": total,
            "currency": "USD",
        }

    @app.post("/payment/charge")
    def payment_charge(payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        if not is_service(service_name, "payment"):
            raise HTTPException(status_code=404, detail="Endpoint is only exposed by payment")

        amount = float(payload.get("amount", 0.0))
        if random.random() < chaos_float("PAYMENT_SLOW_PROB", payment_slow_prob):
            time.sleep(random.uniform(0.45, 0.95))
            log_event(logger, "warning", service_name, "/payment/charge", request_id, "Slow payment gateway")

        if random.random() < chaos_float("PAYMENT_FAILURE_RATE", payment_failure_rate):
            log_event(logger, "error", service_name, "/payment/charge", request_id, "Payment failed due to gateway timeout")
            raise HTTPException(status_code=504, detail="Gateway timeout")

        payment_id = f"pay-{uuid.uuid4().hex[:8]}"
        payments_db[payment_id] = {"paymentId": payment_id, "amount": amount, "status": "captured"}
        log_event(logger, "info", service_name, "/payment/charge", request_id, "Payment success", payment_id=payment_id, amount=amount)
        return {"service": service_name, "payment": payments_db[payment_id]}

    @app.post("/payment/refund")
    def payment_refund(payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        if not is_service(service_name, "payment"):
            raise HTTPException(status_code=404, detail="Endpoint is only exposed by payment")

        payment_id = payload.get("paymentId", "")
        if payment_id not in payments_db:
            log_event(logger, "error", service_name, "/payment/refund", request_id, "Unknown payment id for refund", payment_id=payment_id)
            raise HTTPException(status_code=404, detail="Payment not found")

        payments_db[payment_id]["status"] = "refunded"
        log_event(logger, "info", service_name, "/payment/refund", request_id, "Refund successful", payment_id=payment_id)
        return {"service": service_name, "payment": payments_db[payment_id]}

    @app.post("/shipping/create")
    def shipping_create(payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        if not is_service(service_name, "shipping"):
            raise HTTPException(status_code=404, detail="Endpoint is only exposed by shipping")

        if random.random() < chaos_float("SHIPPING_WARNING_RATE", shipping_warning_rate):
            log_event(logger, "warning", service_name, "/shipping/create", request_id, "Carrier delay observed")
            time.sleep(random.uniform(0.35, 0.8))

        if random.random() < chaos_float("SHIPPING_FAILURE_RATE", shipping_failure_rate):
            log_event(logger, "error", service_name, "/shipping/create", request_id, "Carrier unavailable")
            raise HTTPException(status_code=503, detail="Shipping unavailable")

        order_id = payload.get("orderId", f"ord-{uuid.uuid4().hex[:8]}")
        shipment_id = f"shp-{uuid.uuid4().hex[:8]}"
        shipments_db[order_id] = {"shipmentId": shipment_id, "orderId": order_id, "status": "created"}
        log_event(logger, "info", service_name, "/shipping/create", request_id, "Shipment created", order_id=order_id, shipment_id=shipment_id)
        return {"service": service_name, "shipment": shipments_db[order_id]}

    @app.get("/shipping/{order_id}")
    def shipping_get(order_id: str, x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        if not is_service(service_name, "shipping"):
            raise HTTPException(status_code=404, detail="Endpoint is only exposed by shipping")

        shipment = shipments_db.get(order_id)
        if not shipment:
            log_event(logger, "warning", service_name, f"/shipping/{order_id}", request_id, "Shipment not found", order_id=order_id)
            raise HTTPException(status_code=404, detail="Shipment not found")
        log_event(logger, "info", service_name, f"/shipping/{order_id}", request_id, "Shipment fetched", order_id=order_id)
        return {"service": service_name, "shipment": shipment}

    @app.post("/email/send")
    def email_send(payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        if not is_service(service_name, "email"):
            raise HTTPException(status_code=404, detail="Endpoint is only exposed by email")

        recipient = payload.get("to", "buyer@example.com")
        if random.random() < chaos_float("EMAIL_WARNING_RATE", email_warning_rate):
            log_event(logger, "warning", service_name, "/email/send", request_id, "Email delivery delayed", recipient=recipient)
            time.sleep(random.uniform(0.1, 0.4))

        message_id = f"mail-{uuid.uuid4().hex[:8]}"
        log_event(logger, "info", service_name, "/email/send", request_id, "Email sent", recipient=recipient, message_id=message_id)
        return {"service": service_name, "messageId": message_id, "status": "sent"}

    @app.get("/warn")
    def warn(x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        log_event(logger, "warning", service_name, "/warn", request_id, "Synthetic warning endpoint triggered")
        return {"status": "warning_logged", "service": service_name}

    @app.get("/error")
    def error(x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        log_event(logger, "error", service_name, "/error", request_id, "Synthetic error endpoint triggered")
        raise HTTPException(status_code=500, detail="Internal Server Error triggered")

    @app.get("/simulate-cpu")
    def simulate_cpu(x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        log_event(logger, "warning", service_name, "/simulate-cpu", request_id, "CPU spike simulation started")
        start = time.time()
        while time.time() - start < 2:
            _ = [i * i for i in range(1000)]
        return {"status": "cpu_load_done", "service": service_name}

    @app.get("/delay/{seconds}")
    def simulate_delay(seconds: int, x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        seconds = min(seconds, 30)
        time.sleep(seconds)
        log_event(logger, "warning", service_name, "/delay/{seconds}", request_id, "Latency simulation executed", delay_seconds=seconds)
        return {"status": "success", "service": service_name, "delay_simulated_seconds": seconds}

    @app.get("/dependencies/health")
    def dependencies_health(x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        health_status = http_session.get_health_status()
        log_event(logger, "info", service_name, "/dependencies/health", request_id, "Dependency health queried", num_dependencies=len(health_status))
        return {
            "service": service_name,
            "request_id": request_id,
            "dependencies": health_status,
            "timestamp": datetime.utcnow().isoformat(),
        }

    @app.post("/mesh/ping-all")
    def mesh_ping_all(x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        caller = canonical_service(service_name)
        outcomes = []

        for target, base_url in service_urls.items():
            if canonical_service(target) == caller:
                continue

            for endpoint in ("/health", "/warn", "/error"):
                response, latency_ms, success, reason = call_service_resilient(
                    base_url=base_url,
                    method="GET",
                    endpoint=endpoint,
                    request_id=request_id,
                    dependency=target,
                    timeout=6,
                )

                level = "info" if success else "warning"
                if endpoint == "/error":
                    level = "warning"  # Expected to fail

                if response and response.status_code >= 500:
                    level = "error"

                outcomes.append(
                    {
                        "target": target,
                        "endpoint": endpoint,
                        "status_code": response.status_code if response else None,
                        "success": success,
                        "reason": reason,
                        "latency_ms": latency_ms,
                    }
                )

        return {
            "service": service_name,
            "request_id": request_id,
            "fanout_calls": len(outcomes),
            "outcomes": outcomes,
        }

    @app.post("/chaos/config")
    def chaos_config(payload: Dict[str, Any] = Body(default={}), x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        if not isinstance(payload, dict) or "overrides" not in payload or not isinstance(payload["overrides"], dict):
            raise HTTPException(status_code=400, detail="Body must be {\"overrides\": {KEY: float, ...}}")
        applied: Dict[str, float] = {}
        with _chaos_lock:
            for key, raw in payload["overrides"].items():
                try:
                    value = max(0.0, min(1.0, float(raw)))
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail=f"Value for {key} must be a number in [0,1]")
                CHAOS_OVERRIDES[key] = value
                applied[key] = value
        log_event(logger, "warning", service_name, "/chaos/config", request_id, "Chaos overrides applied", overrides=applied)
        return {"service": service_name, "applied": applied, "active": dict(CHAOS_OVERRIDES)}

    @app.post("/chaos/reset")
    def chaos_reset(x_request_id: str = Header(default="")):
        request_id = resolve_request_id(x_request_id)
        with _chaos_lock:
            CHAOS_OVERRIDES.clear()
        log_event(logger, "info", service_name, "/chaos/reset", request_id, "Chaos overrides cleared")
        return {"service": service_name, "active": {}}

    @app.get("/chaos/status")
    def chaos_status():
        with _chaos_lock:
            return {"service": service_name, "active": dict(CHAOS_OVERRIDES)}

    return app
