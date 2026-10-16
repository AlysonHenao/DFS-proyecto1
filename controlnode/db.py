import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any
import uuid

import config
from config import (
    BLOCK_SIZE_BYTES,
    DB_PATH,
    DEAD_TIMEOUT_S,
    REPLICATION_FACTOR,
    SCHEMA_PATH,
)

LOGGER = logging.getLogger(__name__)
_LOCK = threading.Lock()


class _ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Creates a new SQLite connection configured with WAL and foreign keys."""
    target_path = db_path if db_path is not None else getattr(config, "DB_PATH", DB_PATH)
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target_path, timeout=10.0, factory=_ManagedConnection)
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


def init_db(db_path: str | None = None, schema_path: str = SCHEMA_PATH) -> None:
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

def get_user_by_username(username: str, db_path: str | None = None) -> dict[str, Any] | None:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT id, username, password_hash, created_at FROM users WHERE username = ?",
            (username,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def create_user(username: str, password_hash: str, db_path: str | None = None) -> dict[str, Any]:
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

def get_entry(owner_id: int, path: str, db_path: str | None = None) -> dict[str, Any] | None:
    norm_path = normalize_path(path)
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT id, owner_id, path, type, size, block_size, status, created_at "
            "FROM entries WHERE owner_id = ? AND path = ?",
            (owner_id, norm_path),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def create_directory(owner_id: int, path: str, db_path: str | None = None) -> dict[str, Any]:
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


def list_directory(owner_id: int, path: str = "/", db_path: str | None = None) -> list[dict[str, Any]]:
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


def remove_directory(owner_id: int, path: str, db_path: str | None = None) -> None:
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


def remove_file(owner_id: int, path: str, db_path: str | None = None) -> None:
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
    db_path: str | None = None,
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
    db_path: str | None = None,
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
            ensure_version_for_entry(conn, entry_id)
            conn.commit()


def ensure_version_for_entry(conn: sqlite3.Connection, entry_id: int) -> int:
    """Ensures at least version 1 exists for a ready file entry that has blocks, returning latest version_num."""
    cursor = conn.execute(
        "SELECT MAX(version_num) as max_v FROM file_versions WHERE entry_id = ?",
        (entry_id,),
    )
    row = cursor.fetchone()
    if row and row["max_v"] is not None:
        return row["max_v"]

    b_cursor = conn.execute(
        "SELECT block_id, idx, size FROM blocks WHERE entry_id = ? ORDER BY idx",
        (entry_id,),
    )
    blocks = b_cursor.fetchall()
    if not blocks:
        return 0

    entry_cur = conn.execute("SELECT size, block_size FROM entries WHERE id = ?", (entry_id,))
    entry = entry_cur.fetchone()
    if not entry:
        return 0

    conn.execute(
        "INSERT INTO file_versions (entry_id, version_num, size) VALUES (?, 1, ?)",
        (entry_id, entry["size"]),
    )
    version_id = conn.execute(
        "SELECT id FROM file_versions WHERE entry_id = ? AND version_num = 1",
        (entry_id,),
    ).fetchone()[0]

    block_size = entry["block_size"] or BLOCK_SIZE_BYTES
    for b in blocks:
        conn.execute(
            "INSERT OR IGNORE INTO version_blocks (version_id, idx, block_id, offset, size) VALUES (?, ?, ?, ?, ?)",
            (version_id, b["idx"], b["block_id"], b["idx"] * block_size, b["size"]),
        )
    return 1


def get_current_file_version(conn: sqlite3.Connection, entry_id: int) -> int:
    """Returns current committed version number for a file entry, migrating legacy RF2 if needed."""
    cursor = conn.execute(
        "SELECT MAX(version_num) as max_v FROM file_versions WHERE entry_id = ?",
        (entry_id,),
    )
    row = cursor.fetchone()
    if row and row["max_v"] is not None:
        return row["max_v"]

    cur = conn.execute(
        "SELECT b.block_id FROM blocks b JOIN replicas r ON r.block_id = b.block_id WHERE b.entry_id = ? LIMIT 1",
        (entry_id,),
    )
    if cur.fetchone():
        return ensure_version_for_entry(conn, entry_id)
    return 0


def abort_upload(owner_id: int, path: str, db_path: str | None = None) -> None:
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



def get_download_plan(owner_id: int, path: str, db_path: str | None = None) -> dict[str, Any] | None:
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

        # Check if version_blocks exist for the latest version
        cursor = conn.execute(
            "SELECT vb.block_id, vb.idx, vb.size, vb.sha256 FROM version_blocks vb "
            "JOIN file_versions v ON v.id = vb.version_id "
            "WHERE v.entry_id = ? AND v.version_num = ("
            "  SELECT MAX(version_num) FROM file_versions WHERE entry_id = ?"
            ") ORDER BY vb.idx",
            (entry["id"], entry["id"]),
        )
        blocks = cursor.fetchall()

        if not blocks:
            cursor = conn.execute(
                "SELECT block_id, idx, size, NULL as sha256 FROM blocks WHERE entry_id = ? ORDER BY idx",
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

            block_info = {
                "index": b["idx"],
                "block_id": b["block_id"],
                "size": b["size"],
                "nodes": addresses,
            }
            if b["sha256"]:
                block_info["sha256"] = b["sha256"]
            plan_blocks.append(block_info)

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
    db_path: str | None = None,
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


def get_alive_nodes(db_path: str | None = None) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT node_id, address, free_bytes, total_bytes, last_seen, status "
            "FROM nodes WHERE status = 'alive' ORDER BY free_bytes DESC"
        )
        return [dict(row) for row in cursor.fetchall()]


def mark_dead_nodes(dead_timeout_s: float = DEAD_TIMEOUT_S, db_path: str | None = None) -> list[str]:
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
    db_path: str | None = None,
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
    db_path: str | None = None,
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

def create_snapshot_bytes(db_path: str | None = None) -> bytes:
    """Takes a consistent binary snapshot of the SQLite database."""
    with _LOCK:
        with get_connection(db_path) as conn:
            return conn.serialize()


def restore_from_snapshot_bytes(snapshot_bytes: bytes, db_path: str | None = None) -> None:
    """Restores SQLite database from binary snapshot bytes atomically."""
    with _LOCK:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # Write to temporary file then atomic replace
        temp_path = f"{db_path}.tmp"
        with open(temp_path, "wb") as f:
            f.write(snapshot_bytes)
        Path(temp_path).replace(db_path)
        LOGGER.info("Successfully restored metadata database from snapshot (%d bytes)", len(snapshot_bytes))


# ----------------------------------------------------------------------
# File Access & Versioning (RF3: open, close, read, write, lock)
# ----------------------------------------------------------------------

def open_file_session(
    owner_id: int,
    path: str,
    mode: str = "r",
    append: bool = False,
    lease_seconds: int = 60,
    db_path: str | None = None,
) -> dict[str, Any]:
    norm_path = normalize_path(path)
    if norm_path == "/":
        raise ValueError("Cannot open root directory as a file")
    if mode not in ("r", "w", "a"):
        raise ValueError(f"Invalid mode: {mode}")

    parent_path = get_parent_path(norm_path)
    now = int(time.time())
    lease_until = now + lease_seconds

    with _LOCK:
        with get_connection(db_path) as conn:
            # Check parent directory exists
            parent = conn.execute(
                "SELECT id, type, status FROM entries WHERE owner_id = ? AND path = ?",
                (owner_id, parent_path),
            ).fetchone()
            if not parent or parent["type"] != "dir":
                raise KeyError("parent directory not found")

            # Check entry
            cursor = conn.execute(
                "SELECT id, type, size, block_size, status FROM entries WHERE owner_id = ? AND path = ?",
                (owner_id, norm_path),
            )
            entry = cursor.fetchone()

            if not entry:
                if mode == "r":
                    raise KeyError("file not found")
                # Create empty file entry
                conn.execute(
                    "INSERT INTO entries (owner_id, path, type, size, block_size, status) "
                    "VALUES (?, ?, 'file', 0, ?, 'ready')",
                    (owner_id, norm_path, BLOCK_SIZE_BYTES),
                )
                entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                block_size = BLOCK_SIZE_BYTES
                base_version = 0
                file_size = 0
            else:
                if entry["type"] != "file":
                    raise ValueError("path is a directory")
                entry_id = entry["id"]
                block_size = entry["block_size"] or BLOCK_SIZE_BYTES
                base_version = get_current_file_version(conn, entry_id)
                v_cur = conn.execute(
                    "SELECT size FROM file_versions WHERE entry_id = ? AND version_num = ?",
                    (entry_id, base_version),
                )
                v_row = v_cur.fetchone()
                file_size = v_row["size"] if v_row else (entry["size"] if base_version > 0 else 0)

            session_id = str(uuid.uuid4())

            # Check locks
            if mode in ("w", "a"):
                lock_cur = conn.execute(
                    "SELECT session_id, owner_id, lease_until FROM file_locks WHERE entry_id = ?",
                    (entry_id,),
                )
                lock = lock_cur.fetchone()
                if lock and lock["lease_until"] > now:
                    raise FileExistsError("file is locked by another session")

                # Acquire exclusive lock
                conn.execute(
                    "INSERT OR REPLACE INTO file_locks (entry_id, session_id, owner_id, lease_until) "
                    "VALUES (?, ?, ?, ?)",
                    (entry_id, session_id, owner_id, lease_until),
                )

            # Record session
            conn.execute(
                "INSERT INTO file_sessions (session_id, entry_id, owner_id, mode, base_version, lease_until, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active')",
                (session_id, entry_id, owner_id, mode, base_version, lease_until),
            )
            conn.commit()

            return {
                "session_id": session_id,
                "path": norm_path,
                "mode": mode,
                "append": append,
                "base_version": base_version,
                "version": base_version,
                "size": file_size,
                "block_size": block_size,
                "lease_seconds": lease_seconds,
            }


def lock_file_session(
    owner_id: int,
    session_id: str,
    lease_seconds: int = 60,
    db_path: str | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    new_lease = now + lease_seconds

    with _LOCK:
        with get_connection(db_path) as conn:
            sess = conn.execute(
                "SELECT entry_id, status FROM file_sessions WHERE session_id = ? AND owner_id = ?",
                (session_id, owner_id),
            ).fetchone()
            if not sess or sess["status"] != "active":
                raise KeyError("active session not found")

            entry_id = sess["entry_id"]
            lock = conn.execute(
                "SELECT session_id, lease_until FROM file_locks WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            if lock and lock["session_id"] != session_id and lock["lease_until"] > now:
                raise FileExistsError("file is locked by another session")

            conn.execute(
                "INSERT OR REPLACE INTO file_locks (entry_id, session_id, owner_id, lease_until) "
                "VALUES (?, ?, ?, ?)",
                (entry_id, session_id, owner_id, new_lease),
            )
            conn.execute(
                "UPDATE file_sessions SET lease_until = ? WHERE session_id = ?",
                (new_lease, session_id),
            )
            conn.commit()
            return {"status": "locked", "session_id": session_id, "lease_seconds": lease_seconds}


def renew_file_lease(
    owner_id: int,
    session_id: str,
    lease_seconds: int = 60,
    db_path: str | None = None,
) -> dict[str, Any]:
    return lock_file_session(owner_id, session_id, lease_seconds, db_path)


def unlock_file_session(
    owner_id: int,
    session_id: str,
    db_path: str | None = None,
) -> None:
    with _LOCK:
        with get_connection(db_path) as conn:
            sess = conn.execute(
                "SELECT session_id FROM file_sessions WHERE session_id = ? AND owner_id = ?",
                (session_id, owner_id),
            ).fetchone()
            if not sess:
                raise KeyError("session not found")
            conn.execute(
                "DELETE FROM file_locks WHERE session_id = ?",
                (session_id,),
            )
            conn.commit()


def get_read_plan_rf3(
    owner_id: int,
    session_id: str,
    offset: int = 0,
    length: int | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    with get_connection(db_path) as conn:
        sess = conn.execute(
            "SELECT s.entry_id, s.base_version, s.lease_until, s.status, e.block_size, e.size "
            "FROM file_sessions s JOIN entries e ON e.id = s.entry_id "
            "WHERE s.session_id = ? AND s.owner_id = ?",
            (session_id, owner_id),
        ).fetchone()
        if not sess or sess["status"] != "active":
            raise KeyError("session not found or not active")
        if sess["lease_until"] < now:
            raise TimeoutError("session lease expired")

        entry_id = sess["entry_id"]
        base_version = sess["base_version"]
        block_size = sess["block_size"] or BLOCK_SIZE_BYTES

        if base_version == 0:
            return {"block_size": block_size, "version": 0, "size": 0, "blocks": []}

        v_row = conn.execute(
            "SELECT id, size FROM file_versions WHERE entry_id = ? AND version_num = ?",
            (entry_id, base_version),
        ).fetchone()
        if not v_row:
            return {"block_size": block_size, "version": base_version, "size": sess["size"], "blocks": []}

        version_id = v_row["id"]
        file_size = v_row["size"]

        range_end = (offset + length) if length is not None else file_size
        b_cur = conn.execute(
            "SELECT idx, block_id, offset, size, sha256 FROM version_blocks "
            "WHERE version_id = ? ORDER BY idx",
            (version_id,),
        )
        plan_blocks = []
        for b in b_cur.fetchall():
            b_offset = b["offset"]
            b_size = b["size"]
            b_end = b_offset + b_size
            if b_end <= offset or b_offset >= range_end:
                continue

            node_cur = conn.execute(
                "SELECT n.address FROM replicas r JOIN nodes n ON n.node_id = r.node_id "
                "WHERE r.block_id = ? AND n.status = 'alive' ORDER BY n.free_bytes DESC",
                (b["block_id"],),
            )
            addrs = [r["address"] for r in node_cur.fetchall()]
            if not addrs:
                node_cur = conn.execute(
                    "SELECT n.address FROM replicas r JOIN nodes n ON n.node_id = r.node_id "
                    "WHERE r.block_id = ?",
                    (b["block_id"],),
                )
                addrs = [r["address"] for r in node_cur.fetchall()]

            plan_blocks.append({
                "index": b["idx"],
                "block_id": b["block_id"],
                "offset": b["offset"],
                "size": b["size"],
                "nodes": addrs,
                "sha256": b["sha256"],
            })

        return {
            "block_size": block_size,
            "version": base_version,
            "size": file_size,
            "blocks": plan_blocks,
        }


def get_write_plan_rf3(
    owner_id: int,
    session_id: str,
    offset: int,
    length: int,
    append: bool = False,
    db_path: str | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    with _LOCK:
        with get_connection(db_path) as conn:
            sess = conn.execute(
                "SELECT s.entry_id, s.mode, s.base_version, s.lease_until, s.status, e.block_size "
                "FROM file_sessions s JOIN entries e ON e.id = s.entry_id "
                "WHERE s.session_id = ? AND s.owner_id = ?",
                (session_id, owner_id),
            ).fetchone()
            if not sess or sess["status"] != "active":
                raise KeyError("session not found or not active")
            if sess["mode"] not in ("w", "a"):
                raise PermissionError("session not opened in write mode")

            entry_id = sess["entry_id"]
            block_size = sess["block_size"] or BLOCK_SIZE_BYTES
            base_version = sess["base_version"]

            # Lock verification
            lock = conn.execute(
                "SELECT session_id, lease_until FROM file_locks WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            if not lock or lock["session_id"] != session_id or lock["lease_until"] < now:
                raise PermissionError("lock expired or not held by session")

            alive_nodes = get_alive_nodes(db_path)
            if len(alive_nodes) < REPLICATION_FACTOR:
                raise RuntimeError("not enough DataNodes alive")

            # Determine base size
            base_size = 0
            if base_version > 0:
                v_row = conn.execute(
                    "SELECT size FROM file_versions WHERE entry_id = ? AND version_num = ?",
                    (entry_id, base_version),
                ).fetchone()
                if v_row:
                    base_size = v_row["size"]

            effective_offset = base_size if append else max(0, offset)
            write_end = effective_offset + length

            if length == 0:
                affected_indices = [effective_offset // block_size]
            else:
                start_idx = effective_offset // block_size
                end_idx = max(start_idx, (write_end - 1) // block_size)
                affected_indices = list(range(start_idx, end_idx + 1))

            plan_blocks = []
            for i, idx in enumerate(affected_indices):
                b_offset = idx * block_size
                b_size = min(block_size, max(0, write_end - b_offset))
                new_block_id = str(uuid.uuid4())

                selected_nodes = list(alive_nodes[:REPLICATION_FACTOR])
                if i % 2 == 1 and len(selected_nodes) >= 2:
                    selected_nodes = list(reversed(selected_nodes))
                chain = [n["address"] for n in selected_nodes]

                # Record uncommitted block in blocks and session_blocks
                conn.execute(
                    "INSERT INTO blocks (block_id, entry_id, idx, size) VALUES (?, ?, ?, ?)",
                    (new_block_id, entry_id, idx, b_size),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO session_blocks (session_id, idx, block_id, size, offset, sha256) "
                    "VALUES (?, ?, ?, ?, ?, NULL)",
                    (session_id, idx, new_block_id, b_size, b_offset),
                )

                plan_blocks.append({
                    "index": idx,
                    "block_id": new_block_id,
                    "offset": b_offset,
                    "size": b_size,
                    "chain": chain,
                })

            conn.commit()
            return {
                "block_size": block_size,
                "base_version": base_version,
                "blocks": plan_blocks,
            }


def commit_file_session(
    owner_id: int,
    session_id: str,
    blocks: list[dict[str, Any]] | None = None,
    min_write_acks: int = 2,
    db_path: str | None = None,
) -> dict[str, Any]:
    now = int(time.time())
    with _LOCK:
        with get_connection(db_path) as conn:
            sess = conn.execute(
                "SELECT s.entry_id, s.mode, s.base_version, s.lease_until, s.status, e.block_size, e.path "
                "FROM file_sessions s JOIN entries e ON e.id = s.entry_id "
                "WHERE s.session_id = ? AND s.owner_id = ?",
                (session_id, owner_id),
            ).fetchone()
            if not sess or sess["status"] != "active":
                raise KeyError("session not found or not active")

            entry_id = sess["entry_id"]
            mode = sess["mode"]
            base_version = sess["base_version"]
            block_size = sess["block_size"] or BLOCK_SIZE_BYTES

            if mode == "r":
                conn.execute("UPDATE file_sessions SET status = 'committed' WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM file_locks WHERE session_id = ?", (session_id,))
                conn.commit()
                return {"status": "closed", "version": base_version}

            # For 'w' and 'a':
            # 1. Lock check
            lock = conn.execute(
                "SELECT session_id, lease_until FROM file_locks WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            if not lock or lock["session_id"] != session_id or lock["lease_until"] < now:
                raise PermissionError("lock expired or not held by session")

            # 2. CAS (Compare-And-Swap) Check
            current_version = get_current_file_version(conn, entry_id)
            if current_version != base_version:
                conn.execute("UPDATE file_sessions SET status = 'aborted' WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM file_locks WHERE session_id = ?", (session_id,))
                conn.commit()
                raise ValueError(
                    f"version conflict: expected base version {base_version}, but file is at version {current_version}"
                )

            # 3. Quorum check for newly committed blocks
            committed_blocks = blocks or []
            for b in committed_blocks:
                stored_on = b.get("stored_on", [])
                if len(stored_on) < min_write_acks:
                    raise ValueError(f"Block {b['block_id']} has fewer than {min_write_acks} confirmations")

                for addr in stored_on:
                    node = conn.execute("SELECT node_id FROM nodes WHERE address = ?", (addr,)).fetchone()
                    node_id = node["node_id"] if node else addr.split(":")[0]
                    if not node:
                        conn.execute(
                            "INSERT OR IGNORE INTO nodes (node_id, address, free_bytes, total_bytes, last_seen, status) "
                            "VALUES (?, ?, 0, 0, ?, 'alive')",
                            (node_id, addr, now),
                        )
                    conn.execute(
                        "INSERT OR REPLACE INTO replicas (block_id, node_id) VALUES (?, ?)",
                        (b["block_id"], node_id),
                    )

            # 4. Assemble new version blocks (Copy-On-Write)
            version_map: dict[int, dict[str, Any]] = {}
            if base_version > 0:
                v_cur = conn.execute(
                    "SELECT vb.idx, vb.block_id, vb.offset, vb.size, vb.sha256 FROM version_blocks vb "
                    "JOIN file_versions v ON v.id = vb.version_id "
                    "WHERE v.entry_id = ? AND v.version_num = ? ORDER BY vb.idx",
                    (entry_id, base_version),
                )
                for row in v_cur.fetchall():
                    version_map[row["idx"]] = dict(row)

            for b in committed_blocks:
                idx = b["index"]
                b_size = b.get("size")
                if b_size is None:
                    sb = conn.execute("SELECT size FROM blocks WHERE block_id = ?", (b["block_id"],)).fetchone()
                    b_size = sb["size"] if sb else 0
                version_map[idx] = {
                    "idx": idx,
                    "block_id": b["block_id"],
                    "offset": idx * block_size,
                    "size": b_size,
                    "sha256": b.get("sha256"),
                }

            new_version_num = current_version + 1
            sorted_blocks = [version_map[i] for i in sorted(version_map.keys())]
            total_size = sum(b["size"] for b in sorted_blocks)

            # Insert new version
            conn.execute(
                "INSERT INTO file_versions (entry_id, version_num, size) VALUES (?, ?, ?)",
                (entry_id, new_version_num, total_size),
            )
            new_v_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            for b in sorted_blocks:
                conn.execute(
                    "INSERT INTO version_blocks (version_id, idx, block_id, offset, size, sha256) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (new_v_id, b["idx"], b["block_id"], b["offset"], b["size"], b.get("sha256")),
                )

            # Update entry status and size
            conn.execute(
                "UPDATE entries SET size = ?, status = 'ready' WHERE id = ?",
                (total_size, entry_id),
            )

            # Release lock, mark session committed, clean session_blocks
            conn.execute("DELETE FROM file_locks WHERE session_id = ?", (session_id,))
            conn.execute("UPDATE file_sessions SET status = 'committed' WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM session_blocks WHERE session_id = ?", (session_id,))
            conn.commit()

            return {
                "status": "closed",
                "version": new_version_num,
                "size": total_size,
            }


def abort_file_session(
    owner_id: int,
    session_id: str,
    db_path: str | None = None,
) -> None:
    with _LOCK:
        with get_connection(db_path) as conn:
            sess = conn.execute(
                "SELECT entry_id FROM file_sessions WHERE session_id = ? AND owner_id = ?",
                (session_id, owner_id),
            ).fetchone()
            if sess:
                conn.execute("UPDATE file_sessions SET status = 'aborted' WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM file_locks WHERE session_id = ?", (session_id,))
                conn.execute(
                    "DELETE FROM blocks WHERE block_id IN ("
                    "  SELECT block_id FROM session_blocks WHERE session_id = ?"
                    ")",
                    (session_id,),
                )
                conn.execute("DELETE FROM session_blocks WHERE session_id = ?", (session_id,))
                conn.commit()


def clean_expired_locks_and_sessions(db_path: str | None = None) -> tuple[int, int]:
    now = int(time.time())
    with _LOCK:
        with get_connection(db_path) as conn:
            lock_cur = conn.execute("DELETE FROM file_locks WHERE lease_until <= ?", (now,))
            locks_deleted = lock_cur.rowcount

            sess_cur = conn.execute(
                "SELECT session_id FROM file_sessions WHERE status = 'active' AND lease_until <= ?",
                (now,),
            )
            expired_sessions = [row["session_id"] for row in sess_cur.fetchall()]
            for s_id in expired_sessions:
                conn.execute("UPDATE file_sessions SET status = 'expired' WHERE session_id = ?", (s_id,))
                conn.execute(
                    "DELETE FROM blocks WHERE block_id IN ("
                    "  SELECT block_id FROM session_blocks WHERE session_id = ?"
                    ")",
                    (s_id,),
                )
                conn.execute("DELETE FROM session_blocks WHERE session_id = ?", (s_id,))

            conn.commit()
            return locks_deleted, len(expired_sessions)

