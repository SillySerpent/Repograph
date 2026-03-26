from __future__ import annotations

from repograph.core.models import FileRecord
from repograph.core.plugin_framework import ExporterPlugin, PluginManifest
from repograph.docs.mirror import generate_mirror
from repograph.docs.staleness import StalenessTracker
from repograph.graph_store.store import GraphStore


def _file_records_from_store(store: GraphStore, repo_root: str) -> list[FileRecord]:
    records: list[FileRecord] = []
    for row in store.get_all_files():
        rel = row.get("path", "")
        full = (repo_root.rstrip("/") + "/" + rel).replace("//", "/") if repo_root else rel
        records.append(FileRecord(
            path=rel,
            abs_path=full,
            name=rel.rsplit("/", 1)[-1],
            extension=("." + rel.rsplit(".", 1)[-1]) if "." in rel else "",
            language=row.get("language", ""),
            size_bytes=0,
            line_count=row.get("line_count") or 0,
            source_hash=row.get("source_hash") or "",
            is_test=bool(row.get("is_test")),
            is_config=bool(row.get("is_config")),
            mtime=0.0,
        ))
    return records


class DocsMirrorExporterPlugin(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.docs_mirror",
        name="Docs mirror exporter",
        kind="exporter",
        description="Generates .repograph/mirror structured and narrative sidecars from the indexed graph.",
        requires=("graph.pathways",),
        produces=("artifacts.mirror", "artifacts.meta_json"),
        hooks=("on_export",),
        order=220,
        after=("exporter.modules", "exporter.pathways"),
    )

    def export(self, store: GraphStore | None = None, repograph_dir: str = "", config=None, **kwargs):
        if store is None or not repograph_dir:
            return {"kind": "docs_mirror", "count": 0}
        repo_root = getattr(config, "repo_root", "") if config is not None else ""
        files = _file_records_from_store(store, repo_root)
        staleness = StalenessTracker(repograph_dir)
        generate_mirror(files, store, repograph_dir, staleness)
        return {"kind": "docs_mirror", "count": len(files)}


def build_plugin() -> DocsMirrorExporterPlugin:
    return DocsMirrorExporterPlugin()
