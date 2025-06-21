# File: app/services/kafka_producer.py
import json
import structlog
from confluent_kafka import Producer, KafkaException
from typing import Optional

from app.core.config import settings

log = structlog.get_logger(__name__)

class KafkaProducerClient:
    """A client to produce messages to a Kafka topic."""

    def __init__(self):
        producer_config = {
            'bootstrap.servers': settings.KAFKA_BOOTSTRAP_SERVERS,
            'acks': settings.KAFKA_PRODUCER_ACKS,
            'linger.ms': settings.KAFKA_PRODUCER_LINGER_MS,
            # Para AWS MSK con IAM Auth, se necesitarían más configuraciones.
            # 'security.protocol': 'SASL_SSL',
            # 'sasl.mechanisms': 'AWS_MSK_IAM',
            # Para este proyecto universitario, se asume una red simple sin IAM auth.
        }
        self.producer = Producer(producer_config)
        self.log = log.bind(component="KafkaProducerClient")
        self.log.info("Kafka producer initialized.", config=producer_config)

    def _delivery_report(self, err, msg):
        """Callback called once for each message produced."""
        if err is not None:
            self.log.error(f"Message delivery failed to topic '{msg.topic()}'", key=msg.key().decode('utf-8'), error=str(err))
        else:
            self.log.info(f"Message delivered to topic '{msg.topic()}'", key=msg.key().decode('utf-8'), partition=msg.partition(), offset=msg.offset())

    def produce(self, topic: str, key: str, value: dict):
        """
        Produces a message to the specified Kafka topic.

        Args:
            topic: The target Kafka topic.
            key: The message key (e.g., document_id).
            value: The message payload as a dictionary.
        """
        try:
            self.producer.produce(
                topic=topic,
                key=key.encode('utf-8'),
                value=json.dumps(value).encode('utf-8'),
                callback=self._delivery_report
            )
            # poll() es crucial para que se envíen los callbacks de entrega
            # y se procesen los mensajes en el buffer del productor.
            self.producer.poll(0)
        except BufferError:
            self.log.error(
                "Kafka producer's local queue is full. Messages may be dropped.",
                topic=topic
            )
            self.producer.flush() # Intenta forzar el envío
        except KafkaException as e:
            self.log.exception("Failed to produce message to Kafka", topic=topic, error=str(e))
            raise
        except Exception as e:
            self.log.exception("An unexpected error occurred in Kafka producer", topic=topic, error=str(e))
            raise
    
    def flush(self):
        """Waits for all outstanding messages to be delivered."""
        self.log.info("Flushing Kafka producer...")
        self.producer.flush()
        self.log.info("Kafka producer flushed.")