# File: embedding-service/app/main.py
import sys
import json
import asyncio
import structlog
from typing import Any, List, Generator, Dict

# Configurar logging primero que nada
from app.core.logging_config import setup_logging
setup_logging()

from app.core.config import settings
from app.services.kafka_clients import KafkaConsumerClient, KafkaProducerClient, KafkaError
from app.infrastructure.embedding_models.openai_adapter import OpenAIAdapter
from app.application.use_cases.embed_texts_use_case import EmbedTextsUseCase

log = structlog.get_logger(__name__)

def main():
    """Punto de entrada principal para el worker de embeddings."""
    log.info("Initializing Embedding Worker...")
    try:
        openai_adapter = OpenAIAdapter()
        asyncio.run(openai_adapter.initialize_model())
        use_case = EmbedTextsUseCase(embedding_model=openai_adapter)
        
        consumer = KafkaConsumerClient(topics=[settings.KAFKA_INPUT_TOPIC])
        producer = KafkaProducerClient()
    except Exception as e:
        log.critical("Failed to initialize worker dependencies", error=str(e), exc_info=True)
        sys.exit(1)

    log.info("Worker initialized successfully. Starting consumption loop...")
    try:
        for message_batch in batch_consumer(consumer, batch_size=50, batch_timeout_s=5):
            process_message_batch(message_batch, use_case, producer)
            consumer.commit(message=message_batch[-1])
    except KeyboardInterrupt:
        log.info("Shutdown signal received.")
    except Exception as e:
        log.critical("Critical error in consumer loop.", error=str(e), exc_info=True)
    finally:
        log.info("Closing worker resources...")
        consumer.close()
        producer.flush()
        log.info("Worker shut down gracefully.")

def batch_consumer(consumer: KafkaConsumerClient, batch_size: int, batch_timeout_s: int) -> Generator[List[Any], None, None]:
    """Agrupa mensajes de Kafka en lotes para un procesamiento eficiente."""
    batch = []
    while True:
        msg = consumer.consumer.poll(timeout=batch_timeout_s)
        if msg is None:
            if batch: yield batch; batch = []
            continue
        if msg.error():
            if msg.error().code() != KafkaError._PARTITION_EOF:
                log.error("Kafka consumer poll error", error=msg.error())
            continue
        batch.append(msg)
        if len(batch) >= batch_size:
            yield batch; batch = []

def process_message_batch(message_batch: List[Any], use_case: EmbedTextsUseCase, producer: KafkaProducerClient):
    batch_log = log.bind(batch_size=len(message_batch))
    texts_to_embed, metadata_list = [], []
    for msg in message_batch:
        try:
            event_data = json.loads(msg.value().decode('utf-8'))
            if "text" in event_data and event_data["text"] is not None:
                texts_to_embed.append(event_data["text"])
                metadata_list.append(event_data)
            else:
                batch_log.warning("Skipping message with missing or null 'text' field", offset=msg.offset())
        except json.JSONDecodeError:
            batch_log.error("Failed to decode Kafka message", offset=msg.offset())

    if not texts_to_embed:
        batch_log.debug("No valid texts to embed in this batch.")
        return

    try:
        embeddings, _ = asyncio.run(use_case.execute(texts_to_embed))
        if len(embeddings) != len(metadata_list):
            batch_log.error("Mismatch in embedding results count.", expected=len(metadata_list), got=len(embeddings))
            return

        for i, vector in enumerate(embeddings):
            meta = metadata_list[i]
            output_payload = {
                "chunk_id": meta.get("chunk_id"),
                "document_id": meta.get("document_id"),
                "company_id": meta.get("company_id"), 
                "vector": vector,
            }
            producer.produce(settings.KAFKA_OUTPUT_TOPIC, key=str(meta.get("document_id")), value=output_payload)
        
        batch_log.info(f"Processed and produced {len(embeddings)} embeddings.")
    except Exception as e:
        batch_log.error("Unhandled error processing batch", error=str(e), exc_info=True)

if __name__ == "__main__":
    main()