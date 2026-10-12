# Estado del proyecto

Actualizar al terminar cada sesión de trabajo.

## Entrega Persona B - 2026-10-10

Se completó una implementación funcional de RF1/RF2 contra un mock temporal
del ControlNode. El flujo validado es:

```text
login → mkdir → ls → put → get → SHA-256 → rm → rmdir
```

La prueba pasó con Docker Compose usando dos DataNodes y bloques de 64 KiB.
El valor de 64 KiB es solo para desarrollo; producción mantiene 8 MiB.

## Hecho
- [x] H0: contratos (`proto/dfsha.proto`, `controlnode/schema.sql`, `docs/api.md`, `docs/decisions.md`, compose y `.env.example`)
- [x] Arquitectura de dos ControlNodes: `control-leader` activo y `control-follower` standby, con replicación de metadatos y failover manual

## Fase 1: núcleo (put/get con N=2 en 3 DataNodes)
**Persona A (ControlNode)**
- [x] Arranque: crear BD con `schema.sql`, FastAPI + servidor gRPC `Heartbeat`
- [x] `register` / `login` (bcrypt + JWT)
- [x] `ls`, `mkdir`, `rmdir`, `rm`
- [x] `put/plan`, `put/commit`, `put/abort`, `get/plan`
- [x] Heartbeat: upsert de nodos, espacio libre, comandos DELETE para huérfanos
- [x] Marcar nodos `dead` tras `DEAD_TIMEOUT_S`

**Persona B (DataNode + Cliente)**
- [x] DataNode: `WriteBlock` (guardar + reenviar a la cadena) y `ReadBlock`
- [x] Refactor interno del DataNode: RPC, almacenamiento, chunks y replicación separados
- [ ] AES-GCM por bloque (nonce de 12 bytes guardado junto al bloque)
- [x] DataNode: heartbeat a todas las direcciones de `CONTROL_GRPC_ADDRS`, con tolerancia a fallos
- [x] DataNode: comandos DELETE idempotentes con papelera y REPLICATE con API key
- [x] CLI: `login`, `put` (partir en bloques), `get` (reensamblar), `ls`, `mkdir`, `rm`, `rmdir`
- [x] Refactor interno del cliente: autenticación, REST, gRPC, transferencia y CLI separados
- [x] `scripts/smoke_test.ps1`: RF1 + RF2 + comparar SHA-256
- [x] `scripts/smoke_test.sh`: equivalente Linux para VMs
- [x] CLI RF1 básico contra el mock: `ls`, `mkdir`, `rm`, `rmdir`

## Fase 2: resiliencia y red segura
- [x] A: re-replicación (comando REPLICATE) · snapshots consistentes periódicos del SQLite del leader al ControlNode follower · Runbook de 5 pasos para failover (`FAILOVER.md`)
- [ ] B: `ReplicateBlock` desde el heartbeat · lectura con fallback a otra réplica · TLS + API key
- [ ] Juntos: demo de matar un DataNode
- [ ] Juntos: demo de matar un DataNode

## Fase 3: cierre
- [ ] Informe · video · benchmark mínimo de tamaño de bloque

## Bloqueos / notas
- El `mock/controlnode/` actual es un mock en memoria para integración. Persona A
  debe reemplazar su persistencia y autenticación por SQLite, bcrypt y JWT,
  conservando el contrato REST descrito en `api.md`.
- El mock no implementa todavía heartbeat, replicación de metadatos entre
  ControlNodes ni selección dinámica de DataNodes.
- RF3 (`open`, `close`, `read`, `write`, `lock`) permanece fuera de alcance.

## Integración para Persona A

### Para Persona A

No se implementó la lógica real del ControlNode. Quedan a cargo de Persona A:

- servidor gRPC real de heartbeat y persistencia de nodos;
- `/health` con el rol actual;
- fencing mediante `CONTROL_PEER_URL`;
- recepción y envío de snapshots SQLite;
- garantizar que solo el leader devuelva comandos en la respuesta del heartbeat.

Persona A debe revisar especialmente:

- `client/control_client.py`: contrato REST consumido por el cliente.
- `mock/controlnode/models/`: cuerpos Pydantic reutilizables para los endpoints.
- `api.md`: rutas, cuerpos y códigos HTTP esperados.
- `dfsha.proto`: contrato gRPC de DataNode y ControlNode interno.

El proto compartido todavía conserva `ReplicateMetadata`; el cambio a
`PushSnapshot(stream SnapshotChunk)` queda pendiente de una rama/revisión de
Persona A y no se mezcla con esta entrega.

El cliente espera que `put/plan` devuelva `block_size`, `blocks`, `index`,
`block_id`, `size` y `chain`; que `put/commit` acepte `path` y `blocks`; y que
`get/plan` devuelva `size`, `block_size`, `blocks` y `nodes`.
