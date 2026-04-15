from fastapi import FastAPI, HTTPException
import os
import requests
import time
import json
from datetime import datetime
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
    
    # Mock in-memory storage for resources
    resources_db = {}
    operation_status = {}
    
    # Optional downstream service to call (for backward compatibility)
    next_service_url = os.getenv("NEXT_SERVICE_URL")
    
    # Parse multi-service URLs for new endpoints (DAG pattern - no cycles)
    validate_services = parse_service_urls("VALIDATE_SERVICES_URL")
    fetch_services = parse_service_urls("FETCH_SERVICES_URL")
    verify_services = parse_service_urls("VERIFY_SERVICES_URL")
    check_services = parse_service_urls("CHECK_SERVICES_URL")
    sync_services = parse_service_urls("SYNC_SERVICES_URL")

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
