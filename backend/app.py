from fastapi import FastAPI, HTTPException, Form, UploadFile, File, Query,Request
from fastapi.middleware.cors import CORSMiddleware
import os
from typing import Optional, List
import openai
import tempfile
from langchain.embeddings import OpenAIEmbeddings
from mongo_db import MongoDBHandler
from information_retrieval import InformationRetrievalProcessor
from test_case_generation import TestCaseGenerator
from test_suite_generation import TestSuiteGenerator
from prompt_manager import PromptManager

app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize OpenAI configuration
openai.api_type = ""
openai.api_base = ""
openai.api_version = ""
openai.api_key = ""

# Initialize services
embeddings = OpenAIEmbeddings(
    engine="text-embedding-ada-002",
    openai_api_key=openai.api_key
)
# Initialize MongoDB handler
db_handler = MongoDBHandler()
prompt_manager = PromptManager(db_handler)

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
    """Upload one or multiple documents"""
    try:
        # Process each file
        temp_files = []
        file_paths = []
        
        for file in files:
            file_ext = os.path.splitext(file.filename)[1].lower()
            if file_ext not in ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.csv']:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {file_ext}. Supported types: PDF, DOCX, DOC, XLSX, XLS, CSV"
                )
            
            # Create a temp file with the correct extension
            try:
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
            # Process and upload to MongoDB
            results = db_handler.upload_multiple_files(
                file_paths=file_paths,
                doc_type=doc_type,
                embeddings=embeddings,
                titles=[new_title] * len(file_paths),
                max_pages=max_pages
            )
            
            # Check results
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
            # Clean up temp files
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


@app.get("/documents")
async def list_documents(doc_type: Optional[str] = None):
    """Endpoint for listing uploaded documents."""
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
                "feedback_items": form_data.get("feedback_items"),  # List of feedback items
                "max_test_cases": form_data.get("max_test_cases") # Include this

            }

        # Validate required fields
        if not data.get("query"):
            raise HTTPException(status_code=400, detail="Query is required")
        if not data.get("operation_type"):
            raise HTTPException(status_code=400, detail="Operation type is required")

        # Initialize components
        test_case_generator = TestCaseGenerator(db_handler)
        test_suite_generator = TestSuiteGenerator(db_handler)

        # Process based on operation type
        if data["operation_type"] == "test_case_generation":
            if not data.get("generation_type"):
                raise HTTPException(status_code=400, detail="Generation type is required")
            
            print(data["generation_type"])
            if data["generation_type"] == "Existing Products":
                if not data.get("product_a"):
                    raise HTTPException(status_code=400, detail="Product A required for existing product")
                result = test_case_generator.generate_for_existing_product(
                    data["query"], 
                    data["product_a"]
                )
            elif data["generation_type"] == "Similar Products":
                if not data.get("product_a") or not data.get("product_b"):
                    raise HTTPException(status_code=400, detail="Both products required for similar product")
                result = test_case_generator.generate_for_similar_product(
                    feature_description=data["query"],
                    primary_product=data["product_a"],
                    secondary_product=data["product_b"]
                )

            elif data["generation_type"] == "New Products":
                if not data.get("product_a"):
                    raise HTTPException(status_code=400, detail="Product name required for new product")
                result = test_case_generator.generate_for_new_product(
                    feature_description=data["query"],
                    product_title=data["product_a"]
                )

            else:
                raise HTTPException(status_code=400, detail="Invalid generation type")

        elif data["operation_type"] == "test_suite_generation":
            if not data.get("generation_type"):
                raise HTTPException(status_code=400, detail="Generation type is required")
                
            if data["generation_type"] == "Existing Products":
                if not data.get("product_a"):
                    raise HTTPException(status_code=400, detail="Product A required for existing product")
                result = test_suite_generator.generate_for_existing_product(
                    data["query"], 
                    data["product_a"],
                    no_testcase=int(data["max_test_cases"])
                )
            elif data["generation_type"] == "Similar Products":
                if not data.get("product_a") or not data.get("product_b"):
                    raise HTTPException(status_code=400, detail="Both products required for similar product")
                result = test_suite_generator.generate_for_similar_product(
                    feature_description=data["query"],
                    primary_product=data["product_a"],
                    secondary_product=data["product_b"],
                    no_testcase=int(data["max_test_cases"])
                )
            elif data["generation_type"] == "New Products":
                if not data.get("product_a"):
                    raise HTTPException(status_code=400, detail="Product name required for new product")
                result = test_suite_generator.generate_for_new_product(
                    feature_description=data["query"],
                    product_title=data["product_a"],
                    no_testcase=int(data["max_test_cases"])
                )
            else:
                raise HTTPException(status_code=400, detail="Invalid generation type")
        else:
            raise HTTPException(status_code=400, detail="Invalid operation type")
            
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
