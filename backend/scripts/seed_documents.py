"""Seed script: ingests demo documents into the RAG store.

Usage:
    python scripts/seed_documents.py --count 12
"""
import argparse


def main():
    parser = argparse.ArgumentParser(description="Seed RAG store with demo documents")
    parser.add_argument("--count", type=int, default=12, help="Number of documents to ingest")
    args = parser.parse_args()
    print(f"Would ingest {args.count} documents (not yet implemented)")


if __name__ == "__main__":
    main()
