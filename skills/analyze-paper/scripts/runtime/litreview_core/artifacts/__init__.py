"""Portable artifact I/O; no database prerequisite."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from ..errors import ReviewError


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identifier(prefix, value):
    return prefix + "_" + digest(canonical(value).encode())[:24]


def envelope(kind, payload, producer=None, schema_version='1.0.0'):
    result = {"schema_version": schema_version, "artifact_type": kind,
              "artifact_id": identifier(kind.lower(), payload), "payload": payload}
    if producer is not None:
        result["producer"] = producer
    return result


def atomic_bytes(path, data, replace=False):
    """fsync temp, then commit. Default is race-safe create-or-identical."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise ReviewError("OUTPUT_CONFLICT", "Refusing to overwrite a different artifact", str(path))
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path, value, replace=False):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(), replace)


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ReviewError("INVALID_JSON", "Duplicate object key", key)
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (ValueError, UnicodeError) as exc:
        raise ReviewError("INVALID_JSON", str(exc), str(path)) from exc


def safe_path(root, relative):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ReviewError("UNSAFE_PATH", "Path leaves the specified root", str(relative))
    return target
