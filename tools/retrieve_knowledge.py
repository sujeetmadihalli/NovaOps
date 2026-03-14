"""Knowledge retrieval tool — Amazon Bedrock Knowledge Bases with TF-IDF fallback.

Live mode: Queries a Bedrock Knowledge Base (semantic vector search over runbooks/skills).
Mock mode: Falls back to enhanced TF-IDF search over local skills + runbooks.

Environment variables:
  KNOWLEDGE_BASE_ID — Bedrock Knowledge Base ID (required for live mode)
  NOVAOPS_USE_MOCK  — "true" to use TF-IDF fallback (default: true)
  AWS_DEFAULT_REGION — region for Bedrock KB (default: us-east-1)
"""

import json
import logging
import os
from pathlib import Path

from strands import tool

from agents.knowledge_base import KnowledgeBaseRAG

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent.parent / "skills"


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


USE_MOCK = _env_bool("NOVAOPS_USE_MOCK", True)
HACKATHON_MODE = _env_bool("HACKATHON_MODE", True)

# Enhanced TF-IDF KB that also indexes skills markdown (not just runbooks)
_kb: KnowledgeBaseRAG | None = None


def _get_kb() -> KnowledgeBaseRAG:
    """Lazy-init the TF-IDF KB with skills pre-loaded."""
    global _kb
    if _kb is None:
        _kb = KnowledgeBaseRAG()
        _index_skills(_kb)
    return _kb


def _index_skills(kb: KnowledgeBaseRAG):
    """Index all skills markdown files into the TF-IDF KB."""
    if not SKILLS_DIR.exists():
        return

    count = 0
    for md_file in SKILLS_DIR.rglob("*.md"):
        rel = md_file.relative_to(SKILLS_DIR)
        # Create a synthetic filename for the KB index
        safe_name = str(rel).replace("\\", "-").replace("/", "-").lower()
        content = md_file.read_text(encoding="utf-8")
        # Add to internal runbooks list with TF-IDF indexing
        from collections import Counter
        tokens = content.lower().split()
        kb._runbooks.append({
            "filename": f"skill-{safe_name}",
            "content": content,
            "tf": Counter(tokens),
            "length": len(tokens),
        })
        count += 1

    # Rebuild IDF with new documents
    if count > 0:
        import math
        N = len(kb._runbooks)
        df: dict[str, int] = {}
        for rb in kb._runbooks:
            for term in set(rb["tf"].keys()):
                df[term] = df.get(term, 0) + 1
        kb._idf = {
            term: math.log((N + 1) / (freq + 1)) + 1
            for term, freq in df.items()
        }
        logger.info(f"Indexed {count} skill files into knowledge base ({N} total docs)")


def _retrieve_bedrock(query: str, num_results: int = 3) -> str:
    """Query Amazon Bedrock Knowledge Base for semantic search."""
    import boto3
    from botocore.config import Config as BotocoreConfig

    kb_id = os.environ.get("KNOWLEDGE_BASE_ID")
    if not kb_id:
        logger.warning("KNOWLEDGE_BASE_ID not set, falling back to TF-IDF")
        return _retrieve_tfidf(query, num_results)

    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    config = BotocoreConfig(user_agent_extra="novaops-retrieve")

    client = boto3.client("bedrock-agent-runtime", region_name=region, config=config)
    response = client.retrieve(
        retrievalQuery={"text": query},
        knowledgeBaseId=kb_id,
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": num_results}
        },
    )

    results = response.get("retrievalResults", [])
    if not results:
        return "No relevant knowledge found."

    formatted = []
    for r in results:
        score = r.get("score", 0.0)
        text = r.get("content", {}).get("text", "")
        source = r.get("location", {}).get("s3Location", {}).get("uri", "unknown")
        formatted.append(f"[Score: {score:.3f}] Source: {source}\n{text}")

    return "\n---\n".join(formatted)


def _retrieve_tfidf(query: str, num_results: int = 3) -> str:
    """TF-IDF fallback search over local skills + runbooks."""
    kb = _get_kb()
    if not kb._runbooks:
        return "No knowledge base documents available."

    query_tokens = kb._tokenize(query)
    scored = [(kb._tfidf_score(query_tokens, rb), rb) for rb in kb._runbooks]
    scored.sort(key=lambda x: x[0], reverse=True)

    top = scored[:num_results]
    if top[0][0] == 0:
        return "No relevant knowledge found for this query."

    formatted = []
    for score, rb in top:
        if score == 0:
            break
        formatted.append(f"[Score: {score:.4f}] Source: {rb['filename']}\n{rb['content'][:1500]}")

    return "\n---\n".join(formatted)


def _use_local_retrieval() -> bool:
    """Return True when local retrieval should be preferred over managed KB."""
    if HACKATHON_MODE:
        return True
    if USE_MOCK:
        return True
    if not os.environ.get("KNOWLEDGE_BASE_ID"):
        return True
    return False


@tool
def retrieve_knowledge(query: str, num_results: int = 3) -> str:
    """Search the SRE knowledge base for relevant runbooks, playbooks, and past incident learnings.

    Use this to find domain-specific guidance for root cause analysis or remediation planning.

    Args:
        query: Natural language search query (e.g. "OOM caused by deployment" or "how to remediate connection pool exhaustion")
        num_results: Maximum number of results to return (default 3)
    """
    try:
        if _use_local_retrieval():
            return _retrieve_tfidf(query, num_results)
        else:
            return _retrieve_bedrock(query, num_results)
    except Exception as e:
        logger.warning(f"Knowledge retrieval failed: {e}. Falling back to TF-IDF.")
        return _retrieve_tfidf(query, num_results)
