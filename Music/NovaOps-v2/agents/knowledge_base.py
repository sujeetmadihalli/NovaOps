"""TF-IDF knowledge base — self-learning runbook search.

Zero external dependencies. PIRs auto-saved as runbooks for future RAG.
"""

import os
import math
import logging
from collections import Counter
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

RUNBOOKS_DIR = Path(__file__).parent.parent / "runbooks"


class KnowledgeBaseRAG:
    def __init__(self, runbooks_dir: str = str(RUNBOOKS_DIR)):
        self.runbooks_dir = runbooks_dir
        self._runbooks: List[Dict] = []
        self._idf: Dict[str, float] = {}
        self._load_and_index()

    def _tokenize(self, text: str) -> List[str]:
        return text.lower().split()

    def _load_and_index(self):
        os.makedirs(self.runbooks_dir, exist_ok=True)

        self._runbooks = []
        for filename in os.listdir(self.runbooks_dir):
            if filename.endswith(".md"):
                filepath = os.path.join(self.runbooks_dir, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                tokens = self._tokenize(content)
                self._runbooks.append({
                    "filename": filename,
                    "content": content,
                    "tf": Counter(tokens),
                    "length": len(tokens),
                })

        N = len(self._runbooks)
        if N == 0:
            return

        df: Dict[str, int] = Counter()
        for rb in self._runbooks:
            for term in set(rb["tf"].keys()):
                df[term] += 1

        self._idf = {
            term: math.log((N + 1) / (freq + 1)) + 1
            for term, freq in df.items()
        }
        logger.info(f"Indexed {N} runbooks ({len(self._idf)} terms)")

    def _tfidf_score(self, query_tokens: List[str], runbook: Dict) -> float:
        score = 0.0
        tf = runbook["tf"]
        length = max(runbook["length"], 1)
        for token in query_tokens:
            if token in tf:
                score += (tf[token] / length) * self._idf.get(token, 1.0)
        return score

    def search_relevant_runbook(self, query: str) -> str:
        if not self._runbooks:
            return ""

        query_tokens = self._tokenize(query)
        scored = [(self._tfidf_score(query_tokens, rb), rb) for rb in self._runbooks]
        scored.sort(key=lambda x: x[0], reverse=True)

        best_score, best_rb = scored[0]
        if best_score == 0:
            return ""

        logger.info(f"Matched runbook: {best_rb['filename']} (score={best_score:.4f})")
        return best_rb["content"]

    def has_similar_runbook(self, alert_name: str, service_name: str) -> bool:
        """Check if a runbook exists for this alert+service.

        Layer 1: Exact filename match (pir-{service}-{alert}.md)
        Layer 2: Keyword overlap (3+ keywords match between alert+service and runbook filename)
        """
        target = self._make_filename(alert_name, service_name)

        # Layer 1: Exact filename match
        for rb in self._runbooks:
            if rb["filename"] == target:
                logger.info(f"Found exact runbook match: {rb['filename']}")
                return True

        # Layer 2: Keyword overlap fallback
        # Extract keywords from alert+service (normalize hyphens to spaces)
        combined = (alert_name + " " + service_name).lower().replace("-", " ")
        alert_keywords = set(combined.split())

        for rb in self._runbooks:
            # Extract keywords from runbook filename (remove .md and pir- prefix, replace - with space)
            fname = rb["filename"].replace(".md", "").replace("pir-", "").replace("-", " ").lower()
            fname_keywords = set(fname.split())
            overlap = alert_keywords & fname_keywords
            if len(overlap) >= 3:
                logger.info(
                    f"Found runbook via keyword overlap: {rb['filename']} "
                    f"(keywords: {overlap})"
                )
                return True

        logger.info(f"No existing runbook found for '{alert_name}' on '{service_name}'")
        return False

    def save_as_runbook(self, alert_name: str, service_name: str, content: str) -> str:
        filename = self._make_filename(alert_name, service_name)
        filepath = os.path.join(self.runbooks_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Saved runbook: {filename}")
        self._load_and_index()
        return filename

    def _make_filename(self, alert_name: str, service_name: str) -> str:
        raw = f"pir-{service_name}-{alert_name}"
        safe = raw.lower().replace(" ", "-")
        safe = "".join(c for c in safe if c.isalnum() or c == "-")
        return f"{safe}.md"
