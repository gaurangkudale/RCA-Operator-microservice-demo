# Multi-Service API Patterns Guide

## Overview

This document explains the new multi-service API endpoints and how they follow a Directed Acyclic Graph (DAG) pattern to avoid circular API calls.

## Architecture

### 6 Microservices
1. **proxy-service** - Entry point, orchestrates requests
2. **auth-service** - Authentication service
3. **user-service** - User management service
4. **order-service** - Order processing service
5. **payment-service** - Payment handling service
6. **inventory-service** - Inventory management (leaf service)

### DAG (Directed Acyclic Graph) Pattern

The services are connected in a DAG pattern to ensure no circular dependencies:

```
proxy-service (level 0)
    ├── auth-service (level 1)
    ├── user-service (level 1)
    └── order-service (level 1)
        ├── payment-service (level 2)
        └── inventory-service (level 3)
```

**Key Rule:** A service at level N can only call services at level N+1 or higher (downstream only).

## New API Endpoints

### 1. `/validate` - Multi-Service Validation

Validates data/state across multiple downstream services.

**Purpose:** Ensure data consistency across services

**Configuration:** `VALIDATE_SERVICES_URL` environment variable

**Example Response:**
```json
{
  "status": "validated",
  "service": "proxy-service",
  "responses": [
    {
      "url": "http://auth-service:8080",
      "status": 200,
      "data": {"status": "validated", "service": "auth-service", ...}
    },
    {
      "url": "http://user-service:8080",
      "status": 200,
      "data": {"status": "validated", "service": "user-service", ...}
    }
  ]
}
```

### 2. `/fetch-data` - Aggregated Data Collection

Fetches and aggregates data from multiple downstream services.

**Purpose:** Gather data from multiple sources in a single call

**Configuration:** `FETCH_SERVICES_URL` environment variable

**Example Response:**
```json
{
  "status": "success",
  "service": "user-service",
  "aggregated_data": [
    {
      "url": "http://payment-service:8080",
      "status": 200,
      "data": {"status": "success", "service": "payment-service", ...}
    },
    {
      "url": "http://inventory-service:8080",
      "status": 200,
      "data": {"status": "success", "service": "inventory-service", ...}
    }
  ]
}
```

### 3. `/verify` - Cross-Service Verification

Performs verification checks across multiple services.

**Purpose:** Cross-validate state across services

**Configuration:** `VERIFY_SERVICES_URL` environment variable

**Example Response:**
```json
{
  "status": "verified",
  "service": "order-service",
  "verification_results": [
    {
      "url": "http://payment-service:8080",
      "status": 200,
      "data": {"status": "verified", "service": "payment-service", ...}
    },
    {
      "url": "http://inventory-service:8080",
      "status": 200,
      "data": {"status": "verified", "service": "inventory-service", ...}
    }
  ]
}
```

### 4. `/check` - Multi-Service Health Check

Checks health/status across multiple downstream services.

**Purpose:** Verify dependencies are healthy

**Configuration:** `CHECK_SERVICES_URL` environment variable

**Example Response:**
```json
{
  "status": "healthy",
  "service": "proxy-service",
  "dependency_status": [
    {
      "url": "http://auth-service:8080",
      "status": 200,
      "data": {"status": "healthy", "service": "auth-service", ...}
    },
    {
      "url": "http://inventory-service:8080",
      "status": 200,
      "data": {"status": "healthy", "service": "inventory-service", ...}
    }
  ]
}
```

## Service Configuration

### Environment Variables

Each service is configured with environment variables that specify which downstream services to call:

```yaml
NEXT_SERVICE_URL: "http://next-service:8080"           # Original (backward compatible)
VALIDATE_SERVICES_URL: "http://svc1:8080, http://svc2:8080"  # New
FETCH_SERVICES_URL: "http://svc1:8080, http://svc2:8080"     # New
VERIFY_SERVICES_URL: "http://svc1:8080"                       # New
CHECK_SERVICES_URL: "http://svc1:8080, http://svc2:8080"      # New
```

### Current Service Routing Configuration

#### proxy-service (Entry Point)
```yaml
VALIDATE_SERVICES_URL: http://auth-service:8080, http://user-service:8080
FETCH_SERVICES_URL: http://auth-service:8080, http://order-service:8080
VERIFY_SERVICES_URL: http://user-service:8080, http://payment-service:8080
CHECK_SERVICES_URL: http://auth-service:8080, http://inventory-service:8080
```

#### auth-service
```yaml
VALIDATE_SERVICES_URL: http://user-service:8080
FETCH_SERVICES_URL: http://user-service:8080, http://order-service:8080
VERIFY_SERVICES_URL: http://user-service:8080
CHECK_SERVICES_URL: http://payment-service:8080
```

#### user-service
```yaml
VALIDATE_SERVICES_URL: http://payment-service:8080, http://inventory-service:8080
FETCH_SERVICES_URL: http://order-service:8080, http://payment-service:8080
VERIFY_SERVICES_URL: http://inventory-service:8080
CHECK_SERVICES_URL: http://payment-service:8080, http://inventory-service:8080
```

#### order-service
```yaml
VALIDATE_SERVICES_URL: http://payment-service:8080, http://inventory-service:8080
FETCH_SERVICES_URL: http://payment-service:8080
VERIFY_SERVICES_URL: http://inventory-service:8080
CHECK_SERVICES_URL: http://inventory-service:8080
```

#### payment-service
```yaml
VALIDATE_SERVICES_URL: http://inventory-service:8080
FETCH_SERVICES_URL: http://inventory-service:8080
VERIFY_SERVICES_URL: http://inventory-service:8080
CHECK_SERVICES_URL: http://inventory-service:8080
```

#### inventory-service (Leaf Node)
```yaml
# No downstream services configured
```

## Testing the APIs

### Test /validate endpoint
```bash
curl http://localhost:8080/validate
```

### Test /fetch-data endpoint
```bash
curl http://localhost:8080/fetch-data
```

### Test /verify endpoint
```bash
curl http://localhost:8080/verify
```

### Test /check endpoint
```bash
curl http://localhost:8080/check
```

## Tracing and Observability

All new endpoints automatically:
- Generate OpenTelemetry spans for each service call
- Include trace context propagation across services
- Log all calls with proper context
- Track timing and errors

This enables end-to-end distributed tracing through the microservice mesh.

## Guarantees

✅ **No Circular Dependencies:** Services only call downstream services (higher levels)
✅ **Scalability:** Can easily add more services by following DAG pattern
✅ **Observability:** Full distributed tracing support with OpenTelemetry
✅ **Backward Compatible:** Original `/process` endpoint still works
✅ **Flexible Configuration:** Easy to adjust service routing via environment variables

## Adding New Services

To add a new service following this pattern:

1. Create a new service with the same FastAPI structure
2. Add it to the Helm chart configuration
3. Define its downstream services in environment variables
4. Ensure it only calls services at the next level in the DAG
5. Update the README documentation

Example: If adding a "notifications-service" at level 2:
- It can call inventory-service (level 3+)
- It cannot call proxy-service, auth-service, or user-service (level 0-1)

## Implementation Details

### Multi-Service Call Helper
The `call_downstream_service()` function in [src/common/service_base.py](src/common/service_base.py#L14-L26):
- Calls multiple services in parallel (via individual requests)
- Handles timeouts and errors gracefully
- Collects responses for aggregation
- Logs all calls with proper context

### Environment Variable Parsing
The `parse_service_urls()` function in [src/common/service_base.py](src/common/service_base.py#L7-L10):
- Parses comma-separated service URLs
- Handles whitespace and edge cases
- Returns a clean list of URLs

## Performance Considerations

- Each `/validate`, `/fetch-data`, `/verify`, `/check` call makes N downstream calls (N = number of configured services)
- These calls happen sequentially by default
- For production, consider implementing parallel calls for performance
- Timeout is set to 5 seconds per downstream call

## Error Handling

If a downstream service fails:
- The response is marked with status "failed"
- Error details are included in the response
- Errors are logged but don't stop the entire chain
- Caller receives partial results from successful services

Example error response:
```json
{
  "url": "http://payment-service:8080",
  "status": "failed",
  "error": "Connection timeout"
}
```

---

For more information, see [README.md](README.md) and the service implementation in [src/common/service_base.py](src/common/service_base.py).
