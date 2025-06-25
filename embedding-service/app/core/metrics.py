# File: embedding-service/app/core/metrics.py
from prometheus_client import Counter, Histogram

MESSAGES_CONSUMED_TOTAL = Counter(
    "embedding_messages_consumed_total",
    "Total number of Kafka messages consumed from a batch.",
    ["topic", "partition"]
)

BATCH_PROCESSING_DURATION_SECONDS = Histogram(
    "embedding_batch_processing_duration_seconds",
    "Time taken to process a batch of texts.",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30]
)

TEXTS_PROCESSED_TOTAL = Counter(
    "embedding_texts_processed_total",
    "Total number of individual texts processed for embedding.",
    ["company_id"]
)

OPENAI_API_DURATION_SECONDS = Histogram(
    "embedding_openai_api_duration_seconds",
    "Duration of calls to the OpenAI Embedding API.",
    ["model_name"]
)

OPENAI_API_ERRORS_TOTAL = Counter(
    "embedding_openai_api_errors_total",
    "Total number of errors from the OpenAI API.",
    ["model_name", "error_type"]
)

KAFKA_MESSAGES_PRODUCED_TOTAL = Counter(
    "embedding_kafka_messages_produced_total",
    "Total number of embedding messages produced to Kafka.",
    ["topic", "status"]
)