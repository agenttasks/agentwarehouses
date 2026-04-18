"""Clio — privacy-preserving document analysis pipeline for agentwarehouses.

Adapted from Anthropic's Clio system (arxiv.org/abs/2412.13678) and
Phylliida/OpenClio. Analyzes crawled documentation pages and research
session content through a five-stage pipeline:

  1. Facet extraction  — identify topic, type, complexity from each doc
  2. Embedding         — sentence-transformer vectors for semantic similarity
  3. Base clustering   — k-means on embeddings to form initial groups
  4. Hierarchy         — recursive clustering to build navigable tree
  5. Summarization     — LLM-generated cluster names and descriptions

Unlike the original Clio (which analyzes user conversations), this version
operates on public documentation pages — no PII privacy layer needed, but
the pipeline architecture is preserved for consistency.

Usage:
    from agentwarehouses.clio import ClioConfig, ClioPipeline
    pipeline = ClioPipeline(config)
    results = pipeline.run(documents)
"""
