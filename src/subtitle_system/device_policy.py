from __future__ import annotations

import datetime
import os
from typing import Any

from src.utils import get_runtime_data_dir


def is_cuda_available(torch_module: Any | None = None) -> bool:
    ok, _, _ = get_cuda_status(torch_module=torch_module)
    return bool(ok)


def _append_log(name: str, content: str):
    try:
        base = get_runtime_data_dir()
        logs_dir = os.path.join(base, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        path = os.path.join(logs_dir, name)
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write(content)
    except Exception:
        return None


def get_cuda_status(torch_module: Any | None = None) -> tuple[bool, str, dict[str, Any]]:
    m = torch_module
    if m is None:
        try:
            import torch as m  # type: ignore
        except Exception as e:
            return False, "torch_import_error", {"error": f"{type(e).__name__}: {e}"}

    details: dict[str, Any] = {}
    try:
        details["torch_version"] = getattr(m, "__version__", None)
    except Exception:
        details["torch_version"] = None
    try:
        v = getattr(m, "version", None)
        details["torch_build_cuda"] = getattr(v, "cuda", None) if v is not None else None
    except Exception as e:
        details["torch_build_cuda"] = f"{type(e).__name__}: {e}"

    cuda = getattr(m, "cuda", None)
    if cuda is None:
        return False, "torch_no_cuda_attr", details

    try:
        is_avail = bool(cuda.is_available())
        details["cuda_is_available"] = is_avail
    except Exception as e:
        details["cuda_is_available"] = f"{type(e).__name__}: {e}"
        return False, "cuda_is_available_error", details

    try:
        details["cuda_device_count"] = int(cuda.device_count())
    except Exception as e:
        details["cuda_device_count"] = f"{type(e).__name__}: {e}"

    try:
        if details.get("cuda_device_count") and int(details["cuda_device_count"]) > 0:
            details["cuda_device0_name"] = cuda.get_device_name(0)
    except Exception as e:
        details["cuda_device0_name"] = f"{type(e).__name__}: {e}"

    torch_build_cuda = details.get("torch_build_cuda")
    torch_version = str(details.get("torch_version") or "")
    if torch_build_cuda in (None, "", "None"):
        if "+cpu" in torch_version:
            return False, "torch_cpu_build", details

    if not is_avail:
        return False, "cuda_unavailable", details

    return True, "ok", details


def log_cuda_status(*, context: str, torch_module: Any | None = None):
    ok, reason, details = get_cuda_status(torch_module=torch_module)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = (
        f"[{ts}] context={context}\n"
        f"ok={ok}\n"
        f"reason={reason}\n"
        + "\n".join([f"{k}={details.get(k)}" for k in sorted(details.keys())])
        + "\n----\n"
    )
    _append_log("subtitle_cuda_diag.log", payload)
    return ok, reason, details


def normalize_asr_device(device: str | None) -> str:
    v = (device or "").strip().lower()
    return v if v in ("cpu", "cuda") else ""


def choose_default_asr_device(*, saved_device: str | None, can_use_gpu: bool, cuda_available: bool) -> str:
    v = normalize_asr_device(saved_device)
    if v == "cuda":
        return "cuda" if (bool(can_use_gpu) and bool(cuda_available)) else "cpu"
    if v == "cpu":
        return "cpu"
    if bool(can_use_gpu) and bool(cuda_available):
        return "cuda"
    return "cpu"
