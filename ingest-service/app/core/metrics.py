# File: ingest-service/app/core/metrics.py
from prometheus_client import Counter, Histogram

# General metrics
UPLOADS_TOTAL = Counter(
    "ingest_uploads_total",
    "Total number of file upload attempts.",
    ["company_id", "content_type", "status"]
)

UPLOAD_FILE_SIZE_BYTES = Histogram(
    "ingest_upload_file_size_bytes",
    "Size of uploaded files in bytes.",
    ["company_id", "content_type"],
    buckets=(1024*10, 1024*50, 1024*100, 1024*512, 1024*1024, 1024*1024*5, 1024*1024*10)
)

REQUEST_PROCESSING_DURATION_SECONDS = Histogram(
    "ingest_request_processing_duration_seconds",
    "Time taken to process an HTTP request.",
    ["method", "path"]
)

# Kafka metrics
KAFKA_MESSAGES_PRODUCED_TOTAL = Counter(
    "ingest_kafka_messages_produced_total",
    "Total number of messages produced to Kafka.",
    ["topic", "status"]
)