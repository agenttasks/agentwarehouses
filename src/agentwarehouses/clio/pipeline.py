"""Clio pipeline — five-stage document analysis with clustering and hierarchy.

Implements the pipeline from Anthropic's Clio paper (arxiv.org/abs/2412.13678)
adapted for documentation pages. Uses:
  - Anthropic Claude API for facet extraction and summarization
  - sentence-transformers for embeddings (same as OpenClio)
  - scikit-learn KMeans for clustering (simpler than FAISS for our scale)

Pipeline stages:
  1. extract_facets()    — ask LLM questions about each doc
  2. embed_facets()      — sentence-transformer vectors
  3. base_cluster()      — k-means on embeddings
  4. build_hierarchy()   — recursive clustering into tree
  5. summarize()         — LLM names and descriptions for clusters
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import orjson

from agentwarehouses.clio.facets import DEFAULT_FACETS
from agentwarehouses.clio.prompts import (
    CLUSTER_NAME,
    FACET_EXTRACTION,
    FACET_EXTRACTION_NUMERIC,
    HIERARCHY_NAMES,
    HIERARCHY_RENAME,
)
from agentwarehouses.clio.types import (
    ClioConfig,
    ClioResults,
    Cluster,
    DocumentFacets,
    EmbeddingArray,
    Facet,
    FacetValue,
)
from agentwarehouses.log import get_logger

logger = get_logger(__name__)


class ClioPipeline:
    """Five-stage document analysis pipeline.

    Usage:
        config = ClioConfig(output_dir="output/clio")
        pipeline = ClioPipeline(config)

        # documents: list of dicts with 'url', 'title', 'body_markdown'
        results = pipeline.run(documents)
    """

    def __init__(
        self,
        config: ClioConfig | None = None,
        facets: list[Facet] | None = None,
    ) -> None:
        self.config = config or ClioConfig()
        self.facets = facets or DEFAULT_FACETS
        self._embedder: Any = None
        self._client: Any = None

    # ── Public API ───────────────────────────────────────────────────

    def run(self, documents: list[dict[str, Any]]) -> ClioResults:
        """Run the full five-stage pipeline on a list of documents.

        Args:
            documents: List of dicts, each with at least 'body_markdown'.
                       Optional: 'url', 'title', 'content_type'.

        Returns:
            ClioResults with facets, clusters, and hierarchy.
        """
        n = len(documents)
        logger.info("Clio pipeline starting: %d documents, %d facets", n, len(self.facets))

        # Stage 1: Facet extraction
        doc_facets = self.extract_facets(documents)
        logger.info("Stage 1 complete: extracted facets for %d documents", len(doc_facets))

        # Stage 2: Embedding
        embeddings = self.embed_facets(doc_facets)
        logger.info("Stage 2 complete: generated embeddings for %d facets", len(embeddings))

        # Stage 3: Base clustering
        base_clusters = self.base_cluster(doc_facets, embeddings)
        logger.info("Stage 3 complete: %s", {k: len(v) for k, v in base_clusters.items()})

        # Stage 4: Hierarchy
        root_clusters = self.build_hierarchy(base_clusters)
        logger.info("Stage 4 complete: hierarchy built")

        # Stage 5: Summarize (already done inline during stages 3-4)

        results = ClioResults(
            facets=self.facets,
            doc_facets=doc_facets,
            base_clusters=base_clusters,
            root_clusters=root_clusters,
            n_documents=n,
        )

        # Write output
        self._write_results(results)

        return results

    # ── Stage 1: Facet extraction ────────────────────────────────────

    def extract_facets(self, documents: list[dict[str, Any]]) -> list[DocumentFacets]:
        """Extract all facet values from each document using the LLM."""
        results: list[DocumentFacets] = []

        for i, doc in enumerate(documents):
            body = doc.get("body_markdown", "")[:self.config.max_doc_tokens * 4]  # rough char limit
            facet_values: list[FacetValue] = []

            for facet in self.facets:
                value = self._extract_single_facet(facet, body)
                facet_values.append(FacetValue(facet_name=facet.name, value=value))

            results.append(DocumentFacets(
                doc_index=i,
                url=doc.get("url", ""),
                title=doc.get("title", ""),
                facet_values=facet_values,
            ))

            if self.config.verbose and (i + 1) % 10 == 0:
                logger.info("  Facets extracted: %d/%d", i + 1, len(documents))

        return results

    def _extract_single_facet(self, facet: Facet, document: str) -> str:
        """Extract a single facet value from a document."""
        if facet.numeric_range:
            prompt = FACET_EXTRACTION_NUMERIC.format(
                document=document,
                question=facet.question,
                facet_name=facet.name,
                min_val=facet.numeric_range[0],
                max_val=facet.numeric_range[1],
            )
        else:
            prompt = FACET_EXTRACTION.format(
                document=document,
                question=facet.question,
                facet_name=facet.name,
            )

        response = self._call_llm(prompt)
        # Extract value from tagged response if present
        value = self._extract_tag(response, facet.name) or response.strip()
        return value

    # ── Stage 2: Embedding ───────────────────────────────────────────

    def embed_facets(
        self, doc_facets: list[DocumentFacets]
    ) -> dict[str, EmbeddingArray]:
        """Generate embeddings for each clusterable facet.

        Returns dict mapping facet_name -> (n_docs, embed_dim) array.
        """
        embedder = self._get_embedder()
        embeddings: dict[str, EmbeddingArray] = {}

        for facet in self.facets:
            if not facet.should_cluster():
                continue

            # Collect facet values for this facet across all docs
            texts = []
            for df in doc_facets:
                fv = next((v for v in df.facet_values if v.facet_name == facet.name), None)
                texts.append(fv.value if fv else "")

            if not texts:
                continue

            # Batch encode
            vecs = embedder.encode(
                texts,
                batch_size=self.config.embedding_batch_size,
                show_progress_bar=self.config.verbose,
                normalize_embeddings=True,
            )
            embeddings[facet.name] = np.array(vecs, dtype=np.float32)
            logger.info("  Embedded facet '%s': shape %s", facet.name, embeddings[facet.name].shape)

        return embeddings

    # ── Stage 3: Base clustering ─────────────────────────────────────

    def base_cluster(
        self,
        doc_facets: list[DocumentFacets],
        embeddings: dict[str, EmbeddingArray],
    ) -> dict[str, list[Cluster]]:
        """Create base-level clusters for each facet using k-means."""
        from sklearn.cluster import KMeans

        base_clusters: dict[str, list[Cluster]] = {}
        n_docs = len(doc_facets)

        for facet in self.facets:
            if facet.name not in embeddings:
                continue

            vecs = embeddings[facet.name]
            n_clusters = self.config.n_base_clusters(n_docs)

            logger.info("  Clustering facet '%s': %d docs -> %d clusters", facet.name, n_docs, n_clusters)

            km = KMeans(
                n_clusters=n_clusters,
                random_state=self.config.seed,
                n_init=10,
            )
            labels = km.fit_predict(vecs)

            # Build cluster objects
            clusters: list[Cluster] = []
            for cid in range(n_clusters):
                indices = [int(i) for i in np.where(labels == cid)[0]]
                if not indices:
                    continue

                # Sample docs for naming
                name, summary = self._name_cluster(
                    facet, doc_facets, indices, labels, cid
                )

                clusters.append(Cluster(
                    facet_name=facet.name,
                    name=name,
                    summary=summary,
                    doc_indices=indices,
                    level=0,
                ))

            base_clusters[facet.name] = clusters

        return base_clusters

    def _name_cluster(
        self,
        facet: Facet,
        doc_facets: list[DocumentFacets],
        indices: list[int],
        labels: Any,
        cluster_id: int,
    ) -> tuple[str, str]:
        """Generate a name and summary for a cluster using LLM."""
        rng = np.random.RandomState(self.config.seed + cluster_id)

        # Sample inside the cluster
        n_inside = min(self.config.n_samples_per_cluster, len(indices))
        inside_idx = rng.choice(indices, size=n_inside, replace=False)
        inside_samples = self._format_samples(doc_facets, facet.name, inside_idx)

        # Sample outside the cluster (for contrast)
        outside_mask = labels != cluster_id
        outside_pool = np.where(outside_mask)[0]
        n_outside = min(self.config.n_samples_outside_cluster, len(outside_pool))
        if n_outside > 0:
            outside_idx = rng.choice(outside_pool, size=n_outside, replace=False)
            outside_samples = self._format_samples(doc_facets, facet.name, outside_idx)
        else:
            outside_samples = "(none)"

        prompt = CLUSTER_NAME.format(
            inside_samples=inside_samples,
            outside_samples=outside_samples,
        )

        response = self._call_llm(prompt)
        name = self._extract_tag(response, "name") or f"Cluster {cluster_id}"
        summary = self._extract_tag(response, "summary") or ""
        return name, summary

    # ── Stage 4: Hierarchy ───────────────────────────────────────────

    def build_hierarchy(
        self, base_clusters: dict[str, list[Cluster]]
    ) -> dict[str, list[Cluster]]:
        """Recursively build cluster hierarchies using k-means + LLM naming.

        Mirrors OpenClio's getHierarchy(): at each level, cluster the
        cluster descriptions, name the parent categories, assign children,
        and rename parents based on actual children.
        """
        from sklearn.cluster import KMeans

        root_clusters: dict[str, list[Cluster]] = {}

        for facet_name, clusters in base_clusters.items():
            if len(clusters) <= self.config.min_top_level_size:
                root_clusters[facet_name] = clusters
                continue

            current_level = list(clusters)
            level = 1

            while len(current_level) > self.config.min_top_level_size:
                n_parents = max(
                    self.config.min_top_level_size,
                    int(len(current_level) * self.config.hierarchy_reduction_ratio),
                )
                n_parents = min(n_parents, len(current_level) - 1)

                logger.info(
                    "  Hierarchy level %d: %d clusters -> %d parents",
                    level, len(current_level), n_parents,
                )

                # Embed cluster descriptions
                embedder = self._get_embedder()
                texts = [f"{c.name}: {c.summary}" for c in current_level]
                vecs = embedder.encode(texts, normalize_embeddings=True)

                # Cluster the clusters
                km = KMeans(n_clusters=n_parents, random_state=self.config.seed + level, n_init=5)
                labels = km.fit_predict(vecs)

                # Generate parent category names
                category_names = self._generate_hierarchy_names(current_level, n_parents)

                # Assign children to parents
                parents: list[Cluster] = []
                for pid in range(n_parents):
                    child_indices = [i for i, lbl in enumerate(labels) if lbl == pid]
                    if not child_indices:
                        continue

                    children = [current_level[i] for i in child_indices]

                    # Pick best category name for this group
                    parent_name = category_names[pid] if pid < len(category_names) else f"Group {pid}"

                    # Aggregate doc indices from children
                    all_doc_indices: list[int] = []
                    for child in children:
                        all_doc_indices.extend(child.doc_indices)

                    parents.append(Cluster(
                        facet_name=facet_name,
                        name=parent_name,
                        summary="",
                        doc_indices=all_doc_indices,
                        children=children,
                        level=level,
                    ))

                # Rename parents based on actual children
                for parent in parents:
                    if parent.children:
                        name, summary = self._rename_parent(parent)
                        parent.name = name
                        parent.summary = summary

                current_level = parents
                level += 1

            root_clusters[facet_name] = current_level

        return root_clusters

    def _generate_hierarchy_names(
        self, clusters: list[Cluster], n_target: int
    ) -> list[str]:
        """Generate higher-level category names from cluster descriptions."""
        cluster_list = "\n".join(
            f"- {c.name}: {c.summary}" for c in clusters[:50]  # cap for prompt length
        )

        prompt = HIERARCHY_NAMES.format(
            n_clusters=len(clusters),
            n_target=n_target,
            cluster_list=cluster_list,
        )

        response = self._call_llm(prompt)
        categories_text = self._extract_tag(response, "categories") or response
        names = [line.strip().lstrip("- ").lstrip("0123456789.)")
                 for line in categories_text.strip().split("\n") if line.strip()]
        return names

    def _rename_parent(self, parent: Cluster) -> tuple[str, str]:
        """Rename a parent cluster based on its actual children."""
        children_list = "\n".join(
            f"- {c.name}" for c in (parent.children or [])[:10]
        )

        prompt = HIERARCHY_RENAME.format(
            category_name=parent.name,
            children_list=children_list,
        )

        response = self._call_llm(prompt)
        name = self._extract_tag(response, "name") or parent.name
        summary = self._extract_tag(response, "summary") or ""
        return name, summary

    # ── Utilities ────────────────────────────────────────────────────

    def _get_embedder(self) -> Any:
        """Lazy-load sentence-transformer model."""
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(self.config.embedding_model)
            logger.info("Loaded embedding model: %s", self.config.embedding_model)
        return self._embedder

    def _get_client(self) -> Any:
        """Lazy-load Anthropic client."""
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
            logger.info("Initialized Anthropic client")
        return self._client

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM and return the response text."""
        client = self._get_client()
        response = client.messages.create(
            model=self.config.llm_model,
            max_tokens=1024,
            temperature=self.config.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def _format_samples(
        self, doc_facets: list[DocumentFacets], facet_name: str, indices: Any
    ) -> str:
        """Format document samples for LLM prompts."""
        lines = []
        for idx in indices:
            df = doc_facets[int(idx)]
            fv = next((v for v in df.facet_values if v.facet_name == facet_name), None)
            title = df.title or df.url or f"Doc {df.doc_index}"
            value = fv.value if fv else ""
            lines.append(f"- [{title}] {value}")
        return "\n".join(lines)

    @staticmethod
    def _extract_tag(text: str, tag: str) -> str | None:
        """Extract content between XML-style tags."""
        pattern = rf"<{tag}>(.*?)</{tag}>"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else None

    def _write_results(self, results: ClioResults) -> None:
        """Write results to output directory as JSONL + summary."""
        out_dir = Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Write facet data
        facets_path = out_dir / "facets.jsonl"
        with facets_path.open("wb") as f:
            for df in results.doc_facets:
                f.write(orjson.dumps(df.model_dump()) + b"\n")

        # Write cluster hierarchy as JSON
        for facet_name, clusters in results.root_clusters.items():
            cluster_path = out_dir / f"clusters_{facet_name}.json"
            cluster_data = [c.model_dump() for c in clusters]
            cluster_path.write_bytes(orjson.dumps(cluster_data, option=orjson.OPT_INDENT_2))

        # Summary
        summary = {
            "n_documents": results.n_documents,
            "facets": [f.name for f in results.facets],
            "base_clusters": {k: len(v) for k, v in results.base_clusters.items()},
            "root_clusters": {k: len(v) for k, v in results.root_clusters.items()},
        }
        (out_dir / "summary.json").write_bytes(
            orjson.dumps(summary, option=orjson.OPT_INDENT_2)
        )

        logger.info("Results written to %s", out_dir)
