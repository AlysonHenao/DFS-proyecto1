# Estado del proyecto

Actualizado: 2026-10-12

## Implementación actual

La implementación funcional está integrada en `controlnode/`, `datanode/` y
`client/`. El despliegue local usa dos ControlNodes (`leader`/`follower`) y
tres DataNodes configurados mediante Docker Compose.

## Entrega Persona A - ControlNode

### Completado

- [x] Inicialización de SQLite a partir de `schema.sql`.
- [x] API FastAPI con `/health` y control explícito del rol `leader` o
      `follower`.
- [x] Registro y login de usuarios con bcrypt y tokens JWT.
- [x] Operaciones de filesystem: `ls`, `mkdir`, `rmdir` y `rm`.
- [x] Flujo RF2: `put/plan`, `put/commit`, `put/abort` y `get/plan`.
- [x] Selección de DataNodes vivos por espacio disponible y generación de
      cadenas de replicación para los bloques.
- [x] Heartbeat gRPC de DataNodes con actualización de capacidad y estado.
- [x] Comandos `DELETE` para bloques huérfanos y `REPLICATE` para bloques
      sub-replicados.
- [x] Marcado de nodos como `dead` después de `DEAD_TIMEOUT_S`.
- [x] Re-replicación coordinada por el monitor del cluster.
- [x] Snapshots periódicos de SQLite del leader al follower mediante
      `ReplicateMetadata`.
- [x] Failover manual documentado en [FAILOVER.md](./FAILOVER.md).
- [x] El follower rechaza operaciones REST mientras conserva ese rol y no
      devuelve comandos de mantenimiento a los DataNodes.

### Validación

- [x] Tests de autenticación, usuarios, directorios, upload/download, quorum
      de escritura, detección de nodos caídos y backup/restore de snapshots en
      `tests/test_controlnode.py`.
- [x] Flujo de re-replicación validado mediante el ControlNode real y el
      comando `REPLICATE` ejecutado por un DataNode.

## Entrega Persona B - DataNode y cliente

### Completado

- [x] DataNode gRPC con `WriteBlock` y `ReadBlock`.
- [x] Escritura por chunks, almacenamiento local y reenvío por cadena de
      replicación.
- [x] Separación interna de RPC, almacenamiento, chunks y replicación.
- [x] Heartbeat a todas las direcciones configuradas en
      `CONTROL_GRPC_ADDRS`, con tolerancia a que un ControlNode no responda.
- [x] Comandos `DELETE` idempotentes mediante papelera y limpieza posterior.
- [x] Ejecución de `REPLICATE` desde comandos recibidos por heartbeat, usando
      API key cuando está configurada.
- [x] Cliente CLI con `login`, `ls`, `mkdir`, `put`, `get`, `rm` y `rmdir`.
- [x] Refactor interno del cliente en autenticación, REST, gRPC,
      transferencia y CLI.
- [x] Cifrado AES-GCM por bloque con clave de 32 bytes, nonce aleatorio de
      12 bytes y formato en disco `[nonce][ciphertext+tag]`.
- [x] Descifrado transparente en `read_block` y `read_block_chunks`; la
      replicación continúa enviando datos planos y cada DataNode cifra al
      guardar.
- [x] Fallback de lectura: el cliente intenta las réplicas restantes cuando
      falla un DataNode o falla el descifrado.
- [x] Scripts de smoke test para Windows y Linux con RF1/RF2 y comparación de
      SHA-256.
- [x] Tests de almacenamiento, cifrado, papelera, eliminación idempotente,
      resolución de múltiples direcciones de ControlNode y fallback entre
      réplicas.

## Seguridad y resiliencia

- [x] TLS opcional para los servidores y canales gRPC de heartbeats,
      replicación, cliente-DataNode y snapshots leader-follower.
- [x] HTTPS opcional para la API REST del ControlNode, incluyendo configuración
      de Uvicorn con certificado y clave.
- [x] Verificación de certificados desde el cliente mediante la CA configurada.
- [x] Script `scripts/gen_certs.sh` para generar una CA local y un certificado
      de servidor con SAN para los servicios Docker y `localhost`.
- [x] Certificados locales excluidos de Git mediante `certs/` en `.gitignore`.
- [x] TLS de servidor más API key para RPC internos; mTLS queda fuera de este
      alcance.
- [x] Demo manual de caída, fallback y re-replicación documentada en
      [docs/demo.md](./docs/demo.md).

### Verificaciones realizadas

- [x] Configuración de Docker Compose validada.
- [x] Certificado de servidor validado contra la CA local con `openssl verify`.
- [x] Handshake TLS validado desde el contenedor del cliente.
- [x] Login HTTPS validado contra el ControlNode.
- [x] Flujo manual de almacenamiento cifrado y recuperación desde una réplica
      validado.
- [ ] Repetir la suite local completa con un intérprete que tenga instaladas
      todas las dependencias; el Python global usado en una ejecución reciente
      no tenía instalado `cryptography`.
- [ ] Completar y registrar la ejecución final de los smoke tests con
      `TLS_ENABLED=false` y `TLS_ENABLED=true`.
- [ ] Registrar la prueba final con archivo de varios bloques de 8 MiB y
      comparación de SHA-256.

## Fase 3: cierre

- [ ] Informe final.
- [ ] Video de demostración.
- [ ] Benchmark mínimo comparando tamaños de bloque.
- [ ] **RF3 (`open`, `close`, `read`, `write`, `lock`) permanece pendiente, por confirmar con el profesor **

## Fuera de alcance

- [ ] El failover entre ControlNodes es manual; no hay elección automática ni
      tolerancia a split-brain.
- [ ] La replicación de metadatos usa el RPC `ReplicateMetadata` con un
      snapshot completo de SQLite; el cambio a
      `PushSnapshot(stream SnapshotChunk)` queda fuera de esta entrega.
- [ ] mTLS no está implementado; la configuración actual usa autenticación del
      servidor mediante TLS y API key para los RPC internos.

## Notas y configuración

- El mock de `mock/controlnode/` se conserva como referencia, pero la
  integración actual del proyecto usa el ControlNode real de `controlnode/`.
- La configuración de desarrollo usa bloques de 64 KiB; producción mantiene
  bloques de 8 MiB.
- `DATANODE_MASTER_KEY` debe ser una clave Base64 que decodifique exactamente a
  32 bytes.
