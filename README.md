# DFSha - Distributed File System with High Availability

**DFSha** es un sistema de archivos distribuido con alta disponibilidad (HA), inspirado en el diseño de arquitecturas como **GFS (Google File System)** y **HDFS (Hadoop Distributed File System)**. El sistema separa el plano de control (metadatos del filesystem, usuarios y sesiones) del plano de datos (almacenamiento, streaming de bloques y replicación).

---

## ¿Qué contiene el proyecto a grandes rasgos?

El proyecto está compuesto por tres componentes principales y una suite de infraestructura:

```text
               ┌────────────────────────────────────────────────────────┐
               │                      CLIENTE CLI                       │
               │        (Autenticación JWT, Put/Get, Open/Read/Write)   │
               └──────────────┬───────────────────────────┬─────────────┘
          REST (Metadata/Plan)│                           │ gRPC (Streaming de Bloques)
                              ▼                           ▼
 ┌──────────────────────────────────────────────┐    ┌───────────────────────────────────┐
 │             CONTROLNODE (Metadatos)          │    │            DATANODES              │
 │  • Activo / Standby (Leader / Follower)      │    │  • Pipeline de replicación        │
 │  • Base de datos SQLite (WAL + Snapshots)    │◀───│  • Heartbeats periódicos          │
 │  • Autenticación de usuarios (Bcrypt + JWT)  │    │  • Cifrado AES-GCM en reposo      │
 │  • Monitoreo y auto-re-replicación           │    │  • Papelera y borrado idempotente │
 └──────────────────────────────────────────────┘    └───────────────────────────────────┘
```

### 1. ControlNode (`controlnode/`) — Plano de Control y Metadatos

- **Alta Disponibilidad Activo-Pasivo**: Cuenta con un nodo **Líder** que procesa solicitudes y un nodo **Follower** (Standby) que recibe réplicas periódicas de metadatos vía gRPC. En caso de caída, se puede promover el seguidor a líder.
- **Persistencia de Metadatos**: Utiliza **SQLite** con modo WAL para gestionar el árbol de directorios, permisos, metadatos de archivos, mapeo de bloques y sesiones.
- **Autenticación y Seguridad**: Registro y autenticación de usuarios mediante contraseñas hasheadas con **Bcrypt** y emisión de tokens **JWT** (OAuth2 Bearer).
- **Gestión del Clúster y Salud**: Recibe _heartbeats_ gRPC de los DataNodes, monitorea capacidades de almacenamiento, detecta nodos caídos (`dead timeout`) y emite comandos de **re-replicación** cuando un bloque queda sub-replicado.

### 2. DataNodes (`datanode/`) — Plano de Datos y Almacenamiento

- **Transferencia de Alto Rendimiento (gRPC)**: Escritura y lectura de bloques en streaming mediante gRPC (`WriteBlock`, `ReadBlock`).
- **Replicación en Cadena (Pipelining)**: Al recibir un bloque, el primer DataNode lo guarda localmente y simultáneamente reenvía el flujo de datos al siguiente DataNode en la cadena.
- **Cifrado en Reposo**: Cifrado local por bloque usando **AES-256-GCM** con nonces aleatorios y control de integridad.
- **Mantenimiento Autónomo**: Notifica periódicamente sus bloques al ControlNode y atiende órdenes de replicación o borrado a través de su papelera (`trash retention`).

### 3. Cliente CLI (`client/`) — Interfaz de Usuario

- Herramienta de línea de comandos para usuarios y administradores:
  - Gestión de sesión: `register`, `login`.
  - Navegación remota: `ls`, `mkdir`, `rm`, `rmdir`.
  - Transferencia de archivos: `put` (divide el archivo en bloques y los distribuye) y `get` (recupera y une los bloques).
  - Control de sesiones: `open`, `close`, `read`, `write`, `lock`, `unlock`.

### 4. Seguridad de Red y Cifrado en Tránsito

- **TLS / mTLS**: Comunicaciones cifradas de extremo a extremo (tanto el tráfico REST HTTP/HTTPS como los canales gRPC) mediante certificados x509 generados localmente.

---

## Estructura del Repositorio

| Directorio / Archivo     | Descripción                                                                                                                     |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| **`controlnode/`**       | Servidor FastAPI + gRPC del nodo maestro de metadatos y lógica de cluster.                                                      |
| **`datanode/`**          | Servidor gRPC de almacenamiento y replicación de bloques en disco.                                                              |
| **`client/`**            | Código del cliente CLI, lógica de autenticación y transferencias.                                                               |
| **`deployment/`**        | Archivos Compose (`docker-compose.vm1.yml`, `docker-compose.vm2.yml`) y **guía paso a paso para despliegue manual en AWS EC2**. |
| **`scripts/`**           | Scripts de utilidad (generador de certificados `gen_certs.sh`, smoke tests).                                                    |
| **`tests/`**             | Suite completa de pruebas unitarias y de integración (`pytest`).                                                                |
| **`docs/`**              | Documentación de diseño, decisiones arquitectónicas y flujos de validación.                                                     |
| **`docker-compose.yml`** | Configuración para despliegue y desarrollo local en un solo host.                                                               |
| **`dfsha.proto`**        | Contratos de interfaces gRPC entre ControlNodes, DataNodes y Cliente.                                                           |
| **`schema.sql`**         | Esquema relacional de la base de datos de metadatos SQLite.                                                                     |

---

## Cómo empezar

### Opción A. Desarrollo Local (Docker Compose)

Para levantar el clúster completo en tu máquina local:

```bash
# 1. Copiar variables de entorno
cp .env.example .env

# 2. Generar certificados TLS (opcional si TLS está habilitado)
./scripts/gen_certs.sh localhost 127.0.0.1

# 3. Iniciar todos los contenedores
docker compose up -d --build

# 4. Probar con el cliente
docker compose run --rm client register alice password123
docker compose run --rm client login alice password123
docker compose run --rm client ls /
```

### Opción B. Despliegue en AWS EC2 (2 Máquinas Virtuales)

Para desplegar en alta disponibilidad distribuyendo nodos en dos máquinas virtuales en la nube, consulta la guía detallada:
- **[Guía de Despliegue Manual en AWS (deployment/README.md)](./deployment/README.md)**
