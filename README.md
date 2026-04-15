# RCA-Operator Microservice Demo

This repository contains a 6-microservice architecture, a load tester, and a comprehensive Helm chart designed to test the Phase 2 correlation engine of the [RCA-Operator](https://github.com/gaurangkudale/RCA-Operator/pull/111).

## Architecture

The system consists of the following 6 FastAPI microservices linked in a chain, each equipped with OpenTelemetry (traces, metrics, and logs):
1.  `proxy-service`
2.  `auth-service`
3.  `user-service`
4.  `order-service`
5.  `payment-service`
6.  `inventory-service`

**Supporting Services:**
-   **Load Tester**: A Python script continuously calling the `proxy-service` with a random mix of success and failure requests (4xx, 5xx, CPU spikes, OOM simulations).
-   **PostgreSQL**: A simple database provisioned via the Bitnami Helm chart dependency.
-   **Observability Stack**: Prometheus (for RED metrics), Jaeger (for Distributed Traces), and optionally Signoz.

## API Endpoints

Each service exposes the following endpoints (with fault injection built-in):

### Health & Status Endpoints
-   `/health`: Returns 200 OK with service status and timestamp.
-   `/ready`: Kubernetes readiness probe - checks if service is ready to accept traffic and reports resource count.

### CRUD Operations (Production Resource Management)
-   `/list`: Get list of all resources managed by the service.
-   `/get/{resource_id}`: Get a specific resource by ID.
-   `/create`: Create a new resource with auto-generated ID.
-   `/update/{resource_id}`: Update an existing resource by ID.
-   `/delete/{resource_id}`: Delete a resource by ID.
-   `/search?query=<string>`: Search resources by query string.

### Multi-Service Orchestration (DAG Pattern - No Circular Calls)
-   `/process`: Triggers a cascading call down the service chain (original linear pattern).
-   `/validate`: Validates through multiple downstream services configured via `VALIDATE_SERVICES_URL`.
-   `/fetch-data`: Fetches aggregated data from multiple downstream services via `FETCH_SERVICES_URL`.
-   `/verify`: Performs cross-service verification via `VERIFY_SERVICES_URL`.
-   `/check`: Checks health status across multiple downstream services via `CHECK_SERVICES_URL`.
-   `/sync`: Synchronizes state with downstream services configured via `SYNC_SERVICES_URL`.

### Operation & State Management
-   `/status/{operation_id}`: Get status of a previously executed operation.
-   `/rollback/{operation_id}`: Rollback a previous operation (POST request).
-   `/metrics`: Get service metrics including resource counts and health status.

### Testing & Fault Injection
-   `/warn`: Logs a warning with trace context.
-   `/error`: Logs a deliberate error and throws a 500 HTTP Exception.
-   `/simulate-oom`: Triggers a Python `MemoryError` and logs an OutOfMemory-like trace.
-   `/simulate-cpu`: Spikes CPU usage for 2 seconds.
-   `/delay/{seconds}`: Simulate network latency by sleeping for N seconds (max 30).

### Service Dependency Graph (DAG Pattern)
```
                    proxy-service (entry point)
                    /        |          \
                   /         |           \
            auth-service  user-service  order-service
                 |        /        \          |
                 |       /          \         |
                 |      /            \        |
                 |     /              \       |
            user-service         payment-service
                 |                    /       |
                 |                   /        |
                 |                  /         |
                 |                 /          |
            inventory-service ←----/----------/
```

**Environment Variables for Multi-Service Routing:**
Each service can be configured with the following environment variables (comma-separated service URLs):
- `VALIDATE_SERVICES_URL`: Services to call for `/validate` endpoint
- `FETCH_SERVICES_URL`: Services to call for `/fetch-data` endpoint
- `VERIFY_SERVICES_URL`: Services to call for `/verify` endpoint
- `CHECK_SERVICES_URL`: Services to call for `/check` endpoint
- `SYNC_SERVICES_URL`: Services to call for `/sync` endpoint

These are configured in `helm/rca-demo/values.yaml` to follow a Directed Acyclic Graph (DAG) pattern, ensuring no circular API calls.

## Setup Instructions

### Prerequisites
1.  Docker
2.  Kubernetes Cluster (e.g., `minikube` or `kind`)
3.  Helm

### 1. (Optional) Build Docker Images Locally
The Helm chart is configured by default to pull the pre-built images from the GitHub Container Registry (`ghcr.io/gaurangkudale/rca-operator-microservice-demo-...`).

If you prefer to build and test them locally, you can do so.

**For Minikube:**
```bash
eval $(minikube docker-env)

# Build the main microservice image
cd src
docker build -t ghcr.io/gaurangkudale/rca-operator-microservice-demo-app:main .
cd ..

# Build the load tester image
cd load-tester
docker build -t ghcr.io/gaurangkudale/rca-operator-microservice-demo-load-tester:main .
cd ..
```

**For Kind:**
```bash
cd src
docker build -t ghcr.io/gaurangkudale/rca-operator-microservice-demo-app:main .
cd ..
cd load-tester
docker build -t ghcr.io/gaurangkudale/rca-operator-microservice-demo-load-tester:main .
cd ..

kind load docker-image ghcr.io/gaurangkudale/rca-operator-microservice-demo-app:main
kind load docker-image ghcr.io/gaurangkudale/rca-operator-microservice-demo-load-tester:main
```

### 2. Deploy from GitHub Container Registry (GHCR)
You can directly deploy the packaged Helm chart from the GitHub Container Registry without needing to clone the repository or build the images manually.

1. **Login to Helm Registry (if the repository is private):**
   ```bash
   echo "YOUR_GITHUB_PAT" | helm registry login ghcr.io --username YOUR_GITHUB_USERNAME --password-stdin
   ```

2. **Install the Chart:**
   ```bash
   helm upgrade --install rca-demo oci://ghcr.io/gaurangkudale/charts/rca-demo-apps \
     --version 0.1.0 \
     --namespace rca-demo \
     --create-namespace
   ```

*(Note: Signoz is disabled by default to save resources. If you want to enable it, append `--set signoz.enabled=true` to the helm command)*

### 4. Verify the Deployment
Check that all pods are running successfully:

```bash
kubectl get pods -n rca-demo
```

The load tester pod should start hitting the `proxy-service` automatically, which in turn calls the other services, generating rich telemetry data.

### 5. Access the Observability UIs

To visualize the traces, metrics, and logs being generated, you can port-forward the respective services to your local machine.

**Access Jaeger UI (Default)**
Jaeger is enabled by default to visualize distributed traces. Port-forward the `jaeger-query` service:
```bash
kubectl port-forward svc/rca-demo-jaeger-query 16686:80 -n rca-demo
```
- Open your browser to: [http://localhost:16686](http://localhost:16686)

**Access Signoz UI (If Enabled)**
If you installed the chart with `--set signoz.enabled=true`, Signoz provides a unified UI for traces, metrics, and logs. Port-forward the Signoz frontend service:
```bash
kubectl port-forward svc/rca-demo-signoz-frontend 3301:3301 -n rca-demo
```
- Open your browser to: [http://localhost:3301](http://localhost:3301)

### 6. Observe Telemetry for RCA-Operator
Because OpenTelemetry and python-json-logger are properly configured, all standard output logs from the pods will be emitted in structured JSON format with `TraceID`, `SpanID`, `Severity`, and `Exception` fields, matching the ingestion patterns required by the RCA-Operator's Correlation Engine.