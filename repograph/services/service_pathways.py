"""Pathway-oriented RepoGraph service methods."""
from __future__ import annotations

from repograph.services.service_base import RepoGraphServiceProtocol, _observed_service_call


class ServicePathwaysMixin:
    """Pathway lookup and context-document surfaces."""

    @_observed_service_call(
        "service_pathways",
        metadata_fn=lambda self, min_confidence=0.0, include_tests=False: {
            "min_confidence": float(min_confidence),
            "include_tests": bool(include_tests),
        },
    )
    def pathways(
        self: RepoGraphServiceProtocol,
        min_confidence: float = 0.0,
        include_tests: bool = False,
    ) -> list[dict]:
        """Return all detected pathways, sorted by importance then confidence."""
        store = self._get_store()
        all_pathways = store.get_all_pathways()
        if not include_tests:
            all_pathways = [
                pathway
                for pathway in all_pathways
                if pathway.get("source") != "auto_detected_test"
            ]
        filtered = [
            pathway
            for pathway in all_pathways
            if pathway.get("confidence", 0) >= min_confidence
        ]
        return sorted(
            filtered,
            key=lambda pathway: (
                -(pathway.get("importance_score") or 0.0),
                -(pathway.get("confidence") or 0.0),
            ),
        )

    @_observed_service_call(
        "service_get_pathway",
        metadata_fn=lambda self, name: {"pathway_name": name},
    )
    def get_pathway(self: RepoGraphServiceProtocol, name: str) -> dict | None:
        """Return the full stored record for a named pathway."""
        return self._get_store().get_pathway(name)

    @_observed_service_call(
        "service_pathway_steps",
        metadata_fn=lambda self, name: {"pathway_name": name},
    )
    def pathway_steps(self: RepoGraphServiceProtocol, name: str) -> list[dict]:
        """Return ordered execution steps for a named pathway."""
        store = self._get_store()
        pathway = store.get_pathway(name)
        if pathway is None:
            return []
        return store.get_pathway_steps(pathway["id"])

    @_observed_service_call(
        "service_pathway_document",
        metadata_fn=lambda self, name: {"pathway_name": name},
    )
    def pathway_document(self: RepoGraphServiceProtocol, name: str) -> str | None:
        """Return the full context document for a pathway, generating it on demand."""
        store = self._get_store()
        pathway = store.get_pathway(name)
        if pathway is None:
            return None
        context_doc = pathway.get("context_doc") or ""
        if not context_doc:
            from repograph.plugins.exporters.pathway_contexts.generator import generate_pathway_context

            context_doc = generate_pathway_context(pathway["id"], store)
        return context_doc or None
