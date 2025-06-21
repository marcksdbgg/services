# File: app/services/kafka_clients.py
import json
import structlog
from confluent_kafka import Consumer, Producer, KafkaError, KafkaException
from typing import Optional, Generator, Any, Dict

from app.core.config import settings

log = structlog.get_logger(__name__)

# --- Kafka Producer ---
class KafkaProducerClient:
    def __init__(self):
        producer_config = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'acks': 'all',
        }
        self.producer = Producer(producer_config)
        self.log = log.bind(component="KafkaProducerClient")

    def _delivery_report(self, err, msg):
        if err is not None:
            self.log.error(f"Message delivery failed to topic '{msg.topic()}'", error=str(err))
        else:
            self.log.debug(f"Message delivered to {msg.topic()} [{msg.partition()}]")

    def produce(self, topic: str, key: str, value: Dict[str, Any]):
        try:
            self.producer.produce(
                topic,
                key=key.encode('utf-8'),
                value=json.dumps(value).encode('utf-8'),
                callback=self._delivery_report
            )
        except KafkaException as e:
            self.log.exception("Failed to produce message", error=str(e))
            raise

    def flush(self, timeout: float = 10.0):
        self.log.info(f"Flushing producer with a timeout of {timeout}s...")
        self.producer.flush(timeout)
        self.log.info("Producer flushed.")

# --- Kafka Consumer ---
class KafkaConsumerClient:
    def __init__(self, topics: list[str]):
        consumer_config = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'group.id': settings.KAFKA_CONSUMER_GROUP_ID,
            'auto.offset.reset': settings.KAFKA_AUTO_OFFSET_RESET,
            'enable.auto.commit': False,  # Commits manuales para procesar "at-least-once"
        }
        self.consumer = Consumer(consumer_config)
        self.consumer.subscribe(topics)
        self.log = log.bind(component="KafkaConsumerClient", topics=topics)

    def consume(self) -> Generator[Any, None, None]:
        self.log.info("Starting Kafka consumer loop...")
        try:
            while True:
                msg = self.consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        self.log.error("Kafka consumer error", error=msg.error())
                        raise KafkaException(msg.error())
                
                # Mensaje válido recibido, lo entregamos para procesar
                yield msg
                
                # Una vez procesado (fuera de esta función), se hace commit.
                # Aquí simulamos el commit después de yield
                self.consumer.commit(asynchronous=True)
                
        except KeyboardInterrupt:
            self.log.info("Consumer loop interrupted by user.")
        finally:
            self.close()

    def commit(self, message: Any):
        """Commits the offset for the given message."""
        self.consumer.commit(message=message, asynchronous=False)

    def close(self):
        self.log.info("Closing Kafka consumer...")
        self.consumer.close()