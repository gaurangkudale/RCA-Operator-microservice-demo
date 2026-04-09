from fastapi import FastAPI, HTTPException, Response
import os
import requests
import time
from pydantic import BaseModel
from typing import Optional
from common.telemetry import setup_telemetry

def create_app(service_name: str):
    app = FastAPI(title=service_name)
    logger = setup_telemetry(app, service_name)
    
    # Optional downstream service to call
    next_service_url = os.getenv("NEXT_SERVICE_URL")

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
