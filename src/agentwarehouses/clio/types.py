"""Clio type definitions — facets, clusters, config, and results.

Adapted from OpenClio's opencliotypes.py for document analysis.
Uses Pydantic instead of dataclasses for validation consistency
with the rest of agentwarehouses.
"""
from __future__ import annotations

import numpy as np
from numpy import typing as npt
from pydantic import BaseModel, Field

# Type alias for embedding arrays
EmbeddingArray = npt.NDArray[np.float32]


class Facet(BaseModel):
    """A dimension of analysis extracted from each document.

    Facets are the core abstraction in Clio — each represents a question
    asked about every document (e.g. "what topic?", "what complexity?").

    Mirrors OpenClio's Facet dataclass but adds Pydantic validation.
    """

    model_config = {"frozen": True, "arbitrary_types_allowed": True}

    name: str = Field(description="Short identifier (e.g. 'topic', 'complexity')")
    question: str = Field(default="", description="Question to extract this facet from a document")
    prefill: str = Field(default="", description="Prefill text for LLM response")
    summary_criteria: str | None = Field(
        default=None,
        description="Criteria for summarizing clusters of this facet. If set, cluster hierarchy is built.",
    )
    numeric_range: tuple[int, int] | None = Field(
        default=None,
        description="If set, facet values are numeric in this range (e.g. (1, 5) for complexity)",
    )

    def should_cluster(self) -> bool:
        """Whether this facet should have a cluster hierarchy built."""
        return self.summary_criteria is not None


class FacetValue(BaseModel):
    """Extracted facet value for a single document."""

    facet_name: str
    value: str


class DocumentFacets(BaseModel):
    """All extracted facet values for a single document."""

    doc_index: int = Field(description="Index into the source document list")
    url: str = Field(default="")
    title: str = Field(default="")
    facet_values: list[FacetValue] = Field(default_factory=list)


class Cluster(BaseModel):
    """A group of semantically similar documents or sub-clusters.

    Mirrors OpenClio's ConversationCluster but for documents.
    Clusters form a tree: leaf clusters contain document indices,
    parent clusters contain child clusters.
    """

    model_config = {"arbitrary_types_allowed": True}

    facet_name: str = Field(description="Which facet this cluster is for")
    name: str = Field(description="Short cluster label")
    summary: str = Field(default="", description="Longer description of cluster contents")
    doc_indices: list[int] = Field(default_factory=list, description="Indices of documents in this cluster")
    children: list[Cluster] | None = Field(default=None, description="Child clusters (None for leaf)")
    level: int = Field(default=0, description="Depth in hierarchy (0 = leaf)")

    def is_leaf(self) -> bool:
        return self.children is None or len(self.children) == 0

    def doc_count(self) -> int:
        if self.is_leaf():
            return len(self.doc_indices)
        return sum(c.doc_count() for c in (self.children or []))


class ClioConfig(BaseModel):
    """Configuration for the Clio pipeline.

    Mirrors OpenClio's OpenClioConfig with sensible defaults for
    document analysis (vs conversation analysis).
    """

    model_config = {"arbitrary_types_allowed": True}

    # Reproducibility
    seed: int = Field(default=42, description="Random seed for k-means and sampling")

    # Clustering
    n_base_clusters_ratio: float = Field(
        default=0.1,
        description="Ratio of documents to base clusters (e.g. 0.1 = 1 cluster per 10 docs)",
    )
    min_base_clusters: int = Field(default=3, description="Minimum number of base clusters")
    max_base_clusters: int = Field(default=500, description="Maximum number of base clusters")
    min_top_level_size: int = Field(default=3, description="Stop hierarchy when this few clusters remain")

    # Sampling for LLM summarization
    n_samples_per_cluster: int = Field(default=5, description="Docs to sample per cluster for naming")
    n_samples_outside_cluster: int = Field(default=3, description="Contrast docs from other clusters")

    # Hierarchy
    hierarchy_reduction_ratio: float = Field(
        default=0.3,
        description="Target ratio of parent clusters to children at each level",
    )

    # Embedding
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence-transformer model for embeddings",
    )
    embedding_batch_size: int = Field(default=256, description="Batch size for embedding generation")

    # LLM
    llm_model: str = Field(default="claude-sonnet-4-20250514", description="Model for facet extraction/summarization")
    llm_batch_size: int = Field(default=50, description="Batch size for LLM calls")
    max_doc_tokens: int = Field(default=4000, description="Max tokens per document sent to LLM")
    temperature: float = Field(default=0.3, description="LLM temperature for extraction")

    # Output
    output_dir: str = Field(default="output/clio", description="Where to write results")
    verbose: bool = Field(default=True, description="Log progress")

    def n_base_clusters(self, n_docs: int) -> int:
        """Calculate number of base clusters for a given document count."""
        n = max(self.min_base_clusters, int(n_docs * self.n_base_clusters_ratio))
        return min(n, self.max_base_clusters, n_docs)


class ClioResults(BaseModel):
    """Complete output of a Clio pipeline run."""

    model_config = {"arbitrary_types_allowed": True}

    facets: list[Facet]
    doc_facets: list[DocumentFacets]
    base_clusters: dict[str, list[Cluster]] = Field(
        default_factory=dict,
        description="Base clusters keyed by facet name",
    )
    root_clusters: dict[str, list[Cluster]] = Field(
        default_factory=dict,
        description="Top-level hierarchy keyed by facet name",
    )
    n_documents: int = 0
