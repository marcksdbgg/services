### **Paso 1: Configurar Prometheus para Recolectar las Métricas**

Prometheus necesita saber dónde encontrar los endpoints `/metrics` de tus servicios. Esto se hace a través de su archivo de configuración, típicamente llamado `prometheus.yml`.

**Análisis del Código:**
Basado en el código que proporcionaste en la solicitud anterior:
- **`ingest-service`**: Expone las métricas en su puerto principal (el que usa FastAPI/Uvicorn), que asumiremos es **puerto 8000**, bajo la ruta `/metrics`.
- **`docproc-service`**: Inicia un servidor de métricas independiente en el **puerto 8003**. (`start_http_server(8003)`)
- **`embedding-service`**: Inicia un servidor de métricas independiente en el **puerto 8002**. (`start_http_server(8002)`)
- **`api-gateway`**: En el código proporcionado, este servicio no fue instrumentado con métricas de Prometheus. Actúa como un proxy simple y su monitoreo se centrará en los logs y, potencialmente, en métricas de latencia del Ingest Service que él llama. Por lo tanto, no lo incluiremos en la configuración de scrapeo de Prometheus.

#### **Archivo `prometheus.yml`**

Debes crear o editar el archivo `prometheus.yml` en tu nodo maestro de EMR donde se ejecuta Prometheus. El contenido debería ser el siguiente:

```yaml
# prometheus.yml
# Configuración global
global:
  scrape_interval: 15s # Con qué frecuencia recolectar métricas. 15 segundos es un buen valor por defecto.
  evaluation_interval: 15s # Con qué frecuencia evaluar las reglas de alerta.

# Reglas de alerta (opcional, puedes dejarlo vacío por ahora)
# rule_files:
#   - "first_rules.yml"
#   - "second_rules.yml"

# Configuración de los "scrape jobs" - A quién monitorear.
# Aquí es donde le decimos a Prometheus dónde encontrar tus servicios.
scrape_configs:
  # Job para el propio Prometheus. Útil para monitorear su estado.
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  # Job para el Ingest Service
  - job_name: "ingest-service"
    metrics_path: /metrics # La ruta donde se exponen las métricas
    static_configs:
      - targets: ["localhost:8000"] # El host y puerto donde corre ingest-service
        labels:
          service: "ingest"

  # Job para el Document Processing Service
  - job_name: "docproc-service"
    static_configs:
      - targets: ["localhost:8003"] # El host y puerto que definiste para sus métricas
        labels:
          service: "docproc"

  # Job para el Embedding Service
  - job_name: "embedding-service"
    static_configs:
      - targets: ["localhost:8002"] # El host y puerto que definiste para sus métricas
        labels:
          service: "embedding"

```

**Instrucciones:**

1.  **Guarda** este contenido en el archivo `prometheus.yml`.
2.  **Reinicia** el servicio de Prometheus en tu nodo maestro para que cargue la nueva configuración. La forma de reiniciarlo depende de cómo lo hayas instalado (Systemd, Docker, etc.), pero generalmente es un comando como `sudo systemctl restart prometheus` o `docker restart <prometheus_container_id>`.
3.  **Verifica**: Abre un navegador y ve a `http://<IP_EMR_MASTERNODE>:9090/targets`. Deberías ver tus tres servicios (`ingest-service`, `docproc-service`, `embedding-service`) con el estado "UP" en color verde. Si alguno está "DOWN", revisa que el servicio esté corriendo y que el puerto en `prometheus.yml` sea el correcto.

---

### **Paso 2: Conectar Prometheus como Data Source en Grafana**

1.  Abre Grafana en tu navegador, que generalmente corre en `http://<IP_EMR_MASTERNODE>:3000`.
2.  Ve a **Configuration** (el ícono de engranaje ⚙️ en el menú de la izquierda).
3.  Haz clic en **Data Sources**.
4.  Haz clic en **Add data source**.
5.  Selecciona **Prometheus** de la lista.
6.  En la sección **HTTP**, en el campo **URL**, escribe la dirección de tu Prometheus. Como Grafana corre en el mismo nodo, la dirección es `http://localhost:9090`.
7.  Deja el resto de las opciones por defecto y haz clic en el botón **Save & test** al final. Debería aparecer un mensaje verde confirmando que el "Data source is working".

---

### **Paso 3: Crear Dashboards en Grafana para Visualizar las Métricas**

Ahora viene la parte más visual. Crearemos un Dashboard con paneles para cada servicio.

1.  Haz clic en el **signo más (+)** en el menú de la izquierda y selecciona **Dashboard**.
2.  Haz clic en **Add visualization**. Esto te llevará a la pantalla de creación de paneles.
3.  Asegúrate de que tu Data Source de Prometheus esté seleccionado en la parte superior.

A continuación, te proporciono las queries (en lenguaje PromQL) para visualizar cada una de las métricas que definiste.

#### **Dashboard para `ingest-service`**

**Panel 1: Tasa de Documentos Subidos (Éxito vs. Error)**

*   **Título del Panel:** Tasa de Ingesta de Documentos
*   **Tipo de Visualización:** Time series
*   **Query A:**
    ```promql
    sum(rate(ingest_uploads_total{status="success"}[5m])) by (content_type)
    ```
    *   En la pestaña "Legend", puedes poner `{{content_type}} - Success` para una leyenda clara.
*   **Query B:** (Haz clic en `+ Query` para añadir otra)
    ```promql
    sum(rate(ingest_uploads_total{status=~"error_.*"}[5m])) by (content_type)
    ```
    *   En la pestaña "Legend", puedes poner `{{content_type}} - Error`

**Panel 2: Latencia de Peticiones (95th Percentile)**

*   **Título del Panel:** Latencia de Petición (p95)
*   **Tipo de Visualización:** Time series
*   **Unidad (Unit):** En "Standard options" a la derecha, busca "Unit" y selecciona `Time > seconds (s)`.
*   **Query:**
    ```promql
    histogram_quantile(0.95, sum(rate(ingest_request_processing_duration_seconds_bucket[5m])) by (le, path))
    ```
    *   Esto muestra la latencia por debajo de la cual se encuentran el 95% de las peticiones, agrupado por la ruta del endpoint.

**Panel 3: Tasa de Mensajes Producidos a Kafka**

*   **Título del Panel:** Tasa de Producción a Kafka (Ingest)
*   **Tipo de Visualización:** Time series
*   **Query:**
    ```promql
    sum(rate(ingest_kafka_messages_produced_total[5m])) by (topic, status)
    ```
    *   Esto te mostrará en tiempo real cuántos mensajes por segundo se están produciendo correctamente (o fallando) en cada topic.

---

#### **Dashboard para `docproc-service`**

**Panel 1: Throughput de Procesamiento de Documentos**

*   **Título del Panel:** Documentos Procesados por Minuto
*   **Tipo de Visualización:** Time series
*   **Query:**
    ```promql
    sum(rate(docproc_processing_duration_seconds_count[1m]) * 60) by (content_type)
    ```
    *   La métrica `_count` de un histograma nos dice cuántas observaciones (en este caso, cuántos documentos procesados) ha habido. La `rate` nos da el valor por segundo, y multiplicamos por 60 para obtenerlo por minuto.

**Panel 2: Duración del Procesamiento por Tipo de Documento (p95)**

*   **Título del Panel:** Duración del Procesamiento (p95)
*   **Tipo de Visualización:** Time series
*   **Unidad:** `Time > seconds (s)`
*   **Query:**
    ```promql
    histogram_quantile(0.95, sum(rate(docproc_processing_duration_seconds_bucket[5m])) by (le, content_type))
    ```
    *   Ideal para ver si un tipo de archivo (ej. PDF) tarda significativamente más que otros en procesarse.

**Panel 3: Total de Chunks Generados**

*   **Título del Panel:** Tasa de Chunks Producidos
*   **Tipo de Visualización:** Time series
*   **Query:**
    ```promql
    sum(rate(docproc_chunks_produced_total[5m])) by (company_id)
    ```

**Panel 4: Tasa de Errores de Procesamiento**

*   **Título del Panel:** Tasa de Errores de Procesamiento (DocProc)
*   **Tipo de Visualización:** Time series
*   **Query:**
    ```promql
    sum(rate(docproc_processing_errors_total[5m])) by (stage)
    ```
    *   Muy útil para diagnosticar dónde están fallando los documentos (en validación, descarga S3, etc.).

---

#### **Dashboard para `embedding-service`**

**Panel 1: Throughput del Worker de Embeddings**

*   **Título del Panel:** Chunks Procesados para Embedding por Minuto
*   **Tipo de Visualización:** Stat (un número grande y claro) o Time Series si quieres ver la tendencia.
*   **Unidad:** Standard > short, con "ops/min" como sufijo.
*   **Query para Stat:**
    ```promql
    sum(rate(embedding_batch_processing_duration_seconds_count[1m]) * 60)
    ```
    *   Esto cuenta el número de lotes (batches) procesados por minuto.

*   **Query para Time Series (Chunks/segundo):**
    ```promql
    sum(rate(embedding_texts_processed_total[5m])) by (company_id)
    ```

**Panel 2: Latencia de la API de OpenAI (p95)**

*   **Título del Panel:** Latencia API OpenAI (p95)
*   **Tipo de Visualización:** Time series
*   **Unidad:** `Time > seconds (s)`
*   **Query:**
    ```promql
    histogram_quantile(0.95, sum(rate(embedding_openai_api_duration_seconds_bucket[5m])) by (le, model_name))
    ```

**Panel 3: Tasa de Errores de la API de OpenAI**

*   **Título del Panel:** Errores de API OpenAI
*   **Tipo de Visualización:** Time series
*   **Query:**
    ```promql
    sum(rate(embedding_openai_api_errors_total[5m])) by (error_type)
    ```
    *   Te permite distinguir rápidamente entre errores de autenticación, rate limits, etc.

**Panel 4: Total de Mensajes Consumidos vs. Producidos (Kafka)**

*   **Título del Panel:** Flujo de Mensajes Kafka (Embedding)
*   **Tipo de Visualización:** Time series
*   **Query A (Consumidos):**
    ```promql
    sum(rate(embedding_messages_consumed_total[5m])) by (topic)
    ```
    *   Leyenda: `Consumidos de {{topic}}`
*   **Query B (Producidos):** (clic `+ Query`)
    ```promql
    sum(rate(embedding_kafka_messages_produced_total[5m])) by (topic)
    ```
    *   Leyenda: `Producidos a {{topic}}`
    *   En un estado ideal, la tasa de `chunks.processed` consumidos debería ser similar a la tasa de `embeddings.ready` producidos. Cualquier discrepancia grande indica un problema.

**¡No olvides guardar tu dashboard!** Dale un nombre descriptivo como "Vis