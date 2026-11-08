"""Accelerator detection (CUDA -> MPS -> CPU) without hard-depending on torch."""

from __future__ import annotations

import importlib.util


def available_devices() -> list[str]:
    devices = ["cpu"]
    if importlib.util.find_spec("torch") is None:
        return devices
    try:
        import torch
    except Exception:
        return devices
    if torch.cuda.is_available():
        devices.insert(0, "cuda")
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        devices.insert(0 if "cuda" not in devices else 1, "mps")
    return devices


def resolve_device(requested: str) -> str:
    devices = available_devices()
    if requested == "auto":
        return devices[0]
    if requested not in devices:
        from inkthaw.errors import InkthawError

        raise InkthawError(
            f"Device '{requested}' requested but not available (have: {', '.join(devices)})"
        )
    return requested
