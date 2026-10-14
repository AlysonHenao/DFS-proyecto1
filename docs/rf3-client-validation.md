# Validación diferida del cliente RF3

El ControlNode actual solo expone RF1/RF2. Las pruebas del cliente RF3 se
dividen en pruebas unitarias ejecutables ahora y pruebas de integración
pendientes de la implementación de la Persona A.

## Contrato esperado del ControlNode

El cliente espera estas operaciones autenticadas:

| Método | Ruta | Campos mínimos |
|---|---|---|
| POST | `/files/open` | `path`, `mode`, `append` |
| POST | `/files/close` | `session_id`, opcionalmente `blocks` |
| POST | `/files/lock` | `session_id`, `lease_seconds` |
| POST | `/files/unlock` | `session_id` |
| POST | `/files/lock/renew` | `session_id`, `lease_seconds` |
| GET | `/files/read/plan` | `session_id`, `offset`, `length` |
| POST | `/files/write/plan` | `session_id`, `offset`, `length`, `append` |

Los planes de lectura deben devolver `block_size` y bloques con `index`,
`size`, `block_id`, `nodes` y, preferiblemente, `sha256`. Los planes de
escritura deben devolver bloques nuevos con `chain`, `block_id`, `index` y
`sha256` esperado. `close` debe aplicar CAS contra la versión base y rechazar
con `409` un conflicto, un lock ausente o un lease vencido.

## Pruebas disponibles ahora

Desde la raíz del repositorio:

```powershell
python -m unittest tests.test_rf3_client tests.test_transfer
```

No requieren Docker, ControlNode RF3 ni DataNodes reales. Un endpoint RF3
ausente se considera una dependencia pendiente, nunca un éxito silencioso.

## Pruebas posteriores a la entrega de A

1. Arrancar el stack con `TLS_ENABLED=false`.
2. Abrir un archivo de varios bloques en lectura y leer un rango que cruce
   bloques; comparar SHA-256.
3. Abrir en escritura, modificar una región parcial y cerrar; confirmar una
   versión nueva y que la anterior siga siendo legible.
4. Probar `append`, dos clientes con lock exclusivo y un commit CAS en
   conflicto.
5. Detener un DataNode durante la escritura/lectura y verificar fallback,
   quorum y ausencia de una versión publicada parcialmente.
6. Repetir los pasos con `TLS_ENABLED=true`, `TLS_CA` configurada y
   certificados válidos.

Los smoke tests integrados de RF3 se añadirán a
`scripts/smoke_test.sh` y `scripts/smoke_test.ps1` una vez que la Persona A
confirme la forma final de las respuestas RF3. Los escenarios requeridos son:
lectura por rango, escritura parcial, append, conflicto, expiración de lease,
caída de DataNode y limpieza de bloques huérfanos.
