"""
VLM provider abstraction: Groq for development, a local OpenAI-compatible
endpoint for offline evaluation.

This replaces a 40-line module whose `explain_candidate` was an f-string with a
binary `if sar_confirmed` branch, which never read GROQ_API_KEY and never made a
network call, while config/providers.yaml declared a `vision_model` and the
benchmark reported 1840 ms of "VLM explanation" latency.

Design constraint from PRD section 10.1: the VLM explains, it never searches.
Retrieval is done by the indices; only the top N candidates reach a model, and a
model failure degrades the explanation rather than the result set.

Switching providers is one line in config/providers.yaml (PRD section 10.4):

    active: "groq"    # development
    active: "local"   # offline evaluation

The deterministic template remains as a third tier. It is what runs when no
provider is reachable, and it is honest about being a template -- the previous
implementation presented template output as model reasoning.
"""

from __future__ import annotations

import base64
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROVIDERS_CONFIG = os.path.join(ROOT, "config", "providers.yaml")

SYSTEM_PROMPT = (
    "You are an imagery analysis assistant supporting a human analyst. "
    "You are shown a before/after pair from Sentinel-2 optical imagery and a "
    "structured evidence record computed by an upstream change-detection "
    "pipeline. Explain, in at most three sentences, what changed and why the "
    "evidence does or does not support the proposed change type. "
    "Ground every statement in the evidence you are given. If the imagery does "
    "not support the pipeline's claim, say so plainly. Never invent dates, "
    "measurements, or sensors that are not in the record."
)


@dataclass
class Explanation:
    """What the analyst sees, plus how it was produced."""

    text: str
    provider: str
    model: str
    latency_ms: float
    degraded: bool = False
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 1),
            "degraded": self.degraded,
            "error": self.error,
        }


def load_provider_config(path: Optional[str] = None) -> Dict[str, Any]:
    with open(path or PROVIDERS_CONFIG, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _evidence_block(entity: Dict[str, Any]) -> str:
    """Render the structured record the model must stay grounded in."""
    rel = entity.get("relations", {}) or {}
    ev = entity.get("evidence", {}) or {}
    lines = [
        "entity_id: %s" % entity.get("entity_id"),
        "entity_type: %s" % entity.get("entity_type"),
        "proposed_change: %s" % entity.get("change_type"),
        "area_m2: %s" % entity.get("area_m2"),
        "first_seen: %s (CI %s)" % (entity.get("first_seen"), entity.get("first_seen_ci")),
        "optical_change_z: %s" % ev.get("optical_z"),
        "sar_confirmation: %s (z=%s)" % (ev.get("sar"), ev.get("sar_z")),
        "observations_after_break: %s" % ev.get("observations_after_break"),
        "registration_residual_px: %s" % ev.get("registration_residual_px"),
        "cloud_free_pct: %s" % ev.get("cloud_free_pct"),
        "distance_to_water_m: %s" % rel.get("river_distance_m"),
        "distance_to_road_m: %s" % rel.get("road_distance_m"),
        "confidence: %s" % entity.get("confidence"),
    ]
    gates = ev.get("gates") or []
    for gate in gates:
        lines.append(
            "gate %s: %s (metric %s vs threshold %s)"
            % (
                gate.get("name"),
                "PASS" if gate.get("passed") else "FAIL",
                gate.get("metric"),
                gate.get("threshold"),
            )
        )
    return "\n".join(lines)


def _encode_image(path_or_bytes) -> Optional[str]:
    """Base64-encode a chip for the vision message."""
    try:
        if isinstance(path_or_bytes, (bytes, bytearray)):
            raw = bytes(path_or_bytes)
        else:
            candidate = path_or_bytes
            if not os.path.isabs(candidate):
                candidate = os.path.join(ROOT, candidate.lstrip("/\\"))
            if not os.path.exists(candidate):
                return None
            with open(candidate, "rb") as fh:
                raw = fh.read()
        return base64.b64encode(raw).decode("ascii")
    except OSError:
        return None


# --------------------------------------------------------------------------- template


def template_explanation(entity: Dict[str, Any]) -> str:
    """
    Deterministic, offline, hallucination-free fallback.

    Composed from database fields only, in the spirit of PRD section 5.4. It is
    labelled as a template wherever it surfaces, so nobody mistakes it for model
    reasoning.
    """
    ev = entity.get("evidence", {}) or {}
    rel = entity.get("relations", {}) or {}

    change = (entity.get("change_type") or "change").replace("_", " ")
    etype = entity.get("entity_type") or "object"
    area = entity.get("area_m2")
    first_seen = entity.get("first_seen")
    ci = entity.get("first_seen_ci") or []

    parts = ["A %s consistent with %s" % (etype, change)]
    if area:
        parts.append("covering approximately %s m2" % int(area))
    if rel.get("river_distance_m") is not None:
        parts.append("%d m from water" % int(rel["river_distance_m"]))
    if rel.get("road_distance_m") is not None:
        parts.append("%d m from a road" % int(rel["road_distance_m"]))
    sentence_one = ", ".join(parts) + "."

    if len(ci) == 2:
        sentence_two = "The break is bounded between %s and %s." % (ci[0], ci[1])
    elif first_seen:
        sentence_two = "First observed %s." % first_seen
    else:
        sentence_two = "No break date was established."

    if ev.get("sar"):
        sentence_three = (
            "Optical change (z=%s) is corroborated by Sentinel-1 SAR (z=%s)."
            % (ev.get("optical_z"), ev.get("sar_z"))
        )
    else:
        sentence_three = (
            "Optical change (z=%s) is not corroborated by SAR, so this candidate "
            "rests on a single witness." % ev.get("optical_z")
        )

    return " ".join([sentence_one, sentence_two, sentence_three])


# --------------------------------------------------------------------------- providers


class BaseProvider:
    name = "base"

    def available(self) -> bool:
        raise NotImplementedError

    def explain(self, entity: Dict[str, Any], images: Optional[List[str]] = None) -> Explanation:
        raise NotImplementedError

    def parse_query(self, query: str, schema_hint: str) -> Optional[str]:
        raise NotImplementedError


class TemplateProvider(BaseProvider):
    """Always available. Never fails. Never pretends to be a model."""

    name = "template"

    def available(self) -> bool:
        return True

    def explain(self, entity, images=None) -> Explanation:
        t0 = time.perf_counter()
        text = template_explanation(entity)
        return Explanation(
            text=text,
            provider="template",
            model="offline_deterministic",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            degraded=True,
        )

    def parse_query(self, query, schema_hint):
        return None


class GroqProvider(BaseProvider):
    """
    Groq-hosted vision model, for development iteration.

    Model selection is resolved at runtime against the live /models endpoint.
    config/providers.yaml previously named `llama-3.2-11b-vision-preview`, which
    Groq has since decommissioned, so a hardcoded ID is a liability.
    """

    name = "groq"

    VISION_PREFERENCES = [
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
    ]

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.api_key = os.getenv(cfg.get("api_key_env", "GROQ_API_KEY"), "")
        self.timeout = float(cfg.get("timeout_sec", 10))
        self.temperature = float(cfg.get("temperature", 0.1))
        self._client = None
        self._vision_model: Optional[str] = None
        self._text_model: Optional[str] = cfg.get("model")
        self._lock = threading.Lock()

    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            from groq import Groq

            self._client = Groq(api_key=self.api_key, timeout=self.timeout)
        return self._client

    def _resolve_vision_model(self) -> Optional[str]:
        if self._vision_model:
            return self._vision_model
        with self._lock:
            if self._vision_model:
                return self._vision_model
            try:
                served = {m.id for m in self._get_client().models.list().data}
            except Exception:  # noqa: BLE001
                served = set()

            configured = self.cfg.get("vision_model")
            for candidate in ([configured] if configured else []) + self.VISION_PREFERENCES:
                if candidate and candidate in served:
                    self._vision_model = candidate
                    return candidate

            # Nothing matched the preference list; take any served model whose
            # name suggests vision rather than failing outright.
            for model_id in sorted(served):
                if any(tag in model_id for tag in ("vision", "scout", "maverick")):
                    self._vision_model = model_id
                    return model_id
        return None

    def explain(self, entity, images=None) -> Explanation:
        t0 = time.perf_counter()
        model = self._resolve_vision_model() or self._text_model

        content: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": "Evidence record:\n%s\n\nExplain this candidate."
                % _evidence_block(entity),
            }
        ]
        for image_path in (images or [])[:2]:
            encoded = _encode_image(image_path)
            if encoded:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,%s" % encoded},
                    }
                )

        try:
            response = self._get_client().chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ],
                temperature=self.temperature,
                max_tokens=220,
            )
            text = (response.choices[0].message.content or "").strip()
            if not text:
                raise ValueError("empty completion")
            return Explanation(
                text=text,
                provider="groq",
                model=model,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            # A provider outage must not lose the result. Degrade, and say so.
            return Explanation(
                text=template_explanation(entity),
                provider="template",
                model="offline_deterministic",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                degraded=True,
                error="groq unavailable: %s" % exc,
            )

    def parse_query(self, query, schema_hint):
        try:
            response = self._get_client().chat.completions.create(
                model=self._text_model or self._resolve_vision_model(),
                messages=[
                    {"role": "system", "content": schema_hint},
                    {"role": "user", "content": query},
                ],
                temperature=0.0,
                max_tokens=400,
                response_format={"type": "json_object"},
            )
            return (response.choices[0].message.content or "").strip() or None
        except Exception:  # noqa: BLE001
            return None


class LocalProvider(BaseProvider):
    """
    OpenAI-compatible local endpoint (llama.cpp server or vLLM).

    This is the path that satisfies PRD section 17: no traffic leaves the host.

    Sizing note for the 4 GB RTX 2050 this is developed on: Qwen2.5-VL-7B in
    fp16 needs roughly 16 GB and will not fit. Qwen2.5-VL-3B-Instruct at Q4
    (~2.4 GB) does fit in VRAM and is the model to serve here; the 7B at Q4
    (~5.5 GB) requires a CPU/GPU split and lands around 15-40 s per explanation,
    which is too slow for a live top-5.
    """

    name = "local"

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.endpoint = os.getenv("LOCAL_VLM_ENDPOINT", cfg.get("endpoint", "")).rstrip("/")
        self.model = cfg.get("model_name", "qwen2.5-vl-3b-instruct")
        self.timeout = float(cfg.get("timeout_sec", 60))

    def available(self) -> bool:
        if not self.endpoint:
            return False
        import httpx

        try:
            resp = httpx.get("%s/models" % self.endpoint, timeout=2.0)
            return resp.status_code < 500
        except Exception:  # noqa: BLE001
            return False

    def _post(self, payload: Dict[str, Any]):
        import httpx

        resp = httpx.post(
            "%s/chat/completions" % self.endpoint, json=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def explain(self, entity, images=None) -> Explanation:
        t0 = time.perf_counter()
        content: List[Dict[str, Any]] = [
            {
                "type": "text",
                "text": "Evidence record:\n%s\n\nExplain this candidate."
                % _evidence_block(entity),
            }
        ]
        for image_path in (images or [])[:2]:
            encoded = _encode_image(image_path)
            if encoded:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,%s" % encoded},
                    }
                )

        try:
            data = self._post(
                {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": content},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 220,
                }
            )
            text = (data["choices"][0]["message"]["content"] or "").strip()
            if not text:
                raise ValueError("empty completion")
            return Explanation(
                text=text,
                provider="local",
                model=self.model,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
            )
        except Exception as exc:  # noqa: BLE001
            return Explanation(
                text=template_explanation(entity),
                provider="template",
                model="offline_deterministic",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                degraded=True,
                error="local vlm unavailable: %s" % exc,
            )

    def parse_query(self, query, schema_hint):
        try:
            data = self._post(
                {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": schema_hint},
                        {"role": "user", "content": query},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 400,
                }
            )
            return (data["choices"][0]["message"]["content"] or "").strip() or None
        except Exception:  # noqa: BLE001
            return None


# --------------------------------------------------------------------------- registry


class VLMRegistry:
    """Resolves config/providers.yaml to a live provider, with template fallback."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or PROVIDERS_CONFIG
        self._cfg: Optional[Dict[str, Any]] = None
        self._provider: Optional[BaseProvider] = None
        self._template = TemplateProvider()

    def reload(self):
        self._cfg = None
        self._provider = None

    @property
    def config(self) -> Dict[str, Any]:
        if self._cfg is None:
            self._cfg = load_provider_config(self.config_path)
        return self._cfg

    @property
    def active_name(self) -> str:
        return self.config.get("active", "local")

    def provider(self) -> BaseProvider:
        if self._provider is not None:
            return self._provider

        name = self.active_name
        block = (self.config.get("providers", {}) or {}).get(name, {}) or {}

        if name == "groq":
            candidate: BaseProvider = GroqProvider(block)
        elif name == "local":
            if block.get("provider_type") == "offline_deterministic":
                # The config explicitly asks for the template path rather than a
                # served model. Honour it instead of probing an endpoint.
                candidate = self._template
            else:
                candidate = LocalProvider(block)
        else:
            candidate = self._template

        self._provider = candidate if candidate.available() else self._template
        return self._provider

    def status(self) -> Dict[str, Any]:
        provider = self.provider()
        return {
            "configured": self.active_name,
            "active": provider.name,
            "degraded": provider.name == "template" and self.active_name != "local",
        }

    def explain(self, entity: Dict[str, Any], images: Optional[List[str]] = None) -> Explanation:
        return self.provider().explain(entity, images=images)

    def parse_query(self, query: str, schema_hint: str) -> Optional[str]:
        return self.provider().parse_query(query, schema_hint)


registry = VLMRegistry()


def explain_candidate(entity: Dict[str, Any], images: Optional[List[str]] = None) -> Explanation:
    """Explain one candidate. Used for the top N only, never during retrieval."""
    return registry.explain(entity, images=images)


def provider_status() -> Dict[str, Any]:
    return registry.status()
