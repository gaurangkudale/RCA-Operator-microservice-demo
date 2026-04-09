import os
from common.service_base import create_app

service_name = os.getenv("SERVICE_NAME", "unknown-service")
app = create_app(service_name)
