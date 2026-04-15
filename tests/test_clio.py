"""Tests for the Clio document analysis pipeline — types, facets, prompts, and pipeline stages."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from agentwarehouses.clio.facets import CLUSTERED_FACETS, DEFAULT_FACETS, TOPIC_FACET
from agentwarehouses.clio.pipeline import ClioPipeline
from agentwarehouses.clio.prompts import CLUSTER_NAME, FACET_EXTRACTION, HIERARCHY_NAMES
from agentwarehouses.clio.types import (
    ClioConfig,
    ClioResults,
    Cluster,
    DocumentFacets,
    Facet,
    FacetValue,
)

# ── Sample data ──────────────────────────────────────────────────────

SAMPLE_DOCS = [
    {
        "url": "https://example.com/docs/getting-started",
        "title": "Getting Started",
        "body_markdown": ("# Getting Started\n\nInstall the CLI and start coding.\n\n## Prerequisites\n\nPython 3.11+"),
    },
    {
        "url": "https://example.com/docs/api-reference",
        "title": "API Reference",
        "body_markdown": (
            "# API Reference\n\n## Messages\n\n"
            "Create a message with `client.messages.create()`."
            "\n\n## Parameters\n\n- model: string"
        ),
    },
    {
        "url": "https://example.com/docs/security",
        "title": "Security Guide",
        "body_markdown": (
            "# Security\n\n## Authentication\n\nUse API keys for auth.\n\n## Best Practices\n\nRotate keys regularly."
        ),
    },
]


# ── Types ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestFacet:
    def test_should_cluster_with_criteria(self) -> None:
        facet = Facet(name="topic", question="What?", summary_criteria="the topic")
        assert facet.should_cluster() is True

    def test_should_not_cluster_without_criteria(self) -> None:
        facet = Facet(name="audience", question="Who?")
        assert facet.should_cluster() is False

    def test_frozen(self) -> None:
        facet = Facet(name="test", question="What?")
        with pytest.raises(Exception):  # Pydantic frozen validation error
            facet.name = "changed"  # type: ignore[misc]


@pytest.mark.unit
class TestCluster:
    def test_is_leaf_no_children(self) -> None:
        c = Cluster(facet_name="topic", name="Test", doc_indices=[0, 1, 2])
        assert c.is_leaf() is True

    def test_is_leaf_empty_children(self) -> None:
        c = Cluster(facet_name="topic", name="Test", children=[])
        assert c.is_leaf() is True

    def test_is_not_leaf(self) -> None:
        child = Cluster(facet_name="topic", name="Child", doc_indices=[0])
        parent = Cluster(facet_name="topic", name="Parent", children=[child])
        assert parent.is_leaf() is False

    def test_doc_count_leaf(self) -> None:
        c = Cluster(facet_name="topic", name="Test", doc_indices=[0, 1, 2])
        assert c.doc_count() == 3

    def test_doc_count_parent(self) -> None:
        c1 = Cluster(facet_name="topic", name="A", doc_indices=[0, 1])
        c2 = Cluster(facet_name="topic", name="B", doc_indices=[2, 3, 4])
        parent = Cluster(facet_name="topic", name="P", children=[c1, c2])
        assert parent.doc_count() == 5


@pytest.mark.unit
class TestClioConfig:
    def test_defaults(self) -> None:
        cfg = ClioConfig()
        assert cfg.seed == 42
        assert cfg.embedding_model == "all-MiniLM-L6-v2"
        assert cfg.verbose is True

    def test_n_base_clusters_ratio(self) -> None:
        cfg = ClioConfig(n_base_clusters_ratio=0.1, min_base_clusters=3, max_base_clusters=100)
        assert cfg.n_base_clusters(100) == 10
        assert cfg.n_base_clusters(10) == 3  # min
        assert cfg.n_base_clusters(2000) == 100  # max

    def test_n_base_clusters_small_dataset(self) -> None:
        cfg = ClioConfig(min_base_clusters=3)
        assert cfg.n_base_clusters(5) == 3  # min but capped at n_docs
        assert cfg.n_base_clusters(2) == 2  # can't have more clusters than docs


@pytest.mark.unit
class TestDocumentFacets:
    def test_construction(self) -> None:
        df = DocumentFacets(
            doc_index=0,
            url="https://example.com",
            title="Test",
            facet_values=[FacetValue(facet_name="topic", value="testing")],
        )
        assert df.doc_index == 0
        assert len(df.facet_values) == 1
        assert df.facet_values[0].value == "testing"


@pytest.mark.unit
class TestClioResults:
    def test_construction(self) -> None:
        results = ClioResults(
            facets=[TOPIC_FACET],
            doc_facets=[],
            n_documents=0,
        )
        assert len(results.facets) == 1
        assert results.n_documents == 0
        assert results.base_clusters == {}


# ── Facets ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDefaultFacets:
    def test_four_default_facets(self) -> None:
        assert len(DEFAULT_FACETS) == 4

    def test_facet_names(self) -> None:
        names = {f.name for f in DEFAULT_FACETS}
        assert names == {"topic", "doc_type", "complexity", "audience"}

    def test_clustered_facets(self) -> None:
        assert len(CLUSTERED_FACETS) == 2
        names = {f.name for f in CLUSTERED_FACETS}
        assert names == {"topic", "doc_type"}

    def test_complexity_is_numeric(self) -> None:
        complexity = next(f for f in DEFAULT_FACETS if f.name == "complexity")
        assert complexity.numeric_range == (1, 5)

    def test_topic_has_summary_criteria(self) -> None:
        assert TOPIC_FACET.summary_criteria is not None


# ── Prompts ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestPrompts:
    def test_facet_extraction_has_placeholders(self) -> None:
        assert "{document}" in FACET_EXTRACTION
        assert "{question}" in FACET_EXTRACTION
        assert "{facet_name}" in FACET_EXTRACTION

    def test_facet_extraction_renders(self) -> None:
        rendered = FACET_EXTRACTION.format(
            document="# Test\n\nContent",
            question="What is the topic?",
            facet_name="topic",
        )
        assert "# Test" in rendered
        assert "What is the topic?" in rendered
        assert "<topic>" in rendered

    def test_cluster_name_has_placeholders(self) -> None:
        assert "{inside_samples}" in CLUSTER_NAME
        assert "{outside_samples}" in CLUSTER_NAME

    def test_hierarchy_names_has_placeholders(self) -> None:
        assert "{n_clusters}" in HIERARCHY_NAMES
        assert "{n_target}" in HIERARCHY_NAMES
        assert "{cluster_list}" in HIERARCHY_NAMES


# ── Pipeline ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestPipelineExtractTag:
    def test_extracts_tag(self) -> None:
        text = "prefix <name>My Cluster</name> suffix"
        assert ClioPipeline._extract_tag(text, "name") == "My Cluster"

    def test_extracts_multiline_tag(self) -> None:
        text = "<summary>\nLine 1\nLine 2\n</summary>"
        assert ClioPipeline._extract_tag(text, "summary") == "Line 1\nLine 2"

    def test_returns_none_for_missing_tag(self) -> None:
        assert ClioPipeline._extract_tag("no tags here", "name") is None

    def test_strips_whitespace(self) -> None:
        text = "<name>  padded  </name>"
        assert ClioPipeline._extract_tag(text, "name") == "padded"


@pytest.mark.unit
class TestPipelineInit:
    def test_default_config(self) -> None:
        pipeline = ClioPipeline()
        assert pipeline.config.seed == 42
        assert len(pipeline.facets) == 4

    def test_custom_config(self) -> None:
        cfg = ClioConfig(seed=99, verbose=False)
        pipeline = ClioPipeline(config=cfg)
        assert pipeline.config.seed == 99

    def test_custom_facets(self) -> None:
        custom = [Facet(name="custom", question="test?", summary_criteria="test")]
        pipeline = ClioPipeline(facets=custom)
        assert len(pipeline.facets) == 1


@pytest.mark.integration
class TestPipelineFormatSamples:
    def test_format_samples(self) -> None:
        pipeline = ClioPipeline()
        doc_facets = [
            DocumentFacets(
                doc_index=0,
                url="https://a.com",
                title="Doc A",
                facet_values=[FacetValue(facet_name="topic", value="Getting started guide")],
            ),
            DocumentFacets(
                doc_index=1,
                url="https://b.com",
                title="Doc B",
                facet_values=[FacetValue(facet_name="topic", value="API reference")],
            ),
        ]
        result = pipeline._format_samples(doc_facets, "topic", [0, 1])
        assert "[Doc A]" in result
        assert "Getting started guide" in result
        assert "[Doc B]" in result

    def test_format_samples_missing_facet(self) -> None:
        pipeline = ClioPipeline()
        doc_facets = [
            DocumentFacets(doc_index=0, title="No Facets", facet_values=[]),
        ]
        result = pipeline._format_samples(doc_facets, "topic", [0])
        assert "[No Facets]" in result


@pytest.mark.integration
class TestPipelineExtractFacets:
    def test_extract_facets_calls_llm(self) -> None:
        pipeline = ClioPipeline(config=ClioConfig(verbose=False))
        pipeline._call_llm = MagicMock(return_value="The topic is testing")  # type: ignore[assignment]

        results = pipeline.extract_facets(SAMPLE_DOCS[:1])

        assert len(results) == 1
        assert results[0].doc_index == 0
        assert results[0].url == "https://example.com/docs/getting-started"
        assert len(results[0].facet_values) == 4  # 4 default facets

    def test_extract_facets_extracts_tagged_values(self) -> None:
        pipeline = ClioPipeline(
            config=ClioConfig(verbose=False),
            facets=[Facet(name="topic", question="What?")],
        )
        pipeline._call_llm = MagicMock(return_value="<topic>Machine learning</topic>")  # type: ignore[assignment]

        results = pipeline.extract_facets(SAMPLE_DOCS[:1])
        assert results[0].facet_values[0].value == "Machine learning"


@pytest.mark.integration
class TestPipelineBaseCluster:
    def test_base_cluster_creates_clusters(self) -> None:
        pipeline = ClioPipeline(
            config=ClioConfig(verbose=False, min_base_clusters=2, max_base_clusters=2),
            facets=[Facet(name="topic", question="What?", summary_criteria="topic")],
        )
        pipeline._call_llm = MagicMock(return_value="<name>Test Cluster</name>\n<summary>A test</summary>")  # type: ignore[assignment]

        doc_facets = [
            DocumentFacets(
                doc_index=i,
                title=f"Doc {i}",
                facet_values=[FacetValue(facet_name="topic", value=f"Value {i}")],
            )
            for i in range(10)
        ]

        # Create fake embeddings
        rng = np.random.RandomState(42)
        embeddings = {"topic": rng.randn(10, 8).astype(np.float32)}

        clusters = pipeline.base_cluster(doc_facets, embeddings)
        assert "topic" in clusters
        assert len(clusters["topic"]) == 2
        total_docs = sum(c.doc_count() for c in clusters["topic"])
        assert total_docs == 10
