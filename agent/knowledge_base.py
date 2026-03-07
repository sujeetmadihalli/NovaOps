import os
import math
import logging
from collections import Counter
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class KnowledgeBaseRAG:
    """
    Self-contained TF-IDF runbook search. No external vector DB dependencies.
    Works on any Python version with zero extra installs.
    """

    def __init__(self, runbooks_dir: str = "./runbooks", **kwargs):
        self.runbooks_dir = runbooks_dir
        self._runbooks: List[Dict] = []
        self._idf: Dict[str, float] = {}
        self._load_and_index()

    # ------------------------------------------------------------------ #
    #  Indexing                                                            #
    # ------------------------------------------------------------------ #

    def _tokenize(self, text: str) -> List[str]:
        return text.lower().split()

    def _load_and_index(self):
        if not os.path.exists(self.runbooks_dir):
            os.makedirs(self.runbooks_dir, exist_ok=True)
            logger.info(f"Created runbooks directory at {self.runbooks_dir}")
            return

        for filename in os.listdir(self.runbooks_dir):
            if filename.endswith(".md"):
                filepath = os.path.join(self.runbooks_dir, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                tokens = self._tokenize(content)
                tf = Counter(tokens)
                self._runbooks.append({
                    "filename": filename,
                    "content": content,
                    "tf": tf,
                    "length": len(tokens),
                })

        # Compute IDF across all runbooks
        N = len(self._runbooks)
        if N == 0:
            return

        df: Dict[str, int] = Counter()
        for rb in self._runbooks:
            for term in set(rb["tf"].keys()):
                df[term] += 1

        self._idf = {term: math.log((N + 1) / (freq + 1)) + 1 for term, freq in df.items()}
        logger.info(f"Indexed {N} runbooks with TF-IDF ({len(self._idf)} unique terms)")

    # ------------------------------------------------------------------ #
    #  Search                                                              #
    # ------------------------------------------------------------------ #

    def _tfidf_score(self, query_tokens: List[str], runbook: Dict) -> float:
        score = 0.0
        tf = runbook["tf"]
        length = max(runbook["length"], 1)
        for token in query_tokens:
            if token in tf:
                tf_val = tf[token] / length
                idf_val = self._idf.get(token, 1.0)
                score += tf_val * idf_val
        return score

    def search_relevant_runbook(self, alert_description: str) -> str:
        if not self._runbooks:
            return "No runbooks found. Proceed with general troubleshooting."

        query_tokens = self._tokenize(alert_description)
        scored = [(self._tfidf_score(query_tokens, rb), rb) for rb in self._runbooks]
        scored.sort(key=lambda x: x[0], reverse=True)

        best_score, best_rb = scored[0]
        logger.info(f"TF-IDF matched '{best_rb['filename']}' with score {best_score:.4f}")

        if best_score == 0:
            return "No strictly relevant runbook found. Proceed with general troubleshooting."

        return f"Found relevant Runbook ({best_rb['filename']}):\n{best_rb['content']}"
