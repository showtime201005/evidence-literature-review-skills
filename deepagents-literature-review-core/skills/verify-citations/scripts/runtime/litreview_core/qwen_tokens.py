"""Token budgeting with Qwen's pinned public tokenizer; no model weights.

Providers may render chat templates differently. This counts complete request
JSON with the official vocabulary and adds framing headroom; it is explicitly
an estimate, calibrated against returned usage rather than called exact usage.
"""
import argparse
from dataclasses import fields
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from uuid import uuid4

MODEL = "Qwen/Qwen3.8-27B"
REVISION = "1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0"
EXPECTED_SHA256 = "0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3"
DEFAULT_PATH = Path(os.environ.get("LITREVIEW_TOKENIZER_PATH", str(Path.home() / ".cache/litreview/qwen3.8-27b-tokenizer.json")))


class QwenRequestCounter:
    def __init__(self, path=DEFAULT_PATH):
        from tokenizers import Tokenizer
        path = Path(path)
        digest = sha256(path.read_bytes()).hexdigest()
        if digest != EXPECTED_SHA256:
            raise ValueError('Tokenizer content differs from the pinned Qwen asset')
        self.tokenizer = Tokenizer.from_file(str(path))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        self.identity = {"model": MODEL, "revision": REVISION,
                         "tokenizer_sha256": digest,
                         "method": "complete serialized request tokens + 5% + 2048 framing; provider-template estimate"}

    def __call__(self, payload):
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        count = len(self.tokenizer.encode(encoded, add_special_tokens=False).ids)
        return math.ceil(count * 1.05) + 2048 + 32 * len(payload.get("messages", []))


def config_dict(config):
    if config is None:
        return None
    result = {field.name: getattr(config, field.name) for field in fields(config) if field.name != "token_counter"}
    counter = config.token_counter
    if counter is None:
        result["token_counter"] = None
    elif hasattr(counter, "identity"):
        result["token_counter"] = counter.identity
    else:
        raise ValueError("A custom token counter must expose stable JSON-serializable .identity for resumable proofs")
    return result


def download(path=DEFAULT_PATH):
    import httpx
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex[:8] + ".tmp")
    try:
        url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/tokenizer.json"
        size = 0
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for block in response.iter_bytes():
                    size += len(block)
                    if size > 50_000_000:
                        raise ValueError("Unexpected tokenizer asset size; no model weights should be downloaded")
                    handle.write(block)
        QwenRequestCounter(temporary)  # Parse as data; never execute remote Python.
        os.replace(temporary, path)
        return QwenRequestCounter(path).identity
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    result = download(args.path) if args.download else QwenRequestCounter(args.path).identity
    print(json.dumps(result, ensure_ascii=True, indent=2))
