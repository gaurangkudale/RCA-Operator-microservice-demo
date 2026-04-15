# Production Microservice API Patterns Guide

## Overview

This document explains the comprehensive API endpoints designed for production-grade microservices including CRUD operations, multi-service orchestration, resource management, and distributed tracing support.

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

---

## API Endpoints by Category

### 1. Health & Readiness Endpoints

#### `/health` - Health Check
Returns service health status with timestamp.

**Method:** GET  
**Purpose:** Basic service health verification

**Example Response:**
```json
{
  "status": "ok",
  "service": "user-service",
  "timestamp": "2026-04-16T10:30:45.123456"
}
```

#### `/ready` - Kubernetes Readiness Probe
Checks if service is ready to accept traffic.

**Method:** GET  
**Purpose:** Kubernetes readiness probe (traffic routing decision)

**Example Response:**
```json
{
  "ready": true,
  "service": "user-service",
  "resources_count": 42
}
```

---

### 2. CRUD Operations (Production Resource Management)

#### `/list` - Get All Resources
Retrieve list of all resources managed by the service.

**Method:** GET

**Example Response:**
```json
{
  "status": "success",
  "service": "user-service",
  "count": 3,
  "resources": [
    {
      "id": "res_1713267045123",
      "service": "user-service",
      "created_at": "2026-04-16T10:10:45.123456",
      "status": "active"
    }
  ],
  "timestamp": "2026-04-16T10:30:45.123456"
}
```

#### `/get/{resource_id}` - Get Specific Resource
Retrieve a specific resource by ID.

**Method:** GET  
**Path Parameter:** `resource_id` - ID of the resource

**Success Response:**
```json
{
  "status": "success",
  "service": "user-service",
  "resource": {
    "id": "res_1713267045123",
    "service": "user-service",
    "created_at": "2026-04-16T10:10:45.123456",
    "status": "active"
  }
}
```

**Error Response (404):**
```json
{
  "detail": "Resource res_unknown not found"
}
```

#### `/create` - Create New Resource
Create a new resource with auto-generated ID.

**Method:** POST

**Response:**
```json
{
  "status": "success",
  "service": "user-service",
  "resource_id": "res_1713267045123",
  "message": "Resource created successfully"
}
```

#### `/update/{resource_id}` - Update Resource
Update an existing resource by ID.

**Method:** PUT  
**Path Parameter:** `resource_id` - ID of the resource to update

**Response:**
```json
{
  "status": "success",
  "service": "user-service",
  "resource_id": "res_1713267045123",
  "message": "Resource updated successfully"
}
```

#### `/delete/{resource_id}` - Delete Resource
Delete a resource by ID.

**Method:** DELETE  
**Path Parameter:** `resource_id` - ID of the resource to delete

**Response:**
```json
{
  "status": "success",
  "service": "user-service",
  "resource_id": "res_1713267045123",
  "deleted_resource": {
    "id": "res_1713267045123",
    "service": "user-service",
    "created_at": "2026-04-16T10:10:45.123456",
    "status": "active"
  },
  "message": "Resource deleted successfully"
}
```

#### `/search?query=<string>` - Search Resources
Search resources by query string.

**Method:** GET  
**Query Parameter:** `query` (optional) - Search query string

**Response:**
```json
{
  "status": "success",
  "service": "user-service",
  "query": "res_171",
  "result_count": 2,
  "results": [
    {
      "id": "res_1713267045123",
      "service": "user-service",
      "created_at": "2026-04-16T10:10:45.123456",
      "status": "active"
    }
  ]
}
```

---

### 3. Operation & State Management

#### `/status/{operation_id}` - Get Operation Status
Get status of a previously executed operation.

**Method:** GET  
**Path Parameter:** `operation_id` - ID of the operation

**Response (Found):**
```json
{
  "status": "success",
  "service": "user-service",
  "operation_id": "op-123",
  "operation_status": {
    "operation": "create",
    "status": "completed"
  }
}
```

**Response (Not Found):**
```json
{
  "status": "unknown",
  "service": "user-service",
  "operation_id": "op-unknown",
  "message": "Operation not found"
}
```

#### `/rollback/{operation_id}` - Rollback Operation
Rollback a previous operation.

**Method:** POST  
**Path Parameter:** `operation_id` - ID of the operation to rollback

**Response:**
```json
{
  "status": "success",
  "service": "user-service",
  "operation_id": "op-123",
  "original_status": {
    "operation": "create",
    "status": "completed"
  },
  "message": "Operation rolled back successfully"
}
```

---

### 4. Metrics & Monitoring

#### `/metrics` - Service Metrics
Get service metrics including resource counts and health status.

**Method:** GET

**Response:**
```json
{
  "service": "user-service",
  "timestamp": "2026-04-16T10:30:45.123456",
  "metrics": {
    "total_resources": 42,
    "total_operations": 156,
    "uptime_check": true,
    "memory_healthy": true
  }
}
```

---

### 5. New Multi-Service Endpoints

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

## Testing the APIs

### Health Checks
```bash
curl http://localhost:8080/health
curl http://localhost:8080/ready
```

### CRUD Operations
```bash
# Create resource
curl -X POST http://localhost:8080/create

# List all resources
curl http://localhost:8080/list

# Get specific resource
curl http://localhost:8080/get/res_1713267045123

# Search resources
curl "http://localhost:8080/search?query=res_171"

# Update resource
curl -X PUT http://localhost:8080/update/res_1713267045123

# Delete resource
curl -X DELETE http://localhost:8080/delete/res_1713267045123
```

### Operations & State
```bash
curl http://localhost:8080/status/op-123
curl -X POST http://localhost:8080/rollback/op-123
```

### Multi-Service Orchestration
```bash
curl http://localhost:8080/validate
curl http://localhost:8080/fetch-data
curl http://localhost:8080/verify
curl http://localhost:8080/check
curl http://localhost:8080/sync
curl http://localhost:8080/process
```

### Metrics & Monitoring
```bash
curl http://localhost:8080/metrics
```

### Fault Injection & Testing
```bash
curl http://localhost:8080/warn
curl http://localhost:8080/error
curl http://localhost:8080/simulate-cpu
curl http://localhost:8080/simulate-oom
curl http://localhost:8080/delay/3
```

## Load Testing Distribution

The load tester (`load-tester/main.py`) distributes requests across all endpoints with realistic production proportions:

- **Health & Status endpoints:** 15%
- **CRUD operations:** 25%
- **Multi-service orchestration:** 20%
- **Data operations:** 15%
- **Status & operation tracking:** 10%
- **Error scenarios:** 10%
- **Latency simulation:** 5%

This simulates real-world traffic patterns in production microservice environments.

## Tracing and Observability

All new endpoints automatically:
- Generate OpenTelemetry spans for each service call
- Include trace context propagation across services
- Log all calls with proper context
- Track timing and errors

This enables end-to-end distributed tracing through the microservice mesh.

## Production Features

✅ **CRUD Operations:** Full resource lifecycle management (create, read, update, delete, search)  
✅ **Resource Management:** Auto-generated IDs, timestamps, and status tracking  
✅ **Operation Tracking:** Status monitoring and rollback capabilities  
✅ **Health Probes:** Kubernetes-ready health and readiness endpoints  
✅ **Multi-Service Orchestration:** DAG-pattern based service composition  
✅ **Distributed Tracing:** Full OpenTelemetry instrumentation  
✅ **Metrics & Monitoring:** Service health and resource metrics  
✅ **Fault Injection:** Built-in testing endpoints for chaos engineering  
✅ **Error Handling:** Graceful failure handling across services  
✅ **No Circular Dependencies:** Services only call downstream (higher levels)  
✅ **Backward Compatible:** Original `/process` endpoint still works  
✅ **Flexible Configuration:** Easy to adjust via environment variables  
✅ **Realistic Load Testing:** Distributed requests matching production patterns  

## Guarantees

✅ **No Circular Dependencies:** Services only call downstream services (higher levels)
✅ **Scalability:** Can easily add more services by following DAG pattern
✅ **Observability:** Full distributed tracing support with OpenTelemetry
✅ **Backward Compatible:** Original `/process` endpoint still works
✅ **Flexible Configuration:** Easy to adjust service routing via environment variables
✅ **Production Ready:** CRUD operations, state management, and health checks
✅ **Realistic Traffic:** Load tester simulates real-world microservice patterns

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
