# RCA-Operator Microservice Demo

This repository contains a realistic e-commerce microservice simulator, a load generator, and a comprehensive Helm chart designed to test the Phase 2 correlation engine of the [RCA-Operator](https://github.com/gaurangkudale/RCA-Operator/pull/111).

## Architecture

The system consists of the following core e-commerce services (all FastAPI services with structured logs and production resilience patterns):

1. `frontend`
2. `product-catalog`
3. `cart`
4. `checkout`
5. `payment`
6. `shipping`
7. `email`
8. `quote`
9. `ad-service`

**Production-Ready Features:**

All services include:
- **Resilient HTTP sessions** with connection pooling
- **Retry logic** with exponential backoff and jitter
- **Circuit breaker pattern** to prevent cascading failures
- **Bulkhead pattern** to limit concurrent calls per dependency
- **Dependency health monitoring** exposed via `/dependencies/health`
- **Graceful degradation** for non-critical side-effects (e.g., email)
- **Request tracing** with unique request IDs across all calls

**Supporting Services:**

- **Load Generator**: A Python script continuously generating realistic multi-step workflows (browse→cart→checkout) plus health checks, chaos injection, and mesh fanout probes.
- **PostgreSQL**: A simple database provisioned via the Bitnami Helm chart dependency.
- **Observability Stack**: Prometheus (for RED metrics), Jaeger (for distributed traces), and optionally Signoz.

## API Endpoints

Each service exposes the following endpoints (with fault injection built-in):

### Health & Status Endpoints

- `/health`: Returns 200 OK with service status and timestamp.
- `/ready`: Kubernetes readiness probe.
- `/dependencies/health`: Circuit breaker state and dependency health (production-ready).

### Core E-Commerce APIs (Canonical)

- `/products` (frontend): product browse entrypoint.
- `/cart/add` (frontend/cart): add item to cart.
- `/checkout` (frontend/checkout): orchestrates quote -> payment -> shipping -> email.
- `/products` and `/products/{id}` (product-catalog): catalog data.
- `/cart/{userId}` (cart): fetch current cart.
- `/quote` (quote): compute total with discounts.
- `/discounts?userId=` (ad-service): discount rules.
- `/payment/charge`, `/payment/refund` (payment): payment operations.
- `/shipping/create`, `/shipping/{orderId}` (shipping): shipment operations.
- `/email/send` (email): notification side-effect.

### Testing & Fault Injection

- `/warn`: emits warning log signal.
- `/error`: emits error log signal.
- `/simulate-cpu`: spikes CPU usage for 2 seconds.
- `/delay/{seconds}`: simulates latency.
- `/mesh/ping-all`: each service calls every other service's `/health`, `/warn`, and `/error` endpoints.

### Service Dependency Graph (DAG Pattern)

```text
frontend
  -> product-catalog
  -> cart
  -> checkout
     -> quote
        -> ad-service
     -> payment
     -> shipping
     -> email
```

**Controlled Failure Knobs (Env Vars):**

- `PAYMENT_FAILURE_RATE` (default `0.15`)
- `PAYMENT_SLOW_PROB` (default `0.2`)
- `SHIPPING_FAILURE_RATE` (default `0.1`)
- `SHIPPING_WARNING_RATE` (default `0.2`)
- `CATALOG_LATENCY_PROB` (default `0.2`)
- `CATALOG_ERROR_PROB` (default `0.05`)
- `AD_DELAY_PROB` (default `0.2`)
- `AD_ERROR_PROB` (default `0.03`)
- `QUOTE_MISMATCH_RATE` (default `0.05`)
- `EMAIL_WARNING_RATE` (default `0.1`)

These are set in `helm/rca-demo/values.yaml` for reproducible RCA test scenarios.

## Setup Instructions

### Prerequisites

1. Docker
2. Kubernetes Cluster (for example, `minikube` or `kind`)
3. Helm

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

The load generator pod now runs production-ready traffic patterns:

**Traffic Distribution (per cycle):**
- **60% Realistic Workflows**: Multi-step e-commerce scenarios (browse → cart → checkout, etc.) that naturally trigger cross-service dependency chains.
- **20% Health Checks**: Service health and readiness probes with dependency monitoring.
- **10% Fault Injection**: Synthetic errors and latency for chaos testing and observability validation.
- **10% Mesh Fanout**: Each service calls every other service via `/mesh/ping-all` endpoint, generating dense distributed traces.

**Workflows include:**
- Browse products → Add to cart → Checkout (full transaction with payment, shipping, email)
- Catalog browsing with discount rule queries
- Quote calculation triggering product lookups
- Payment + shipping coordination
- Multi-user concurrent shopping

All traffic carries unique request IDs for tracing through the entire call chain, and generates info/warning/error logs based on response status codes.

### 5. Access the Observability UIs

To visualize the traces, metrics, and logs being generated, you can port-forward the respective services to your local machine.

#### Access Jaeger UI (Default)

Jaeger is enabled by default to visualize distributed traces. Port-forward the `jaeger-query` service:

```bash
kubectl port-forward svc/rca-demo-jaeger-query 16686:80 -n rca-demo
```

- Open your browser to: [http://localhost:16686](http://localhost:16686)

#### Access Signoz UI (If Enabled)

If you installed the chart with `--set signoz.enabled=true`, Signoz provides a unified UI for traces, metrics, and logs. Port-forward the Signoz frontend service:

```bash
kubectl port-forward svc/rca-demo-signoz-frontend 3301:3301 -n rca-demo
```

- Open your browser to: [http://localhost:3301](http://localhost:3301)

### 6. Observe Telemetry for RCA-Operator

Because OpenTelemetry and python-json-logger are properly configured, all standard output logs from the pods will be emitted in structured JSON format with `TraceID`, `SpanID`, `Severity`, and `Exception` fields, matching the ingestion patterns required by the RCA-Operator's Correlation Engine.
