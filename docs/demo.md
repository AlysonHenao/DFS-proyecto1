# Runbook de Demo: Falla y Recuperación de un DataNode

Esta demo valida que un archivo con RF2 siga disponible cuando se detiene un
DataNode, que el cliente pueda leer desde otra réplica y que el ControlNode
ordene una nueva replicación antes de recuperar el nodo detenido.

La detección de nodos muertos y el envío de `REPLICATE` dependen del
ControlNode real. La demo valida además que el DataNode ejecute correctamente
ese comando.

El procedimiento puede ejecutarse en Docker Compose, en una máquina virtual
Linux o distribuido entre instancias EC2. En AWS, los nombres usados a
continuación deben reemplazarse por DNS privados o direcciones privadas de las
instancias; no se recomienda exponer los puertos gRPC a Internet.

---

## Paso 1: Preparar el entorno

### Docker Compose local

Desde la raíz del repositorio:

```bash
cp .env.example .env
```

En PowerShell:

```powershell
Copy-Item .env.example .env
```

Generar una clave AES de 32 bytes y copiar el resultado a
`DATANODE_MASTER_KEY` en `.env`:

```bash
python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
```

Mantener inicialmente:

```dotenv
TLS_ENABLED=false
```

### VM Linux o AWS EC2

En cada VM:

1. Instalar Docker y Docker Compose, o instalar Python, `grpcio`,
   `cryptography`, FastAPI y las dependencias de cada servicio.
2. Clonar el repositorio en la misma ruta de servicio, por ejemplo
   `/opt/dfsha`.
3. Configurar el mismo `DATANODE_MASTER_KEY` Base64 de 32 bytes en todos los
   DataNodes.
4. Configurar `CONTROL_GRPC_ADDRS` con las direcciones privadas de los
   ControlNodes y `DFSHA_CONTROL_URL` con el endpoint REST del líder.
5. Usar nombres resolubles entre VMs. Si no hay DNS privado, agregar los
   nombres y direcciones privadas a `/etc/hosts`.

Los grupos de seguridad de AWS y los firewalls de las VMs deben permitir
únicamente el tráfico interno necesario:

| Servicio | Puerto | Uso |
|---|---:|---|
| ControlNode REST | 8000 | Cliente y API |
| ControlNode gRPC | 50050 | Heartbeats, snapshots y comandos |
| DataNode gRPC | 50051 | Lectura, escritura y replicación |

El puerto REST puede publicarse a la máquina desde la que se ejecuta la demo.
Los puertos gRPC deben limitarse a las subredes privadas del despliegue.

---

## Paso 2: Generar y distribuir certificados TLS

Para una prueba sin TLS, dejar `TLS_ENABLED=false` y continuar con el paso 3.

Para TLS, generar los certificados en una máquina segura:

```bash
sh scripts/gen_certs.sh
```

El certificado debe incluir como SAN los nombres que usan los servicios:
`control-leader`, `control-follower`, `datanode1`, `datanode2`,
`datanode3` y `localhost`. En AWS/VMs, si los clientes acceden usando otros
nombres DNS, esos nombres o IPs deben estar incluidos en el certificado.

Copiar de forma segura `ca.crt`, `server.crt` y `server.key` a cada nodo.
La clave privada `server.key` no debe subirse al repositorio ni compartirse
fuera de los nodos que ejecutan servicios.

Configurar en `.env` o en el entorno de cada servicio:

```dotenv
TLS_ENABLED=true
TLS_CA=/certs/ca.crt
TLS_CERT=/certs/server.crt
TLS_KEY=/certs/server.key
DFSHA_CONTROL_URL=https://<control-leader-host>:8000
```

En Docker Compose, `certs/` se monta automáticamente en `/certs`. En una VM,
crear esa ruta y restringir permisos:

```bash
sudo install -d -m 700 /certs
sudo install -m 644 ca.crt server.crt /certs/
sudo install -m 600 server.key /certs/
```

Validar el certificado antes de iniciar:

```bash
openssl verify -CAfile /certs/ca.crt /certs/server.crt
```

La respuesta esperada es `OK`.

---

## Paso 3: Iniciar y comprobar los servicios

### Docker Compose local

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 control-leader control-follower datanode1 datanode2 datanode3
```

Esperar hasta que el líder responda y los DataNodes estén escuchando. Los
primeros heartbeats pueden fallar mientras los ControlNodes terminan de
iniciar; deben recuperarse en los siguientes intervalos.

Con TLS desactivado:

```bash
curl -s http://localhost:8000/health
```

Con TLS activado:

```bash
curl --cacert certs/ca.crt -s https://localhost:8000/health
```

La respuesta esperada debe indicar `"status": "ok"` y
`"role": "leader"`.

### VM Linux o AWS EC2

Iniciar los servicios según el método elegido. Por ejemplo, si se usan
unidades systemd:

```bash
sudo systemctl start dfsha-controlnode
sudo systemctl start dfsha-datanode
sudo systemctl status dfsha-controlnode dfsha-datanode
```

Comprobar desde el host del cliente:

```bash
curl --cacert /certs/ca.crt -s https://<control-leader-host>:8000/health
```

Sin TLS, cambiar `https://` por `http://` y eliminar `--cacert`.

---

## Paso 4: Crear un archivo con RF2

Guardar el archivo de entrada en el cliente:

```bash
printf 'contenido DFSha para la demo\n' > demo-input.txt
sha256sum demo-input.txt
```

En PowerShell:

```powershell
"contenido DFSha para la demo" | Set-Content .\demo-input.txt -NoNewline
Get-FileHash .\demo-input.txt -Algorithm SHA256
```

### Docker Compose local

Registrar un usuario desde el cliente. El nombre puede ser fijo; la fecha no
es necesaria. Si se repite la prueba con el mismo usuario, el servidor
responderá que ese usuario ya existe:

```powershell
docker compose run --rm client register alice
```

La CLI solicitará la contraseña y su confirmación sin mostrarla en pantalla.
También puede recibirse el usuario desde una variable de entorno, pero no es
necesario repetir esa variable en los comandos posteriores.

Iniciar sesión explícitamente y guardar el JWT en el volumen `/work`:

```powershell
docker compose run --rm client login alice
```

La CLI solicitará la contraseña. Después del login, los comandos temporales
pueden reutilizar el JWT guardado sin `-e DFSHA_USERNAME` ni
`-e DFSHA_PASSWORD`:

```powershell
docker compose run --rm client ls /
docker compose run --rm client mkdir /demo
docker compose run --rm client put /work/demo-input.txt /demo/input.txt
```

El token se guarda en `.dfsha-session.json`, excluido de Git. Para invalidar
la sesión local, eliminar ese archivo y ejecutar `login` de nuevo:

```powershell
Remove-Item .\.dfsha-session.json
docker compose run --rm client login alice
```

Para automatizar el flujo sin prompts, las credenciales pueden proporcionarse
solo en `register` y `login`:

```powershell
docker compose run --rm `
  -e DFSHA_USERNAME=alice `
  -e DFSHA_PASSWORD='S3gura-Prueba-2026!' `
  client register

docker compose run --rm `
  -e DFSHA_USERNAME=alice `
  -e DFSHA_PASSWORD='S3gura-Prueba-2026!' `
  client login
```

No es necesario incluir esas variables al ejecutar `ls`, `mkdir`, `put`, `get`
u otros comandos protegidos mientras `.dfsha-session.json` exista y el JWT no
haya expirado. Si se necesita un usuario nuevo en cada ejecución automática,
se puede generar un nombre único con `Get-Date`, pero esto solo evita el
conflicto `user already exists`.

### VM Linux o AWS EC2

Ejecutar el cliente en la VM que tenga acceso al ControlNode:

```bash
export DFSHA_CONTROL_URL=https://<control-leader-host>:8000
./client/cli.py mkdir /demo
./client/cli.py put ./demo-input.txt /demo/input.txt
```

Si la CLI se ejecuta como contenedor independiente, usar el mismo comando
`docker compose run` con el archivo de configuración adaptado a las
direcciones privadas de las VMs.

El `put` debe terminar correctamente y crear dos réplicas del bloque.

---

## Paso 5: Confirmar réplicas y cifrado en disco

### Docker Compose local

```bash
docker compose exec datanode1 find /data -maxdepth 1 -type f
docker compose exec datanode2 find /data -maxdepth 1 -type f
docker compose exec datanode3 find /data -maxdepth 1 -type f
```

### VM Linux o AWS EC2

En cada VM DataNode:

```bash
find /data -maxdepth 1 -type f
```

Identificar el `block_id` presente en dos nodos. El contenido almacenado no
debe ser texto plano:

```bash
grep -a 'contenido DFSha' /data/<block_id>
```

El comando no debe devolver coincidencias. No descifrar ni modificar los
archivos directamente: las lecturas deben realizarse mediante el DataNode.

---

## Paso 6: Detener un DataNode y validar el fallback

Detener uno de los nodos que contiene una réplica, por ejemplo `datanode1`.

### Docker Compose local

```bash
docker compose stop datanode1
docker compose run --rm client get /demo/input.txt /work/demo-output-fallback.txt
```

### VM Linux o AWS EC2

En la VM del DataNode seleccionado:

```bash
sudo systemctl stop dfsha-datanode
```

Ejecutar el `get` desde el cliente:

```bash
./client/cli.py get /demo/input.txt ./demo-output-fallback.txt
```

Comparar el SHA-256:

```bash
sha256sum demo-input.txt demo-output-fallback.txt
```

En PowerShell:

```powershell
Get-FileHash .\demo-input.txt -Algorithm SHA256
Get-FileHash .\demo-output-fallback.txt -Algorithm SHA256
```

Los dos hashes deben coincidir. Esto demuestra que el cliente pasó a la
réplica disponible cuando la primera falló.

---

## Paso 7: Esperar la detección y la re-replicación

Mantener detenido el DataNode. Esperar al menos:

```text
DEAD_TIMEOUT_S + HEARTBEAT_INTERVAL_S
```

Revisar los logs.

### Docker Compose local

```bash
docker compose logs --tail=300 control-leader datanode2 datanode3
```

### VM Linux o AWS EC2

```bash
sudo journalctl -u dfsha-controlnode --since "5 minutes ago"
sudo journalctl -u dfsha-datanode --since "5 minutes ago"
```

Debe observarse el nodo marcado como `dead`, el bloque identificado como
`under-replicated` y un comando `REPLICATE`.

Antes de reiniciar el nodo detenido, confirmar que el bloque apareció en otro
DataNode:

```bash
find /data -maxdepth 1 -type f
```

En Compose, repetir el comando para `datanode2` y `datanode3`. En AWS/VMs,
ejecutarlo en cada DataNode disponible. El número de copias debe volver a
cumplir RF2.

---

## Paso 8: Recuperar el DataNode y validar la lectura final

### Docker Compose local

```bash
docker compose start datanode1
docker compose run --rm client get /demo/input.txt /work/demo-output-final.txt
```

### VM Linux o AWS EC2

```bash
sudo systemctl start dfsha-datanode
sudo systemctl status dfsha-datanode
./client/cli.py get /demo/input.txt ./demo-output-final.txt
```

Comparar nuevamente los hashes:

```bash
sha256sum demo-input.txt demo-output-final.txt
```

Los hashes finales también deben coincidir. Revisar que el DataNode vuelva a
enviar heartbeats y que el ControlNode lo marque como vivo.

---

## Resultado esperado

La demo es satisfactoria cuando se cumplen todas estas condiciones:

1. El `put` crea dos réplicas.
2. Los archivos físicos de `/data` no contienen el texto plano.
3. El `get` funciona con un DataNode detenido y conserva el SHA-256.
4. El ControlNode detecta el nodo muerto y solicita `REPLICATE`.
5. La réplica faltante aparece en un DataNode disponible antes de recuperar
   el nodo original.
6. El DataNode recuperado vuelve a enviar heartbeats.
7. El `get` final conserva el mismo SHA-256.
