import os
import json
import logging
import math
from typing import List, Dict

logger = logging.getLogger(__name__)

class KnowledgeBaseRAG:
    """
    A lightweight in-memory RAG implementation for Runbooks.
    In a true production environment, this would connect to Qdrant or Pinecone.
    For this agent, we use a basic TF-IDF or direct keyword matching for simplicity 
    to fetch the relevant Markdown runbook based on the alert string.
    """
    def __init__(self, runbooks_dir: str = "./runbooks"):
        self.runbooks_dir = runbooks_dir
        self.runbooks = []
        self._load_runbooks()

    def _load_runbooks(self):
        """Loads all markdown runbooks from the local directory."""
        if not os.path.exists(self.runbooks_dir):
            os.makedirs(self.runbooks_dir, exist_ok=True)
            logger.info(f"Created runbooks directory at {self.runbooks_dir}")
            return
            
        for filename in os.listdir(self.runbooks_dir):
            if filename.endswith(".md"):
                filepath = os.path.join(self.runbooks_dir, filename)
                with open(filepath, 'r') as f:
                    content = f.read()
                    self.runbooks.append({
                        "name": filename,
                        "content": content
                    })
        logger.info(f"Loaded {len(self.runbooks)} runbooks into Knowledge Base.")

    def search_relevant_runbook(self, alert_description: str) -> str:
        """
        Searches for the most relevant runbook based on the alert text.
        Fallbacks to a simple keyword match.
        """
        if not self.runbooks:
            return "No runbooks available in the Knowledge Base."
            
        # Very simple baseline retrieval: count keyword overlaps
        alert_words = set(alert_description.lower().split())
        
        best_match = None
        highest_score = 0
        
        for runbook in self.runbooks:
            content_words = set(runbook['content'].lower().split())
            score = len(alert_words.intersection(content_words))
            
            # Boost score if filename matches closely
            if runbook['name'].replace('.md', '').lower() in alert_description.lower():
                score += 10
                
            if score > highest_score:
                highest_score = score
                best_match = runbook
                
        if best_match and highest_score > 0:
            return f"Found relevant Runbook ({best_match['name']}):\n{best_match['content']}"
            
        return "No strictly relevant runbook found. Proceed with general troubleshooting."
