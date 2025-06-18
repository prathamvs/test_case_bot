from pymongo import MongoClient
from typing import List, Dict, Optional, Union
from langchain.vectorstores import FAISS
from langchain.schema import Document
import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from document_processor import DocumentParser
from typing import List, Dict, Optional
import re
from spire.doc import *
from spire.doc.common import *

class MongoDBHandler:
    def __init__(self):
        self.client = MongoClient("mongodb://localhost:27017/")
        self.db = self.client["main_db"]
        self.collection = self.db["documents"]
        self.vector_indices = self.db["vector_indices"]
        self.feedback_collection = self.db["test_case_feedback"]
        self.parser = DocumentParser()
        self.prompts = self.db["prompts"]
        self.query_cache = self.db["query_cache"]
        self.MAX_CHUNK_SIZE = 15 * 1024 * 1024
        self.MAX_PARALLEL_REQUESTS = 6
        self.TARGET_TOKENS_PER_BATCH = 8000
        self.RETRY_DELAY = 60
        self.PROGRESS_UPDATE_INTERVAL = 10

    def _get_next_available_doctype(self, title: str, base_doctype: str) -> str:
        """Find the next available doctype by checking existing documents and incrementing the number"""
        # Find all existing doctypes for this title that match the pattern
        existing_docs = self.collection.find(
            {"title": title, "doc_type": {"$regex": f"^{base_doctype}\d*$"}},
            {"doc_type": 1}
        )
        
        existing_doctypes = {doc["doc_type"] for doc in existing_docs}
        
        if base_doctype not in existing_doctypes:
            return base_doctype
        
        # Find the highest number suffix
        max_num = 0
        for doctype in existing_doctypes:
            if doctype == base_doctype:
                num = 1
            else:
                # Extract the number from the end
                match = re.search(r'(\d+)$', doctype)
                num = int(match.group(1)) if match else 0
            
            if num > max_num:
                max_num = num
        
        return f"{base_doctype}{max_num + 1}"

    def process_batch_with_retry(self, batch: List[Document], embeddings) -> FAISS:
        """Process batch with optimized retry logic"""
        last_error_time = 0
        while True:
            try:
                elapsed = time.time() - last_error_time
                if elapsed < self.RETRY_DELAY:
                    time.sleep(self.RETRY_DELAY - elapsed)
                return FAISS.from_documents(batch, embeddings)
            except Exception as e:
                print(f"Error processing batch: {e}. Retrying in {self.RETRY_DELAY} seconds...")
                last_error_time = time.time()
                time.sleep(self.RETRY_DELAY)

    def process_documents_parallel(self, documents: List[Document], embeddings) -> FAISS:
        """Ultra-fast parallel processing with optimized batching"""
        doc_tokens = [self.parser.count_tokens(doc.page_content) for doc in documents]
        total_tokens = sum(doc_tokens)
        avg_tokens = total_tokens / len(documents) if documents else 0
        
        dynamic_batch_size = max(1, min(100, int(self.TARGET_TOKENS_PER_BATCH / avg_tokens))) if avg_tokens else 50
        batches = [documents[i:i + dynamic_batch_size] 
                  for i in range(0, len(documents), dynamic_batch_size)]
        
        print(f"Processing {len(documents)} documents in {len(batches)} batches "
              f"(avg {avg_tokens:.0f} tokens/doc)")
        
        faiss_index = None
        completed = 0
        start_time = time.time()
        last_update = time.time()
        
        with ThreadPoolExecutor(max_workers=self.MAX_PARALLEL_REQUESTS) as executor:
            futures = {executor.submit(self.process_batch_with_retry, batch, embeddings): i 
                      for i, batch in enumerate(batches)}
            
            for future in as_completed(futures):
                try:
                    batch_index = future.result()
                    completed += 1
                    
                    if faiss_index is None:
                        faiss_index = batch_index
                    else:
                        faiss_index.merge_from(batch_index)
                    
                    if time.time() - last_update > self.PROGRESS_UPDATE_INTERVAL:
                        elapsed = (time.time() - start_time) / 60
                        rate = completed / elapsed if elapsed > 0 else 0
                        remaining = (len(batches) - completed) / max(rate, 0.1)
                        print(f"Progress: {completed}/{len(batches)} batches "
                              f"({rate:.1f}/min, ~{remaining:.1f} min remaining)")
                        last_update = time.time()
                        
                except Exception as e:
                    print(f"Failed to process batch: {e}")
        
        total_time = (time.time() - start_time) / 60
        print(f"\nCompleted {len(batches)} batches in {total_time:.1f} minutes")
        return faiss_index

    def update_vector_index(self, doc_type: str, title: str, embeddings) -> Optional[FAISS]:
        """Create/update FAISS index for specific document"""
        try:
            query = {"title": title, "doc_type": doc_type}
            docs = list(self.collection.find(query, {
                "_id": 1, "title": 1, "doc_type": 1, 
                "page_no": 1, "content": 1, "original_filename": 1
            }))
            
            if not docs:
                print(f"No documents found for title: {title} and doc_type: {doc_type}")
                return None
            
            lc_docs = self.parser.create_langchain_documents(docs)
            print(f"Processing {len(lc_docs)} documents for {title} ({doc_type})")
            
            index = self.process_documents_parallel(lc_docs, embeddings)
            if not index:
                return None
            
            index_name = f"faiss_index_{doc_type}_{title.replace(' ', '_')}"
            index_bytes = index.serialize_to_bytes()
            chunks = [index_bytes[i:i+self.MAX_CHUNK_SIZE] 
                     for i in range(0, len(index_bytes), self.MAX_CHUNK_SIZE)]
            
            self.vector_indices.delete_many({"name": index_name})
            
            for i, chunk in enumerate(chunks):
                self.vector_indices.insert_one({
                    "name": index_name,
                    "chunk_number": i,
                    "total_chunks": len(chunks),
                    "index_chunk": chunk,
                    "doc_type": doc_type,
                    "title": title,
                    "last_updated": datetime.datetime.now()
                })
            
            print(f"Index updated for {title} ({doc_type}) with {len(lc_docs)} documents")
            return index
        
        except Exception as e:
            print(f"Error updating index: {e}")
            return None

    def upload_file_to_mongodb(self, file_path: str, doc_type: str, 
                             embeddings, 
                             title: Optional[str] = None, 
                             max_pages: Optional[int] = None) -> bool:
        """Process and upload any supported file type to MongoDB with vector indexing"""
        try:
            if not title:
                title = os.path.splitext(os.path.basename(file_path))[0]
            
            # Check for existing documents with same title and doctype
            final_doctype = self._get_next_available_doctype(title, doc_type)
            
            file_ext = os.path.splitext(file_path)[1].lower()
            
            try:
                if file_ext == '.pdf':
                    file_data = self.parser.extract_pdf_content(file_path, final_doctype, max_pages)
                elif file_ext == '.docx':
                    file_data = self.parser.process_docx(file_path, final_doctype, max_pages)
                elif file_ext == '.doc':
                    file_data = self.parser.process_doc(file_path, final_doctype, max_pages)
                elif file_ext in ('.xlsx', '.xls', '.csv'):
                    file_data = self.parser.process_excel(file_path)
                else:
                    print(f"Unsupported file type: {file_ext}")
                    return False
                
                if not file_data:
                    print(f"No content extracted from {file_path}")
                    return False
                
                # Delete existing documents with same title and doctype first
                self.collection.delete_many({
                    "title": title,
                    "doc_type": final_doctype
                })
                
                mongo_docs = [{
                    "title": title,
                    "name": os.path.basename(file_path),
                    "page_no": item["page_no"],
                    "content": item["content"],
                    "doc_type": final_doctype,
                    "upload_date": datetime.datetime.now(),
                    "original_filename": item.get("original_filename", os.path.basename(file_path))
                } for item in file_data]
                
                result = self.collection.insert_many(mongo_docs)
                print(f"Uploaded {len(mongo_docs)} pages from {file_path} as {final_doctype}")
                
                self.update_vector_index(final_doctype, title, embeddings)
                
                if max_pages:
                    print(f"Note: Processed only first {max_pages} pages")
                
                return True
                
            except Exception as e:
                print(f"Error processing file content for {file_path}: {str(e)}")
                return False
                
        except Exception as e:
            print(f"Error in upload_file_to_mongodb for {file_path}: {str(e)}")
            return False
        finally:
            # Ensure the original uploaded file is closed and can be deleted
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Warning: Could not delete temp file {file_path}: {str(e)}")


    def upload_multiple_files(self, file_paths: List[str], doc_type: str, 
                            embeddings,
                            titles: Optional[List[str]] = None,
                            max_pages: Optional[int] = None) -> Dict[str, bool]:
        """Upload multiple files with parallel processing"""
        results = {}
        
        if titles is None:
            titles = [os.path.splitext(os.path.basename(fp))[0] for fp in file_paths]
        elif len(titles) != len(file_paths):
            print("Warning: titles list length doesn't match file_paths length. Using default titles.")
            titles = [os.path.splitext(os.path.basename(fp))[0] for fp in file_paths]
        
        # Process files sequentially instead of parallel to avoid LibreOffice conflicts
        for file_path, title in zip(file_paths, titles):
            try:
                results[file_path] = self.upload_file_to_mongodb(
                    file_path, 
                    doc_type, 
                    embeddings,
                    title,
                    max_pages
                )
            except Exception as e:
                print(f"Error processing {file_path}: {e}")
                results[file_path] = False
        
        return results

    def get_product_documents(self, product_title: str) -> List[dict]:
        """Get ALL documents for a specific product title (exact match only)"""
        return list(self.collection.find(
            {"title": product_title},
            {"content": 1, "title": 1, "doc_type": 1, "page_no": 1, "_id": 0}
        ))
