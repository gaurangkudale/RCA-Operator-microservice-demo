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
-   `/health`: Returns 200 OK.
-   `/process`: Triggers a cascading call down the service chain.
-   `/warn`: Logs a warning with trace context.
-   `/error`: Logs a deliberate error and throws a 500 HTTP Exception.
-   `/simulate-oom`: Triggers a Python `MemoryError` and logs an OutOfMemory-like trace.
-   `/simulate-cpu`: Spikes CPU usage for 2 seconds.

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

### 5. Access Jaeger
Port-forward Jaeger to view the distributed traces:

```bash
kubectl port-forward svc/rca-demo-jaeger-query 16686:16686 -n rca-demo
```
Open [http://localhost:16686](http://localhost:16686) in your browser. You will see traces containing errors, cascading failures, and standard health checks.

### 6. Observe Telemetry for RCA-Operator
Because OpenTelemetry and python-json-logger are properly configured, all standard output logs from the pods will be emitted in structured JSON format with `TraceID`, `SpanID`, `Severity`, and `Exception` fields, matching the ingestion patterns required by the RCA-Operator's Correlation Engine.