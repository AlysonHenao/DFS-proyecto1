# Despliegue reproducible en dos VM

Esta carpeta contiene la infraestructura y los archivos Compose para desplegar
DFSha en dos VM Linux:

- **VM1:** ControlNode leader + `datanode1`.
- **VM2:** ControlNode follower + `datanode2` y `datanode3`.

Terraform crea las VM, la red de acceso y las reglas de firewall. Docker
Compose ejecuta los servicios en cada VM. Los secretos, certificados y el
archivo `.env` se deben proporcionar fuera de Git.

## Estructura

```text
deployment/
├── README.md
├── docker-compose.vm1.yml
├── docker-compose.vm2.yml
└── terraform/
    ├── main.tf
    ├── variables.tf
    ├── outputs.tf
    ├── terraform.tfvars.example
    └── .gitignore
```

## 1. Requisitos

- Cuenta AWS con permisos para EC2, VPC y grupos de seguridad.
- Terraform >= 1.6.
- AWS CLI configurado (`aws configure`).
- Una clave SSH de EC2.
- El repositorio disponible en ambas VM, por ejemplo en `/opt/dfsha`.

No subir a Git `terraform.tfvars`, `*.tfstate`, `.env`, claves privadas ni
certificados.

## 2. Crear las VM con Terraform

Desde `deployment/terraform`:

```bash
cp terraform.tfvars.example terraform.tfvars
```

Editar `terraform.tfvars`:

```hcl
aws_region  = "us-east-1"
project_name = "dfsha"
instance_type = "t3.small"
key_name = "mi-clave-ec2"
ssh_cidr = "TU_IP_PUBLICA/32"
client_cidr = "TU_IP_PUBLICA/32"
```

`ssh_cidr` debe limitarse a la IP pública desde la que se administrarán las
VM. No usar `0.0.0.0/0` salvo durante una prueba temporal.

```bash
terraform init
terraform fmt
terraform validate
terraform plan
terraform apply
```

Guardar las salidas:

```bash
terraform output
terraform output -raw vm1_public_ip
terraform output -raw vm2_public_ip
```

## 3. Preparar las VM

Terraform instala Docker y crea `/opt/dfsha`. En cada VM, clonar o copiar el
repositorio:

```bash
ssh ubuntu@VM1_PUBLIC_IP
sudo git clone URL_DEL_REPOSITORIO /opt/dfsha
sudo chown -R "$USER:$USER" /opt/dfsha
```

Repetir en VM2. Si el repositorio es privado, usar un mecanismo seguro de
acceso; no incrustar tokens en Terraform ni en `user_data`.

## 4. Configurar red y secretos

En ambas VM, crear `/opt/dfsha/.env` a partir de `.env.example`. Usar las IP
privadas de Terraform para la comunicación interna:

```bash
terraform output -raw vm1_private_ip
terraform output -raw vm2_private_ip
```

Valores mínimos comunes:

```dotenv
REPLICATION_FACTOR=2
MIN_WRITE_ACKS=2
TLS_ENABLED=true
JWT_SECRET=CAMBIAR_POR_UN_SECRETO_LARGO
CLUSTER_API_KEY=CAMBIAR_POR_OTRA_CLAVE_LARGA
DATANODE_MASTER_KEY=CLAVE_BASE64_DE_32_BYTES
```

Generar una clave para DataNode:

```bash
python3 -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
```

Generar certificados cuyo SAN incluya los nombres/IP que usarán las VM. Los
certificados se montan en `/opt/dfsha/certs`; nunca deben subirse al
repositorio.

## 5. Iniciar los servicios

En VM1:

```bash
cd /opt/dfsha
docker compose -f deployment/docker-compose.vm1.yml up -d --build
docker compose -f deployment/docker-compose.vm1.yml ps
```

En VM2:

```bash
cd /opt/dfsha
docker compose -f deployment/docker-compose.vm2.yml up -d --build
docker compose -f deployment/docker-compose.vm2.yml ps
```

Sustituir en ambos Compose los marcadores `VM1_PRIVATE_IP` y
`VM2_PRIVATE_IP`, o convertirlos en variables de un archivo `.env` de
despliegue. Los DataNodes deben anunciar direcciones privadas alcanzables
desde la otra VM, no `datanode1:50051` ni `localhost`.

## 6. Validar

Desde un equipo con acceso a VM1:

```bash
curl --cacert certs/ca.crt -s https://VM1_PUBLIC_IP:8000/health
curl --cacert certs/ca.crt -s https://VM2_PUBLIC_IP:8001/health
```

La primera respuesta debe indicar `role: leader` y la segunda `role:
follower`.

Revisar heartbeats y errores de red:

```bash
docker compose -f deployment/docker-compose.vm1.yml logs --tail=100 control-leader datanode1
docker compose -f deployment/docker-compose.vm2.yml logs --tail=100 control-follower datanode2 datanode3
```

Los DataNodes registran cada heartbeat exitoso con el destino, el nodo, la
cantidad de bloques reportados y los comandos recibidos. Los ControlNodes
también registran cada heartbeat recibido y su rol. Durante el arranque pueden
aparecer fallos transitorios de conexión hasta que el servidor gRPC esté listo.

Registrar y autenticar el cliente contra el leader. Después del login, las
operaciones pueden reutilizar el JWT persistido:

```bash
docker compose run --rm client register alice
docker compose run --rm client login alice
docker compose run --rm client ls /
```

## 7. Destruir la infraestructura

Solo después de respaldar los datos:

```bash
cd deployment/terraform
terraform destroy
```

Terraform no respalda los volúmenes Docker ni la base SQLite; el borrado de las
VM implica perder esos datos.
