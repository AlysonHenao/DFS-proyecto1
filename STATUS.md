# Estado del proyecto

Actualizado: 2026-10-14

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
- [x] Cliente RF3 preparado contra el contrato REST esperado: métodos para
      `open`, `close`, `lock`, `unlock`, renovación de lease y planes de
      lectura/escritura en `client/control_client.py`.
- [x] Lectura de rangos en `client/transfer.py`, incluyendo rangos que cruzan
      bloques, verificación SHA-256 y fallback ante fallo de RPC o integridad.
- [x] Escritura de bloques nuevos por cadena de replicación en
      `client/transfer.py`, conservando `stored_on` y el hash calculado para
      el commit.
- [x] Comandos CLI iniciales de RF3: `open`, `close`, `read`, `lock` y
      `unlock`.
- [x] Pruebas unitarias independientes del ControlNode RF3 en
      `tests/test_rf3_client.py`; la suite completa local pasó con 20 tests.
- [x] Procedimiento y contrato esperado documentados en
      `docs/rf3-client-validation.md`.
- [x] Cliente autenticado con credenciales configurables mediante
      `DFSHA_USERNAME` y `DFSHA_PASSWORD`; si no se proporcionan, solicita el
      usuario y la contraseña de forma interactiva sin mostrar esta última.
      Se eliminó el uso obligatorio de `demo/demo`.
- [x] Flujo Docker validado con un usuario nuevo: registro, login y `ls`
      autenticado; una contraseña incorrecta devuelve `401`.
- [x] CLI con comandos explícitos `register [USERNAME]` y `login [USERNAME]`;
      el JWT se persiste sin guardar la contraseña.
- [x] Flujo Docker validado con `client register`, `client login` y una
      operación posterior reutilizando el JWT persistido en `/work`.
- [x] Flujo recomendado documentado: registrar un usuario con
      `docker compose run --rm client register <USUARIO>`, iniciar sesión con
      `docker compose run --rm client login <USUARIO>` y ejecutar después los
      comandos protegidos sin repetir usuario ni contraseña.
- [x] Confirmado que el sufijo basado en fecha, por ejemplo
      `clustercheck$(Get-Date -Format 'HHmmss')`, es opcional y solo sirve para
      evitar conflictos al repetir pruebas; no forma parte de la autenticación.

## RF3: Acceso a archivos (`open`, `close`, `read`, `write`, `lock`)

Respuesta del profesor (2026-10-13): `write()` debe considerarse, pero no
tiene que permitir cualquier modificación. El grupo define y justifica la
semántica de escritura, y debe poder explicar qué ocurre con (1) dos clientes
escribiendo a la vez, (2) varias réplicas de un archivo y (3) la caída de un
nodo durante una escritura. No basta con implementar las operaciones.

### Semántica propuesta (por confirmar en el equipo antes de implementar)

La idea es reutilizar lo que ya existe (bloques inmutables, `put/plan`,
`put/commit`, `put/abort`, quorum, `DELETE` de huérfanos) y agregar solo
versionamiento y locks.

- **Archivos versionados con copy-on-write por bloque.** Un bloque nunca se
  modifica en sitio; escribir sobre un bloque crea un bloque nuevo. Cada
  `close` exitoso genera una nueva versión del archivo. Los bloques no
  tocados se comparten entre versiones.
- **Lectura consistente.** `open` en modo lectura fija la versión vigente;
  `read(offset, length)` se resuelve a los bloques de esa versión, sin ver
  escrituras a medias.
- **Escritura.** `open` en modo escritura exige lock exclusivo y registra la
  versión base. `write(offset, data)` reescribe solo los bloques afectados
  (read-modify-write para bloques parciales, con AES-GCM por bloque nuevo).
  El modo adición (`append`) es un caso particular.
- **Commit atómico.** `close` confirma la nueva versión con
  compare-and-swap sobre la versión base: si otra escritura la cambió,
  el commit se rechaza con conflicto y se aborta la sesión.
- **Lock exclusivo con lease.** `lock`/`unlock`/renovación con TTL; el
  monitor del ControlNode expira los locks de clientes caídos.
- **Integridad.** SHA-256 por bloque y por versión registrado en metadatos,
  verificado por el cliente al leer (el tag de AES-GCM ya autentica en disco).
- **Plan B si el tiempo no alcanza.** Reducir a reemplazo completo versionado
  + `append`, manteniendo lock, versiones y CAS (justificar en el informe).

### Respuestas a los tres escenarios del profesor (a validar con pruebas)

- **Dos clientes escriben a la vez:** el segundo no obtiene el lock exclusivo;
  si escribe sin lock (o con lease vencido), el commit falla por conflicto de
  versión. No hay pérdida silenciosa de datos.
- **Varias réplicas:** el commit solo ocurre cuando los bloques nuevos
  alcanzaron el quorum de escritura; la versión anterior sigue íntegra hasta
  entonces. La re-replicación existente completa las réplicas faltantes.
- **Nodo cae durante la escritura:** la escritura sigue si se cumple el quorum
  o se aborta; los bloques de sesiones abortadas quedan huérfanos y se
  eliminan con `DELETE`. Si cae el cliente, el lease expira y ocurre lo mismo.
  Si cae el leader, la promoción manual restaura locks y versiones desde el
  último snapshot; las sesiones abiertas se invalidan (limitación documentada).

### Persona A - ControlNode

- [ ] Esquema SQLite: versiones de archivo (lista ordenada de bloques por
      versión, SHA-256), locks con dueño/TTL y sesiones de escritura abiertas.
- [ ] Endpoints REST: `open`, `close`, `lock`, `unlock`, renovación de lease
      y consulta de versión.
- [ ] Plan de lectura por rango (`get/plan` con offset/length) y plan de
      escritura que reutilice solo los bloques afectados.
- [ ] Commit con compare-and-swap sobre la versión base y validación de que
      se cumple el quorum de los bloques nuevos.
- [ ] Expiración de locks/leases y aborto de sesiones desde el monitor del
      cluster; envío de `DELETE` de bloques huérfanos de sesiones abortadas.
- [ ] Incluir locks y versiones en el snapshot leader→follower y documentar
      el efecto en [FAILOVER.md](./FAILOVER.md).
- [ ] Tests: lock exclusivo, conflicto de versión, expiración de lease,
      commit sin quorum, aborto con limpieza de huérfanos.

### Persona B - DataNode y cliente

`[~]` indica trabajo parcial: la lógica cliente está preparada, pero la
integración no puede cerrarse hasta que la Persona A entregue el ControlNode
RF3.

- [~] Métodos cliente para `open`/`close`, `lock`, `unlock`, renovación de
      lease y planes de lectura/escritura preparados en
      `client/control_client.py`; quedan bloqueados para integración hasta que
      la Persona A implemente y confirme las rutas RF3.
- [~] CLI con `open`, `close`, `read`, `lock` y `unlock` implementados.
      `write`, `append` y la renovación automática del lease todavía requieren
      cerrar el contrato de sesión y de bloques nuevos con la Persona A.
- [~] Lectura por rango, verificación SHA-256 por bloque y fallback entre
      réplicas implementados en `client/transfer.py`. El
      read-modify-write completo depende de que el plan de escritura de A
      indique los bloques afectados y la versión base.
- [x] Escritura de un bloque nuevo por la cadena de replicación preparada en
      `client/transfer.py`, con `stored_on` y hash para el commit.
- [ ] Manejo final de conflicto, lock denegado, lease vencido y quorum con
      mensajes específicos; se implementará después de confirmar los códigos
      y cuerpos de error RF3.
- [x] Tests unitarios de lectura por rango, límites, integridad, fallback y
      contrato REST simulado en `tests/test_rf3_client.py`.
- [ ] Tests integrados de escritura parcial, append y caída de DataNode a
      mitad de escritura; requieren el ControlNode RF3 de la Persona A.
- [ ] Extender los smoke tests con un escenario RF3 (`TLS_ENABLED=false` y
      `true`). El procedimiento diferido está documentado en
      `docs/rf3-client-validation.md`.

### Ambas personas

- [ ] Prueba de concurrencia: dos clientes escribiendo el mismo archivo
      (con lock y sin lock) y registro del resultado.
- [ ] Prueba de falla: caer un DataNode y luego un cliente durante `write`;
      verificar que no queda una versión corrupta ni bloques huérfanos.
- [ ] Documentar la semántica elegida y su justificación (alimenta el informe).

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

### Despliegue

- [ ] Desplegar en 2 o 3 VMs (AWS Academy o GCP académico) con Docker
      Compose: ControlNodes leader/follower y 3 DataNodes distribuidos.
      Responsables: ambas personas (A: ControlNodes; B: DataNodes y cliente).
- [ ] Configurar red/puertos expuestos, TLS con certificados con SAN de las
      IPs o nombres reales, `DATANODE_MASTER_KEY` y API key (fuera de Git).
- [ ] Repetir en las VMs los smoke tests (RF1, RF2 y RF3) y registrar el
      resultado.
- [ ] README del repositorio reproducible: requisitos, pasos de despliegue
      local y en VMs, variables de entorno y comandos de ejemplo.

### Informe técnico (PDF o Word)

Cada persona redacta lo que implementó y se revisa de forma cruzada.

- [ ] Objetivo y marco teórico breve (B).
- [ ] Descripción del servicio y problema abordado (A).
- [ ] Arquitectura y diagramas, incluyendo ControlNodes leader/follower (A).
- [ ] Especificación de protocolos y APIs: REST, gRPC y endpoints RF3 (A y B).
- [ ] Algoritmos de particionamiento, distribución y replicación (A).
- [ ] **Semántica de escritura de RF3 y su justificación**: versionamiento,
      lock con lease, CAS y validación de integridad, con los tres escenarios
      pedidos por el profesor (A y B).
- [ ] Entorno de ejecución en Docker y despliegue en VMs (A y B).
- [ ] Pruebas y análisis de resultados: smoke tests, concurrencia, fallas,
      benchmark de bloques (A y B).
- [ ] Limitaciones conocidas (failover manual, sin mTLS, sesiones abiertas al
      promover el follower).

### Video de demostración (10-15 min)

- [ ] Guion repartido: explicación de arquitectura (A) y demo del cliente y
      DataNodes (B).
- [ ] Demo RF1/RF2: subir/bajar archivo de varios bloques, comparar SHA-256.
- [ ] Demo RF3: dos clientes escribiendo (lock y conflicto), lectura por
      rango, versión nueva tras `close`.
- [ ] Demo de falla: caída de un DataNode durante una escritura/lectura,
      fallback y re-replicación; failover manual del ControlNode.
- [ ] Grabar sobre el despliegue en VMs.

### Otros

- [ ] Benchmark mínimo comparando tamaños de bloque.
- [ ] Repositorio GitHub documentado y reproducible.

## Fuera de alcance

- [ ] El failover entre ControlNodes es manual; no hay elección automática ni
      tolerancia a split-brain.
- [ ] La replicación de metadatos usa el RPC `ReplicateMetadata` con un
      snapshot completo de SQLite; el cambio a
      `PushSnapshot(stream SnapshotChunk)` queda fuera de esta entrega.
- [ ] mTLS no está implementado; la configuración actual usa autenticación del
      servidor mediante TLS y API key para los RPC internos.
- [ ] RF3 no ofrece semántica POSIX completa: sin locks por rango de bytes,
      sin escrituras concurrentes sobre el mismo archivo (se serializan con
      lock exclusivo) y sin fusión automática de versiones en conflicto.
- [ ] Los locks no sobreviven sin pérdida a un failover: se restauran desde
      el último snapshot y las sesiones abiertas se invalidan.

## Notas y configuración

- El mock de `mock/controlnode/` se conserva como referencia, pero la
  integración actual del proyecto usa el ControlNode real de `controlnode/`.
- La configuración de desarrollo usa bloques de 64 KiB; producción mantiene
  bloques de 8 MiB.
- `DATANODE_MASTER_KEY` debe ser una clave Base64 que decodifique exactamente a
  32 bytes.
- Decisión de RF3 pendiente de confirmar en el equipo: escritura por offset
  con copy-on-write vs. plan B (reemplazo completo versionado + `append`).