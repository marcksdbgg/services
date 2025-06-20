### **Plan de Refactorización para Integrar Kafka, Flink y HDFS en AWS**

#### **1. Arquitectura General Propuesta en AWS**

Para mantener la simplicidad y cumplir con los requisitos, la arquitectura será la siguiente:

1.  **VPC (Virtual Private Cloud):** Una red privada para que todos nuestros servicios se comuniquen de forma segura.
2.  **Amazon MSK (Managed Streaming for Kafka):** Será nuestro clúster de Kafka gestionado. Actuará como el sistema nervioso central de la aplicación, desacoplando los microservicios.
3.  **Amazon EMR (Elastic MapReduce):** Desplegaremos un clúster EMR que incluirá:
    *   **HDFS:** Para cumplir el requisito de almacenamiento distribuido.
    *   **Apache Flink:** Para el procesamiento de datos en streaming (tiempo real).
    *   **Apache Spark:** Para el trabajo de procesamiento en batch (nocturno).
4.  **Amazon S3:** Reemplazará a Google Cloud Storage (GCS) como el almacén de objetos para los archivos originales. Es el estándar en AWS y se integra perfectamente con EMR.
5.  **Amazon ECS on Fargate:** Para desplegar tus microservicios (`api-gateway`, `ingest`, `docproc`, `embedding`). Fargate es la opción "serverless" para contenedores, lo que significa que no tienes que gestionar servidores EC2. Es más simple que EKS (Kubernetes) y perfecto para este caso.
6.  **Kafka Connect (MSK Connect):** Usaremos un conector HDFS Sink para que, de forma automática, los mensajes de los topics de Kafka se guarden en HDFS en el clúster de EMR.

#### **2. Diseño de Topics de Kafka**

Los microservicios se comunicarán a través de los siguientes topics en MSK. Esto cumple el requisito de tener múltiples productores y consumidores.

| Topic              | Partición por | Payload (JSON)                                | Productor             | Consumidor(es)                                            |
| ------------------ | ------------- | --------------------------------------------- | --------------------- | --------------------------------------------------------- |
| `documents.raw`    | `document_id` | `{ "document_id", "company_id", "s3_path" }`    | `ingest-service`      | `docproc-service`, `HDFS Sink Connector`                  |
| `chunks.processed` | `document_id` | `{ "chunk_id", "document_id", "text", "page" }` | `docproc-service`     | `embedding-service`, `HDFS Sink Connector`                |
| `embeddings.ready` | `document_id` | `{ "chunk_id", "document_id", "vector" }`       | `embedding-service`   | `Job de Flink` (en EMR), `HDFS Sink Connector`            |
| `analytics.flink`  | `company_id`  | `{ "timestamp", "company_id", "count" }`        | `Job de Flink` (en EMR) | (Para la demo, se puede leer con un consumidor de consola) |

---

### **3. Plan de Refactorización por Microservicio**

#### **API Gateway (`api-gateway`)**

**Objetivo:** Simplificarlo al máximo para que sea solo un punto de entrada para subir y ver archivos.

*   **Autenticación y Usuarios:**
    *   **Eliminar por completo la lógica de autenticación.** No más JWT, no más llamadas a PostgreSQL para validar usuarios.
    *   Eliminar el directorio `app/auth` y el `user_router.py`.
    *   Eliminar las dependencias de `python-jose`, `passlib` y `asyncpg` del `pyproject.toml`.
    *   El header `X-Company-ID` se puede seguir usando, pero en la demo se enviará con un valor fijo (ej. `"default-company-uuid"`) desde el frontend o Postman.
*   **Endpoints:**
    *   **Mantener `POST /ingest/upload`:** Este seguirá siendo el endpoint para subir archivos. Su lógica será simplemente reenviar el archivo al `ingest-service`.
    *   **Mantener `GET /ingest/status` y `GET /ingest/status/{document_id}`:** Para poder ver el estado de los documentos subidos. Reenviarán la petición al `ingest-service`.
    *   **Eliminar todos los demás endpoints:** `/login`, `/users/me/ensure-company`, etc.
*   **Base de Datos:**
    *   Eliminar toda la conexión y lógica de `postgres_client.py`. Este servicio ya no necesitará conectarse a la base de datos.
*   **Despliegue:**
    *   Se desplegará como un servicio en **ECS Fargate**.

#### **Ingest Service (`ingest-service`)**

**Objetivo:** Transformarlo en un productor de Kafka que inicia el pipeline.

*   **Lógica de Ingesta (`/upload`):**
    *   **Reemplazar GCS por S3:** Cambiar la lógica de `gcs_client.py` por un `s3_client.py` que use `boto3` para subir el archivo original a un bucket de S3. La ruta puede ser similar: `{company_id}/{document_id}/{filename}`.
    *   **Eliminar Celery:** La llamada a la tarea Celery (`process_document_standalone.delay`) será reemplazada.
    *   **Producir a Kafka:** Después de subir el archivo a S3 y crear el registro en PostgreSQL con estado `uploaded`, el servicio producirá un mensaje en el topic **`documents.raw`**. El mensaje contendrá `{ "document_id", "company_id", "s3_path" }`.
*   **Lógica del Worker (Celery):**
    *   **Eliminar por completo la tarea `process_document.py`**. Toda la orquestación (llamar a `docproc`, `embedding`, `milvus`) ya no es responsabilidad de este servicio.
*   **Dependencias:**
    *   Añadir una librería de Kafka como `confluent-kafka-python`.
    *   Añadir `boto3` para S3.
    *   Eliminar `celery` y `redis`.
*   **Base de Datos:**
    *   Se mantiene la conexión a PostgreSQL para registrar los metadatos del documento, pero se simplifica enormemente (ya no necesita la tabla `document_chunks`). La conexión del worker (`SQLAlchemy`) ya no es necesaria.
*   **Despliegue:**
    *   Se desplegará como un servicio en **ECS Fargate**.

#### **Document Processing Service (`docproc-service`)**

**Objetivo:** Convertirlo en un consumidor de Kafka que procesa archivos y produce los chunks a otro topic.

*   **Modo de Ejecución:**
    *   **Eliminar la API FastAPI:** Este servicio ya no necesita un endpoint HTTP. Se convertirá en un script de larga duración (un "worker") que se ejecuta en un contenedor.
    *   El punto de entrada del contenedor (`Dockerfile` `CMD`) ejecutará un script Python que inicia un consumidor de Kafka.
*   **Lógica del Consumidor:**
    1.  Iniciar un bucle que consuma mensajes del topic **`documents.raw`**.
    2.  Por cada mensaje, extraer el `s3_path`.
    3.  Descargar el archivo correspondiente desde S3 a una ubicación temporal.
    4.  Utilizar la lógica de extracción y chunking existente (`ProcessDocumentUseCase`) para obtener los fragmentos de texto.
    5.  Para cada chunk generado, producir un mensaje en el topic **`chunks.processed`**. El payload será `{ "chunk_id", "document_id", "text", "page" }`.
*   **Dependencias:**
    *   Añadir `confluent-kafka-python` y `boto3`.
    *   Se pueden eliminar `fastapi` y `uvicorn` si se quita la API por completo.
*   **Despliegue:**
    *   Se desplegará como un servicio en **ECS Fargate**, corriendo como una tarea de fondo (worker).

#### **Embedding Service (`embedding-service`)**

**Objetivo:** Convertirlo en un consumidor de Kafka que genera embeddings y los produce al siguiente topic.

*   **Modo de Ejecución:**
    *   Similar a `docproc-service`, se eliminará la API FastAPI y se convertirá en un worker consumidor de Kafka.
*   **Lógica del Consumidor:**
    1.  Iniciar un bucle que consuma mensajes del topic **`chunks.processed`**.
    2.  Por cada mensaje, extraer el `text`.
    3.  Usar la lógica existente (`OpenAIAdapter`) para generar el vector de embedding.
    4.  Producir un mensaje en el topic **`embeddings.ready`**. El payload será `{ "chunk_id", "document_id", "vector" }`.
*   **Dependencias:**
    *   Añadir `confluent-kafka-python`.
    *   Se pueden eliminar `fastapi` y `uvicorn`.
*   **Despliegue:**
    *   Se desplegará como un servicio en **ECS Fargate**, corriendo como una tarea de fondo (worker).

---

### **4. Jobs de Procesamiento en EMR**

Estos son los nuevos componentes que deberás crear para cumplir los requisitos de streaming y batch.

#### **Job de Flink (Análisis en Tiempo Real)**

*   **Propósito:** Contar cuántos chunks se han procesado por compañía en ventanas de 1 minuto.
*   **Lógica (PyFlink):**
    1.  Leer datos del topic de Kafka **`embeddings.ready`**.
    2.  Definir una ventana de tiempo (ej. `TumblingEventTimeWindows` de 1 minuto).
    3.  Agrupar por `company_id` y contar los eventos (`COUNT(*)`) dentro de cada ventana.
    4.  Producir el resultado agregado al topic **`analytics.flink`**.
*   **Despliegue:** Se empaqueta como un script de PyFlink y se envía al clúster de EMR para ejecución continua (modo `per-job` en YARN).

#### **Job de Spark (Análisis en Batch)**

*   **Propósito:** Generar un reporte diario del total de chunks procesados por documento.
*   **Lógica (PySpark):**
    1.  Leer los datos del día anterior desde **HDFS**. El HDFS Sink Connector habrá guardado los datos de los topics en directorios particionados por fecha.
    2.  Leer los datos del directorio correspondiente a `embeddings.ready`.
    3.  Realizar una agregación `GROUP BY document_id, company_id` y `COUNT(*)`.
    4.  Escribir el resultado como un archivo Parquet de vuelta en HDFS (o en S3 para consultarlo con Athena).
*   **Despliegue:** Se empaqueta como un script de PySpark y se ejecuta una vez al día usando "EMR Steps".

---

### **5. Pasos para el Despliegue en AWS (Resumen)**

1.  **Preparar Código:** Realizar todos los cambios de refactorización mencionados anteriormente en cada microservicio. Actualizar los `Dockerfile` para que los workers ejecuten los scripts de consumidor en lugar de `uvicorn`.
2.  **Configurar AWS:**
    *   Crear una VPC.
    *   Crear un bucket en S3.
    *   Configurar un clúster de Amazon MSK.
    *   Configurar un clúster de Amazon EMR con Flink y Spark.
3.  **Desplegar Microservicios:**
    *   Construir y subir las imágenes Docker a Amazon ECR (Elastic Container Registry).
    *   Crear definiciones de tareas en ECS para cada uno de los 4 microservicios.
    *   Crear servicios en ECS (usando el tipo de lanzamiento Fargate) para exponer la API (`api-gateway`) y para ejecutar los workers (`ingest`, `docproc`, `embedding`).
4.  **Configurar Conectores:**
    *   Configurar un MSK Connect con el HDFS Sink Connector para que los datos de los topics `documents.raw`, `chunks.processed`, y `embeddings.ready` se almacenen en el HDFS del clúster EMR.
5.  **Ejecutar Jobs en EMR:**
    *   Enviar el job de Flink al clúster de EMR para su ejecución continua.
    *   Configurar un EMR Step para que ejecute el job de Spark batch diariamente.

Con este plan, cumplirás todos los requisitos del curso de una manera estructurada, moderna y utilizando las herramientas adecuadas para cada tarea, manteniendo la complejidad bajo control. ¡Mucho éxito en la implementación