import json
import os
import shutil
from dataclasses import dataclass
from typing import Any

from src.utils import get_runtime_base_dir, get_runtime_data_dir


@dataclass(frozen=True)
class LocalASRModel:
    model_id: str
    backend: str
    display_name: str
    model_ref: str
    allow_cpu: bool
    allow_gpu: bool


def get_models_dir() -> str:
    return os.path.join(get_runtime_data_dir(), "models")


def get_manifest_path() -> str:
    p = os.path.join(get_models_dir(), "manifest.json")
    if os.path.exists(p):
        return p
    base_p = os.path.join(os.path.join(get_runtime_base_dir(), "models"), "manifest.json")
    if os.path.exists(base_p):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
            shutil.copy2(base_p, p)
        except Exception:
            return base_p
    return p


def _read_json_file(path: str) -> Any | None:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _as_bool(v: Any, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def _norm_abs(p: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(p))
    except Exception:
        return p


def load_manifest_models() -> list[LocalASRModel]:
    data = _read_json_file(get_manifest_path()) or {}
    models_raw = data.get("models")
    if not isinstance(models_raw, list):
        models_raw = []

    out: list[LocalASRModel] = []
    for item in models_raw:
        if not isinstance(item, dict):
            continue
        backend = str(item.get("backend") or "").strip().lower()
        if not backend:
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            continue
        display_name = str(item.get("display_name") or model_id).strip()
        model_ref = str(item.get("model") or item.get("model_ref") or "").strip()
        if not model_ref:
            continue
        allow_cpu = _as_bool(item.get("allow_cpu"), True)
        allow_gpu = _as_bool(item.get("allow_gpu"), True)
        out.append(
            LocalASRModel(
                model_id=model_id,
                backend=backend,
                display_name=display_name,
                model_ref=model_ref,
                allow_cpu=allow_cpu,
                allow_gpu=allow_gpu,
            )
        )

    return out


def _looks_like_ctranslate2_model_dir(dir_path: str) -> bool:
    if not dir_path or not os.path.isdir(dir_path):
        return False
    try:
        names = set(os.listdir(dir_path))
    except Exception:
        return False
    if "model.bin" not in names:
        return False
    for marker in ("tokenizer.json", "vocabulary.json", "config.json", "preprocessor_config.json"):
        if marker in names:
            return True
    return False


def discover_whisperx_models_from_dir() -> list[LocalASRModel]:
    base = get_models_dir()
    root = os.path.join(base, "whisperx", "whisper")
    if not os.path.isdir(root):
        return []

    out: list[LocalASRModel] = []
    try:
        entries = os.listdir(root)
    except Exception:
        entries = []

    for name in entries:
        p = os.path.join(root, name)
        if not _looks_like_ctranslate2_model_dir(p):
            continue
        model_id = f"local:{name}"
        out.append(
            LocalASRModel(
                model_id=model_id,
                backend="whisperx",
                display_name=f"本地模型: {name}",
                model_ref=p,
                allow_cpu=True,
                allow_gpu=True,
            )
        )
    return out


def list_available_local_models(*, backend: str | None = None) -> list[LocalASRModel]:
    backend_norm = (backend or "").strip().lower()
    items: list[LocalASRModel] = []
    items.extend(load_manifest_models())
    items.extend(discover_whisperx_models_from_dir())

    seen: set[tuple[str, str]] = set()
    deduped: list[LocalASRModel] = []
    for m in items:
        if backend_norm and m.backend != backend_norm:
            continue
        key = (m.backend, _norm_abs(m.model_ref))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(m)
    deduped.sort(key=lambda x: (x.backend, x.display_name.lower()))
    return deduped


def get_default_whisperx_model_id() -> str:
    models = list_available_local_models(backend="whisperx")
    for m in models:
        if m.model_id and not m.model_id.startswith("local:"):
            return m.model_id
    if models:
        return models[0].model_id
    return "whisper-large-v3"
