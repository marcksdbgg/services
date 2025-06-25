# Sistema de Procesamiento de Documentos Asíncrono en AWS

Este proyecto implementa un pipeline de procesamiento de documentos distribuido y asíncrono utilizando microservicios, Kafka, S3 y EMR (Flink/HDFS) en AWS. El sistema está diseñado para ser escalable, resiliente y observable.

## 1. Arquitectura General

El flujo de procesamiento de documentos sigue los siguientes pasos:

1.  **Ingesta**: Un usuario sube un documento a través del `ingest-service`.
2.  **Almacenamiento y Evento**: El servicio guarda el archivo original en un bucket de **Amazon S3** y produce un evento en el topic de Kafka `documents.raw`. Este evento contiene metadatos sobre el archivo, incluyendo su ubicación en S3.
3.  **Procesamiento de Documento**: El `docproc-service`, un consumidor de Kafka, recibe el evento, descarga el archivo de S3, extrae el texto y lo divide en fragmentos (chunks).
4.  **Producción de Chunks**: Por cada chunk generado, `docproc-service` produce un nuevo evento al topic `chunks.processed`.
5.  **Generación de Embeddings**: El `embedding-service`, otro consumidor, toma cada chunk de texto, utiliza la API de OpenAI para generar un vector de embedding y produce el resultado al topic `embeddings.ready`.
6.  **Análisis y Almacenamiento Final**:
    *   Un conector **HDFS Sink** (a través de MSK Connect) consume de todos los topics y persiste los datos en **HDFS** en el clúster de EMR para análisis batch.
    *   Un job de **Apache Flink** consume del topic `embeddings.ready` para realizar análisis en tiempo real (streaming).

 <!-- Reemplazar con un diagrama real si es posible -->

### Componentes Tecnológicos Clave
- **Amazon S3**: Almacenamiento de objetos para los documentos originales.
- **Amazon MSK (Managed Streaming for Kafka)**: Broker de mensajería para la comunicación asíncrona entre microservicios.
- **Microservicios en Python**: Desplegados como contenedores (ej. en ECS/Fargate), cada uno con una responsabilidad única.
- **Amazon EMR (Elastic MapReduce)**: Clúster gestionado para ejecutar Apache Flink (streaming) y Apache Spark (batch), utilizando HDFS para el almacenamiento persistente.
- **Prometheus y Grafana**: Sistema de monitoreo y visualización. Cada microservicio expone un endpoint `/metrics` que Prometheus puede scrapear.

---

## 2. Topics de Kafka

La comunicación se basa en los siguientes topics de Kafka:

| Topic              | Partición por | Payload (Ejemplo JSON)                                   | Productor             | Consumidor(es)                                           |
| ------------------ | ------------- | -------------------------------------------------------- | --------------------- | -------------------------------------------------------- |
| `documents.raw`    | `document_id` | `{ "document_id", "company_id", "s3_path" }`             | `ingest-service`      | `docproc-service`, HDFS Sink                             |
| `chunks.processed` | `document_id` | `{ "chunk_id", "document_id", "text", "page" }`          | `docproc-service`     | `embedding-service`, HDFS Sink                           |
| `embeddings.ready` | `document_id` | `{ "chunk_id", "document_id", "vector" }`                | `embedding-service`   | Job de Flink, HDFS Sink                                  |
| `analytics.flink`  | `company_id`  | `{ "timestamp", "company_id", "metric_value" }`          | Job de Flink          | Consumidores de analítica (ej. dashboards)                 |

---

## 3. Microservicios

### 3.1. Ingest Service (`ingest-service`)

- **Propósito**: Punto de entrada del sistema. Recibe los documentos, los almacena en S3 y notifica al resto del sistema a través de Kafka.
- **Tecnología**: Python, FastAPI.
- **Endpoints**:
    - `POST /api/v1/upload`: Endpoint principal para subir un archivo. Requiere el archivo (`multipart/form-data`) y un header `X-Company-ID`.
    - `GET /health`: Endpoint de health check.
    - `GET /metrics`: Expone las métricas en formato Prometheus.
- **Produce a**: `documents.raw`
- **Métricas Clave (expuestas en `http://localhost:80/metrics` por defecto)**:
    - `ingest_uploads_total`: Contador de archivos subidos. (Labels: `company_id`, `content_type`, `status`)
    - `ingest_upload_file_size_bytes`: Histograma del tamaño de los archivos.
    - `ingest_request_processing_duration_seconds`: Histograma de la latencia de las peticiones.
    - `ingest_kafka_messages_produced_total`: Contador de mensajes producidos a Kafka. (Labels: `topic`, `status`)

### 3.2. Document Processing Service (`docproc-service`)

- **Propósito**: Consumir eventos de nuevos documentos, descargarlos de S3, extraer su contenido textual y dividirlos en chunks.
- **Tecnología**: Python (Worker de larga duración).
- **Consume de**: `documents.raw`
- **Produce a**: `chunks.processed`
- **Endpoints**:
    - `GET /metrics`: Expone las métricas en formato Prometheus en un puerto dedicado.
- **Métricas Clave (expuestas en `http://localhost:8001/metrics` por defecto)**:
    - `docproc_messages_consumed_total`: Contador de mensajes consumidos. (Labels: `topic`, `status`)
    - `docproc_processing_duration_seconds`: Histograma del tiempo de procesamiento por documento. (Labels: `company_id`, `content_type`)
    - `docproc_chunks_produced_total`: Contador de chunks generados. (Labels: `company_id`, `content_type`)
    - `docproc_processing_errors_total`: Contador de errores por etapa de procesamiento. (Labels: `stage`)
    - `docproc_s3_download_duration_seconds`: Histograma del tiempo de descarga desde S3.

### 3.3. Embedding Service (`embedding-service`)

- **Propósito**: Consumir los chunks de texto, generar embeddings vectoriales usando un modelo externo (OpenAI) y producir el resultado.
- **Tecnología**: Python (Worker de larga duración).
- **Consume de**: `chunks.processed`
- **Produce a**: `embeddings.ready`
- **Endpoints**:
    - `GET /metrics`: Expone las métricas en formato Prometheus en un puerto dedicado.
- **Métricas Clave (expuestas en `http://localhost:8002/metrics` por defecto)**:
    - `embedding_messages_consumed_total`: Contador de chunks recibidos.
    - `embedding_batch_processing_duration_seconds`: Histograma del tiempo de procesamiento por lote.
    - `embedding_texts_processed_total`: Contador del total de textos convertidos a embeddings. (Labels: `company_id`)
    - `embedding_openai_api_duration_seconds`: Histograma de la latencia de las llamadas a la API de OpenAI.
    - `embedding_openai_api_errors_total`: Contador de errores de la API de OpenAI. (Labels: `model_name`, `error_type`)

---

## 4. Configuración y Ejecución

Cada microservicio es una aplicación de Python que utiliza `Poetry` para la gestión de dependencias.

### Requisitos
- Python 3.10+
- Poetry
- Un broker de Kafka accesible.
- Credenciales de AWS configuradas para acceso a S3 (si no se usa acceso público).

### Ejecución Local (Ejemplo para un worker)
1.  **Navegar al directorio del servicio**:
    ```bash
    cd embedding-service
    ```
2.  **Crear un archivo `.env`** con las variables de entorno necesarias (ver `app/core/config.py` en cada servicio para la lista completa):
    ```env
    # Ejemplo para embedding-service/.env
    EMBEDDING_KAFKA_BOOTSTRAP_SERVERS="kafka:9092"
    EMBEDDING_OPENAI_API_KEY="sk-..."
    ```
3.  **Instalar dependencias**:
    ```bash
    poetry install
    ```
4.  **Ejecutar el worker**:
    ```bash
    poetry run python app/main.py
    ```
Para el `ingest-service` (FastAPI), la ejecución se haría con un servidor ASGI como Uvicorn:
```bash
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000