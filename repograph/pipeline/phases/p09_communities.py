"""Phase 9 — Communities: Leiden algorithm community detection on the call graph."""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict

from repograph.core.models import CommunityNode, NodeID
from repograph.graph_store.store import GraphStore


def run(store: GraphStore, min_community_size: int = 8) -> None:
    """
    Build an undirected graph from CALLS edges, run Leiden community detection,
    label each community, then store Community nodes and MEMBER_OF edges.

    Parameters
    ----------
    store:
        Open GraphStore for the repo.
    min_community_size:
        Communities smaller than this threshold are merged into their
        most-connected neighbour after detection.  Set to 0 or 1 to
        disable merging (keep all micro-clusters).
    """
    try:
        import igraph as ig
        import leidenalg
    except ImportError:
        # Fall back to simple connected-components if leidenalg not available
        _run_simple_communities(store, min_community_size=min_community_size)
        return

    functions = store.get_all_functions()
    call_edges = store.get_all_call_edges()

    if not functions:
        return

    # --- FIX: Filter out fuzzy/low-confidence edges before community detection.
    # Fuzzy edges (conf < 0.5) create spurious connections between otherwise
    # separate modules, causing Leiden to collapse everything into one
    # mega-cluster.  Only use edges we're reasonably confident about.
    MIN_COMMUNITY_CONFIDENCE = 0.5
    call_edges = [e for e in call_edges if e.get("confidence", 0) >= MIN_COMMUNITY_CONFIDENCE]

    # Build igraph
    func_ids = [f["id"] for f in functions]
    id_to_idx = {fid: i for i, fid in enumerate(func_ids)}

    edges_ig: list[tuple[int, int]] = []
    for e in call_edges:
        src = id_to_idx.get(e["from"])
        tgt = id_to_idx.get(e["to"])
        if src is not None and tgt is not None and src != tgt:
            edges_ig.append((src, tgt))

    g = ig.Graph(n=len(func_ids), edges=edges_ig, directed=False)
    g.simplify()  # remove multi-edges and self-loops

    if g.ecount() == 0:
        # No edges — each file is its own community
        _assign_file_communities(functions, store)
        return

    # Run Leiden
    partition = leidenalg.find_partition(g, leidenalg.ModularityVertexPartition)

    # Build community objects
    membership: list[int] = partition.membership

    # Group functions by community
    comm_to_funcs: dict[int, list[dict]] = defaultdict(list)
    for i, fn in enumerate(functions):
        comm_to_funcs[membership[i]].append(fn)

    for comm_id_int, members in comm_to_funcs.items():
        # Label by most common *package* directory (second path segment for src/
        # and scripts/ hierarchies, first segment otherwise).
        # e.g. "src/advisor/engine.py" → "Advisor"
        #      "tests/phase_2/test_risk.py" → "Tests · Phase 2"
        #      "scripts/training/run_gym.py" → "Scripts · Training"
        pkg_labels = [_package_label(f["file_path"]) for f in members]
        label = Counter(pkg_labels).most_common(1)[0][0]

        # Cohesion: internal edges / max possible
        member_ids = {f["id"] for f in members}
        internal = sum(
            1 for e in call_edges
            if e["from"] in member_ids and e["to"] in member_ids
        )
        n = len(members)
        max_possible = n * (n - 1) / 2 if n > 1 else 1
        cohesion = internal / max_possible if max_possible > 0 else 0.0

        comm_node_id = f"community:{comm_id_int}"

        community = CommunityNode(
            id=comm_node_id,
            label=label,
            cohesion=cohesion,
            member_count=len(members),
        )
        store.upsert_community(community)

        # Build set of file paths in this community for class assignment
        member_file_paths = {f["file_path"] for f in members}

        for fn in members:
            store.update_function_flags(fn["id"], community_id=comm_node_id)
            try:
                store.insert_member_of_edge(fn["id"], comm_node_id)
            except Exception:
                pass

        # Assign classes to communities based on which community their file belongs to
        _assign_classes_to_community(store, member_file_paths, comm_node_id)

    # --- Micro-cluster merge pass -------------------------------------------
    # Communities smaller than min_community_size are merged into their
    # most-connected neighbour.  This prevents 500+ single-file fragments
    # from drowning the useful higher-level clusters.
    if min_community_size > 1:
        _merge_micro_communities(
            store, comm_to_funcs, call_edges, functions, min_community_size
        )


def _merge_micro_communities(
    store: GraphStore,
    comm_to_funcs: dict[int, list[dict]],
    call_edges: list[dict],
    all_functions: list[dict],
    min_size: int,
) -> None:
    """Merge communities smaller than *min_size* into their most-connected neighbour.

    Algorithm
    ---------
    1. Identify micro-communities (member_count < min_size).
    2. For each micro-community, count cross-community CALLS edges to every
       other community and pick the target with the most connections.
    3. Reassign all members of the micro-community to the winning target.
    4. Delete the now-empty micro-community node from the store.
    5. Recompute the target community's label, cohesion, and member_count.

    This runs entirely in-process — no additional graph queries per member.
    """
    # Build function-id → community-id map from current assignment
    fn_to_comm: dict[str, int] = {}
    for comm_id_int, members in comm_to_funcs.items():
        for fn in members:
            fn_to_comm[fn["id"]] = comm_id_int

    # Build edge index: fn_id → set of neighbour fn_ids (undirected)
    adj: dict[str, set[str]] = defaultdict(set)
    for e in call_edges:
        src, tgt = e["from"], e["to"]
        adj[src].add(tgt)
        adj[tgt].add(src)

    # Identify micros and larges
    micro_ids = {cid for cid, members in comm_to_funcs.items()
                 if len(members) < min_size}
    if not micro_ids:
        return   # nothing to merge

    # Process each micro-community
    for micro_cid in list(micro_ids):
        if micro_cid not in comm_to_funcs:
            continue   # already merged into another micro in this loop
        micro_members = comm_to_funcs[micro_cid]
        micro_fn_ids = {fn["id"] for fn in micro_members}

        # Count cross-community edges to each candidate target
        edge_counts: Counter = Counter()
        for fn_id in micro_fn_ids:
            for neighbour_id in adj.get(fn_id, set()):
                target_comm = fn_to_comm.get(neighbour_id)
                if target_comm is not None and target_comm != micro_cid:
                    edge_counts[target_comm] += 1

        if not edge_counts:
            # Isolated micro — will be grouped with other isolated micros
            # by package label in the post-pass below.
            continue

        best_target = edge_counts.most_common(1)[0][0]

        # Reassign members
        for fn in micro_members:
            fn_to_comm[fn["id"]] = best_target
            new_comm_node_id = f"community:{best_target}"
            store.update_function_flags(fn["id"], community_id=new_comm_node_id)
            try:
                store.insert_member_of_edge(fn["id"], new_comm_node_id)
            except Exception:
                pass

        comm_to_funcs[best_target].extend(micro_members)
        del comm_to_funcs[micro_cid]

        # Delete the now-empty micro-community node
        try:
            store.query(
                "MATCH (c:Community {id: $id}) DETACH DELETE c",
                {"id": f"community:{micro_cid}"}
            )
        except Exception:
            pass

    # Recompute labels and stats for communities that absorbed micro-clusters
    absorbed_targets = {
        fn_to_comm[fn["id"]]
        for cid in list(comm_to_funcs)
        for fn in comm_to_funcs[cid]
    } - micro_ids

    for target_cid in absorbed_targets:
        members = comm_to_funcs.get(target_cid, [])
        if not members:
            continue
        member_ids = {fn["id"] for fn in members}
        pkg_labels = [_package_label(fn["file_path"]) for fn in members]
        label = Counter(pkg_labels).most_common(1)[0][0]
        internal = sum(
            1 for e in call_edges
            if e["from"] in member_ids and e["to"] in member_ids
        )
        n = len(members)
        max_possible = n * (n - 1) / 2 if n > 1 else 1
        cohesion = internal / max_possible if max_possible > 0 else 0.0
        comm_node_id = f"community:{target_cid}"
        community = CommunityNode(
            id=comm_node_id,
            label=label,
            cohesion=cohesion,
            member_count=len(members),
        )
        store.upsert_community(community)

    # --- Isolated singleton grouping post-pass ----------------------------
    # Any micro-community with no cross-community edges was skipped by the
    # merge loop above (it had nothing to merge into).  Group these isolated
    # singletons by their package label so they form meaningful named buckets
    # rather than staying as hundreds of size-1 noise communities.
    remaining_micros = {
        cid: members
        for cid, members in comm_to_funcs.items()
        if len(members) < min_size
    }
    if remaining_micros:
        # Group isolated micros by coarse folder bucket (e.g. all utils/* → Utils)
        label_to_members: dict[str, list[dict]] = defaultdict(list)
        label_to_micro_cids: dict[str, list[int]] = defaultdict(list)
        for cid, members in remaining_micros.items():
            coarse_keys = [_coarse_isolation_bucket(fn["file_path"]) for fn in members]
            bucket = Counter(coarse_keys).most_common(1)[0][0]
            label_to_members[bucket].extend(members)
            label_to_micro_cids[bucket].append(cid)

        for label, members in label_to_members.items():
            # Use a stable deterministic ID derived from the label
            import hashlib
            bucket_key = hashlib.md5(f"bucket:{label}".encode()).hexdigest()[:8]
            bucket_comm_id = f"community:bucket_{bucket_key}"

            member_ids = {fn["id"] for fn in members}
            internal = sum(
                1 for e in call_edges
                if e["from"] in member_ids and e["to"] in member_ids
            )
            n = len(members)
            max_possible = n * (n - 1) / 2 if n > 1 else 1
            cohesion = internal / max_possible if max_possible > 0 else 0.0

            bucket_community = CommunityNode(
                id=bucket_comm_id,
                label=label,
                cohesion=cohesion,
                member_count=len(members),
            )
            store.upsert_community(bucket_community)

            for fn in members:
                fn_to_comm[fn["id"]] = -1  # sentinel (now in bucket)
                store.update_function_flags(fn["id"], community_id=bucket_comm_id)
                try:
                    store.insert_member_of_edge(fn["id"], bucket_comm_id)
                except Exception:
                    pass

            # Delete the now-empty individual micro-community nodes
            for old_cid in label_to_micro_cids[label]:
                try:
                    store.query(
                        "MATCH (c:Community {id: $id}) DETACH DELETE c",
                        {"id": f"community:{old_cid}"}
                    )
                except Exception:
                    pass


def _assign_classes_to_community(
    store: GraphStore,
    member_file_paths: set[str],
    community_id: str,
) -> None:
    """Assign all classes whose file belongs to this community."""
    for file_path in member_file_paths:
        classes = store.get_classes_in_file(file_path)
        for cls in classes:
            try:
                store.update_class_community(cls["id"], community_id)
                store.insert_class_in_community_edge(cls["id"], community_id)
            except Exception:
                pass


def _coarse_isolation_bucket(file_path: str) -> str:
    """Directory bucket for merging isolated micro-communities.

    Finer :func:`_package_label` splits ``utils/formatting`` vs ``utils/math_utils``
    into different labels; for leftover singletons we still want one bucket per
    shared parent folder (e.g. all ``utils/*`` → ``Utils``).

    Paths may be repo-relative (``utils/foo.py``) or absolute (``/tmp/.../repo/utils/foo.py``),
    so we scan *all* path segments — not only the first.
    """
    _BUCKET_DIRS = frozenset({
        "utils", "util", "helpers", "helper", "common", "shared", "lib", "libs",
    })
    parts = [p for p in file_path.replace("\\", "/").split("/") if p]
    for seg in parts:
        if seg.lower() in _BUCKET_DIRS:
            return seg.replace("_", " ").title()
    if len(parts) >= 2:
        top = parts[0].lower()
        if top in _BUCKET_DIRS:
            return parts[0].replace("_", " ").title()
    return _package_label(file_path)


def _package_label(file_path: str) -> str:
    """Return a human-readable community label derived from the file path.

    Strategy:
    - "src/advisor/engine.py"         → "Advisor"
    - "src/market/candle_builder.py"  → "Market"
    - "tests/phase_2/test_risk.py"    → "Tests · Phase 2"
    - "scripts/training/run_gym.py"   → "Scripts · Training"
    - "main.py"                       → "Root"
    """
    parts = [p for p in file_path.replace("\\", "/").split("/") if p]
    if not parts:
        return "Unknown"

    top = parts[0].lower()

    # Strip common top-level wrappers and use the next meaningful segment
    if top in ("src", "lib", "app", "pkg") and len(parts) >= 3:
        return parts[1].replace("_", " ").title()
    if top in ("src", "lib", "app", "pkg") and len(parts) == 2:
        return parts[1].replace("_", " ").title()

    if top == "tests" and len(parts) >= 3:
        return f"Tests · {parts[1].replace('_', ' ').title()}"
    if top == "tests":
        return "Tests"

    if top in ("scripts", "script") and len(parts) >= 3:
        return f"Scripts · {parts[1].replace('_', ' ').title()}"
    if top in ("scripts", "script"):
        return "Scripts"

    # Generic: use second segment if present, else first
    if len(parts) >= 2:
        return parts[1].replace("_", " ").title()
    return parts[0].replace("_", " ").title()


def _assign_file_communities(functions: list[dict], store: GraphStore) -> None:
    """Fallback: group functions by their containing package directory."""
    dir_to_funcs: dict[str, list[dict]] = defaultdict(list)
    for fn in functions:
        pkg = _package_label(fn["file_path"])
        dir_to_funcs[pkg].append(fn)

    for folder, members in dir_to_funcs.items():
        comm_id = f"community:{hashlib.sha256(folder.encode()).hexdigest()[:8]}"
        label = folder
        community = CommunityNode(
            id=comm_id, label=label, cohesion=1.0, member_count=len(members)
        )
        store.upsert_community(community)
        member_file_paths = {fn["file_path"] for fn in members}
        for fn in members:
            store.update_function_flags(fn["id"], community_id=comm_id)
            try:
                store.insert_member_of_edge(fn["id"], comm_id)
            except Exception:
                pass
        _assign_classes_to_community(store, member_file_paths, comm_id)


def _run_simple_communities(store: GraphStore, min_community_size: int = 8) -> None:
    """Connected-components fallback when leidenalg is unavailable."""
    functions = store.get_all_functions()
    call_edges = store.get_all_call_edges()
    if not functions:
        return

    # Align with Leiden path: ignore fuzzy edges for structure
    MIN_COMMUNITY_CONFIDENCE = 0.5
    call_edges = [e for e in call_edges if e.get("confidence", 0) >= MIN_COMMUNITY_CONFIDENCE]

    # Union-Find
    parent = {f["id"]: f["id"] for f in functions}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for e in call_edges:
        if e["from"] in parent and e["to"] in parent:
            union(e["from"], e["to"])

    # Group by root
    root_to_funcs: dict[str, list[dict]] = defaultdict(list)
    for fn in functions:
        root = find(fn["id"])
        root_to_funcs[root].append(fn)

    comm_to_funcs: dict[int, list[dict]] = {}
    for i, (_root, members) in enumerate(root_to_funcs.items()):
        comm_to_funcs[i] = members

    for comm_id_int, members in comm_to_funcs.items():
        comm_id = f"community:{comm_id_int}"
        pkg_labels = [_package_label(f["file_path"]) for f in members]
        label = Counter(pkg_labels).most_common(1)[0][0]
        community = CommunityNode(
            id=comm_id, label=label, cohesion=1.0, member_count=len(members)
        )
        store.upsert_community(community)
        member_file_paths = {fn["file_path"] for fn in members}
        for fn in members:
            store.update_function_flags(fn["id"], community_id=comm_id)
            try:
                store.insert_member_of_edge(fn["id"], comm_id)
            except Exception:
                pass
        _assign_classes_to_community(store, member_file_paths, comm_id)

    if min_community_size > 1:
        _merge_micro_communities(
            store, comm_to_funcs, call_edges, functions, min_community_size
        )
