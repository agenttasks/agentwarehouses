"""Clio prompt templates for each pipeline stage.

Adapted from OpenClio's prompts.py for document analysis.
Uses Jinja2-style string formatting for clarity.

Prompt design follows Anthropic's Clio paper (Section 3.1):
  - Facet extraction asks a specific question about each document
  - Cluster naming receives samples inside + outside the cluster
  - Hierarchy naming operates on cluster descriptions, not raw docs
"""
from __future__ import annotations

# ── Stage 1: Facet extraction ────────────────────────────────────────

FACET_EXTRACTION = """\
You are analyzing a documentation page. Answer the following question about this document.

<document>
{document}
</document>

Question: {question}

Respond with ONLY the answer in a single concise sentence. Do not include any preamble.
<{facet_name}>"""

FACET_EXTRACTION_NUMERIC = """\
You are analyzing a documentation page. Rate the following on a scale of {min_val} to {max_val}.

<document>
{document}
</document>

Question: {question}

Respond with ONLY a single integer between {min_val} and {max_val}.
<{facet_name}>"""

# ── Stage 3: Base cluster naming ─────────────────────────────────────

CLUSTER_NAME = """\
You are analyzing a group of documentation pages that have been clustered together by semantic similarity.

Here are representative samples FROM this cluster:
{inside_samples}

Here are samples from OTHER clusters (for contrast):
{outside_samples}

Based on the samples from this cluster (NOT the contrast samples), provide:
1. A short, specific name for this cluster (3-8 words)
2. A one-sentence summary of what these documents have in common

The name should be specific enough to distinguish this cluster from the contrast samples.

<name>cluster name here</name>
<summary>one sentence summary here</summary>"""

# ── Stage 4: Hierarchy — higher-level category naming ────────────────

HIERARCHY_NAMES = """\
Below are {n_clusters} cluster names from a documentation analysis. \
Group them into approximately {n_target} higher-level categories.

Clusters:
{cluster_list}

For each higher-level category, provide a name. List one category per line.
Each name should be 3-8 words, specific, and cover multiple clusters.

<categories>
category names, one per line
</categories>"""

HIERARCHY_ASSIGN = """\
Assign the following cluster to one of the higher-level categories.

Cluster name: {cluster_name}
Cluster summary: {cluster_summary}

Available categories:
{categories}

Respond with ONLY the category name that best fits this cluster. \
Use the exact category name from the list above.
<assignment>"""

HIERARCHY_RENAME = """\
You are renaming a higher-level category based on its children.

Category: {category_name}
Children:
{children_list}

Provide a better name and summary for this category based on its actual children.

<name>improved category name (3-8 words)</name>
<summary>one sentence summary</summary>"""

# ── Deduplication ────────────────────────────────────────────────────

DEDUPLICATE_NAMES = """\
Below are category names that may contain duplicates or near-duplicates. \
Merge any that are essentially the same concept into a single representative name.

Names:
{names_list}

Return the deduplicated list, one name per line. Keep the most specific/descriptive \
version when merging. Do not add new categories.

<deduplicated>
deduplicated names, one per line
</deduplicated>"""
