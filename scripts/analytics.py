#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real-Time chunk counter por company_id.
- Lee de Kafka (topic embeddings.ready)
- Agrega en ventanas de 30 segundos
- Publica el resultado en un nuevo topic 'analytics.flink'
"""
import json
import os
import logging
import sys
import time

from pyflink.common import Time as FlinkTime, WatermarkStrategy, Types, Encoder
from pyflink.common.restart_strategy import RestartStrategies
from pyflink.common.time import Duration
from pyflink.datastream import StreamExecutionEnvironment, DeliveryGuarantee
from pyflink.datastream.window import TumblingProcessingTimeWindows
from pyflink.datastream.connectors.kafka import (
    KafkaSource, KafkaSink, KafkaOffsetsInitializer
)
from pyflink.common.serialization import SimpleStringSchema

# --- Configuración desde variables de entorno ---
KAFKA_BROKERS   = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
INPUT_TOPIC     = os.getenv("FLINK_INPUT_TOPIC", "embeddings.ready")
OUTPUT_TOPIC    = os.getenv("FLINK_OUTPUT_TOPIC", "analytics.flink")
CONSUMER_GROUP  = os.getenv("FLINK_CONSUMER_GROUP", "flink-rt-analytics-group")

# --- Logging ---
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
LOG = logging.getLogger(__name__)

def define_workflow(env: StreamExecutionEnvironment):
    """Define el pipeline de Flink."""
    LOG.info(f"Conectando a Kafka: {KAFKA_BROKERS}")
    LOG.info(f"Leyendo del topic: {INPUT_TOPIC}, Grupo: {CONSUMER_GROUP}")
    LOG.info(f"Escribiendo al topic: {OUTPUT_TOPIC}")

    # --- 1. FUENTE KAFKA ---
    kafka_source = KafkaSource.builder() \
        .set_bootstrap_servers(KAFKA_BROKERS) \
        .set_group_id(CONSUMER_GROUP) \
        .set_topics(INPUT_TOPIC) \
        .set_starting_offsets(KafkaOffsetsInitializer.latest()) \
        .set_value_only_deserializer(SimpleStringSchema()) \
        .build()

    stream = env.from_source(
        kafka_source, WatermarkStrategy.no_watermarks(), "KafkaSource_Embeddings"
    )

    # --- 2. LÓGICA DE TRANSFORMACIÓN ---
    def safe_parse(line):
        try:
            data = json.loads(line)
            if 'company_id' in data:
                return (data['company_id'], 1)
        except (json.JSONDecodeError, TypeError):
            LOG.warning(f"Mensaje inválido o malformado omitido: {line[:100]}")
        return ("error_parsing", 1) # Contar errores de parsing también

    company_counts = stream \
        .map(safe_parse, output_type=Types.TUPLE([Types.STRING(), Types.INT()])) \
        .key_by(lambda x: x[0]) \
        .window(TumblingProcessingTimeWindows.of(FlinkTime.seconds(30))) \
        .reduce(lambda a, b: (a[0], a[1] + b[1]))

    # --- 3. SINK KAFKA ---
    def to_json_output(data):
        company_id, count = data
        return json.dumps({
            "company_id": company_id,
            "chunk_count_30s": count,
            "timestamp_utc": time.time()
        })

    output_stream = company_counts.map(to_json_output, output_type=Types.STRING())

    # Imprimir en logs para debugging
    output_stream.print()

    kafka_sink = KafkaSink.builder() \
        .set_bootstrap_servers(KAFKA_BROKERS) \
        .set_record_serializer(Encoder.simple_string_encoder()) \
        .set_delivery_guarantee(DeliveryGuarantee.AT_LEAST_ONCE) \
        .set_topic(OUTPUT_TOPIC) \
        .build()
        
    output_stream.sink_to(kafka_sink)


def run_job():
    """Configura el entorno y ejecuta el job."""
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(1)  # Mantener simple para depuración
    env.enable_checkpointing(30000) # Checkpoint cada 30 segundos
    env.set_restart_strategy(RestartStrategies.fixed_delay_restart(
        3, FlinkTime.seconds(10)
    ))
    define_workflow(env)
    env.execute("RealTimeChunkCountPerCompany")


if __name__ == "__main__":
    run_job()