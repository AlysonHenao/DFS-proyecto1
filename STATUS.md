# Estado del proyecto

Actualizar al terminar cada sesión de trabajo (2 minutos).

## Hecho
- [x] H0: contratos (`proto/dfsha.proto`, `controlnode/schema.sql`, `docs/api.md`, `docs/decisions.md`, compose y `.env.example`)
- [x] Arquitectura de dos ControlNodes: `control-leader` activo y `control-follower` standby, con replicación de metadatos y failover manual

## Fase 1: núcleo (put/get con N=2 en 3 DataNodes)
**Persona A (ControlNode)**
- [ ] Arranque: crear BD con `schema.sql`, FastAPI + servidor gRPC `Heartbeat`
- [ ] `register` / `login` (bcrypt + JWT)
- [ ] `ls`, `mkdir`, `rmdir`, `rm`
- [ ] `put/plan`, `put/commit`, `put/abort`, `get/plan`
- [ ] Heartbeat: upsert de nodos, espacio libre, comandos DELETE para huérfanos
- [ ] Marcar nodos `dead` tras `DEAD_TIMEOUT_S`

**Persona B (DataNode + Cliente)**
- [ ] DataNode: `WriteBlock` (guardar + reenviar a la cadena) y `ReadBlock`
- [ ] AES-GCM por bloque (nonce de 12 bytes guardado junto al bloque)
- [ ] DataNode: heartbeat cada `HEARTBEAT_INTERVAL_S`
- [ ] CLI: `login`, `put` (partir en bloques), `get` (reensamblar), `ls`, `mkdir`, `cd`, `rm`, `rmdir`
- [ ] `scripts/smoke_test.sh`: put → get → comparar sha256

## Fase 2: resiliencia y red segura
- [ ] A: re-replicación (comando REPLICATE) · snapshots consistentes periódicos del SQLite del leader al ControlNode follower
- [ ] B: `ReplicateBlock` desde el heartbeat · lectura con fallback a otra réplica · TLS + API key
- [ ] Juntos: demo de matar un DataNode

## Fase 3: cierre
- [ ] Informe · video · benchmark mínimo de tamaño de bloque

## Bloqueos / notas
- (ninguno)
