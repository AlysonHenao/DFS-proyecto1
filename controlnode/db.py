import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

from config import (
    DB_PATH,
    DEAD_TIMEOUT_S,
    REPLICATION_FACTOR,
    SCHEMA_PATH,
)

LOGGER = logging.getLogger(__name__)
_LOCK = threading.Lock()


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Creates a new SQLite connection configured with WAL and foreign keys."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def normalize_path(path: str) -> str:
    """Normalizes path so it starts with '/' and has no trailing slashes unless root."""
    parts = [part for part in path.strip().split("/") if part]
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def get_parent_path(path: str) -> str:
    """Returns the parent directory path for a normalized path."""
    if path == "/":
        return "/"
    parent = path.rsplit("/", 1)[0]
    return parent if parent else "/"


def init_db(db_path: str = DB_PATH, schema_path: str = SCHEMA_PATH) -> None:
    """Initializes the SQLite schema and seeds default data if needed."""
    with _LOCK:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        if not Path(schema_path).exists():
            raise FileNotFoundError(f"Schema file not found at {schema_path}")

        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        with get_connection(db_path) as conn:
            conn.executescript(schema_sql)
            # Seed default demo user if not exists
            # Default password 'demo' hashed with bcrypt
            # bcrypt hash for 'demo': $2b$12$Kk27eKzCqE4h5a7jK7cK0e8v8C/5k6R.3u2H1Z6c8v1g2h3j4k5l6 (or generate on the fly)
            cursor = conn.execute("SELECT id FROM users WHERE username = 'demo'")
            demo_user = cursor.fetchone()
            if not demo_user:
                # Precomputed standard bcrypt hash for 'demo'
                demo_hash = "$2b$12$xQ5gY5Z11n1vJz1f8b4vje7D1qI2XJ.aYVdGbZqjJ.dD44l388nhe"
                try:
                    import bcrypt
                    demo_hash = bcrypt.hashpw(b"demo", bcrypt.gensalt()).decode("utf-8")
                except Exception:
                    pass
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES ('demo', ?)",
                    (demo_hash,),
                )
                user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute(
                    "INSERT OR IGNORE INTO entries (owner_id, path, type, size, status) VALUES (?, '/', 'dir', 0, 'ready')",
                    (user_id,),
                )
            conn.commit()


# ----------------------------------------------------------------------
# Users & Auth
# ----------------------------------------------------------------------

def get_user_by_username(username: str, db_path: str = DB_PATH) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT id, username, password_hash, created_at FROM users WHERE username = ?",
            (username,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def create_user(username: str, password_hash: str, db_path: str = DB_PATH) -> dict[str, Any]:
    with _LOCK:
        with get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            # Ensure root directory entry exists for this user
            conn.execute(
                "INSERT OR IGNORE INTO entries (owner_id, path, type, size, status) VALUES (?, '/', 'dir', 0, 'ready')",
                (user_id,),
            )
            conn.commit()
            return {"id": user_id, "username": username}


# ----------------------------------------------------------------------
# Filesystem Operations (RF1)
# ----------------------------------------------------------------------

def get_entry(owner_id: int, path: str, db_path: str = DB_PATH) -> dict[str, Any] | None:
    norm_path = normalize_path(path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT id, owner_id, path, type, size, block_size, status, created_at "
            "FROM entries WHERE owner_id = ? AND path = ?",
            (owner_id, norm_path),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def create_directory(owner_id: int, path: str, db_path: str = DB_PATH) -> dict[str, Any]:
    norm_path = normalize_path(path)
    if norm_path == "/":
        raise ValueError("Root directory already exists")

    parent_path = get_parent_path(norm_path)
    with _LOCK:
        with get_connection(db_path) as conn:
            # Check parent exists and is a directory
            cursor = conn.execute(
                "SELECT id, type, status FROM entries WHERE owner_id = ? AND path = ?",
                (owner_id, parent_path),
            )
            parent = cursor.fetchone()
            if not parent or parent["type"] != "dir":
                raise KeyError("parent directory not found")

            # Check target doesn't already exist
            cursor = conn.execute(
                "SELECT id FROM entries WHERE owner_id = ? AND path = ?",
                (owner_id, norm_path),
            )
            if cursor.fetchone():
                raise FileExistsError("path already exists")

            conn.execute(
                "INSERT INTO entries (owner_id, path, type, size, status) VALUES (?, ?, 'dir', 0, 'ready')",
                (owner_id, norm_path),
            )
            conn.commit()
            return {"path": norm_path, "status": "created"}


def list_directory(owner_id: int, path: str = "/", db_path: str = DB_PATH) -> list[dict[str, Any]]:
    norm_path = normalize_path(path)
    with get_connection(db_path) as conn:
        # Check target directory exists
        cursor = conn.execute(
            "SELECT id, type FROM entries WHERE owner_id = ? AND path = ? AND type = 'dir'",
            (owner_id, norm_path),
        )
        dir_entry = cursor.fetchone()
        if not dir_entry:
            raise KeyError("directory not found")

        prefix = "/" if norm_path == "/" else f"{norm_path}/"
        # Query ready entries under owner
        cursor = conn.execute(
            "SELECT path, type, size, created_at FROM entries "
            "WHERE owner_id = ? AND status = 'ready' AND path != ?",
            (owner_id, norm_path),
        )
        rows = cursor.fetchall()

    entries = []
    for row in rows:
        item_path = row["path"]
        if item_path.startswith(prefix):
            remainder = item_path[len(prefix):]
            if "/" not in remainder and remainder:
                entries.append({
                    "name": remainder,
                    "type": row["type"],
                    "size": row["size"] if row["type"] == "file" else 0,
                    "created_at": row["created_at"],
                })

    entries.sort(key=lambda x: (x["type"] != "dir", x["name"]))
    return entries


def remove_directory(owner_id: int, path: str, db_path: str = DB_PATH) -> None:
    norm_path = normalize_path(path)
    if norm_path == "/":
        raise ValueError("Cannot remove root directory")

    prefix = f"{norm_path}/"
    with _LOCK:
        with get_connection(db_path) as conn:
            cursor = conn.execute(
                "SELECT id FROM entries WHERE owner_id = ? AND path = ? AND type = 'dir'",
                (owner_id, norm_path),
            )
            target = cursor.fetchone()
            if not target:
                raise KeyError("directory not found")

            # Check if directory has contents
            cursor = conn.execute(
                "SELECT id FROM entries WHERE owner_id = ? AND path LIKE ? LIMIT 1",
                (owner_id, f"{prefix}%"),
            )
            if cursor.fetchone():
                raise FileExistsError("directory not empty")

            conn.execute(
                "DELETE FROM entries WHERE owner_id = ? AND path = ?",
                (owner_id, norm_path),
            )
            conn.commit()


def remove_file(owner_id: int, path: str, db_path: str = DB_PATH) -> None:
    norm_path = normalize_path(path)
    with _LOCK:
        with get_connection(db_path) as conn:
            cursor = conn.execute(
                "SELECT id FROM entries WHERE owner_id = ? AND path = ? AND type = 'file' AND status = 'ready'",
                (owner_id, norm_path),
            )
            target = cursor.fetchone()
            if not target:
                raise KeyError("file not found")

            # Cascade delete in SQLite will delete blocks and replicas
            conn.execute(
                "DELETE FROM entries WHERE id = ?",
                (target["id"],),
            )
            conn.commit()


# ----------------------------------------------------------------------
# File Transfer Operations (RF2)
# ----------------------------------------------------------------------

def create_upload_plan(
    owner_id: int,
    path: str,
    size: int,
    block_size: int,
    blocks: list[dict[str, Any]],
    db_path: str = DB_PATH,
) -> int:
    norm_path = normalize_path(path)
    parent_path = get_parent_path(norm_path)

    with _LOCK:
        with get_connection(db_path) as conn:
            # Check parent directory exists
            cursor = conn.execute(
                "SELECT id, type FROM entries WHERE owner_id = ? AND path = ?",
                (owner_id, parent_path),
            )
            parent = cursor.fetchone()
            if not parent or parent["type"] != "dir":
                raise KeyError("parent directory not found")

            # Check if path already exists
            cursor = conn.execute(
                "SELECT id, status FROM entries WHERE owner_id = ? AND path = ?",
                (owner_id, norm_path),
            )
            existing = cursor.fetchone()
            if existing:
                if existing["status"] == "ready":
                    raise FileExistsError("path already exists")
                # If there is a previous abandoned upload, delete it
                conn.execute("DELETE FROM entries WHERE id = ?", (existing["id"],))

            conn.execute(
                "INSERT INTO entries (owner_id, path, type, size, block_size, status) "
                "VALUES (?, ?, 'file', ?, ?, 'uploading')",
                (owner_id, norm_path, size, block_size),
            )
            entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            for block in blocks:
                conn.execute(
                    "INSERT INTO blocks (block_id, entry_id, idx, size) VALUES (?, ?, ?, ?)",
                    (block["block_id"], entry_id, block["index"], block["size"]),
                )
            conn.commit()
            return entry_id


def commit_upload(
    owner_id: int,
    path: str,
    blocks_stored_on: list[dict[str, Any]],
    min_write_acks: int = 2,
    db_path: str = DB_PATH,
) -> None:
    norm_path = normalize_path(path)
    with _LOCK:
        with get_connection(db_path) as conn:
            cursor = conn.execute(
                "SELECT id, status FROM entries WHERE owner_id = ? AND path = ? AND type = 'file'",
                (owner_id, norm_path),
            )
            entry = cursor.fetchone()
            if not entry or entry["status"] != "uploading":
                raise KeyError("path not found or not in uploading state")

            entry_id = entry["id"]

            # Fetch expected blocks
            cursor = conn.execute(
                "SELECT block_id, idx, size FROM blocks WHERE entry_id = ? ORDER BY idx",
                (entry_id,),
            )
            expected_blocks = {row["block_id"]: dict(row) for row in cursor.fetchall()}

            received_block_ids = {b["block_id"] for b in blocks_stored_on}
            if set(expected_blocks.keys()) != received_block_ids:
                raise ValueError("Mismatch between expected and committed block IDs")

            # Verify acknowledgements and store replicas
            for b in blocks_stored_on:
                stored_on = b.get("stored_on", [])
                if len(stored_on) < min_write_acks:
                    raise ValueError(f"Block {b['block_id']} has fewer than {min_write_acks} confirmations")

                for addr in stored_on:
                    # Find node_id for address
                    node_cursor = conn.execute("SELECT node_id FROM nodes WHERE address = ?", (addr,))
                    node = node_cursor.fetchone()
                    if node:
                        node_id = node["node_id"]
                    else:
                        # Auto-register node if known address
                        node_id = addr.split(":")[0]
                        conn.execute(
                            "INSERT OR IGNORE INTO nodes (node_id, address, free_bytes, total_bytes, last_seen, status) "
                            "VALUES (?, ?, 0, 0, ?, 'alive')",
                            (node_id, addr, int(time.time())),
                        )

                    conn.execute(
                        "INSERT OR REPLACE INTO replicas (block_id, node_id) VALUES (?, ?)",
                        (b["block_id"], node_id),
                    )

            conn.execute(
                "UPDATE entries SET status = 'ready' WHERE id = ?",
                (entry_id,),
            )
            conn.commit()


def abort_upload(owner_id: int, path: str, db_path: str = DB_PATH) -> None:
    norm_path = normalize_path(path)
    with _LOCK:
        with get_connection(db_path) as conn:
            cursor = conn.execute(
                "SELECT id FROM entries WHERE owner_id = ? AND path = ? AND status = 'uploading'",
                (owner_id, norm_path),
            )
            entry = cursor.fetchone()
            if entry:
                conn.execute("DELETE FROM entries WHERE id = ?", (entry["id"],))
                conn.commit()


def get_download_plan(owner_id: int, path: str, db_path: str = DB_PATH) -> dict[str, Any] | None:
    norm_path = normalize_path(path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT id, size, block_size, status FROM entries "
            "WHERE owner_id = ? AND path = ? AND type = 'file' AND status = 'ready'",
            (owner_id, norm_path),
        )
        entry = cursor.fetchone()
        if not entry:
            return None

        cursor = conn.execute(
            "SELECT block_id, idx, size FROM blocks WHERE entry_id = ? ORDER BY idx",
            (entry["id"],),
        )
        blocks = cursor.fetchall()

        plan_blocks = []
        for b in blocks:
            # Query replica nodes that are currently alive
            node_cursor = conn.execute(
                "SELECT n.address FROM replicas r "
                "JOIN nodes n ON n.node_id = r.node_id "
                "WHERE r.block_id = ? AND n.status = 'alive' "
                "ORDER BY n.free_bytes DESC",
                (b["block_id"],),
            )
            addresses = [row["address"] for row in node_cursor.fetchall()]

            # If no alive nodes found, fallback to any registered replica node
            if not addresses:
                fallback_cursor = conn.execute(
                    "SELECT n.address FROM replicas r "
                    "JOIN nodes n ON n.node_id = r.node_id "
                    "WHERE r.block_id = ?",
                    (b["block_id"],),
                )
                addresses = [row["address"] for row in fallback_cursor.fetchall()]

            plan_blocks.append({
                "index": b["idx"],
                "block_id": b["block_id"],
                "size": b["size"],
                "nodes": addresses,
            })

        return {
            "size": entry["size"],
            "block_size": entry["block_size"],
            "blocks": plan_blocks,
        }


# ----------------------------------------------------------------------
# Nodes & Heartbeats
# ----------------------------------------------------------------------

def upsert_node(
    node_id: str,
    address: str,
    free_bytes: int,
    total_bytes: int,
    db_path: str = DB_PATH,
) -> None:
    now = int(time.time())
    with _LOCK:
        with get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO nodes (node_id, address, free_bytes, total_bytes, last_seen, status) "
                "VALUES (?, ?, ?, ?, ?, 'alive') "
                "ON CONFLICT(node_id) DO UPDATE SET "
                "address = excluded.address, "
                "free_bytes = excluded.free_bytes, "
                "total_bytes = excluded.total_bytes, "
                "last_seen = excluded.last_seen, "
                "status = 'alive'",
                (node_id, address, free_bytes, total_bytes, now),
            )
            conn.commit()


def get_alive_nodes(db_path: str = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT node_id, address, free_bytes, total_bytes, last_seen, status "
            "FROM nodes WHERE status = 'alive' ORDER BY free_bytes DESC"
        )
        return [dict(row) for row in cursor.fetchall()]


def mark_dead_nodes(dead_timeout_s: float = DEAD_TIMEOUT_S, db_path: str = DB_PATH) -> list[str]:
    threshold = int(time.time() - dead_timeout_s)
    with _LOCK:
        with get_connection(db_path) as conn:
            cursor = conn.execute(
                "SELECT node_id FROM nodes WHERE status = 'alive' AND last_seen <= ?",
                (threshold,),
            )
            dead_nodes = [row["node_id"] for row in cursor.fetchall()]
            if dead_nodes:
                conn.execute(
                    "UPDATE nodes SET status = 'dead' WHERE status = 'alive' AND last_seen <= ?",
                    (threshold,),
                )
                conn.commit()
                LOGGER.warning("Marked DataNodes as dead due to timeout: %s", dead_nodes)
            return dead_nodes


def get_orphan_blocks_for_node(
    reported_block_ids: list[str],
    db_path: str = DB_PATH,
) -> list[str]:
    """Returns block IDs from reported_block_ids that do not exist in the blocks table."""
    if not reported_block_ids:
        return []

    orphans = []
    with get_connection(db_path) as conn:
        # Check in batches of 500
        batch_size = 500
        for i in range(0, len(reported_block_ids), batch_size):
            batch = reported_block_ids[i:i + batch_size]
            placeholders = ",".join("?" for _ in batch)
            cursor = conn.execute(
                f"SELECT block_id FROM blocks WHERE block_id IN ({placeholders})",
                batch,
            )
            known_ids = {row["block_id"] for row in cursor.fetchall()}
            for bid in batch:
                if bid not in known_ids:
                    orphans.append(bid)
    return orphans


def get_under_replicated_blocks(
    target_replication: int = REPLICATION_FACTOR,
    db_path: str = DB_PATH,
) -> list[dict[str, Any]]:
    """Identifies ready blocks with fewer than target_replication replicas on alive nodes."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT b.block_id, group_concat(n.address) as alive_addrs, COUNT(n.node_id) as alive_count
            FROM blocks b
            JOIN entries e ON e.id = b.entry_id
            LEFT JOIN replicas r ON r.block_id = b.block_id
            LEFT JOIN nodes n ON n.node_id = r.node_id AND n.status = 'alive'
            WHERE e.status = 'ready'
            GROUP BY b.block_id
            HAVING alive_count < ? AND alive_count > 0
            """,
            (target_replication,),
        )
        rows = cursor.fetchall()
        result = []
        for row in rows:
            addrs = row["alive_addrs"].split(",") if row["alive_addrs"] else []
            result.append({
                "block_id": row["block_id"],
                "alive_addresses": addrs,
                "alive_count": row["alive_count"],
            })
        return result


# ----------------------------------------------------------------------
# Snapshots (Leader -> Follower Replication)
# ----------------------------------------------------------------------

def create_snapshot_bytes(db_path: str = DB_PATH) -> bytes:
    """Takes a consistent binary snapshot of the SQLite database."""
    with _LOCK:
        with get_connection(db_path) as conn:
            return conn.serialize()


def restore_from_snapshot_bytes(snapshot_bytes: bytes, db_path: str = DB_PATH) -> None:
    """Restores SQLite database from binary snapshot bytes atomically."""
    with _LOCK:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # Write to temporary file then atomic replace
        temp_path = f"{db_path}.tmp"
        with open(temp_path, "wb") as f:
            f.write(snapshot_bytes)
        Path(temp_path).replace(db_path)
        LOGGER.info("Successfully restored metadata database from snapshot (%d bytes)", len(snapshot_bytes))
