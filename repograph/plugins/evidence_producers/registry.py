from __future__ import annotations

import threading

from repograph.core.plugin_framework import EvidenceProducerPlugin, PluginRegistry
from repograph.plugins.discovery import EVIDENCE_PRODUCER_ORDER, iter_build_plugins

_EVIDENCE_PRODUCER_REGISTRY: PluginRegistry[EvidenceProducerPlugin] = PluginRegistry("evidence_producer")
_DEFAULTS_REGISTERED = False
_DEFAULTS_LOCK = threading.Lock()


def get_registry() -> PluginRegistry[EvidenceProducerPlugin]:
    ensure_default_evidence_producers_registered()
    return _EVIDENCE_PRODUCER_REGISTRY


def register_evidence_producer(plugin: EvidenceProducerPlugin, *, replace: bool = False) -> None:
    _EVIDENCE_PRODUCER_REGISTRY.register(plugin, replace=replace)


def get_evidence_producer(plugin_id: str) -> EvidenceProducerPlugin | None:
    ensure_default_evidence_producers_registered()
    return _EVIDENCE_PRODUCER_REGISTRY.get(plugin_id)


def evidence_producer_manifests() -> list[dict]:
    ensure_default_evidence_producers_registered()
    return _EVIDENCE_PRODUCER_REGISTRY.manifests()


def ensure_default_evidence_producers_registered() -> None:
    global _DEFAULTS_REGISTERED
    if _DEFAULTS_REGISTERED:
        return
    with _DEFAULTS_LOCK:
        if _DEFAULTS_REGISTERED:
            return
        for build in iter_build_plugins(
            "repograph.plugins.evidence_producers",
            EVIDENCE_PRODUCER_ORDER,
        ):
            register_evidence_producer(build())
        _DEFAULTS_REGISTERED = True
