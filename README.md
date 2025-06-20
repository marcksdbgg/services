### División equitativa de tareas para un equipo de **4 personas**

*(plazo: 2 días hábiles, prioridad: evitar cuellos de botella y dependencias fuertes)*

| Rol / Persona                             | Entregables concretos                                                                                                                                                                                                                                                        | Duración (≈ h) | Dependencias                                                  | Check-point clave                                                           |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- | ------------------------------------------------------------- | --------------------------------------------------------------------------- |
| **P1 – DevOps / Infra**                   | 1. Terraform o CloudFormation mínimo viable:<br> • VPC + subredes + SG<br> • Amazon MSK (3 brokers t3.small)<br> • EMR 7.9.0 (HDFS + Flink + Spark)<br> • MSK Connect servicio vacío<br>2. Buckets S3 y roles IAM básicos                                                    | 10 h           | Ninguna (empieza primero)                                     | Fin del **Día 1 AM**: recursos creados, endpoints listos                    |
| **P2 – Refactor microservicios**          | 1. Adapters Kafka + S3 en **ingest / docproc / embedding** (código y Dockerfile).<br>2. Nuevo worker “consumer” para docproc y embedding.<br>3. API Gateway reducido (subir-archivo + estatus).<br>4. CI local: `docker compose up` publica/consume en Kafka (Redpanda dev). | 12 h           | Sólo repo actual                                              | Fin del **Día 1 PM**: imágenes funcionan localmente; listo para subir a ECR |
| **P3 – Data Engineer (Flink & Spark)**    | 1. Script **PyFlink** `analytics_rt.py` (COUNT por minuto).<br>2. Script **PySpark** batch diario.<br>3. Job descriptors (JSON) para enviarlos como *EMR Steps*.<br>4. Pruebas unitarias con archivos dummy en HDFS local (MiniCluster).                                     | 10 h           | EMR listo (de P1) sólo para despliegue final                  | Fin del **Día 2 AM**: scripts validados en local/mini-cluster               |
| **P4 – Integración, QA & Observabilidad** | 1. ECS Fargate task-defs para las 4 imágenes, variables `KAFKA_BOOTSTRAP_SERVERS`.<br>2. MSK Connect: HDFS Sink config JSON y puesta en marcha.<br>3. Dashboards CloudWatch + Grafana (panel Chunks/min).<br>4. Guía de demo + lista de comandos de validación.              | 10 h           | Necesita:<br>• Images de P2 en ECR<br>• Cluster MSK/EMR de P1 | Fin del **Día 2 PM**: demo end-to-end pasa checklist                        |

---

#### **Secuencia sugerida (48 h)**

| Momento        | P1                                  | P2                                             | P3                                      | P4                                                  |
| -------------- | ----------------------------------- | ---------------------------------------------- | --------------------------------------- | --------------------------------------------------- |
| **Día 1 – AM** | Crea VPC, SG, MSK                   | Clona repo y limpia dependencias               | Esboza scripts Flink/Spark              | Prepara plantillas task-def y dashboard             |
| **Día 1 – PM** | Lanza EMR, habilita puertos         | Prueba local con Redpanda; sube imágenes a ECR | Ajusta esquemas Avro/JSON               | Diseña MSK Connect JSON; define métricas CloudWatch |
| **Día 2 – AM** | Configura roles IAM y topics en MSK | — (buffer / soporte)                           | Testea scripts en EMR (YARN)            | Despliega servicios en ECS, crea connector          |
| **Día 2 – PM** | Asiste a P3/P4 si surgen permisos   | Smoke-test en ECS                              | Exporta checkpoints, ajusta paralelismo | Corre demo end-to-end, documenta pasos              |

---

### Claves para que **“una persona adapte el código en 2 días”** sin bloquear al resto

* P2 trabaja **100 % en local** (Docker + Redpanda + MinIO) hasta tener contenedores estables; no necesita esperar infraestructura.
* P1 y P4 pueden aprovisionar y desplegar **place-holders** (imágenes «hello-world») mientras P2 termina. Sustituir imagen es inmediato.
* P3 usa **MiniCluster** de Flink y `spark-local` para validar lógica; sólo el **deploy final** requiere EMR.
* Contrato de mensajes (esquemas Avro) se define el primer día en un archivo compartido (`/schema/*.avsc`) para evitar sorpresas.

---

### Riesgos y mitigaciones

| Riesgo                                    | Impacto               | Mitigación                                                                     |
| ----------------------------------------- | --------------------- | ------------------------------------------------------------------------------ |
| Tiempo de aprovisionar EMR/MSK (> 30 min) | Atraso P3 despliegue  | P3 desarrolla con MiniCluster; despliegue final ocurre tarde Día 2.            |
| Errores en IAM (access denied)            | Bloqueo Flink o Sink  | P1 y P4 mantienen plantilla de políticas probadas; P1 disponible para hot-fix. |
| Desfase de versiones Kafka-client         | Workers no conectan   | P2 fija `confluent-kafka==2.4.*`, mismo release que MSK 3.6.                   |
| Costos EMR altos                          | Exceso de presupuesto | P1 habilita **auto-terminate** y usa instancias spot para core.                |

---

Con esta asignación cada persona tiene **tareas autocontenidas**, revisables al final de cada bloque de medio día. Ningún paso crítico del Día 2 depende de código que aún no exista: cuando P2 termina *images*, P4 sólo reemplaza tags y relanza servicios. Resultado: implementación completa en 48 h con el menor acoplamiento posible.
