"""Deterministic test implementations; never imported by a production configuration."""


def ingest_bank_document(document, path):
    return {
        "document_date": None,
        "chunks": [
            {"page": page, "text": f"Synthetic OCR page {page}"}
            for page in range(1, document["page_count"] + 1)
        ],
    }
