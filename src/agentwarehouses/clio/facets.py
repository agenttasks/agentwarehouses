"""Default facet definitions for document analysis.

These facets mirror the conversation facets from Anthropic's Clio paper
(Section 3.1) but adapted for documentation pages:
  - topic: What is the main subject?
  - doc_type: What kind of document is this?
  - complexity: How technical is the content?
  - audience: Who is the target reader?
"""

from __future__ import annotations

from agentwarehouses.clio.types import Facet

# Primary facet — used for main cluster hierarchy
TOPIC_FACET = Facet(
    name="topic",
    question="What is the main topic or subject of this documentation page?",
    prefill="The main topic is",
    summary_criteria="the common topic or subject area",
)

DOC_TYPE_FACET = Facet(
    name="doc_type",
    question=(
        "What type of document is this? "
        "(e.g. tutorial, API reference, guide, conceptual explanation, changelog, blog post)"
    ),
    prefill="This is a",
    summary_criteria="the common document type",
)

COMPLEXITY_FACET = Facet(
    name="complexity",
    question=(
        "How technically complex is this document? 1=beginner-friendly overview, 5=advanced implementation details"
    ),
    prefill="",
    numeric_range=(1, 5),
)

AUDIENCE_FACET = Facet(
    name="audience",
    question=(
        "Who is the target audience for this document? "
        "(e.g. beginners, intermediate developers, ML researchers, security engineers)"
    ),
    prefill="The target audience is",
    summary_criteria=None,  # No cluster hierarchy for audience
)

# Default facet set for document analysis
DEFAULT_FACETS: list[Facet] = [
    TOPIC_FACET,
    DOC_TYPE_FACET,
    COMPLEXITY_FACET,
    AUDIENCE_FACET,
]

# Facets that get cluster hierarchies built
CLUSTERED_FACETS: list[Facet] = [f for f in DEFAULT_FACETS if f.should_cluster()]
