# DFSha - decisiones de diseño

Arquitectura: **C/S (Opción 1)**, red privada. DFS **por bloques** estilo HDFS,
con **dos ControlNodes de metadatos (leader/follower)** y 3 DataNodes.

| # | Decisión | Por qué |
|---|---|---|
| 1 | Bloques de **8 MB** en producción y **64 KiB** en desarrollo, configurables mediante `BLOCK_SIZE_BYTES`; el tamaño usado se guarda por archivo | Permite pruebas con archivos pequeños sin cambiar el diseño de producción |
| 2 | **N = 2** réplicas por bloque, 3 DataNodes; **W = 2** (por confirmar) | Cada bloque en 2 de 3 nodos: se aguanta la caída de 1 DataNode |
| 3 | Archivos **WORM** (inmutables; se reemplazan completos) | Elimina conflictos de actualización parcial |
| 4 | Un archivo es visible (`ls`) solo cuando todos sus bloques tienen ≥ W confirmaciones | Visibilidad atómica |
| 5 | Cliente ↔ DataNode **directo** (el ControlNode solo da el plan) | El ControlNode no es cuello de botella |
| 6 | Replicación en **pipeline store-and-forward** (DN1 guarda, reenvía a DN2, espera su ack) | Más simple que streaming simultáneo |
| 7 | REST (FastAPI) solo Cliente ↔ ControlNode; **gRPC** para todo lo demás | Swagger para la demo; un solo `.proto` para los nodos |
| 8 | **Heartbeat** DataNode → ControlNode cada 5 s; muerto tras 15 s | Detección de fallas, registro de nodos y espacio libre |
| 9 | Comandos (borrar huérfanos, re-replicar) viajan en la **respuesta del heartbeat** | Sin canal ControlNode → DataNode |
| 10 | Distribución por **espacio libre** (reportado en el heartbeat) | Balanceo simple |
| 11 | Metadatos en **SQLite** (rutas por usuario, no árbol con `parent_id`) | Atómico, sin servidor, `ls` por prefijo |
| 12 | Auth: usuario/contraseña (bcrypt) + **JWT HS256**; los DataNodes validan el mismo JWT | Simple; sin tokens por bloque |
| 13 | Control de acceso: **dueño** (cada usuario tiene su raíz; toda consulta filtra por `owner_id`) | Cumple "cada cliente gestiona solo sus archivos" |
| 14 | Entre nodos: **API key compartida + TLS** | Mínimo viable; mejora futura: mTLS |
| 15 | En reposo: **AES-GCM por bloque** con llave maestra del DataNode y nonce aleatorio de 12 bytes guardado con el bloque | Cifrado transparente; GCM también detecta corrupción |
| 16 | Re-replicación: el DataNode descifra y reenvía; el destino cifra con su propia llave | Cada nodo tiene su llave; las réplicas no son idénticas byte a byte |
| 17 | Despliegue: **docker-compose** en 2-3 VMs | Requisito de infraestructura |
| 18 | Los ControlNodes operan en modo **activo/standby**: `leader` atiende REST, asigna planes y recibe heartbeats; `follower` mantiene una copia de metadatos y no acepta escrituras | Evita dos líderes simultáneos y permite failover controlado |
| 19 | La replicación de metadatos es **leader → follower**, incluyendo SQLite mediante snapshots consistentes; el follower se promueve manualmente cambiando su rol | Failover explícito, sin split-brain ni elección automática fuera del alcance |
| 20 | El cliente usa `DFSHA_CONTROL_URL` como endpoint del líder; tras promover el follower se actualiza ese endpoint y se reinician los clientes | Mantiene el contrato REST simple |

Limitaciones asumidas (mencionar en el informe): el failover del ControlNode es
manual y puede perder las operaciones posteriores al último snapshot; no hay
elección automática ni fencing entre ControlNodes, por lo que nunca deben estar
dos `leader` activos simultáneamente. Un usuario autenticado que conozca un
`block_id` podría pedirlo directamente al DataNode (los UUID son aleatorios y
solo se entregan al dueño). La llave maestra es compartida por todos los usuarios.

## Variables de entorno

| Variable | Valor por defecto | Quién la usa |
|---|---|---|
| `BLOCK_SIZE_BYTES` | `8388608` | ControlNode |
| `REPLICATION_FACTOR` | `2` | ControlNode |
| `MIN_WRITE_ACKS` | `2` | ControlNode |
| `HEARTBEAT_INTERVAL_S` | `5` | DataNode, ControlNode |
| `DEAD_TIMEOUT_S` | `15` | ControlNode |
| `CHUNK_SIZE_BYTES` | `524288` | Cliente, DataNode |
| `JWT_SECRET` | (secreto) | ControlNode, DataNode |
| `JWT_EXPIRE_MIN` | `60` | ControlNode |
| `CLUSTER_API_KEY` | (secreto) | ControlNode, DataNode |
| `CONTROLNODE_ID` | `control-leader` | Cada ControlNode |
| `CONTROLNODE_ROLE` | `leader` o `follower` | Cada ControlNode |
| `CONTROL_REST_PORT` / `CONTROL_GRPC_PORT` | `8000` / `50050` | Cada ControlNode |
| `DB_PATH` | `/data/meta.db` | Cada ControlNode |
| `CONTROL_PEER_GRPC_ADDR` | `control-follower:50050` | Leader, para replicar metadatos |
| `CONTROL_LEADER_URL` | `http://control-leader:8000` | Follower y clientes |
| `CONTROL_GRPC_ADDR` | `control-leader:50050` | DataNode |
| `DATANODE_ID` | `dn1` | DataNode |
| `DATANODE_ADDR` | `datanode1:50051` | DataNode (dirección que anuncia) |
| `DATANODE_PORT` | `50051` | DataNode |
| `DATANODE_DATA_DIR` | `/data` | DataNode |
| `DATANODE_MASTER_KEY` | (32 bytes en base64) | DataNode |
| `TLS_ENABLED` | `false` | Todos |
| `TLS_CERT`, `TLS_KEY`, `TLS_CA` | rutas | Todos |
| `DFSHA_CONTROL_URL` | `http://control-leader:8000` | Cliente |
