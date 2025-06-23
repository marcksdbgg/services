### **`big_data_pipeline.md`**

# Plan de Implementación: Componentes de Big Data (Flink, Spark, HDFS)

## 0. Arquitectura de Despliegue Simplificada (EMR + EC2)

Dado que no se utilizará Amazon MSK y que Kafka se ha instalado manualmente dentro del clúster de EMR, la arquitectura de despliegue se simplifica de la siguiente manera:

1.  **Clúster Amazon EMR (Plano de Datos):**
    *   Este es el corazón del sistema de Big Data.
    *   **Servicios Activos:** HDFS (para almacenamiento), YARN (gestor de recursos), Apache Flink, Apache Spark, Zookeeper y **Apache Kafka** (instalado manualmente).
    *   **Rol:** Almacena los datos en HDFS y ejecuta los jobs de procesamiento en streaming (Flink) y batch (Spark). Actúa como el bróker de mensajería (Kafka).

2.  **Instancia Amazon EC2 (Plano de Aplicaciones):**
    *   Para simplificar, los cuatro microservicios de Python (`api-gateway`, `ingest-service`, `docproc-service`, `embedding-service`) se desplegarán en una única instancia de Amazon EC2 (ej. `t3.medium`).
    *   **Rol:** Expone la API al exterior y ejecuta la lógica de negocio que produce y consume mensajes de Kafka. Esta instancia actuará como el "host de aplicaciones".

3.  **Comunicación (Networking):**
    *   Ambos, el clúster EMR y la instancia EC2, deben estar en la **misma VPC** para una comunicación eficiente.
    *   **Configuración Crítica:** Se deben configurar los **Security Groups**:
        *   El Security Group del **clúster EMR** debe permitir tráfico entrante en el puerto `9092` (Kafka) desde el Security Group (o la IP privada) de la **instancia EC2**.
        *   La **instancia EC2** debe tener acceso de salida a internet para descargar dependencias y para que el `embedding-service` contacte la API de OpenAI.

**VARIABLE DE ENTORNO CLAVE:** En los archivos `.env` de los microservicios en la instancia EC2, la variable `KAFKA_BOOTSTRAP_SERVERS` ya no será `localhost:9092`. Deberá apuntar a la IP privada del nodo maestro (o uno de los nodos core) del clúster EMR donde Kafka está escuchando.
*   `KAFKA_BOOTSTRAP_SERVERS="LA_IP_PRIVADA_DEL_NODO_EMR:9092"`

## 1. Revisión de la Arquitectura de Datos de Kafka

(Esta sección no cambia, los flujos lógicos permanecen igual)

Basado en el código implementado, los topics y payloads definitivos son:

| Topic | Clave de Partición | Payload (JSON) | Productor | Consumidor(es) Finales |
|---|---|---|---|---|
| `documents.raw` | `document_id` | `{"document_id", "company_id", "s3_path"}` | `ingest-service` | `docproc-service`, **Kafka Connect** |
| `chunks.processed`| `document_id` | `{"chunk_id", "document_id", "company_id", "text", "page"}` | `docproc-service` | `embedding-service`, **Kafka Connect** |
| `embeddings.ready`| `document_id` | `{"chunk_id", "document_id", "company_id", "vector"}` | `embedding-service` | **Job de Flink**, **Kafka Connect** |
| `analytics.flink` | `company_id`  | `{"window_start", "window_end", "company_id", "chunk_count"}` | **Job de Flink**  | (Consumidor de consola, dashboard) |

---

## 2. Tarea 1: Implementación del Job de Streaming con PyFlink

(El código del job no cambia, solo su entorno de ejecución)

**Objetivo:** Analizar en tiempo real los embeddings procesados para contar cuántos chunks por compañía se ingieren en ventanas de 1 minuto.

### **Código de Ejemplo (`flink_analytics_job.py`):**

```python
import os
from pyflink.common import SimpleStringSchema, Time
from pyflink.datastream import StreamExecutionEnvironment, TimeCharacteristic
from pyflink.datastream.connectors.kafka import FlinkKafkaConsumer, FlinkKafkaProducer
from pyflink.datastream.functions import ProcessWindowFunction
from pyflink.datastream.window import TumblingEventTimeWindows
from pyflink.common.watermark_strategy import WatermarkStrategy

import json
from datetime import datetime

class CountChunksInWindow(ProcessWindowFunction):
    """
    Función que cuenta los elementos en una ventana y formatea la salida.
    """
    def process(self, key, context, elements):
        count = sum(1 for _ in elements)
        window_start = datetime.fromtimestamp(context.window.start / 1000).isoformat()
        window_end = datetime.fromtimestamp(context.window.end / 1000).isoformat()
        
        result = {
            "window_start": window_start,
            "window_end": window_end,
            "company_id": key,
            "chunk_count": count
        }
        yield json.dumps(result)

def real_time_analytics_job():
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_stream_time_characteristic(TimeCharacteristic.EventTime)
    
    # --- Configuración de Kafka (leerá del EMR) ---
    kafka_brokers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092") # Flink y Kafka corren en la misma red de EMR
    input_topic = "embeddings.ready"
    output_topic = "analytics.flink"
    consumer_group = "flink_analytics_consumer"

    kafka_consumer = FlinkKafkaConsumer(
        topics=input_topic,
        deserialization_schema=SimpleStringSchema(),
        properties={'bootstrap.servers': kafka_brokers, 'group.id': consumer_group}
    )

    watermark_strategy = WatermarkStrategy.for_bounded_out_of_orderness(Time.seconds(5))

    data_stream = env.add_source(kafka_consumer).assign_timestamps_and_watermarks(watermark_strategy)

    parsed_stream = data_stream.map(lambda msg: json.loads(msg))

    aggregated_stream = parsed_stream \
        .key_by(lambda x: x['company_id']) \
        .window(TumblingEventTimeWindows.of(Time.minutes(1))) \
        .process(CountChunksInWindow())

    kafka_producer = FlinkKafkaProducer(
        topic=output_topic,
        serialization_schema=SimpleStringSchema(),
        producer_config={'bootstrap.servers': kafka_brokers}
    )

    aggregated_stream.add_sink(kafka_producer)
    
    env.execute("RealTimeChunkCountPerCompany")

if __name__ == '__main__':
    real_time_analytics_job()
```

**Despliegue en EMR:**
*   Copia este script a un nodo del clúster de EMR.
*   Ejecútalo usando `flink run -py flink_analytics_job.py`.

---

## 3. Tarea 2: Configuración de Persistencia en HDFS (Kafka Connect en EMR)

**Objetivo:** Almacenar de forma automática y duradera todos los eventos de Kafka en HDFS.

**Componente:** En lugar de MSK Connect, usaremos el framework de **Kafka Connect estándar**, que se ejecuta directamente en un nodo del clúster EMR.

**Configuración del Conector (`hdfs-sink-connector.properties`):**
(El contenido del archivo es el mismo, solo cambia cómo se ejecuta)
```properties
name=HdfsSinkAtenex
connector.class=io.confluent.connect.hdfs3.Hdfs3SinkConnector
tasks.max=2
topics=documents.raw,chunks.processed,embeddings.ready
hdfs.url=hdfs://localhost:8020
format.class=io.confluent.connect.hdfs3.format.json.JsonFormat
flush.size=1000
rotate.interval.ms=600000
partitioner.class=io.confluent.connect.storage.partitioner.TimeBasedPartitioner
path.format='year'=YYYY/'month'=MM/'day'=dd/'hour'=HH
locale=en_US
timezone=UTC
topics.dir=/atenex/kafka-landing
logs.dir=/atenex/kafka-connect/logs
```

**Ejecución en un nodo de EMR:**
1.  Asegúrate de haber instalado el conector HDFS 3 de Confluent en tu instalación de Kafka.
2.  Desde el directorio de Kafka, ejecuta el conector en modo distribuido:
    ```bash
    # La configuración de connect-distributed.properties debe apuntar a tu Kafka en localhost:9092
    ./bin/connect-distributed.sh config/connect-distributed.properties config/hdfs-sink-connector.properties
    ```

---

## 4. Tarea 3: Implementación del Job Batch con PySpark

(El código del job no cambia, solo su entorno de ejecución)

**Objetivo:** Generar un reporte diario que resuma el total de chunks procesados por documento y compañía.

### **Código de Ejemplo (`spark_batch_report_job.py`):**
```python
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, to_date
from datetime import datetime, timedelta

def daily_chunk_report_job():
    spark = SparkSession.builder.appName("AtenexDailyChunkReport").getOrCreate()
    yesterday = datetime.now() - timedelta(1)
    year, month, day = yesterday.strftime('%Y'), yesterday.strftime('%m'), yesterday.strftime('%d')
    
    # HDFS está en el mismo clúster, se puede usar 'localhost' o el nombre del master node
    input_path = f"hdfs:///atenex/kafka-landing/embeddings.ready/year={year}/month={month}/day={day}/*/"
    output_path = f"hdfs:///atenex/reports/daily_chunk_count/date={year}-{month}-{day}"

    print(f"Reading data from: {input_path}")
    print(f"Writing report to: {output_path}")

    try:
        df = spark.read.json(input_path)

        if "document_id" not in df.columns or "company_id" not in df.columns:
            print(f"Error: Required columns not found in {input_path}")
            df.printSchema()
            spark.stop()
            return

        report_df = df.groupBy("company_id", "document_id").count().withColumnRenamed("count", "total_chunks")
        report_df.write.mode("overwrite").parquet(output_path)
        print("Daily chunk report job completed successfully.")

    except Exception as e:
        print(f"An error occurred while reading from {input_path}: {e}")
        
    finally:
        spark.stop()

if __name__ == '__main__':
    daily_chunk_report_job()
```
**Ejecución en EMR:**
*   Copia el script a un nodo EMR.
*   Usa `spark-submit spark_batch_report_job.py` para ejecutarlo.
*   Automatiza la ejecución diaria usando **EMR Steps**.

---

## 5. Plan de Despliegue y Validación (Arquitectura Simplificada)

1.  **Preparar Entorno:**
    *   **Clúster EMR:** Lanza el clúster con Hadoop, Flink y Spark. Conéctate por SSH e instala Zookeeper y Kafka. Inicia ambos servicios y crea los topics necesarios.
    *   **Instancia EC2:** Lanza una instancia EC2 (ej. Amazon Linux 2, `t3.medium`). Instala Python 3.10+, Poetry y Git.
    *   **Configurar Red:** Ajusta los Security Groups para permitir que la EC2 se conecte al puerto 9092 del EMR.

2.  **Desplegar Microservicios en EC2:**
    *   Conéctate por SSH a la instancia EC2.
    *   Clona tu repositorio de microservicios: `git clone ...`.
    *   Para cada uno de los 4 servicios (`api-gateway`, `ingest-service`, etc.):
        *   `cd` al directorio del servicio.
        *   Crea un archivo `.env` y configura **`KAFKA_BOOTSTRAP_SERVERS`** con la IP privada del EMR y la **`OPENAI_API_KEY`** para el `embedding-service`.
        *   Instala dependencias: `poetry install`.
        *   Inicia el servicio en segundo plano (puedes usar `tmux` o `screen` para mantenerlos corriendo):
            *   `poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 &` (para api-gateway)
            *   `poetry run uvicorn app.main:app --host 0.0.0.0 --port 8001 &` (para ingest-service)
            *   `poetry run python -m app.main &` (para docproc y embedding)

3.  **Desplegar Componentes de Big Data en EMR:**
    *   Conéctate por SSH al clúster EMR.
    *   Inicia Kafka Connect para el HDFS Sink.
    *   Ejecuta el job de Flink (`flink run ...`).

4.  **Validación E2E:**
    *   Realiza una petición `POST` al endpoint `/upload` en la **IP pública de tu instancia EC2**, puerto 8000.
    *   Verifica los logs de cada microservicio en la instancia EC2.
    *   Verifica los topics de Kafka en el clúster EMR con un consumidor de consola.
    *   Verifica que los directorios y archivos JSON se creen en HDFS (`hdfs dfs -ls /atenex/kafka-landing/...`).
    *   Ejecuta manualmente el job de Spark y comprueba que el reporte en Parquet se haya creado en HDFS.