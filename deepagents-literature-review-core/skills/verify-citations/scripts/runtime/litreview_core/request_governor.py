"""Portable shared request admission for the 90 minute review budget.

The byte based estimate deliberately over-reserves ordinary text. It is not a
model tokenizer or a claim about measured provider throughput. No text is cut.
"""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
import json
import math
import threading
import time
from typing import Any, Callable, Iterator, Mapping

from .provider_routes import ROUTES, resolve_routes


class ContextCapacityError(ValueError):
    """The caller must split the task or change its explicit capacity settings."""


@dataclass(frozen=True)
class ThroughputConfig:
    workers: int = 16
    active_token_limit: int = 1_000_000
    context_limit: int = 200_000
    context_margin: int = 8_000
    rpm: int | None = None
    tpm: int | None = None
    deadline_seconds: float = 5_400
    hard_deadline: bool = True
    minimum_workers: int = 2
    recovery_successes: int = 8
    # Optional complete-request Qwen counter, including message/tool framing.
    # Do not pass len(text) here: callers must supply a real tokenizer adapter.
    token_counter: Callable[[Mapping[str, Any]], int] | None = field(default=None, repr=False, compare=False)
    # Conservative admission defaults; update this snapshot as endpoints change.
    provider_contexts: Mapping[str, int] = field(default_factory=lambda: {
        "cerebras": 65_536, "modelrun": 262_144, "deepinfra": 262_144,
    })

    def __post_init__(self):
        for name in ("workers", "active_token_limit", "context_limit", "minimum_workers", "recovery_successes"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.context_limit > 200_000:
            raise ValueError("context_limit cannot exceed the requested 200000 cap")
        if not 0 <= self.context_margin < self.context_limit:
            raise ValueError("context_margin must fit within context_limit")
        if self.deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive")
        for name in ("rpm", "tpm"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive or None (unknown)")
        if not self.provider_contexts or any(n <= 0 for n in self.provider_contexts.values()):
            raise ValueError("provider_contexts must contain positive capacities")


@dataclass
class RequestPermit:
    request_id: int
    input_estimate: int
    output_budget: int
    reservation: int
    admitted_at: float
    wait_seconds: float
    usage: dict[str, Any] | None = None
    provider: str | None = None
    response_id: str | None = None
    finish_reasons: list[str | None] = field(default_factory=list)
    reasoning_observation: dict | None = None
    http_status: int | None = None
    retry_after: str | None = None
    provider_error: dict | None = None


def estimate_input_tokens(payload: Mapping[str, Any]) -> int:
    """Conservative UTF-8 byte budget, including framing allowance.

    One token per serialized UTF-8 byte plus framing is intentionally generous
    for common byte/subword tokenizers. A provider tokenizer remains necessary
    for an exact count. The entire payload is counted, including tools/schemas.
    """
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                         default=str).encode("utf-8")
    messages = payload.get("messages", [])
    return len(encoded) + 1_024 + 32 * len(messages)


class RequestGovernor:
    """One process-wide governor shared by every role and worker.

    RPM/TPM limits are disabled when unknown. TPM admission uses reserved tokens,
    not billed usage; actual usage is separately recorded for calibration.
    A hard deadline prevents further admission; completion still requires artifact gates.
    """

    def __init__(self, config: ThroughputConfig | None = None):
        self.config = config or ThroughputConfig()
        self._condition = threading.Condition()
        self._started_at = time.monotonic()
        self._closed = False
        self._pipeline_complete = False
        self._finished_elapsed: float | None = None
        self._active = 0
        self._logical_workers = self.config.workers
        self._success_streak = 0
        self._retries = 0
        self._adaptive_events: deque[dict[str, Any]] = deque(maxlen=2_000)
        self._active_tokens = 0
        self._peak_active = 0
        self._peak_tokens = 0
        self._next_id = 0
        self._completed = 0
        self._failed = 0
        self._total_wait = 0.0
        self._usage_input = 0
        self._usage_output = 0
        self._window: deque[tuple[float, int]] = deque()
        self._events: deque[dict[str, Any]] = deque(maxlen=2_000)

    def reservation_for(self, payload: Mapping[str, Any]) -> tuple[int, int, int]:
        input_estimate = (self.config.token_counter(payload) if self.config.token_counter
                          else estimate_input_tokens(payload))
        if not isinstance(input_estimate, int) or input_estimate < 0:
            raise ValueError("token_counter must return a nonnegative integer")
        output_budget = payload.get("max_completion_tokens", payload.get("max_tokens"))
        if output_budget is None or int(output_budget) <= 0:
            raise ContextCapacityError("Set a positive max_tokens before request admission")
        output_budget = int(output_budget)
        reservation = input_estimate + output_budget + self.config.context_margin
        if reservation > self.config.context_limit:
            raise ContextCapacityError(
                f"Estimated request reservation {reservation} exceeds context cap "
                f"{self.config.context_limit} (UTF-8 input budget {input_estimate}, "
                f"output {output_budget}, margin {self.config.context_margin}). "
                "Split the assigned evidence/task; no content was truncated."
            )
        if reservation > self.config.active_token_limit:
            raise ContextCapacityError(
                f"Request reservation {reservation} exceeds active_token_limit "
                f"{self.config.active_token_limit}; split the task or raise that limit."
            )
        if self.config.tpm is not None and reservation > self.config.tpm:
            raise ContextCapacityError(
                f"Request reservation {reservation} exceeds configured TPM {self.config.tpm}; "
                "split the task or correct the account quota setting."
            )
        return input_estimate, output_budget, reservation

    def provider_preferences(self, preferences: Mapping[str, Any] | None,
                             reservation: int, *, max_tokens: int | None = None) -> dict[str, Any]:
        """Route only to pinned capabilities; new routes require explicit opt-in.

        Base names resolve to known exact tags, never arbitrary variants. Legacy
        callers may omit max_tokens; real transport always supplies the budget.
        """
        result = dict(preferences or {})
        capacities = {key.lower(): value for key, value in self.config.provider_contexts.items()}
        if max_tokens is not None and (type(max_tokens) is not int or max_tokens <= 0):
            raise ValueError('max_tokens must be a positive integer when checking route output capacity')

        def expand(names):
            if not isinstance(names, (list, tuple)):
                raise ContextCapacityError('Provider preferences require lists of verified names')
            expanded = []
            for name in names:
                try:
                    for tag in resolve_routes(name):
                        if tag not in expanded:
                            expanded.append(tag)
                except ValueError as error:
                    raise ContextCapacityError(str(error)) from error
            return expanded

        ignored = set(expand(result.get('ignore', [])))
        # The historical default config has exactly three bases. Adding routes
        # to the pinned registry alone never makes them auto-routing candidates.
        requested = expand(result['only']) if 'only' in result else expand(list(capacities))
        permitted = []
        for tag in requested:
            route = ROUTES[tag]
            configured = capacities.get(tag, capacities.get(tag.split('/', 1)[0], route.context_length))
            if (tag not in ignored and route.named_function and min(configured, route.context_length) >= reservation
                    and (max_tokens is None or route.max_completion_tokens >= max_tokens)):
                permitted.append(tag)
        if not permitted:
            raise ContextCapacityError(
                f"No verified provider fits reservation {reservation} and provider preferences. "
                f"Pinned capacities: {capacities}; requested output {max_tokens}. Split the task or change provider settings."
            )
        ordered = [tag for tag in expand(result.get('order', [])) if tag in permitted]
        ordered.extend(tag for tag in permitted if tag not in ordered)
        result["only"] = permitted
        result["order"] = ordered
        result['require_parameters'] = True
        # Existing sort/quantizations/require_parameters/fallback/ignore settings survive.
        return result

    def _try_acquire(self, costs: tuple[int, int, int], began: float) -> RequestPermit | None:
        """Caller holds the condition. Admission is shared by sync and async paths."""
        now = time.monotonic()
        if self.config.hard_deadline and now - self._started_at >= self.config.deadline_seconds:
            raise TimeoutError("Review deadline exceeded; retain incomplete checkpoint")
        if self._closed:
            raise RuntimeError("RequestGovernor is closed")
        while self._window and now - self._window[0][0] >= 60:
            self._window.popleft()
        input_estimate, output_budget, reservation = costs
        if self._active >= self._logical_workers:
            return None
        if self._active_tokens + reservation > self.config.active_token_limit:
            return None
        if self.config.rpm is not None and len(self._window) >= self.config.rpm:
            return None
        if self.config.tpm is not None and sum(n for _, n in self._window) + reservation > self.config.tpm:
            return None
        self._next_id += 1
        self._active += 1
        self._active_tokens += reservation
        self._peak_active = max(self._peak_active, self._active)
        self._peak_tokens = max(self._peak_tokens, self._active_tokens)
        self._window.append((now, reservation))
        permit = RequestPermit(self._next_id, input_estimate, output_budget,
                               reservation, now, now - began)
        self._total_wait += permit.wait_seconds
        return permit

    def acquire(self, payload: Mapping[str, Any]) -> RequestPermit:
        costs = self.reservation_for(payload)
        began = time.monotonic()
        with self._condition:
            while (permit := self._try_acquire(costs, began)) is None:
                self._condition.wait(timeout=0.25)
            return permit

    async def acquire_async(self, payload: Mapping[str, Any]) -> RequestPermit:
        # No executor thread can acquire after the coroutine has been cancelled.
        costs = self.reservation_for(payload)
        began = time.monotonic()
        while True:
            with self._condition:
                permit = self._try_acquire(costs, began)
            if permit is not None:
                return permit
            await asyncio.sleep(0.05)

    def release(self, permit: RequestPermit, *, error: BaseException | None = None):
        with self._condition:
            self._active -= 1
            self._active_tokens -= permit.reservation
            if error is None:
                self._completed += 1
            else:
                self._failed += 1
            usage = permit.usage or {}
            self._usage_input += int(usage.get("prompt_tokens") or 0)
            self._usage_output += int(usage.get("completion_tokens") or 0)
            now = time.monotonic()
            self._adjust_concurrency(error, now)
            self._events.append({
                "request_id": permit.request_id,
                "elapsed_seconds": round(now - self._started_at, 3),
                "wait_seconds": round(permit.wait_seconds, 3),
                "request_seconds": round(now - permit.admitted_at, 3),
                "input_estimate": permit.input_estimate,
                "output_budget": permit.output_budget,
                "reservation": permit.reservation,
                "provider": permit.provider,
                "response_id": permit.response_id,
                "finish_reasons": permit.finish_reasons,
                "reasoning_observation": permit.reasoning_observation,
                "http_status": permit.http_status,
                "retry_after": permit.retry_after,
                "provider_error": permit.provider_error,
                "usage": usage,
                "error_type": type(error).__name__ if error else None,
                "deadline_exceeded": now - self._started_at > self.config.deadline_seconds,
            })
            self._condition.notify_all()

    def _adjust_concurrency(self, error: BaseException | None, now: float):
        """Called under the condition, after the attempt releases its slot."""
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        timed_out = isinstance(error, TimeoutError) or type(error).__name__ in {
            "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout", "TimeoutException",
        }
        previous = self._logical_workers
        floor = min(self.config.minimum_workers, self.config.workers)
        if status == 429:
            self._logical_workers = max(floor, self._logical_workers // 2)
            self._success_streak = 0
        elif status in (502, 503, 504) or timed_out:
            self._logical_workers = max(floor, self._logical_workers - 1)
            self._success_streak = 0
        elif error is None:
            self._success_streak += 1
            if self._success_streak >= self.config.recovery_successes:
                self._logical_workers = min(self.config.workers, self._logical_workers + 1)
                self._success_streak = 0
        else:
            self._success_streak = 0
        if self._logical_workers != previous:
            self._adaptive_events.append({
                "kind": "concurrency_change",
                "elapsed_seconds": round(now - self._started_at, 3),
                "previous_workers": previous, "logical_workers": self._logical_workers,
                "http_status": status,
                "error_type": type(error).__name__ if error else None,
            })

    def note_retry(self, error: Exception, delay_seconds: float, attempt: int):
        """Record a retry outside any active permit; no request content is logged."""
        with self._condition:
            remaining = self.config.deadline_seconds - (time.monotonic() - self._started_at)
            if self.config.hard_deadline and delay_seconds >= remaining:
                self._adaptive_events.append({'kind': 'retry_exceeds_deadline',
                    'attempt': attempt, 'delay_seconds': delay_seconds,
                    'remaining_seconds': max(0, remaining)})
                raise TimeoutError('Required retry delay exceeds remaining review deadline; no retry issued')
            self._retries += 1
            self._adaptive_events.append({
                "kind": "transport_retry",
                "elapsed_seconds": round(time.monotonic() - self._started_at, 3),
                "attempt": attempt, "delay_seconds": round(delay_seconds, 3),
                "http_status": getattr(getattr(error, "response", None), "status_code", None),
                "error_type": type(error).__name__,
            })

    @contextmanager
    def request(self, payload: Mapping[str, Any]) -> Iterator[RequestPermit]:
        permit = self.acquire(payload)
        error = None
        try:
            yield permit
        except BaseException as exc:
            error = exc
            raise
        finally:
            self.release(permit, error=error)

    @asynccontextmanager
    async def request_async(self, payload: Mapping[str, Any]):
        permit = await self.acquire_async(payload)
        error = None
        try:
            yield permit
        except BaseException as exc:
            error = exc
            raise
        finally:
            self.release(permit, error=error)

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            elapsed = self._finished_elapsed if self._finished_elapsed is not None else time.monotonic() - self._started_at
            return {
                "elapsed_seconds": round(elapsed, 3),
                "deadline_seconds": self.config.deadline_seconds,
                "deadline_exceeded": elapsed > self.config.deadline_seconds,
                "target_met": self._pipeline_complete and elapsed <= self.config.deadline_seconds,
                "pipeline_complete": self._pipeline_complete,
                "deadline_policy": "hard admission deadline" if self.config.hard_deadline else "soft reporting target",
                "input_estimator": ("injected complete-request tokenizer adapter; accuracy depends on adapter"
                                    if self.config.token_counter else
                                    "conservative serialized UTF-8 bytes plus framing; not exact tokenizer"),
                "active_requests": self._active,
                "active_reserved_tokens": self._active_tokens,
                "peak_active_requests": self._peak_active,
                "configured_workers": self.config.workers,
                "logical_workers": self._logical_workers,
                "transport_retries": self._retries,
                "adaptive_events": list(self._adaptive_events),
                "peak_reserved_tokens": self._peak_tokens,
                "admitted_requests": self._next_id,
                "completed_requests": self._completed,
                "failed_requests": self._failed,
                "total_queue_wait_seconds": round(self._total_wait, 3),
                "actual_prompt_tokens": self._usage_input,
                "actual_completion_tokens": self._usage_output,
                "actual_usage_tpm": round((self._usage_input + self._usage_output) * 60 / max(elapsed, 0.001), 2),
                "reserved_tokens_are_not_actual_usage": True,
                "configured_rpm": self.config.rpm,
                "configured_tpm": self.config.tpm,
                "events": list(self._events),
            }

    def finish(self, *, completed: bool = True) -> dict[str, Any]:
        """Call only after the runner has determined overall completion status."""
        with self._condition:
            self._pipeline_complete = completed and self._active == 0
            self._finished_elapsed = time.monotonic() - self._started_at
        return self.snapshot()

    def close(self):
        """Reject new/waiting work; in-flight permits still finish and release."""
        with self._condition:
            self._closed = True
            self._condition.notify_all()
