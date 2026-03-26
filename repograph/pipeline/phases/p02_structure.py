"""Phase 2 — Structure: build folder tree and CONTAINS/IN_FOLDER edges."""
from __future__ import annotations

import os

from repograph.core.models import FileRecord, FolderNode, NodeID
from repograph.graph_store.store import GraphStore


def run(files: list[FileRecord], store: GraphStore, repo_root: str) -> None:
    """
    Build Folder nodes for every directory that contains a source file,
    create CONTAINS edges (Folder→File) and IN_FOLDER edges (File→Folder).
    """
    seen_folders: set[str] = set()

    for fr in files:
        # Build all parent dirs up to repo root
        parts = fr.path.split("/")
        # parts[-1] is the filename, parts[:-1] are directories
        dir_parts = parts[:-1]

        for depth, _ in enumerate(dir_parts):
            folder_path = "/".join(dir_parts[: depth + 1])
            if folder_path in seen_folders:
                continue
            seen_folders.add(folder_path)

            folder_name = dir_parts[depth]
            folder_id = NodeID.make_folder_id(folder_path)

            folder = FolderNode(
                id=folder_id,
                path=folder_path,
                name=folder_name,
                depth=depth + 1,
            )
            store.upsert_folder(folder)

        # Root-level files get associated with a "." folder
        if not dir_parts:
            folder_path = "."
            if folder_path not in seen_folders:
                seen_folders.add(folder_path)
                store.upsert_folder(FolderNode(
                    id=NodeID.make_folder_id("."),
                    path=".", name=".", depth=0,
                ))

        folder_path = "/".join(dir_parts) if dir_parts else "."
        folder_id = NodeID.make_folder_id(folder_path)
        file_id = NodeID.make_file_id(fr.path)

        store.insert_folder_file_edges(folder_id, file_id)
