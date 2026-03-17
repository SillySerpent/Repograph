"""RepoGraph Python API service facade."""
from __future__ import annotations

from repograph.services.service_base import RepoGraphServiceBase
from repograph.services.service_full_report import ServiceFullReportMixin
from repograph.services.service_impact import ServiceImpactMixin
from repograph.services.service_overview import ServiceOverviewMixin
from repograph.services.service_pathways import ServicePathwaysMixin
from repograph.services.service_rules import ServiceRulesMixin
from repograph.services.service_runtime import ServiceLogsMixin, ServiceRuntimeMixin
from repograph.services.service_search import ServiceSearchMixin
from repograph.services.service_symbols import ServiceSymbolsMixin


class RepoGraphService(
    ServiceOverviewMixin,
    ServiceRulesMixin,
    ServiceRuntimeMixin,
    ServicePathwaysMixin,
    ServiceSymbolsMixin,
    ServiceImpactMixin,
    ServiceSearchMixin,
    ServiceFullReportMixin,
    ServiceLogsMixin,
    RepoGraphServiceBase,
):
    """High-level API for indexing and querying a repository with RepoGraph."""

