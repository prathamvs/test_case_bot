#FastAPI handles HTTP requests and responses
#MongoDB stores documents, embeddings, and metadata
#OpenAI provides AI capabilities for understanding and generation
#LangChain manages embeddings and document processing

#Key Features
#1. Flexible Document Processing
#2. Supports multiple file formats
#3. Handles both single and batch uploads
#4. Creates embeddings for semantic search
#5. Organizes documents by type and title

#Intelligent Test Generation
#1. The system can generate test cases in different scenarios:
#2. For existing products using their documentation
#3. By comparing features between similar products
#4. For entirely new products based on feature descriptions

#Feedback Loop
#1. Stores user feedback on generated test cases
#2. Uses feedback to improve future generations
#3. Maintains context of previous test cases


#This is a FastAPI web application that provides a comprehensive system for document management, 
# test case generation, and AI-powered question answering

#The application appears to be a testing automation platform that helps generate test 
#cases and test suites for software products by leveraging uploaded documentation and AI capabilities.

from fastapi import FastAPI, HTTPException, Form, UploadFile, File, Query, Request
from fastapi.middleware.cors import CORSMiddleware
import os
from typing import Optional, List
import openai
import tempfile
from langchain.embeddings import OpenAIEmbeddings
from mongo_db import MongoDBHandler
from test_case_generation import TestCaseGenerator
from prompt_manager import PromptManager
from test_suite_generation import TestSuiteGenerator
from pathlib import Path
from information_retrieval import InformationRetrievalProcessor


app = FastAPI()

#API Framework & Configuration
#Built with FastAPI for creating REST APIs
#CORS middleware enabled to allow cross-origin requests
#OpenAI integration for AI capabilities
#OpenAI embeddings for document vectorization

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# absolute_path = Path.cwd()
# cert_path = os.path.join(absolute_path , 'pki-it-root.crt')
# Initialize OpenAI configuration
openai.api_type = "azure"
openai.api_base = "https://apim-guardian-prv-fc.aihub.se.com"
openai.api_version = "2024-06-01"
openai.api_key = "b74bf34f88b449f5b25764e363d4dd49"
# os.environ["REQUESTS_CA_BUNDLE"]  = cert_path


#MongoDBHandler: Manages document storage and retrieval
#PromptManager: Handles AI prompt generation and management
#TestCaseGenerator: Creates individual test cases
#TestSuiteGenerator: Creates complete test suites
#InformationRetrievalProcessor: Handles Q&A functionality

# Initialize services
embeddings = OpenAIEmbeddings(
    engine="text-embedding-ada-002",
    openai_api_key=openai.api_key
)
db_handler = MongoDBHandler()
test_case_generator = TestCaseGenerator(db_handler)
prompt_manager = PromptManager(db_handler)

#Document Management
#/upload: Upload multiple documents (PDF, DOCX, Excel, CSV) with categorization
#/documents: List all uploaded documents with filtering
#/existing-titles: Get existing document titles for reuse

@app.get("/existing-titles")
async def get_existing_titles(doc_type: Optional[str] = Query(None)):
    """Get list of existing titles (optionally filtered by doc_type)"""
    try:
        query = {"doc_type": doc_type} if doc_type else {}
        titles = db_handler.collection.distinct("title", query)
        return {"titles": titles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload")
async def upload_document(
    files: List[UploadFile] = File(...),
    doc_type: str = Form(...),
    new_title: str = Form(...),
    max_pages: Optional[int] = Form(None)
):
   """Upload one or multiple documents with either existing or new title"""
    try:
        temp_files = []
        file_paths = []
        
        for file in files:
            file_ext = os.path.splitext(file.filename)[1].lower()
            if file_ext not in ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.csv']:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {file_ext}. Supported types: PDF, DOCX, DOC, XLSX, XLS, CSV"
                )
                
            # Validate title selection
            try:
                 # Create a temp file with the correct extension
                with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as temp_file:
                    content = await file.read()
                    temp_file.write(content)
                    temp_file_path = temp_file.name
                
                temp_files.append(temp_file_path)
                file_paths.append(temp_file_path)
            except Exception as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Could not save uploaded file {file.filename}: {str(e)}"
                )
        
        try:
            results = db_handler.upload_multiple_files(
                file_paths=file_paths,
                doc_type=doc_type,
                embeddings=embeddings,
                titles=[new_title] * len(file_paths),
                max_pages=max_pages
            )
            
            failed_files = [f for f, success in results.items() if not success]
            if failed_files:
                error_details = []
                for file_path in failed_files:
                    error_details.append(f"{os.path.basename(file_path)}: Processing failed")
                
                raise HTTPException(
                    status_code=422,
                    detail=f"Failed to process some files: {', '.join(error_details)}"
                )
            
            return {"message": f"Document(s) uploaded and indexed successfully as '{new_title}'"}
        
        finally:
            # Save the uploaded file temporarily
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception as e:
                    print(f"Error deleting temp file {temp_file}: {e}")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

#/ask: Ask questions about uploaded documents using RAG (Retrieval Augmented Generation)
#/process_query/: Main endpoint for test generation with three modes:
#Existing Products: Generate tests based on existing product documentation
#Similar Products: Generate tests by comparing two similar products
#New Products: Generate tests for completely new products

@app.post("/ask")
async def ask_question(question: str = Form(...)):
    """Endpoint for asking questions about the documents."""
    try:
        processor = InformationRetrievalProcessor()
        result = processor.get_answer(question)
        return {
            "answer": result["answer"],
            # "sources": result["sources"] # Uncomment if you want to include sources
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/documents")
async def list_documents(doc_type: Optional[str] = None):
    """Endpoint for listing uploaded documents"""
    try:
        query = {"doc_type": doc_type} if doc_type else {}
        documents = db_handler.collection.find(query, {"title": 1, "doc_type": 1, "upload_date": 1})
        return [{
            "title": doc["title"],
            "doc_type": doc["doc_type"],
            "upload_date": doc["upload_date"]
        } for doc in documents]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/process_query/")
async def process_query(request: Request):
    try:
        content_type = request.headers.get('Content-Type')

        if content_type == "application/json":
            data = await request.json()
        else:
            form_data = await request.form()
            data = {
                "query": form_data.get("query"),
                "operation_type": form_data.get("operation_type"),
                "generation_type": form_data.get("generation_type"),
                "product_a": form_data.get("product_a"),
                "product_b": form_data.get("product_b"),
                "feedback_items": form_data.get("feedback_items", ""), # String of feedback items
                "previous_test_case": form_data.get("previous_test_case", ""),
                "max_test_cases": form_data.get("max_test_cases")
            }

        # Validate required fields
        if not data.get("query"):
            raise HTTPException(status_code=400, detail="Query is required")
        if not data.get("operation_type"):
            raise HTTPException(status_code=400, detail="Operation type is required")

        # Process feedback items if provided
        feedback_items = []
        if data.get("feedback_items"):
            try:
                feedback_items = [item.strip() for item in data["feedback_items"].split(",") if item.strip()]
            except:
                feedback_items = [data["feedback_items"].strip()]

        # Process based on operation type
        if data["operation_type"] == "test_case_generation":
            if not data.get("generation_type"):
                raise HTTPException(status_code=400, detail="Generation type is required")
            
            if data["generation_type"] == "Existing Products":
                if not data.get("product_a"):
                    raise HTTPException(status_code=400, detail="Product A required for existing product")
                
                # Store feedback if provided
                if feedback_items and data.get("previous_test_case"):
                    for feedback in feedback_items:
                        test_case_generator.store_feedback(
                            product_title=data["product_a"],
                            feature=data["query"],
                            feedback=feedback,
                            previous_test_case=data["previous_test_case"]
                        )
                
                result = test_case_generator.generate_for_existing_product(
                    feature_description=data["query"], 
                    product_title=data["product_a"],
                    feedback_items=feedback_items if feedback_items else None
                )

            elif data["generation_type"] == "Similar Products":
                if not data.get("product_a") or not data.get("product_b"):
                    raise HTTPException(status_code=400, detail="Both products required for similar product")
                
                # Store feedback if provided
                if feedback_items and data.get("previous_test_case"):
                    for feedback in feedback_items:
                        test_case_generator.store_feedback(
                            product_title=data["product_b"],
                            feature=data["query"],
                            feedback=feedback,
                            previous_test_case=data["previous_test_case"]
                        )
                
                result = test_case_generator.generate_for_similar_product(
                    feature_description=data["query"],
                    primary_product=data["product_a"],
                    secondary_product=data["product_b"],
                    feedback_items=feedback_items if feedback_items else None
                )

            elif data["generation_type"] == "New Products":
                if not data.get("product_a"):
                    raise HTTPException(status_code=400, detail="Product name required for new product")
                
                # Store feedback if provided
                if feedback_items and data.get("previous_test_case"):
                    for feedback in feedback_items:
                        test_case_generator.store_feedback(
                            product_title=data["product_a"],
                            feature=data["query"],
                            feedback=feedback,
                            previous_test_case=data["previous_test_case"]
                        )
                
                result = test_case_generator.generate_for_new_product(
                    feature_description=data["query"],
                    product_title=data["product_a"],
                    feedback_items=feedback_items if feedback_items else None
                )

            else:
                raise HTTPException(status_code=400, detail="Invalid generation type")

            return result

        elif data["operation_type"] == "test_suite_generation":
            if not data.get("generation_type"):
                raise HTTPException(status_code=400, detail="Generation type is required")
            
            test_suite_generator = TestSuiteGenerator(db_handler)
            
            if data["generation_type"] == "Existing Products":
                if not data.get("product_a"):
                    raise HTTPException(status_code=400, detail="Product A required for existing product")
                
                # Store feedback if provided
                if feedback_items and data.get("previous_test_case"):
                    for feedback in feedback_items:
                        test_suite_generator.store_feedback(
                            product_title=data["product_a"],
                            feature=data["query"],
                            feedback=feedback,
                            previous_test_case=data["previous_test_case"]
                        )
                
                result = test_suite_generator.generate_for_existing_product(
                    feature_description=data["query"], 
                    product_title=data["product_a"],
                    no_testcase=int(data["max_test_cases"]),
                    feedback_items=feedback_items if feedback_items else None
                )

            elif data["generation_type"] == "Similar Products":
                if not data.get("product_a") or not data.get("product_b"):
                    raise HTTPException(status_code=400, detail="Both products required for similar product")
                
                # Store feedback if provided
                if feedback_items and data.get("previous_test_case"):
                    for feedback in feedback_items:
                        test_suite_generator.store_feedback(
                            product_title=data["product_b"],
                            feature=data["query"],
                            feedback=feedback,
                            previous_test_case=data["previous_test_case"]
                        )
                
                result = test_suite_generator.generate_for_similar_product(
                    feature_description=data["query"],
                    primary_product=data["product_a"],
                    secondary_product=data["product_b"],
                    no_testcase=int(data["max_test_cases"]),
                    feedback_items=feedback_items if feedback_items else None
                )

            elif data["generation_type"] == "New Products":
                if not data.get("product_a"):
                    raise HTTPException(status_code=400, detail="Product name required for new product")
                
                # Store feedback if provided
                if feedback_items and data.get("previous_test_case"):
                    for feedback in feedback_items:
                        test_suite_generator.store_feedback(
                            product_title=data["product_a"],
                            feature=data["query"],
                            feedback=feedback,
                            previous_test_case=data["previous_test_case"]
                        )
                
                result = test_suite_generator.generate_for_new_product(
                    feature_description=data["query"],
                    product_title=data["product_a"],
                    no_testcase=int(data["max_test_cases"]),
                    feedback_items=feedback_items if feedback_items else None
                )
                print(result)

            else:
                raise HTTPException(status_code=400, detail="Invalid generation type")

            return result

        else:
            raise HTTPException(status_code=400, detail="Invalid operation type")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

#/generate-and-store-prompts: Create and store AI prompts for reuse
#/get-stored-prompts: Retrieve previously stored prompts
#/store-feedback: Collect user feedback to improve test generation

@app.post("/generate-and-store-prompts")
async def generate_and_store_prompts(
    user_prompt: str = Form(...),
    query: str = Form(...),
    title: str = Form(...)
):
    """Generate and store system/human prompts"""
    try:
        # Generate prompts
        prompts = prompt_manager.analyze_and_generate_prompts(user_prompt, query)

         # Store in MongoDB
        success = prompt_manager.store_prompts(
            title=title,
            feature=prompts["feature"],
            system_prompt=prompts["system_prompt"],
            human_prompt=prompts["human_prompt"]
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to store prompts")
            
        return {
            "message": "Prompts generated and stored successfully",
            "feature": prompts["feature"],
            "system_prompt": prompts["system_prompt"],
            "human_prompt": prompts["human_prompt"]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get-stored-prompts")
async def get_stored_prompts(
    title: str = Query(...),
    feature: Optional[str] = Query(None)
):
    """Retrieve stored prompts"""
    try:
        prompts = prompt_manager.get_prompts(title, feature)
        return {"prompts": prompts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/store-feedback")
async def store_feedback(
    product_title: str = Form(...),
    feature: str = Form(...),
    feedback: str = Form(...),
    previous_test_case: str = Form(...),
    user_prompt: Optional[str] = Form(None)
):
    """Endpoint for storing and processing user feedback with test case context"""
    try:
        success = prompt_manager.process_and_store_feedback(
            product_title=product_title,
            feature=feature,
            raw_feedback=feedback,
            previous_test_case=previous_test_case,
            user_prompt=user_prompt
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to store feedback")
            
        return {"message": "Feedback processed and stored successfully"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
