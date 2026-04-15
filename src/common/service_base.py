from fastapi import FastAPI, HTTPException
import os
import requests
import time
from common.telemetry import setup_telemetry

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

def create_app(service_name: str):
    app = FastAPI(title=service_name)
    logger = setup_telemetry(service_name)
    
    # Optional downstream service to call (for backward compatibility)
    next_service_url = os.getenv("NEXT_SERVICE_URL")
    
    # Parse multi-service URLs for new endpoints (DAG pattern - no cycles)
    validate_services = parse_service_urls("VALIDATE_SERVICES_URL")
    fetch_services = parse_service_urls("FETCH_SERVICES_URL")
    verify_services = parse_service_urls("VERIFY_SERVICES_URL")
    check_services = parse_service_urls("CHECK_SERVICES_URL")

    @app.get("/health")
    def health():
        logger.info(f"{service_name} health check ok")
        return {"status": "ok", "service": service_name}

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

    return app
