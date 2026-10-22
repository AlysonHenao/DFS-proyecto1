# Runbook de Conmutación por Error (Failover Manual)

El sistema DFSha cuenta con dos ControlNodes: `control-leader` (activo) y `control-follower` (standby).
El `control-leader` envía snapshots consistentes de la base de datos de metadatos SQLite periódicamente al `control-follower` a través del servicio gRPC interno `ReplicateMetadata`.

En caso de fallo o mantenimiento del nodo líder, el failover se ejecuta siguiendo este procedimiento de 5 pasos:

---

### Paso 1: Detener el ControlNode Líder
Para evitar estados inconsistentes (*split-brain*), se detiene el contenedor o proceso del líder actual:
```bash
docker compose stop control-leader
```
*(En despliegue IaaS en VMs: `sudo systemctl stop dfsha-controlnode` en la VM del líder).*

---

### Paso 2: Promover el Follower al rol Leader
Se actualiza la variable de entorno `CONTROLNODE_ROLE=leader` en el seguidor:
- Si se usa docker-compose en local:
  Modificar en el `.env` o en `docker-compose.yml`:
  ```yaml
  control-follower:
    environment:
      CONTROLNODE_ROLE: leader
  ```
  Y aplicar el cambio sin reiniciar los DataNodes:
  ```bash
  docker compose up -d --no-deps control-follower
  ```
*(En despliegue IaaS en VMs: actualizar `/etc/dfsha/controlnode.env` con `CONTROLNODE_ROLE=leader` y reiniciar el servicio: `sudo systemctl restart dfsha-controlnode`).*

---

### Paso 3: Actualizar el endpoint en los clientes
La CLI y los servicios que consumen metadatos leen la variable `DFSHA_CONTROL_URL`. Se actualiza al puerto o IP del nodo promovido:
- En entorno Docker local:
  ```bash
  export DFSHA_CONTROL_URL=http://localhost:8001
  ```
- En entorno de producción (VMs / AWS Academy):
  ```bash
  export DFSHA_CONTROL_URL=http://<IP_PUBLICA_FOLLOWER>:8000
  ```

---

### Paso 4: Verificar la salud del nuevo Líder
Consultar el endpoint `/health` del nuevo líder para confirmar que ha asumido el rol activo y el servicio está listo:
```bash
curl -s http://localhost:8001/health
```
Respuesta esperada:
```json
{
  "status": "ok",
  "role": "leader",
  "id": "control-follower"
}
```

---

### Paso 5: Validar integridad y operaciones del File System
Comprobar que el árbol de directorios y los bloques persisten intactos gracias a los snapshots replicados:
```bash
docker compose run --rm -e DFSHA_CONTROL_URL=http://control-follower:8000 client ls /
```
Verificar que los comandos de lectura y escritura (`mkdir`, `put`, `get`) operen normalmente contra el nuevo líder promovido.
