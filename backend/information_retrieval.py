#Class Overview:
#Purpose as a hybrid retrieval system combining vector and keyword search
#Architecture using FAISS, BM25, and GPT-4
#Integration with MongoDB for document storage

from typing import Dict, List, Optional
from pymongo import MongoClient
from langchain.retrievers import BM25Retriever, EnsembleRetriever
from langchain.vectorstores import FAISS
from langchain.schema import Document
from langchain.chains import RetrievalQA
from langchain.chat_models import ChatOpenAI
from langchain.embeddings import OpenAIEmbeddings
import openai
from langchain_core.prompts import PromptTemplate

# Global OpenAI configuration for Azure integration
openai.api_type = "azure"
openai.api_base = ""
openai.api_version = ""
openai.api_key = ""

class InformationRetrievalProcessor:
    """
    A comprehensive information retrieval system that combines vector search and keyword search
    for enhanced document querying capabilities.
    
    This class implements a hybrid retrieval approach using:
    1. FAISS vector search for semantic similarity
    2. BM25 keyword search for exact term matching
    3. Ensemble retrieval to combine both approaches
    4. OpenAI GPT-4 for generating contextual answers
    
    The system is designed to work with documents stored in MongoDB, including
    both the raw document content and pre-computed FAISS vector indexes.
    """
    def __init__(self):
        """
        Initialize the Information Retrieval Processor with all necessary components.
        
        Sets up:
        - OpenAI embeddings for vector similarity search
        - GPT-4 language model for answer generation
        - MongoDB connection for document and index storage
        """
        # Initialize OpenAI embeddings for converting text to vectors
        # Uses Ada-002 model which is optimized for search and retrieval tasks
        self.openai_embeddings = OpenAIEmbeddings(
            engine="text-embedding-ada-002",
            openai_api_key="b74bf34f88b449f5b25764e363d4dd49"
        )
        
        # Initialize GPT-4 language model for answer generation
        # Temperature=0 ensures deterministic, factual responses
        self.llm = ChatOpenAI(
            engine="gpt-4",
            temperature=0,# Deterministic output for consistent answers
            openai_api_key="b74bf34f88b449f5b25764e363d4dd49",# TODO: Move to environment variable
        )
        
        # Initialize MongoDB connection for document storage and retrieval
        self.client = MongoClient("mongodb://localhost:27017/")
        self.db = self.client["original_db"]
        self.vector_indices = self.db["vector_indices"] # Stores FAISS index chunks
        self.collection = self.db["documents"] # Stores processed document content

    def load_all_faiss_indexes(self) -> FAISS:
        """
        Load and combine all FAISS vector indexes from MongoDB storage.
        
        FAISS indexes are stored in MongoDB as chunked binary data to handle
        large index sizes. This method reconstructs the complete indexes by:
        1. Retrieving all index chunks for each named index
        2. Reassembling the binary data
        3. Deserializing into FAISS objects
        4. Merging multiple indexes into a single combined index
        
        Returns:
            FAISS: A combined FAISS index containing all document vectors
            
        Raises:
            ValueError: If no FAISS indexes are found in the database
            
        Note:
            Uses allow_dangerous_deserialization=True because we trust our own
            serialized data. In production, additional validation should be added.
        """
        # Get all unique index names from the database
        index_names = self.vector_indices.distinct("name")
        
        if not index_names:
            raise ValueError("No FAISS indexes found in database")
        
        combined_index = None
         # Process each named index separately
        for index_name in index_names:
            # Retrieve all chunks for this index, sorted by chunk number
            chunks = list(self.vector_indices.find({"name": index_name}).sort("chunk_number", 1))
            # Reassemble the complete binary data from chunks
            faiss_bytes = b"".join(chunk["index_chunk"] for chunk in chunks)

            # Deserialize the binary data back into a FAISS index object
            current_index = FAISS.deserialize_from_bytes(
                embeddings=self.openai_embeddings,
                serialized=faiss_bytes,
                allow_dangerous_deserialization=True
            )
            
            # Combine indexes: first one becomes base, others are merged in
            if combined_index is None:
                combined_index = current_index
            else:
                combined_index.merge_from(current_index)
        
        return combined_index

    def load_hybrid_retriever(self) -> EnsembleRetriever:
        """
        Create a hybrid retriever that combines vector search and keyword search.
        
        This method implements the core hybrid retrieval strategy:
        1. Vector Search (FAISS): Uses semantic embeddings to find conceptually similar content
        2. Keyword Search (BM25): Uses traditional TF-IDF style matching for exact terms
        3. Ensemble Combination: Weights and combines results from both approaches
        
        The hybrid approach ensures both semantic understanding and exact term matching,
        providing more comprehensive and accurate retrieval results.
        
        Returns:
            EnsembleRetriever: A retriever that combines vector and keyword search
            
        Weights:
            - BM25 (keyword): 40% - Good for exact term matching
            - FAISS (vector): 60% - Better for semantic understanding
        """
        # 1. Set up vector-based retriever using combined FAISS indexes
        faiss_index = self.load_all_faiss_indexes()
        vector_retriever = faiss_index.as_retriever(search_kwargs={"k": 25})
        
        # 2. Set up keyword-based retriever using BM25 algorithm
        # First, extract all text content from MongoDB documents

        docs = list(self.collection.find({}, {
            "_id": 0, # Exclude MongoDB ObjectId for cleaner data
            "content": 1, # Include document content
            "page_no": 1, # Include page numbers for reference
            "title": 1, # Include document titles
            "doc_type": 1 # Include document type classification
        }))

        # Convert MongoDB documents to LangChain Document format for BM25
        text_docs = []
        for doc in docs:
            # Process each content element (text blocks and tables)
            for element in doc["content"]:
                if element["type"] == "text": # Only use text elements for keyword search
                    text_docs.append(Document(
                        page_content=element["content"],
                        metadata={
                            "page_no": doc["page_no"],
                            "title": doc.get("title", "Untitled"),
                            "doc_type": doc.get("doc_type", "unknown")
                        }
                    ))
                    
        # Create BM25 retriever from text documents
        bm25_retriever = BM25Retriever.from_documents(text_docs)
        bm25_retriever.k = 25 # Also retrieve top 25 matches for consistency
        
        # 3. Combine both retrievers with weighted ensemble
        return EnsembleRetriever(
            retrievers=[bm25_retriever, vector_retriever],
            weights=[0.4, 0.6] # 40% keyword, 60% vector - favor semantic search
        )

    def get_answer(self, question: str) -> Dict:
        """
        Generate an answer to a question using hybrid retrieval and GPT-4.
        
        This is the main interface method that orchestrates the entire QA pipeline:
        1. Creates hybrid retriever for comprehensive document search
        2. Sets up a specialized prompt template for technical product information
        3. Uses RetrievalQA chain to combine retrieval with answer generation
        4. Formats and returns both the answer and source references
        
        Args:
            question (str): The user's question to be answered
            
        Returns:
            Dict: Contains 'answer' and 'sources' keys
                - answer (str): GPT-4 generated response based on retrieved context
                - sources (List[str]): Formatted source documents with metadata
                
        The method emphasizes accuracy and source attribution, with specific rules
        for technical content like function codes and acronyms.
        """
        
        retriever = self.load_hybrid_retriever()
        
         # Define a specialized prompt template for technical product information
        # This prompt includes specific rules for handling technical content 
        
        prompt_template = """Answer the question based on the context below.
        Be helpful and provide the most relevant information you can find.
        
        Mandatory: - The answer should be from the documents provided.Find the most relevant information and provide it in a concise manner.

        You are a helpful product information assistant with technical expertise. Follow these rules:
            1. Answer STRICTLY using provided context
            2. If answe is not present: "I don't have that information"
            3. For Function Codes: i.e. Function code for device identification? the answer is 43/14 not 43, so Always show full code (e.g., FC 43/14)
            4. Reference specific pages/sections
            5. Never invent details or provide personal opinions
            
            7. Never create full forms for acronyms or abbreviations unless explicitly mentioned in the context
        Context:
        {context}

        Question: {question} in the documents provided.

        Answer:"""
        
        qa_chain = RetrievalQA.from_chain_type(
            llm=ChatOpenAI(
                engine="gpt-4",
                temperature=0,
                openai_api_base="https://apim-guardian-prv-fc.aihub.se.com",
                openai_api_key="b74bf34f88b449f5b25764e363d4dd49"
            ),
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True,
            chain_type_kwargs={
                "prompt": PromptTemplate(
                    template=prompt_template,
                    input_variables=["context", "question"]
                )
            }
        )
        
         # Execute the query with explicit document context requirement
        result = qa_chain({"query": f"{question} in the documents provided."})
        
        # Format source documents for user reference
        # This provides transparency about where answers come from
        sources = []
        for doc in result["source_documents"]:
            # Create detailed source information with document metadata
            source_info = (
                f"Document: {doc.metadata.get('title', 'Untitled')} "
                f"({doc.metadata.get('doc_type', 'unknown')})\n"
                f"Page {doc.metadata.get('page_no', 'N/A')}:\n"
                f"{doc.page_content[:300].strip()}"
            )
            # Add ellipsis if content was truncated
            if len(doc.page_content) > 300:
                source_info += "..."
            sources.append(source_info)

        # Return structured response with answer and source attribution
        return {
            "answer": result["result"],
            "sources": sources
        }

