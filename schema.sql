-- DFSha - esquema SQLite del ControlNode (H0).
-- Se ejecuta al arrancar si la BD no existe. Cambios solo por PR revisado por ambos.
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- Usuarios (login con usuario/contrasena, hash bcrypt).
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Archivos y directorios. Cada usuario tiene su propio espacio de nombres:
-- las rutas son absolutas dentro de SU raiz (ej. /docs/informe.pdf).
-- El control de acceso por dueno se cumple por construccion: toda consulta
-- filtra por owner_id.
CREATE TABLE IF NOT EXISTS entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    path       TEXT NOT NULL,              -- normalizada, sin "/" final, raiz = "/"
    type       TEXT NOT NULL CHECK (type IN ('file', 'dir')),
    size       INTEGER NOT NULL DEFAULT 0, -- bytes (solo archivos)
    block_size INTEGER,                    -- tamano de bloque usado al subir (solo archivos)
    status     TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('uploading', 'ready')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (owner_id, path)
);
-- ls = consulta por prefijo de ruta: path LIKE '/docs/%' (excluyendo subniveles).

-- DataNodes (se registran solos con el primer heartbeat del ControlNode leader).
CREATE TABLE IF NOT EXISTS nodes (
    node_id     TEXT PRIMARY KEY,
    address     TEXT NOT NULL UNIQUE,      -- host:port anunciado
    free_bytes  INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    last_seen   INTEGER NOT NULL,          -- epoch en segundos
    status      TEXT NOT NULL DEFAULT 'alive' CHECK (status IN ('alive', 'dead'))
);

-- Bloques de un archivo. block_id es un UUID generado por el ControlNode en el plan.
-- El plan inserta los bloques con la entrada en estado 'uploading'; asi un bloque
-- recien escrito nunca se confunde con un huerfano.
CREATE TABLE IF NOT EXISTS blocks (
    block_id TEXT PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    idx      INTEGER NOT NULL,             -- posicion del bloque en el archivo (0..n-1)
    size     INTEGER NOT NULL              -- bytes (el ultimo puede ser menor al block_size)
);

-- Donde esta cada bloque. Se llena en put/commit (nodos que confirmaron).
CREATE TABLE IF NOT EXISTS replicas (
    block_id TEXT NOT NULL REFERENCES blocks(block_id) ON DELETE CASCADE,
    node_id  TEXT NOT NULL REFERENCES nodes(node_id)  ON DELETE CASCADE,
    PRIMARY KEY (block_id, node_id)
);

-- Versiones de archivo para RF3 (Copy-On-Write)
CREATE TABLE IF NOT EXISTS file_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    version_num INTEGER NOT NULL,
    size        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (entry_id, version_num)
);

CREATE TABLE IF NOT EXISTS version_blocks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
    idx        INTEGER NOT NULL,
    block_id   TEXT NOT NULL REFERENCES blocks(block_id) ON DELETE CASCADE,
    offset     INTEGER NOT NULL DEFAULT 0,
    size       INTEGER NOT NULL,
    sha256     TEXT,
    UNIQUE (version_id, idx)
);

-- Locks exclusivos con lease (TTL)
CREATE TABLE IF NOT EXISTS file_locks (
    entry_id    INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    session_id  TEXT NOT NULL UNIQUE,
    owner_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lease_until INTEGER NOT NULL, -- epoch seconds
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Sesiones activas de archivos para RF3 (open, read, write, lock)
CREATE TABLE IF NOT EXISTS file_sessions (
    session_id   TEXT PRIMARY KEY,
    entry_id     INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    owner_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mode         TEXT NOT NULL CHECK (mode IN ('r', 'w', 'a')),
    base_version INTEGER NOT NULL,
    lease_until  INTEGER NOT NULL, -- epoch seconds
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'committed', 'aborted', 'expired')),
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Bloques en preparacion para sesiones de escritura no confirmadas
CREATE TABLE IF NOT EXISTS session_blocks (
    session_id TEXT NOT NULL REFERENCES file_sessions(session_id) ON DELETE CASCADE,
    idx        INTEGER NOT NULL,
    block_id   TEXT NOT NULL REFERENCES blocks(block_id) ON DELETE CASCADE,
    size       INTEGER NOT NULL,
    offset     INTEGER NOT NULL,
    sha256     TEXT,
    PRIMARY KEY (session_id, idx)
);

CREATE INDEX IF NOT EXISTS idx_entries_owner_path  ON entries(owner_id, path);
CREATE INDEX IF NOT EXISTS idx_blocks_entry        ON blocks(entry_id);
CREATE INDEX IF NOT EXISTS idx_replicas_node       ON replicas(node_id);
CREATE INDEX IF NOT EXISTS idx_file_versions_entry ON file_versions(entry_id);
CREATE INDEX IF NOT EXISTS idx_version_blocks_ver  ON version_blocks(version_id);
CREATE INDEX IF NOT EXISTS idx_file_sessions_owner ON file_sessions(owner_id);

-- ---------------------------------------------------------------------------
-- Consultas clave (referencia para quien implemente el ControlNode)
--
-- Nodos para un plan de escritura (los REPLICATION_FACTOR vivos con mas espacio):
--   SELECT node_id, address FROM nodes WHERE status='alive'
--   ORDER BY free_bytes DESC LIMIT :n;
--
-- Marcar nodos caidos (bucle cada HEARTBEAT_INTERVAL_S):
--   UPDATE nodes SET status='dead' WHERE status='alive' AND last_seen < :now - :dead_timeout;
--
-- Bloques sub-replicados (menos de N replicas en nodos vivos) -> comando REPLICATE:
--   SELECT b.block_id FROM blocks b JOIN entries e ON e.id=b.entry_id
--   LEFT JOIN replicas r ON r.block_id=b.block_id
--   LEFT JOIN nodes n ON n.node_id=r.node_id AND n.status='alive'
--   WHERE e.status='ready' GROUP BY b.block_id HAVING COUNT(n.node_id) < :n;
--
-- Huerfanos: block_id reportado en un heartbeat que NO existe en `blocks` -> comando DELETE.
--
-- Subidas abandonadas: entries con status='uploading' mas viejas que X minutos
--   se borran (el CASCADE elimina sus bloques y los DataNodes los limpian como huerfanos).
--
-- Los dos ControlNodes tienen la misma estructura local. El leader es el unico
-- que ejecuta estas escrituras; el follower recibe snapshots consistentes y no
-- debe atender cambios mientras conserve el rol follower.
-- ---------------------------------------------------------------------------
