# RCA-Operator Microservice Demo

This repository contains a realistic e-commerce microservice simulator, a load generator, and a comprehensive Helm chart designed to test the Phase 2 correlation engine of the [RCA-Operator](https://github.com/gaurangkudale/RCA-Operator/pull/111).

## Architecture

The system consists of the following core e-commerce services (all FastAPI services with structured logs):

1. `frontend`
2. `product-catalog`
3. `cart`
4. `checkout`
5. `payment`
6. `shipping`
7. `email`
8. `quote`
9. `ad-service`

**Supporting Services:**

- **Load Generator**: A Python script continuously generating realistic shopper traffic (browse, cart, checkout, payment, shipping, email) plus controlled failure patterns.
- **PostgreSQL**: A simple database provisioned via the Bitnami Helm chart dependency.
- **Observability Stack**: Prometheus (for RED metrics), Jaeger (for distributed traces), and optionally Signoz.

## API Endpoints

Each service exposes the following endpoints (with fault injection built-in):

### Health & Status Endpoints

- `/health`: Returns 200 OK with service status and timestamp.
- `/ready`: Kubernetes readiness probe.

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

The load generator pod starts hitting the `frontend` and other core services automatically, generating rich telemetry data with realistic request IDs, warnings, and error bursts.

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
