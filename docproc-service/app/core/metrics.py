# File: docproc-service/app/core/metrics.py
from prometheus_client import Counter, Histogram

MESSAGES_CONSUMED_TOTAL = Counter(
    "docproc_messages_consumed_total",
    "Total number of Kafka messages consumed.",
    ["topic", "status"]
)

PROCESSING_DURATION_SECONDS = Histogram(
    "docproc_processing_duration_seconds",
    "Time taken to process a single document.",
    ["company_id", "content_type"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60]
)

CHUNKS_PRODUCED_TOTAL = Counter(
    "docproc_chunks_produced_total",
    "Total number of chunks produced to Kafka.",
    ["company_id", "content_type"]
)

PROCESSING_ERRORS_TOTAL = Counter(
    "docproc_processing_errors_total",
    "Total number of errors during processing.",
    ["stage"]
)

S3_DOWNLOAD_DURATION_SECONDS = Histogram(
    "docproc_s3_download_duration_seconds",
    "Time taken to download a file from S3.",
    buckets=[0.1, 0.5, 1, 2, 5, 10]
)

KAFKA_MESSAGES_PRODUCED_TOTAL = Counter(
    "docproc_kafka_messages_produced_total",
    "Total number of messages produced to Kafka.",
    ["topic", "status"]
)