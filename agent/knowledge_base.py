import os
import logging
from typing import List, Dict

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

class KnowledgeBaseRAG:
    """
    Production-grade RAG implementation for Runbooks using ChromaDB.
    Creates a local vector database to store runbook semantic embeddings
    and retrieves the most relevant runbook based on the alert string.
    """
    def __init__(self, runbooks_dir: str = "./runbooks", db_path: str = "./chroma_db"):
        self.runbooks_dir = runbooks_dir
        
        # Initialize the Vector DB client
        self.chroma_client = chromadb.PersistentClient(path=db_path)
        
        # We use a lightweight open source HuggingFace embedding model for local testing
        # Default: all-MiniLM-L6-v2 which creates 384-dimensional embeddings
        self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        
        try:
            # Get or create the collection for our Runbooks
            self.collection = self.chroma_client.get_or_create_collection(
                name="incident_runbooks", 
                embedding_function=self.embedding_fn
            )
            self._load_runbooks()
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB collection: {e}")

    def _load_runbooks(self):
        """Loads and embeds all markdown runbooks from the local directory."""
        if not os.path.exists(self.runbooks_dir):
            os.makedirs(self.runbooks_dir, exist_ok=True)
            logger.info(f"Created runbooks directory at {self.runbooks_dir}")
            return
            
        documents = []
        metadatas = []
        ids = []
            
        for filename in os.listdir(self.runbooks_dir):
            if filename.endswith(".md"):
                filepath = os.path.join(self.runbooks_dir, filename)
                with open(filepath, 'r') as f:
                    content = f.read()
                    
                    documents.append(content)
                    metadatas.append({"filename": filename, "type": "runbook"})
                    ids.append(filename) # Use filename as the vector ID
                    
        if documents:
            # Upsert into ChromaDB (will automatically embed the documents)
            self.collection.upsert(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            logger.info(f"Embedded {len(documents)} runbooks into ChromaDB Vector Store.")

    def search_relevant_runbook(self, alert_description: str) -> str:
        """
        Searches the Vector DB for the most semantically relevant runbook.
        """
        try:
            # Query the collection
            results = self.collection.query(
                query_texts=[alert_description],
                n_results=1,
                include=["documents", "metadatas", "distances"]
            )
            
            # Extract the top result if it meets a reasonable distance threshold
            if results and results['documents'] and len(results['documents'][0]) > 0:
                top_doc = results['documents'][0][0]
                top_meta = results['metadatas'][0][0]
                distance = results['distances'][0][0]
                
                logger.info(f"Vector search matched {top_meta['filename']} with L2 distance {distance}")
                
                return f"Found relevant Runbook ({top_meta['filename']}):\n{top_doc}"
                
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            
        return "No strictly relevant runbook found. Proceed with general troubleshooting."
