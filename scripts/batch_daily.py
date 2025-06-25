# FILE: batch_daily.py
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count, date_sub, current_date
import os

def main():
    spark = SparkSession.builder \
        .appName("DailyDocumentChunkCountBatch") \
        .getOrCreate()
        
    print("INFO: Spark Session iniciada para el job batch diario.")

    # 📥 La ruta base en HDFS donde Kafka Connect está guardando los datos del topic.
    # Kafka Connect típicamente crea directorios con el nombre del topic.
    INPUT_PATH_BASE = os.getenv("HDFS_INPUT_PATH", "/topics/embeddings.ready")
    
    # 📤 La ruta en HDFS donde guardaremos los resultados del reporte.
    OUTPUT_PATH_BASE = os.getenv("HDFS_OUTPUT_PATH", "/user/hadoop/reports/daily_chunk_counts")
    
    # Se procesarán los datos del día de ayer
    processing_date = date_sub(current_date(), 1)
    
    # Kafka Connect particiona por fecha, el formato puede variar, pero uno común es 'year=YYYY/month=MM/day=DD'
    # Esta es una implementación genérica que asume que los datos están en un directorio del topic.
    # Para una demo, es más simple leer el directorio completo y luego filtrar por una columna de fecha si existe.
    # En un entorno de producción real, se leería directamente la partición de la fecha.
    print(f"INFO: Leyendo datos de HDFS desde: {INPUT_PATH_BASE}")

    # 🧾 Cargar TODOS los datos JSON del topic. Spark inferirá el esquema.
    try:
        df = spark.read.json(INPUT_PATH_BASE)
        df.printSchema() # Imprime el esquema para debugging
    except Exception as e:
        print(f"ERROR: No se pudieron leer los datos de HDFS desde '{INPUT_PATH_BASE}'. Asegúrate de que la ruta sea correcta y que haya datos. Error: {e}")
        spark.stop()
        return

    # AÑADIR UNA COLUMNA DE FECHA DE PROCESAMIENTO
    # Como los eventos no tienen timestamp, usamos la fecha actual como la de procesamiento del batch.
    # En un escenario real, Kafka Connect añadiría un timestamp o leeríamos de particiones.
    df = df.withColumn("processing_date", processing_date)

    # 📊 Agregación: Contar chunks por compañía y documento para esa fecha.
    result_df = df.groupBy("company_id", "document_id", "processing_date") \
                  .agg(count("*").alias("total_chunks_processed"))

    print(f"INFO: Datos agregados. Generando reporte para la fecha {processing_date.strftime('%Y-%m-%d') if hasattr(processing_date, 'strftime') else processing_date}")
    result_df.show() # Muestra los resultados en la consola

    # 💾 Guardar el resultado en HDFS como Parquet, particionado por la fecha del reporte.
    print(f"INFO: Guardando reporte en HDFS en: {OUTPUT_PATH_BASE}")
    result_df.write \
        .mode("overwrite") \
        .partitionBy("processing_date") \
        .parquet(OUTPUT_PATH_BASE)

    print("INFO: Job batch finalizado correctamente.")
    spark.stop()

if __name__ == "__main__":
    main()