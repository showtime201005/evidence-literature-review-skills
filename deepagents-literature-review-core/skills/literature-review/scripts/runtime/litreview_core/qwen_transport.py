"""Shared OpenRouter settings and credential-free, reusable HTTP transports."""
import asyncio
import json
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import random
import threading
import time
import weakref

from langchain_openrouter import ChatOpenRouter
import httpx
from langchain_openrouter.chat_models import _strip_internal_kwargs
from pydantic import PrivateAttr

from .request_governor import RequestGovernor
from .provider_tool_schema import (STRICT_TOOL_MODE, audit_request_metadata,
    project_submit_tools, validate_strict_provider)

MODEL_ID = "qwen/qwen3.8-27b"


def _reasoning_observation(data):
    """Record field presence and reported counts, never reasoning content.

    Some providers return details with a zero usage count. Neither zero nor
    missing details proves that reasoning was disabled.
    """
    messages = [choice.get('message') or {} for choice in data.get('choices', [])]
    details_present = any(bool(message.get('reasoning_details')) for message in messages)
    text_present = any(bool(message.get('reasoning')) for message in messages)
    usage = data.get('usage') or {}
    reported = (usage.get('completion_tokens_details') or {}).get('reasoning_tokens')
    completion = usage.get('completion_tokens')
    return {'details_present': details_present, 'text_present': text_present,
            'reported_reasoning_tokens': reported,
            'reported_completion_tokens': completion,
            'reasoning_exceeds_completion': (type(reported) is int and type(completion) is int
                                             and reported > completion),
            'zero_with_details': reported == 0 and (details_present or text_present)}


class ProviderGenerationError(RuntimeError):
    """The endpoint returned an explicit failed generation, not a verdict."""
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


class _HTTPClients:
    """Sync connections belong to threads; async connections belong to loops.

    Headers/API keys are passed on each request and never cached in the pool.
    Explicit pool shutdown must run after all workers have stopped.
    """
    def __init__(self):
        self._local = threading.local()
        self._lock = threading.Lock()
        self._sync_clients: list[httpx.Client] = []
        self._async_clients = weakref.WeakKeyDictionary()

    def sync_client(self):
        client = getattr(self._local, "client", None)
        if client is None or client.is_closed:
            client = httpx.Client(limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))
            self._local.client = client
            with self._lock:
                self._sync_clients.append(client)
        return client

    def async_client(self):
        loop = asyncio.get_running_loop()
        with self._lock:
            client = self._async_clients.get(loop)
            if client is None or client.is_closed:
                client = httpx.AsyncClient(limits=httpx.Limits(max_connections=64, max_keepalive_connections=32))
                self._async_clients[loop] = client
            return client

    def close_sync(self):
        with self._lock:
            clients, self._sync_clients = self._sync_clients, []
        for client in clients:
            client.close()

    async def close_current_loop(self):
        with self._lock:
            client = self._async_clients.pop(asyncio.get_running_loop(), None)
        if client is not None:
            await client.aclose()


_HTTP_CLIENTS = _HTTPClients()


def close_http_clients():
    """Close sync transports after joining every worker; never call mid-run."""
    _HTTP_CLIENTS.close_sync()


async def aclose_http_clients():
    """Close this event loop's transport before the loop ends, after its tasks."""
    await _HTTP_CLIENTS.close_current_loop()


class OpenRouterJSONModel(ChatOpenRouter):
    """Keep OpenRouter JSON fields that the generated SDK currently discards.

    The installed SDK's ChatRequestReasoning only serializes effort/summary.
    LangChain still owns message conversion, tool binding, and result parsing.
    """
    _request_governor: RequestGovernor | None = PrivateAttr(default=None)
    _http_closed: bool = PrivateAttr(default=False)
    _strict_tool_mode: str = PrivateAttr(default='off')
    _tool_schema_audits: dict = PrivateAttr(default_factory=dict)

    @property
    def tool_schema_audits(self):
        """Host audit copies keyed by the original schema SHA, never secrets."""
        from copy import deepcopy
        return deepcopy(self._tool_schema_audits)

    def _payload(self, messages, stop, kwargs):
        if self._http_closed:
            raise RuntimeError("This model is closed")
        message_dicts, params = self._create_message_dicts(messages, stop)
        # The SDK emits both plaintext reasoning and reasoning_details for some
        # providers. Drop only a byte-for-byte duplicate plaintext copy; keep
        # every original detail (including encrypted/opaque fields) unchanged.
        # Distinct reasoning, scientific text and source material are untouched.
        message_dicts = [dict(message) for message in message_dicts]
        for message in message_dicts:
            plain = message.get('reasoning')
            details = message.get('reasoning_details')
            if isinstance(plain, str) and plain and isinstance(details, list):
                texts = [item.get('text') for item in details
                         if isinstance(item, dict) and item.get('type') == 'reasoning.text']
                if texts and all(isinstance(value, str) for value in texts) and plain == ''.join(texts):
                    message.pop('reasoning')
        params = {**params, **kwargs, "messages": message_dicts, "stream": False}
        _strip_internal_kwargs(params)
        if self._strict_tool_mode != 'off':
            validate_strict_provider(params.get('provider'))
            if self._request_governor is None:
                raise ValueError('Strict tool mode requires a shared request governor')
            if params.get('model') != MODEL_ID or params.get('models') or params.get('route'):
                raise ValueError('Strict tool mode is verified only for ' + MODEL_ID)
            if params.get('response_format') is not None:
                raise ValueError('Strict tool mode cannot combine tools and response_format')
            params['tools'], audit = project_submit_tools(params.get('tools'))
            self._tool_schema_audits[audit['canonical_schema_sha256']] = audit
            params['tool_choice'] = {'type': 'function', 'function': {'name': 'submit_result'}}
            params['parallel_tool_calls'] = False
            metadata = dict(params.get('metadata') or {})
            metadata.update(audit_request_metadata(audit))
            if (len(metadata) > 16 or any(not isinstance(key, str) or len(key) > 64
                    or not isinstance(value, str) or len(value) > 512 for key, value in metadata.items())):
                raise ValueError('OpenRouter request metadata exceeds its string-map limits')
            params['metadata'] = metadata
        if self._request_governor is not None:
            # Provider fields themselves add a few bytes: re-evaluate until the
            # route and complete-request reservation are stable.
            for _ in range(3):
                _, _, reservation = self._request_governor.reservation_for(params)
                provider = self._request_governor.provider_preferences(params.get("provider"), reservation,
                    max_tokens=params.get('max_completion_tokens', params.get('max_tokens')))
                if provider == params.get("provider"):
                    break
                params["provider"] = provider
            self._request_governor.reservation_for(params)
        if self._strict_tool_mode != 'off':
            validate_strict_provider(params.get('provider'))
            # Check the pinned endpoint cap even if a caller customized the
            # governor's provider capacities. The global 200K cap is unchanged.
            _, output, reservation = self._request_governor.reservation_for(params)
            if reservation > 65_536 or output > 32_768:
                from .request_governor import ContextCapacityError
                raise ContextCapacityError('Strict Cerebras request exceeds 65536 complete context or 32768 output; no fallback or truncation')
        return params

    def _headers(self):
        return {"Authorization": "Bearer " + self.openrouter_api_key.get_secret_value(),
                "Content-Type": "application/json"}

    def _timeout(self):
        return httpx.Timeout((self.request_timeout or 180_000) / 1000, connect=20)

    def _result(self, data, permit=None, tool_schema_audit=None):
        if permit is not None:
            permit.usage = data.get("usage")
            permit.provider = data.get("provider")
            permit.response_id = data.get("id")
            permit.reasoning_observation = _reasoning_observation(data)
            permit.finish_reasons = [choice.get("finish_reason") for choice in data.get("choices", [])]
        if not data.get('choices') or any(c.get('finish_reason') == 'error' for c in data.get('choices', [])):
            provider_error=data.get('error') or next((c.get('error') for c in data.get('choices', []) if c.get('error')),None)
            detail=''
            if provider_error:
                if isinstance(provider_error,dict):
                    code=provider_error.get('code')
                    message=str(provider_error.get('message',''))
                else:
                    code=None
                    message=str(provider_error)
                secret=self.openrouter_api_key.get_secret_value()
                if secret:
                    message=message.replace(secret,'[redacted]')
                detail=f' Provider error code={code}: {message[:1000]}'
            raise ProviderGenerationError(
                f"Provider generation failed; response_id={data.get('id')}, provider={data.get('provider')}. "
                "No scientific verdict was produced; retain usage and incomplete task state."+detail,
                retryable=any(c.get('finish_reason') == 'error' for c in data.get('choices', [])))
        result = self._create_chat_result(data)
        # Retain the raw billing/usage fields as well as LangChain's normalized
        # usage_metadata. Reasoning details still use the inherited converter.
        for generation in result.generations:
            metadata = generation.message.response_metadata
            metadata["token_usage"] = data.get("usage") or {}
            for key in ("id", "model", "provider"):
                if key in data:
                    metadata[key] = data[key]
            metadata.update(generation.generation_info or {})
            if tool_schema_audit is not None:
                metadata['tool_schema_projection'] = tool_schema_audit
        return result

    def _response_data(self, response, permit=None):
        # Error JSON occasionally contains usage too. Preserve it on the failed
        # attempt before raising the status error that drives admission backoff.
        if permit is not None:
            permit.http_status = response.status_code
            permit.retry_after = response.headers.get('Retry-After')
        try:
            data = response.json()
        except ValueError:
            response.raise_for_status()
            raise
        if permit is not None and isinstance(data, dict):
            permit.usage = data.get("usage")
            permit.provider = data.get("provider")
            permit.response_id = data.get("id")
            permit.reasoning_observation = _reasoning_observation(data)
            permit.finish_reasons = [choice.get("finish_reason") for choice in data.get("choices", [])]
            error = data.get('error')
            if error:
                secret = self.openrouter_api_key.get_secret_value()
                clean = lambda value: str(value).replace(secret, '[redacted]')[:2000] if secret else str(value)[:2000]
                details = error if isinstance(error, dict) else {'message': error}
                metadata = details.get('metadata') or {}
                metadata = metadata if isinstance(metadata, dict) else {}
                upstream = metadata.get('raw')
                if isinstance(upstream, str):
                    try:
                        upstream = json.loads(upstream)
                    except ValueError:
                        pass
                if isinstance(upstream, dict):
                    upstream = upstream.get('error', upstream)
                    upstream = upstream.get('message') if isinstance(upstream, dict) else upstream
                permit.provider_error = {'code': clean(details.get('code')),
                    'message': clean(details.get('message', '')),
                    'provider': clean(metadata.get('provider_name')),
                    'upstream_message': clean(upstream) if upstream is not None else None}
        response.raise_for_status()
        return data

    @staticmethod
    def _retry_delay(error):
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        retryable = ((isinstance(error, httpx.HTTPStatusError) and status in (429, 502, 503, 504, 521))
                     or isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout))
                     or isinstance(error, ProviderGenerationError) and error.retryable)
        if not retryable:
            # Read/write timeouts may follow billed server-side processing.
            # JSON/schema/semantic errors and length finishes are never retried.
            # Only explicit provider finish_reason=error gets the same single
            # bounded retry as transport failures, before any tool execution.
            return None
        delay = random.uniform(1.0, 3.0)
        retry_after = response.headers.get("Retry-After") if response is not None else None
        if retry_after is not None:
            try:
                delay = float(retry_after)
            except ValueError:
                try:
                    when = parsedate_to_datetime(retry_after)
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    delay = (when - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    pass
        # Never shorten a server's Retry-After to 10s. The governor rejects a
        # retry that cannot fit the original deadline; async callers remain cancellable.
        if not math.isfinite(delay):
            delay = random.uniform(1.0, 3.0)
        return max(0.0, delay) + random.uniform(0.0, 0.3)

    def _post(self, payload, permit=None):
        response = _HTTP_CLIENTS.sync_client().post("https://openrouter.ai/api/v1/chat/completions",
            headers=self._headers(), json=payload, timeout=self._timeout())
        data = self._response_data(response, permit)
        return self._result(data, permit, self._schema_audit_for(payload))

    def _schema_audit_for(self, payload):
        schema_hash = (payload.get('metadata') or {}).get('canonical_schema_sha256')
        return self.tool_schema_audits.get(schema_hash) if self._strict_tool_mode != 'off' else None

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        payload = self._payload(messages, stop, kwargs)
        for attempt in range(2):
            try:
                if self._request_governor is None:
                    return self._post(payload)
                with self._request_governor.request(payload) as permit:
                    return self._post(payload, permit)
            except Exception as error:
                delay = self._retry_delay(error) if attempt == 0 else None
                if delay is None:
                    raise
                if self._request_governor is not None:
                    self._request_governor.note_retry(error, delay, attempt=attempt + 2)
                # The failed attempt has released its permit before sleeping.
                time.sleep(delay)

    async def _apost(self, payload, permit=None):
        response = await _HTTP_CLIENTS.async_client().post("https://openrouter.ai/api/v1/chat/completions",
            headers=self._headers(), json=payload, timeout=self._timeout())
        data = self._response_data(response, permit)
        return self._result(data, permit, self._schema_audit_for(payload))

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        payload = self._payload(messages, stop, kwargs)
        for attempt in range(2):
            try:
                if self._request_governor is None:
                    return await self._apost(payload)
                async with self._request_governor.request_async(payload) as permit:
                    return await self._apost(payload, permit)
            except Exception as error:
                delay = self._retry_delay(error) if attempt == 0 else None
                if delay is None:
                    raise
                if self._request_governor is not None:
                    self._request_governor.note_retry(error, delay, attempt=attempt + 2)
                await asyncio.sleep(delay)

    def close(self):
        """Close this model; shared transports remain usable by other models."""
        self._http_closed = True

    async def aclose(self):
        """Close this model without interrupting tasks sharing its transport."""
        self.close()


class SubmissionModel(OpenRouterJSONModel):
    """Use a named output tool for bounded tasks whose inputs are fully delivered."""
    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        names = [getattr(t, "name", "") for t in tools]
        if "submit_result" in names:
            tool_choice = {"type": "function", "function": {"name": "submit_result"}}
        return super().bind_tools(tools, tool_choice=tool_choice, **kwargs)


def create_model(*, max_tokens=16384, reasoning_max_tokens=None, reasoning_effort=None, reasoning_enabled=True, temperature=0, force_submit=False, provider_preferences=None, governor=None, profile=None, strict_tool_mode='off'):
    """Construct a model; old calls retain their parameters and behavior.

    Throughput profiles select low reasoning unless explicitly overridden.
    max_tokens remains caller controlled per role, including reasoning output.
    A shared governor must be passed to enforce global request/context limits.
    strict-supported-subset/1 is an explicit Cerebras-only wire experiment;
    it never changes the canonical schema or scientific acceptance gate.
    """
    if profile not in (None, "default", "reader", "verifier", "writer", "comparison", "planner"):
        raise ValueError(f"Unknown throughput profile: {profile}")
    if strict_tool_mode not in ('off', STRICT_TOOL_MODE):
        raise ValueError('Unknown strict_tool_mode: ' + str(strict_tool_mode))
    if strict_tool_mode != 'off':
        if not force_submit or governor is None:
            raise ValueError('Strict tool mode requires force_submit=True and a shared request governor')
        validate_strict_provider(provider_preferences)
    reasoning = {"enabled": reasoning_enabled}
    if not reasoning_enabled:
        pass
    elif reasoning_effort is not None:
        reasoning["effort"] = reasoning_effort
    elif reasoning_max_tokens is not None:
        reasoning["max_tokens"] = reasoning_max_tokens
    elif profile is not None:
        reasoning["effort"] = "low"
    model_class = SubmissionModel if force_submit else OpenRouterJSONModel
    model = model_class(
        model=MODEL_ID,
        reasoning=reasoning,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=180_000,  # langchain-openrouter uses milliseconds.
        max_retries=0,
        openrouter_provider=provider_preferences,
    )
    model._request_governor = governor
    model._strict_tool_mode = strict_tool_mode
    return model
