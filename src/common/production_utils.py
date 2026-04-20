"""
Production-ready patterns: connection pooling, retries, circuit breaker, bulkhead.
"""

import requests
import time
import json
import logging
from typing import Dict, Any, Optional, Callable
from enum import Enum
from threading import Lock
from datetime import datetime, timedelta


class CircuitBreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Prevents cascading failures across service dependencies."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 30, name: str = "circuit"):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        self.failure_count = 0
        self.state = CircuitBreakerState.CLOSED
        self.last_failure_time: Optional[datetime] = None
        self.lock = Lock()

    def record_success(self):
        with self.lock:
            self.failure_count = 0
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.state = CircuitBreakerState.CLOSED

    def record_failure(self):
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = datetime.utcnow()
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN

    def can_attempt(self) -> bool:
        with self.lock:
            if self.state == CircuitBreakerState.CLOSED:
                return True
            if self.state == CircuitBreakerState.OPEN:
                if self.last_failure_time and datetime.utcnow() >= self.last_failure_time + timedelta(seconds=self.recovery_timeout):
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.failure_count = 0
                    return True
                return False
            # HALF_OPEN
            return True

    def get_state(self) -> str:
        with self.lock:
            return self.state.value


class AdaptiveRetry:
    """Exponential backoff with jitter for transient failures."""

    def __init__(self, max_retries: int = 3, base_delay_ms: int = 100, max_delay_ms: int = 5000):
        self.max_retries = max_retries
        self.base_delay_ms = base_delay_ms
        self.max_delay_ms = max_delay_ms

    def get_delay_ms(self, attempt: int) -> int:
        """Calculate exponential backoff with jitter."""
        delay = self.base_delay_ms * (2 ** attempt)
        delay = min(delay, self.max_delay_ms)
        jitter = int(delay * 0.1 * (2 * (hash(datetime.utcnow().isoformat()) % 100) / 100 - 1))
        return max(1, delay + jitter)

    def should_retry(self, status_code: Optional[int], exception: Optional[Exception]) -> bool:
        if exception:
            return isinstance(exception, (requests.ConnectionError, requests.Timeout))
        if status_code:
            return status_code in (408, 429, 500, 502, 503, 504)
        return False


class BulkheadLimiter:
    """Limits concurrent calls per dependency (bulkhead pattern)."""

    def __init__(self, max_concurrent: int = 10):
        self.max_concurrent = max_concurrent
        self.current_count = 0
        self.lock = Lock()

    def acquire(self) -> bool:
        with self.lock:
            if self.current_count < self.max_concurrent:
                self.current_count += 1
                return True
            return False

    def release(self):
        with self.lock:
            self.current_count = max(0, self.current_count - 1)

    def get_load(self) -> float:
        with self.lock:
            return self.current_count / self.max_concurrent


class ResilientHTTPSession:
    """Production-ready HTTP session with pooling, retries, circuit breaker, and bulkhead."""

    def __init__(self, service_name: str, logger: logging.Logger):
        self.service_name = service_name
        self.logger = logger
        self.session = requests.Session()
        # Connection pooling
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20,
            pool_maxsize=20,
            max_retries=requests.adapters.Retry(
                total=0,  # We handle retries manually
                connect=0,
                read=0,
                redirect=0,
                status=0,
            ),
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Production patterns per dependency
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.retry_policies: Dict[str, AdaptiveRetry] = {}
        self.bulkheads: Dict[str, BulkheadLimiter] = {}

    def get_circuit_breaker(self, dependency: str) -> CircuitBreaker:
        if dependency not in self.circuit_breakers:
            self.circuit_breakers[dependency] = CircuitBreaker(name=f"{self.service_name}->{dependency}")
        return self.circuit_breakers[dependency]

    def get_retry_policy(self, dependency: str) -> AdaptiveRetry:
        if dependency not in self.retry_policies:
            self.retry_policies[dependency] = AdaptiveRetry()
        return self.retry_policies[dependency]

    def get_bulkhead(self, dependency: str) -> BulkheadLimiter:
        if dependency not in self.bulkheads:
            self.bulkheads[dependency] = BulkheadLimiter(max_concurrent=10)
        return self.bulkheads[dependency]

    def call_service_resilient(
        self,
        base_url: str,
        method: str,
        endpoint: str,
        request_id: str,
        dependency: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: int = 6,
        on_log: Optional[Callable] = None,
    ) -> tuple:
        """
        Call a service with production resilience patterns.
        Returns (response, latency_ms, success: bool, reason: str)
        """
        if not base_url:
            reason = f"Missing URL for dependency {dependency}"
            if on_log:
                on_log("error", self.service_name, f"/{endpoint}", request_id, message=reason, dependency=dependency)
            return None, 0, False, reason

        circuit_breaker = self.get_circuit_breaker(dependency)
        retry_policy = self.get_retry_policy(dependency)
        bulkhead = self.get_bulkhead(dependency)

        if not circuit_breaker.can_attempt():
            reason = f"Circuit breaker {circuit_breaker.get_state()} for {dependency}"
            if on_log:
                on_log("warning", self.service_name, endpoint, request_id, message=reason, dependency=dependency)
            return None, 0, False, reason

        if not bulkhead.acquire():
            reason = f"Bulkhead limit exceeded for {dependency}"
            if on_log:
                on_log("warning", self.service_name, endpoint, request_id, message=reason, dependency=dependency)
            return None, 0, False, reason

        try:
            started_at = time.time()
            attempt = 0

            while attempt <= retry_policy.max_retries:
                try:
                    response = self.session.request(
                        method=method,
                        url=f"{base_url}{endpoint}",
                        headers={"x-request-id": request_id},
                        json=payload,
                        timeout=timeout,
                    )
                    latency_ms = int((time.time() - started_at) * 1000)

                    if 200 <= response.status_code < 300:
                        circuit_breaker.record_success()
                        if on_log and latency_ms > 200:
                            on_log("info", self.service_name, endpoint, request_id, message="Dependency call succeeded with notable latency", dependency=dependency, latency_ms=latency_ms)
                        return response, latency_ms, True, "success"
                    elif retry_policy.should_retry(response.status_code, None):
                        if attempt < retry_policy.max_retries:
                            delay_ms = retry_policy.get_delay_ms(attempt)
                            if on_log:
                                on_log("warning", self.service_name, endpoint, request_id, message=f"Retryable error {response.status_code}, attempt {attempt + 1}/{retry_policy.max_retries}", dependency=dependency, retry_attempt=attempt + 1)
                            time.sleep(delay_ms / 1000.0)
                            attempt += 1
                            continue
                        circuit_breaker.record_failure()
                        reason = f"Failed after {retry_policy.max_retries} retries (status {response.status_code})"
                        if on_log:
                            on_log("error", self.service_name, endpoint, request_id, message=reason, dependency=dependency, status_code=response.status_code)
                        return response, latency_ms, False, reason
                    else:
                        circuit_breaker.record_failure()
                        latency_ms = int((time.time() - started_at) * 1000)
                        reason = f"Non-retryable error {response.status_code}"
                        if on_log:
                            on_log("error", self.service_name, endpoint, request_id, message=reason, dependency=dependency, status_code=response.status_code)
                        return response, latency_ms, False, reason

                except (requests.ConnectionError, requests.Timeout) as exc:
                    if attempt < retry_policy.max_retries:
                        delay_ms = retry_policy.get_delay_ms(attempt)
                        if on_log:
                            on_log("warning", self.service_name, endpoint, request_id, message=f"Connection error, retrying (attempt {attempt + 1}/{retry_policy.max_retries})", dependency=dependency, error=str(exc), retry_attempt=attempt + 1)
                        time.sleep(delay_ms / 1000.0)
                        attempt += 1
                        continue
                    circuit_breaker.record_failure()
                    latency_ms = int((time.time() - started_at) * 1000)
                    if on_log:
                        on_log("error", self.service_name, endpoint, request_id, message=f"Dependency unavailable after {retry_policy.max_retries} retries", dependency=dependency, error=str(exc))
                    return None, latency_ms, False, str(exc)

        finally:
            bulkhead.release()

        return None, 0, False, "Unknown error"

    def get_health_status(self) -> Dict[str, Any]:
        """Return circuit breaker states for all dependencies."""
        return {
            dep: {
                "state": cb.get_state(),
                "failure_count": cb.failure_count,
            }
            for dep, cb in self.circuit_breakers.items()
        }

    def close(self):
        """Close the session."""
        self.session.close()
