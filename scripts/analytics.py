# FILE: snslytics_rt.py
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import KafkaSource, KafkaOffsetsInitializer
from pyflink.common.serialization import SimpleStringSchema
from pyflink.common.typeinfo import Types
from pyflink.common import WatermarkStrategy
from pyflink.datastream.window import TumblingProcessingTimeWindows
from pyflink.common.time import Time
import json
import os

def main():
    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(1)

    # Variables de configuración desde el entorno o valores por defecto
    KAFKA_BROKERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    INPUT_TOPIC = os.getenv("FLINK_INPUT_TOPIC", "embeddings.ready")
    CONSUMER_GROUP = "flink-realtime-analytics-group"
    
    print(f"INFO: Conectando a Kafka en '{KAFKA_BROKERS}' y consumiendo del topic '{INPUT_TOPIC}'")

    # 🔌 Configura la fuente Kafka para leer del topic 'embeddings.ready'
    kafka_source = KafkaSource.builder() \
        .set_bootstrap_servers(KAFKA_BROKERS) \
        .set_group_id(CONSUMER_GROUP) \
        .set_topics(INPUT_TOPIC) \
        .set_value_only_deserializer(SimpleStringSchema()) \
        .set_starting_offsets(KafkaOffsetsInitializer.latest()) \
        .build()

    # Fuente de datos desde Kafka
    ds = env.from_source(
        source=kafka_source,
        watermark_strategy=WatermarkStrategy.no_watermarks(),
        source_name="Kafka Embeddings Source"
    )

    # 1. Parsear el JSON del mensaje de Kafka
    # Payload esperado: {"chunk_id": ..., "document_id": ..., "company_id": ..., "vector": [...]}
    def parse_kafka_message(line):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            # En caso de un mensaje malformado, lo ignoramos
            return None

    parsed_stream = ds.map(parse_kafka_message, output_type=Types.MAP(Types.STRING(), Types.STRING())) \
                      .filter(lambda x: x is not None)

    # 2. Extraer el 'company_id' y mapear a una tupla (company_id, 1) para conteo
    company_counts = parsed_stream.map(
        lambda data: (data.get("company_id", "unknown_company"), 1),
        output_type=Types.TUPLE([Types.STRING(), Types.INT()])
    )

    # 3. Agrupar por clave (company_id) y aplicar una ventana de 1 minuto
    # Se usa TumblingProcessingTimeWindows porque no dependemos de un timestamp en el evento
    windowed_counts = company_counts \
        .key_by(lambda x: x[0]) \
        .window(TumblingProcessingTimeWindows.of(Time.minutes(1))) \
        .reduce(lambda a, b: (a[0], a[1] + b[1]))

    # 4. Imprimir los resultados a los logs del TaskManager de Flink
    # Este es el "resultado en tiempo real" que le mostrarás al docente
    windowed_counts.print()

    # Establece el nombre del Job que se verá en el Dashboard de Flink
    env.execute("RealTimeChunkCountPerCompany")

if __name__ == "__main__":
    main()