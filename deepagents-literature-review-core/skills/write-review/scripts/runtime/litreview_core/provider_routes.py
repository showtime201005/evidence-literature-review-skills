"""Pinned official Qwen route capabilities; metadata is not a quality test.

Full public response: docs/provider-metadata/openrouter-qwen3.8-20261019.json.
No keys, network fetches, inferred variants or measured throughput are used.
"""
from dataclasses import dataclass
from types import MappingProxyType

CATALOG_SOURCE_URL = 'https://openrouter.ai/api/v1/models/qwen/qwen3.8-27b/endpoints'
CATALOG_FETCHED_UTC = '2026-10-19T20:38:27.544262+00:00'
CATALOG_RESPONSE_SHA256 = '41398d280abe392b0926627656cf5626f80db335a1b641cc394974717676cb09'


@dataclass(frozen=True)
class ProviderRoute:
    tag: str
    context_length: int
    max_completion_tokens: int
    named_function: bool
    default_auto: bool


ROUTES = MappingProxyType({route.tag: route for route in (
    ProviderRoute('cerebras/fp16', 65536, 32768, True, True),
    ProviderRoute('modelrun/fp4', 262144, 235929, True, True),
    ProviderRoute('deepinfra/bf16', 262144, 235929, True, True),
    ProviderRoute('near-ai/fp8', 262144, 65536, True, False),
    ProviderRoute('chutes/fp8', 262144, 65536, True, False),
)})


def resolve_routes(name):
    """Base names resolve only to pinned routes; unknown suffixes never widen."""
    if not isinstance(name, str) or not name.strip() or name != name.strip():
        raise ValueError('Provider must be an exact verified base or full route tag')
    name = name.lower()
    if name in ROUTES:
        return [name]
    if '/' not in name:
        result = [tag for tag in ROUTES if tag.split('/', 1)[0] == name]
        if result:
            return result
    raise ValueError('Unknown or unverified provider route: ' + name)
