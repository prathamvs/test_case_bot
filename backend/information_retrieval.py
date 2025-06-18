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

# Initialize OpenAI configuration
openai.api_type = ""
openai.api_base = ""
openai.api_version = ""
openai.api_key = ""

class InformationRetrievalProcessor:
    def __init__(self):
        # Initialize embeddings
        self.openai_embeddings = OpenAIEmbeddings(
            engine="text-embedding-ada-002",
            openai_api_key="b74bf34f88b449f5b25764e363d4dd49"
        )
        
        # Initialize LLM
        self.llm = ChatOpenAI(
            engine="gpt-4",
            temperature=0,
            openai_api_key="b74bf34f88b449f5b25764e363d4dd49",
        )
        
        # Initialize MongoDB connection
        self.client = MongoClient("mongodb://localhost:27017/")
        self.db = self.client["original_db"]
        self.vector_indices = self.db["vector_indices"]
        self.collection = self.db["documents"]

    def load_all_faiss_indexes(self) -> FAISS:
        """Load and combine all FAISS indexes from MongoDB"""
        index_names = self.vector_indices.distinct("name")
        
        if not index_names:
            raise ValueError("No FAISS indexes found in database")
        
        combined_index = None
        
        for index_name in index_names:
            chunks = list(self.vector_indices.find({"name": index_name}).sort("chunk_number", 1))
            faiss_bytes = b"".join(chunk["index_chunk"] for chunk in chunks)
            
            current_index = FAISS.deserialize_from_bytes(
                embeddings=self.openai_embeddings,
                serialized=faiss_bytes,
                allow_dangerous_deserialization=True
            )
            
            if combined_index is None:
                combined_index = current_index
            else:
                combined_index.merge_from(current_index)
        
        return combined_index

    def load_hybrid_retriever(self) -> EnsembleRetriever:
        """Combines vector and keyword search across all documents"""
        # 1. Load combined FAISS vector retriever
        faiss_index = self.load_all_faiss_indexes()
        vector_retriever = faiss_index.as_retriever(search_kwargs={"k": 25})
        
        # 2. Create BM25 keyword retriever from all documents
        docs = list(self.collection.find({}, {
            "_id": 0, 
            "content": 1, 
            "page_no": 1, 
            "title": 1,
            "doc_type": 1
        }))
        
        text_docs = []
        for doc in docs:
            for element in doc["content"]:
                if element["type"] == "text":
                    text_docs.append(Document(
                        page_content=element["content"],
                        metadata={
                            "page_no": doc["page_no"],
                            "title": doc.get("title", "Untitled"),
                            "doc_type": doc.get("doc_type", "unknown")
                        }
                    ))
        
        bm25_retriever = BM25Retriever.from_documents(text_docs)
        bm25_retriever.k = 25
        
        # 3. Combine both retrievers
        return EnsembleRetriever(
            retrievers=[bm25_retriever, vector_retriever],
            weights=[0.4, 0.6]
        )

    def get_answer(self, question: str) -> Dict:
        """Get answer with sources from all documents"""
        retriever = self.load_hybrid_retriever()
        
        # Simple, direct prompt template
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
        
        # Single direct query
        result = qa_chain({"query": f"{question} in the documents provided."})
        
        # Format sources
        sources = []
        for doc in result["source_documents"]:
            source_info = (
                f"Document: {doc.metadata.get('title', 'Untitled')} "
                f"({doc.metadata.get('doc_type', 'unknown')})\n"
                f"Page {doc.metadata.get('page_no', 'N/A')}:\n"
                f"{doc.page_content[:300].strip()}"
            )
            if len(doc.page_content) > 300:
                source_info += "..."
            sources.append(source_info)
        
        return {
            "answer": result["result"],
            "sources": sources
        }

