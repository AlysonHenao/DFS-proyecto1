# API REST del ControlNode líder (Cliente ↔ ControlNode)

Base: `http(s)://<control-leader>:8000` (FastAPI; Swagger en `/docs`).
El sistema tiene dos ControlNodes: `leader` y `follower`. Solo el `leader`
atiende operaciones REST, genera planes y modifica metadatos. El `follower`
mantiene una copia de la base de datos en modo standby y rechaza operaciones
de escritura. El failover es manual: se detiene el `leader`, se promueve el
`follower` y se actualiza `DFSHA_CONTROL_URL` al endpoint promovido.
Auth: `Authorization: Bearer <JWT>` en todo salvo `/auth/*` y `/health`.
JWT: HS256, claims `sub` (username) y `exp`. El mismo JWT lo validan los DataNodes.
Rutas: absolutas dentro de la raíz del usuario (`/`, `/docs`, `/docs/a.pdf`). `cd` es solo del cliente (guarda el directorio actual en `~/.dfsha`).

Errores (JSON `{"detail": "..."}`): `401` sin/invalid token · `404` no existe · `409` ya existe / no vacío · `422` datos inválidos · `503` no hay suficientes DataNodes vivos.

## Autenticación

| Método | Ruta | Body | Respuesta |
|---|---|---|---|
| POST | `/auth/register` | `{"username","password"}` | `201 {"username"}` |
| POST | `/auth/login` | `{"username","password"}` | `{"access_token","token_type":"bearer","expires_in"}` |
| GET | `/health` | - | `{"status":"ok"}` |

## Sistema de archivos (RF1)

| Método | Ruta | Descripción | Respuesta |
|---|---|---|---|
| GET | `/fs/ls?path=/` | Lista un directorio | `{"path","entries":[{"name","type","size","created_at"}]}` |
| POST | `/fs/mkdir` | Body `{"path"}`. El padre debe existir | `201` · `404` padre · `409` existe |
| DELETE | `/fs/rmdir?path=` | Solo si está vacío | `204` · `409` no vacío |
| DELETE | `/fs/file?path=` | `rm`: borra metadatos; los DataNodes borran los bloques huérfanos vía heartbeat | `204` |

## Transferencia (RF2)

Archivos WORM: no se actualizan; para reemplazar, `rm` y luego `put`.

### Subir

1. `POST /files/put/plan` · body `{"path","size"}`
   - Crea la entrada en estado `uploading` y sus bloques (UUID por bloque).
   - Respuesta:
     ```json
     {
       "block_size": 8388608,
       "blocks": [
         {"index": 0, "block_id": "uuid", "size": 8388608,
          "chain": ["dn1:50051", "dn3:50051"]},
         {"index": 1, "block_id": "uuid", "size": 1048576,
          "chain": ["dn2:50051", "dn1:50051"]}
       ]
     }
     ```
   - `chain[0]` es el nodo al que el cliente envía; el resto es la cadena del pipeline. Nodos elegidos: los `REPLICATION_FACTOR` vivos con más espacio libre. `409` si la ruta existe, `503` si hay menos nodos vivos que `REPLICATION_FACTOR`.
2. El cliente envía cada bloque por gRPC (`WriteBlock`) a `chain[0]` y guarda el `stored_on` de la respuesta.
3. `POST /files/put/commit` · body:
   ```json
   {"path": "/docs/a.pdf",
    "blocks": [{"index": 0, "block_id": "uuid", "stored_on": ["dn1:50051", "dn3:50051"]}]}
   ```
   - Exige que **todos** los bloques tengan al menos `MIN_WRITE_ACKS` (W) confirmaciones; si no, `422`.
   - Inserta las réplicas y pasa la entrada a `ready` (recién ahí aparece en `ls`).
4. `POST /files/put/abort` · body `{"path"}`: borra la entrada `uploading` si el cliente falla.

### Bajar

`GET /files/get/plan?path=/docs/a.pdf` →
```json
{"size": 9437184, "block_size": 8388608,
 "blocks": [{"index": 0, "block_id": "uuid", "size": 8388608,
             "nodes": ["dn1:50051", "dn3:50051"]}]}
```
`nodes` = réplicas vivas del bloque. El cliente prueba en orden; si una falla, usa la siguiente. Reensambla por `index`.

## Cómo se ve el flujo

```
put:  CLI → ControlNode leader (login) → put/plan → [CLI → DN1 → DN2] por bloque → put/commit
get:  CLI → ControlNode leader (login) → get/plan → [CLI ← DNx] por bloque → reensamblar
replicacion: ControlNode leader → ControlNode follower (snapshot de metadatos)
failover: detener leader → promover follower → actualizar DFSHA_CONTROL_URL
```

## gRPC (resumen; ver `proto/dfsha.proto`)

| Canal | Servicio / RPC | Auth |
|---|---|---|
| Cliente → DataNode | `DataNode.WriteBlock`, `DataNode.ReadBlock` | `authorization: Bearer <JWT>` |
| DataNode → DataNode | `DataNode.WriteBlock` (cadena y re-replicación) | `x-api-key` |
| DataNode → ControlNode | `ControlNodeInternal.Heartbeat` (devuelve comandos DELETE/REPLICATE) | `x-api-key` |
