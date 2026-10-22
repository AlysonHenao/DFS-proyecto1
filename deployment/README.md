# Guía de Despliegue Manual en AWS EC2 (2 VMs)

Esta guía detalla el paso a paso para desplegar **DFSha** de forma manual en **dos instancias virtuales EC2** dentro de la VPC por defecto de AWS, configurando redes, grupos de seguridad, certificados TLS, variables de entorno y ejecución con Docker Compose.

---

## ¿Qué es DFSha? (A grandes rasgos)

**DFSha** es un sistema de archivos distribuido de alta disponibilidad inspirado en HDFS/GFS:
- **ControlNode (Metadatos):** Gestiona el árbol de directorios, permisos, sesiones y ubicaciones de bloques en SQLite. Opera en esquema Activo-Pasivo (Líder / Seguidor).
- **DataNodes (Almacenamiento):** Almacenan bloques de datos en disco cifrados con AES-256-GCM y los replican en cadena vía streaming gRPC.
- **Cliente CLI:** Interfaz de usuario para autenticarse (JWT) y ejecutar operaciones (`put`, `get`, `ls`, `mkdir`, `rm`, etc.).

---

## Arquitectura del Despliegue

| Nodo | Componentes / Contenedores | Puertos expuestos en host |
|---|---|---|
| **VM1 (Líder)** | `control-leader` (ControlNode activo)<br>`datanode1` (DataNode 1)<br>`client` (Herramienta CLI / pruebas) | • `8000` (REST API Líder)<br>• `50050` (gRPC ControlNode)<br>• `50051` (gRPC DataNode 1) |
| **VM2 (Seguidor)** | `control-follower` (ControlNode standby)<br>`datanode2` (DataNode 2)<br>`datanode3` (DataNode 3) | • `8001` (REST API Follower)<br>• `50050` (gRPC ControlNode)<br>• `50052` (gRPC DataNode 2)<br>• `50053` (gRPC DataNode 3) |

---

## Paso 1. Crear el Security Group en AWS

1. Ve a la consola de **AWS EC2** > **Security Groups** > **Create security group**.
2. **Nombre**: `dfsha-cluster-sg`
3. **Descripción**: `Reglas de comunicacion para cluster DFS-HA`
4. **VPC**: Selecciona la **VPC por defecto** (generalmente `172.31.0.0/16`).
5. **Inbound rules (Reglas de entrada)**:
   - **SSH (22)**: TCP `22` — Origen: `Tu IP pública` (`x.x.x.x/32`) o `0.0.0.0/0` (temporalmente).
   - **ControlNode REST**: TCP `8000` y `8001` — Origen: `0.0.0.0/0` o la IP de administración/cliente.
   - **Comunicación Interna del Clúster (ControlNodes y DataNodes gRPC)**:
     - Agrega una regla de **Todo el tráfico (All traffic)** con origen en el **CIDR de la VPC** (ej. `172.31.0.0/16`) o apuntando al **mismo Security Group ID** (`sg-xxxxxxxxx`).
     *(Esto permite que VM1 y VM2 intercambien heartbeats, replicación y llamadas en los puertos `50050`, `50051`, `50052`, `50053` sin bloqueos).*
6. Guarda el Security Group.

---

## Paso 2. Lanzar las dos Máquinas Virtuales (EC2)

1. En la consola de EC2, haz clic en **Launch instances**.
2. **Cantidad de instancias**: `2`
3. **AMI**: `Ubuntu Server 22.04 LTS` o `Ubuntu Server 24.04 LTS` (x86_64).
4. **Tipo de instancia**: `t3.small` (recomendado) o `t2.micro`.
5. **Key pair**: Selecciona o crea tu par de claves `.pem` para acceder por SSH.
6. **Network settings**:
   - **VPC**: VPC por defecto.
   - **Auto-assign public IP**: `Enable`.
   - **Firewall (security groups)**: Selecciona el grupo existente `dfsha-cluster-sg`.
7. **Lanza las instancias**.
8. Una vez iniciadas, asígnales nombres para identificarlas:
   - Instancia 1: `dfsha-vm1`
   - Instancia 2: `dfsha-vm2`
9. **Apunta las direcciones IP:**
   - `VM1_PUBLIC_IP` y `VM1_PRIVATE_IP` (ejemplo: `172.31.17.22`)
   - `VM2_PUBLIC_IP` y `VM2_PRIVATE_IP` (ejemplo: `172.31.25.40`)

---

## Paso 3. Instalar Docker y Preparar el Repositorio

> Realiza este procedimiento en **ambas máquinas virtuales** (conéctate vía SSH a cada una).

```bash
# 1. Actualizar repositorios e instalar paquetes base
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg git jq

# 2. Instalar Docker y Docker Compose
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 3. Dar permisos al usuario ubuntu para ejecutar docker sin sudo
sudo usermod -aG docker ubuntu
newgrp docker

# 4. Clonar el repositorio en /opt/dfsha
sudo mkdir -p /opt/dfsha
sudo chown -R ubuntu:ubuntu /opt/dfsha
git clone <URL_DE_TU_REPOSITORIO> /opt/dfsha
cd /opt/dfsha
```

---

## Paso 4. Configurar el archivo `.env`

Crea o edita el archivo `/opt/dfsha/.env` en **ambas máquinas** (`VM1` y `VM2`). Ambas deben tener las mismas claves secretas y las IPs privadas reales de tu despliegue.

```bash
nano /opt/dfsha/.env
```

Contenido base del `.env` (ajusta las IPs privadas según las asignadas por AWS):

```dotenv
# --- Politica del cluster ---
BLOCK_SIZE_BYTES=65536
REPLICATION_FACTOR=2
MIN_WRITE_ACKS=2
HEARTBEAT_INTERVAL_S=5
DEAD_TIMEOUT_S=15
CHUNK_SIZE_BYTES=524288

# --- Seguridad ---
# Genera claves seguras con: python3 -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"
JWT_SECRET=inMYmzJvb44MsHZYlOgZ1V3rUrWeHQpPPDeRYQB17lI=
JWT_EXPIRE_MIN=60
CLUSTER_API_KEY=clave-secreta-para-comunicacion-interna
DATANODE_MASTER_KEY=fZssTxqOPW1cO5qPfm1cSzo/Hg2ci7pnXk08KxoPno0=

# --- IPs Privadas de AWS EC2 (¡Actualizar con las IPs reales!) ---
VM1_PRIVATE_IP=172.31.17.22
VM2_PRIVATE_IP=172.31.25.40

# --- ControlNodes ---
CONTROL_REST_PORT=8000
CONTROL_GRPC_PORT=50050
DB_PATH=/data/meta.db

# --- DataNodes ---
DATANODE_PORT=50051
DATANODE_DATA_DIR=/data
TRASH_RETENTION_S=600

# --- TLS ---
TLS_ENABLED=true
TLS_CERT=/certs/server.crt
TLS_KEY=/certs/server.key
TLS_CA=/certs/ca.crt

# --- Cliente ---
DFSHA_CONTROL_URL=https://control-leader:8000
```

> **Nota:** Si prefieres probar inicialmente **sin TLS**, establece `TLS_ENABLED=false` y en `DFSHA_CONTROL_URL` usa `http://control-leader:8000`.

---

## Paso 5. Generación de Certificados TLS y Traslado a VM2

Los certificados deben generarse incluyendo en el **Subject Alternative Name (SAN)** las IPs privadas de ambas máquinas para que gRPC y HTTPS no rechacen la conexión.

### 5.1 Generar certificados en VM1

En **VM1**:

```bash
cd /opt/dfsha

# Asegurar permisos de ejecución en el script
chmod +x scripts/gen_certs.sh

# Ejecutar el script pasando las IPs privadas de VM1 y VM2
./scripts/gen_certs.sh $VM1_PRIVATE_IP $VM2_PRIVATE_IP
```

Esto creará los certificados dentro del directorio `/opt/dfsha/certs/`:
- `ca.crt`, `ca.key`
- `server.crt`, `server.key`

### 5.2 Copiar los certificados a VM2

Tienes dos alternativas sencillas:

**Opción A (Mediante `scp` desde VM1):**
Si tienes tu llave `.pem` en VM1:
```bash
scp -i ~/.ssh/tu-clave.pem -r /opt/dfsha/certs ubuntu@$VM2_PRIVATE_IP:/opt/dfsha/
```

**Opción B (Desde tu máquina local):**
Descarga la carpeta de VM1 y súbela a VM2:
```bash
# En tu máquina local:
scp -i tu-clave.pem -r ubuntu@VM1_PUBLIC_IP:/opt/dfsha/certs ./certs-temp
scp -i tu-clave.pem -r ./certs-temp ubuntu@VM2_PUBLIC_IP:/opt/dfsha/certs
rm -rf ./certs-temp
```

Verifica en **VM2** que los archivos existan:
```bash
ls -la /opt/dfsha/certs
```

---

## Paso 6. Levantar los Contenedores

### 6.1 Iniciar VM1 (Líder + DataNode 1)

En **VM1**:

```bash
cd /opt/dfsha
docker compose -f deployment/docker-compose.vm1.yml up -d --build
```

Revisar que los contenedores estén corriendo:
```bash
docker compose -f deployment/docker-compose.vm1.yml ps
```

### 6.2 Iniciar VM2 (Follower + DataNodes 2 y 3)

En **VM2**:

```bash
cd /opt/dfsha
docker compose -f deployment/docker-compose.vm2.yml up -d --build
```

Revisar el estado:
```bash
docker compose -f deployment/docker-compose.vm2.yml ps
```

---

## Paso 7. Verificar el Estado del Clúster (Health & Logs)

### 7.1 Consultar el estado de salud de los nodos

Desde la consola de **VM1**:

- Con TLS activo:
  ```bash
  curl --cacert certs/ca.crt https://localhost:8000/health
  # Respuesta esperada: {"status":"healthy","role":"leader",...}
  ```
- Si TLS está desactivado:
  ```bash
  curl http://localhost:8000/health
  ```

Verificar el nodo seguidor en **VM2**:
```bash
curl --cacert certs/ca.crt https://localhost:8001/health
# Respuesta esperada: {"status":"healthy","role":"follower",...}
```

### 7.2 Inspeccionar Heartbeats en los logs

Revisar que DataNode 1 y los DataNodes remotos se estén reportando al líder:

```bash
# En VM1:
docker compose -f deployment/docker-compose.vm1.yml logs --tail=50 -f control-leader

# En VM2:
docker compose -f deployment/docker-compose.vm2.yml logs --tail=50 -f datanode2
```

---

## Paso 8. Uso del Cliente CLI

El servicio `client` ya viene configurado en `deployment/docker-compose.vm1.yml` para conectarse al `control-leader` con el volumen montado para persistir la sesión.

En **VM1**, ejecuta las siguientes operaciones:

### 1. Registrar y autenticar un usuario
```bash
# Registrar usuario nuevo
docker compose -f deployment/docker-compose.vm1.yml run --rm client register alice password123

# Iniciar sesión (el token se guardará en /opt/dfsha/.dfsha-session.json)
docker compose -f deployment/docker-compose.vm1.yml run --rm client login alice password123
```

### 2. Operaciones con archivos
```bash
# Listar directorio raíz
docker compose -f deployment/docker-compose.vm1.yml run --rm client ls /

# Subir un archivo (put)
docker compose -f deployment/docker-compose.vm1.yml run --rm client put /work/prueba.txt /remoto.txt

# Listar nuevamente para comprobar la subida
docker compose -f deployment/docker-compose.vm1.yml run --rm client ls /

# Descargar el archivo (get)
docker compose -f deployment/docker-compose.vm1.yml run --rm client get /remoto.txt /work/descargado.txt

# Verificar integridad local
cat /opt/dfsha/descargado.txt
```

---

## Detener o Reiniciar Servicios

Para reiniciar o apagar el despliegue:

```bash
# En VM1
docker compose -f deployment/docker-compose.vm1.yml down

# En VM2
docker compose -f deployment/docker-compose.vm2.yml down
```
