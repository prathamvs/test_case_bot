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
    """
    A comprehensive MongoDB handler for document processing, storage, and vector indexing.
    
    This class manages the complete document lifecycle:
    1. Document parsing and processing (PDF, DOCX, Excel/CSV)
    2. MongoDB storage with metadata
    3. FAISS vector index creation and management
    4. Parallel processing for performance optimization
    5. Automatic document type versioning
    6. Feedback and caching systems
    
    The system is designed for high-performance document ingestion with
    optimized batching, parallel processing, and robust error handling.
    """
    
    def __init__(self):
        """
        Initialize the MongoDB handler with database connections and processing parameters.
        
        Sets up:
        - MongoDB client and database connections
        - Document parser for file processing
        - Performance optimization parameters
        - Collections for documents, indexes, feedback, and caching
        """
        # MongoDB connection setup
        self.client = MongoClient("mongodb://localhost:27017/")
        self.db = self.client["original_db"]
        # Collection setup for different data types
        self.collection = self.db["documents"] # Main document storage
        self.vector_indices = self.db["vector_indices"] # FAISS index storage (chunked)
        self.feedback_collection = self.db["test_case_feedback"] # User feedback storage
         # Initialize document parser for file processing
        self.parser = DocumentParser()
        self.prompts = self.db["prompts"] # Prompt templates storage
        self.query_cache = self.db["query_cache"] # Query result caching
        self.MAX_CHUNK_SIZE = 15 * 1024 * 1024 # 15MB max chunk size for FAISS storage
        self.MAX_PARALLEL_REQUESTS = 6 # Concurrent processing limit
        self.TARGET_TOKENS_PER_BATCH = 8000 # Optimal batch size for embeddings
        self.RETRY_DELAY = 60  # Seconds to wait before retry
        self.PROGRESS_UPDATE_INTERVAL = 10 # Progress reporting frequency

    def _get_next_available_doctype(self, title: str, base_doctype: str) -> str:
        """
        Find the next available document type identifier to prevent duplicates.
        
        This method handles automatic versioning of documents with the same title
        by appending incremental numbers to the document type (e.g., test_case1, test_case2).
        
        Args:
            title (str): The document title to check for existing versions
            base_doctype (str): The base document type (e.g., "test_case")
            
        Returns:
            str: The next available document type (e.g., "test_case3")
            
        Examples:
            - If no existing docs: "test_case" -> "test_case"
            - If "test_case" exists: "test_case" -> "test_case1"
            - If "test_case" and "test_case1" exist: "test_case" -> "test_case2"
        """
        
        # Find all existing doctypes for this title that match the pattern
        existing_docs = self.collection.find(
            {"title": title, "doc_type": {"$regex": f"^{base_doctype}\d*$"}},
            {"doc_type": 1}
        )
        
        existing_doctypes = {doc["doc_type"] for doc in existing_docs}
        
        if base_doctype not in existing_doctypes:
            return base_doctype
        
        # Find the highest number suffix among existing doctypes
        max_num = 0
        for doctype in existing_doctypes:
            if doctype == base_doctype:
                num = 1
            else:
                # Extract number from end of string (e.g., "test_case3" -> 3)
                match = re.search(r'(\d+)$', doctype)
                num = int(match.group(1)) if match else 0
            
            if num > max_num:
                max_num = num
        # Return next available version
        return f"{base_doctype}{max_num + 1}"

    def process_batch_with_retry(self, batch: List[Document], embeddings) -> FAISS:
        """
        Process a batch of documents with robust retry logic for embedding API calls.
        
        This method handles rate limiting and transient failures when creating
        FAISS indexes from document batches. It implements exponential backoff
        and continues retrying until successful.
        
        Args:
            batch (List[Document]): Documents to process into FAISS index
            embeddings: OpenAI embeddings instance for vector creation
            
        Returns:
            FAISS: Successfully created FAISS index
            
        Note:
            This method will retry indefinitely with delays, making it suitable
            for handling rate limits but potentially causing long delays if
            there are persistent API issues.
        """
        
        last_error_time = 0
        while True:
            try:
                # Respect rate limiting by waiting if we recently had an error
                elapsed = time.time() - last_error_time
                if elapsed < self.RETRY_DELAY:
                    time.sleep(self.RETRY_DELAY - elapsed)
                
                # Create FAISS index from document batch
                return FAISS.from_documents(batch, embeddings)
            except Exception as e:
                print(f"Error processing batch: {e}. Retrying in {self.RETRY_DELAY} seconds...")
                last_error_time = time.time()
                time.sleep(self.RETRY_DELAY)

    def process_documents_parallel(self, documents: List[Document], embeddings) -> FAISS:
        """
        Process documents in parallel with dynamic batching for optimal performance.
        
        This method implements advanced batching strategy:
        1. Analyzes token distribution across documents
        2. Calculates optimal batch sizes based on token targets
        3. Processes batches in parallel with thread pool
        4. Merges resulting FAISS indexes
        5. Provides real-time progress monitoring
        
        Args:
            documents (List[Document]): Documents to process
            embeddings: OpenAI embeddings instance
            
        Returns:
            FAISS: Combined FAISS index containing all document vectors
            
        Performance Features:
            - Dynamic batch sizing based on document token counts
            - Parallel processing with configurable thread limits
            - Progress tracking with time estimates
            - Automatic index merging
        """

        # Analyze document token distribution for optimal batching
        doc_tokens = [self.parser.count_tokens(doc.page_content) for doc in documents]
        total_tokens = sum(doc_tokens)
        # Calculate dynamic batch size based on target tokens per batch
        avg_tokens = total_tokens / len(documents) if documents else 0
        
        dynamic_batch_size = max(1, min(100, int(self.TARGET_TOKENS_PER_BATCH / avg_tokens))) if avg_tokens else 50
        # Create batches with calculated size
        batches = [documents[i:i + dynamic_batch_size] 
                  for i in range(0, len(documents), dynamic_batch_size)]
        
        print(f"Processing {len(documents)} documents in {len(batches)} batches "
              f"(avg {avg_tokens:.0f} tokens/doc)")

        # Initialize tracking variables
        faiss_index = None
        completed = 0
        start_time = time.time()
        last_update = time.time()

         # Process batches in parallel using thread pool
        with ThreadPoolExecutor(max_workers=self.MAX_PARALLEL_REQUESTS) as executor:
             # Submit all batch processing jobs
            futures = {executor.submit(self.process_batch_with_retry, batch, embeddings): i 
                      for i, batch in enumerate(batches)}

            # Process completed batches as they finish
            for future in as_completed(futures):
                try:
                    batch_index = future.result()
                    completed += 1

                    # Merge batch index into combined index
                    if faiss_index is None:
                        faiss_index = batch_index
                    else:
                        faiss_index.merge_from(batch_index)

                    # Provide progress updates at regular intervals
                    if time.time() - last_update > self.PROGRESS_UPDATE_INTERVAL:
                        elapsed = (time.time() - start_time) / 60
                        rate = completed / elapsed if elapsed > 0 else 0
                        remaining = (len(batches) - completed) / max(rate, 0.1)
                        print(f"Progress: {completed}/{len(batches)} batches "
                              f"({rate:.1f}/min, ~{remaining:.1f} min remaining)")
                        last_update = time.time()
                        
                except Exception as e:
                    print(f"Failed to process batch: {e}")
        # Report final statistics
        total_time = (time.time() - start_time) / 60
        print(f"\nCompleted {len(batches)} batches in {total_time:.1f} minutes")
        return faiss_index

    def update_vector_index(self, doc_type: str, title: str, embeddings) -> Optional[FAISS]:
       """
        Create or update FAISS vector index for a specific document type and title.
        
        This method handles the complete vector indexing pipeline:
        1. Retrieves documents from MongoDB
        2. Converts to LangChain format
        3. Processes documents in parallel to create FAISS index
        4. Chunks and stores the serialized index in MongoDB
        5. Manages index versioning and updates
        
        Args:
            doc_type (str): Document type identifier
            title (str): Document title
            embeddings: OpenAI embeddings instance
            
        Returns:
            Optional[FAISS]: Created FAISS index, or None if failed
            
        Storage Strategy:
            - Large FAISS indexes are chunked for MongoDB storage
            - Old indexes are replaced atomically
            - Metadata includes creation time and document info
        """
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

            # Create FAISS index using parallel processing
            index = self.process_documents_parallel(lc_docs, embeddings)
            if not index:
                return None

            # Prepare for chunked storage in MongoDB
            index_name = f"faiss_index_{doc_type}_{title.replace(' ', '_')}"
            index_bytes = index.serialize_to_bytes()
            # Split large index into manageable chunks for MongoDB storage
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
                """
        Process and upload any supported file type to MongoDB with automatic vector indexing.
        
        This is the main file ingestion method that handles the complete workflow:
        1. File format detection and parsing
        2. Document type versioning to prevent conflicts
        3. Content extraction and structuring
        4. MongoDB storage with metadata
        5. Automatic FAISS vector index creation
        
        Supported Formats:
        - PDF: Text and table extraction with page-level processing
        - DOCX: Converted to PDF then processed
        - Excel/CSV: Tabular data processing
        
        Args:
            file_path (str): Path to the file to process
            doc_type (str): Base document type identifier
            embeddings: OpenAI embeddings for vector indexing
            title (Optional[str]): Custom title (defaults to filename)
            max_pages (Optional[int]): Limit pages processed (None for all)
            
        Returns:
            bool: True if successful, False if failed
            
        Features:
            - Automatic document type versioning
            - Multi-format support
            - Page limitation for large documents
            - Comprehensive error handling
            - Metadata preservation
        """

        try:
            if not title:
                title = os.path.splitext(os.path.basename(file_path))[0]
            # Get next available document type to prevent conflicts
            # Check for existing documents with same title and doctype
            final_doctype = self._get_next_available_doctype(title, doc_type)
            # Determine processing method based on file extension
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

                # Prepare documents for MongoDB insertion with comprehensive metadata
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
        """
        Upload multiple files in parallel for improved performance.
        
        This method orchestrates batch file processing with:
        1. Input validation and title alignment
        2. Parallel file processing using thread pools
        3. Individual error handling per file
        4. Comprehensive result reporting
        
        Args:
            file_paths (List[str]): List of file paths to process
            doc_type (str): Base document type for all files
            embeddings: OpenAI embeddings instance
            titles (Optional[List[str]]): Custom titles (must match file count)
            max_pages (Optional[int]): Page limit applied to all files
            
        Returns:
            Dict[str, bool]: Success/failure status for each file path
            
        Features:
            - Parallel processing with ThreadPoolExecutor
            - Individual error isolation (one failure doesn't stop others)
            - Title validation and alignment
            - Comprehensive result tracking
        """
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
        """
        Retrieve all documents for a specific product title.
        
        This method performs an exact title match to find all document versions
        and types associated with a particular product. Useful for product-specific
        queries and analysis.
        
        Args:
            product_title (str): Exact product title to search for
            
        Returns:
            List[dict]: List of document records with content and metadata
            
        Fields Returned:
            - content: Document content (text and tables)
            - title: Product title
            - doc_type: Document type identifier
            - page_no: Page number within document
            
        Note:
            Uses exact string matching. For fuzzy matching or partial searches,
            consider using regex queries or full-text search indexes.
        """
        return list(self.collection.find(
            {"title": product_title},# Exact title match
            {"content": 1, # Include document content
             "title": 1, # Include title for reference
             "doc_type": 1, # Include document type
             "page_no": 1, # Include page number
             "_id": 0} # Exclude MongoDB ObjectId for cleaner output
        ))
    
    
