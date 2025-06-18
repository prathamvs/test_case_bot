# AI Test Case Generator

## Table of Contents
1. [Project Overview](#project-overview)
2. [System Architecture](#system-architecture)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Running the Application](#running-the-application)
6. [API Endpoints](#api-endpoints)
7. [Features](#features)
8. [Troubleshooting](#troubleshooting)

## Project Overview
An AI-powered application that generates comprehensive test cases and test suites, and provides document Q&A capabilities for technical documentation.

## System Architecture
```
AI Test Case Generator
├── frontend/ (Streamlit UI)
│ ├── Home.py (Main application)
│ ├── mongo_db.py (Database connection)
│ └── pages/ (Feature modules)
│ ├── information_retrieval.py (Q&A)
│ ├── test_app.py (Test Cases)
│ └── test_suite.py (Test Suites)
└── backend/ (FastAPI server)
    ├── app.py (API endpoints)
    ├── document_processor.py (Document parsing)
    ├── information_retrieval.py (Q&A processing)
    ├── mongo_db.py (DB operations)
    ├── prompt_manager.py (AI prompts)
    ├── test_case_generation.py
    └── test_suite_generation.py
```

## Prerequisites
- Python 3.9+
- MongoDB 5.0+ (running locally on port 27017)
- Azure OpenAI API credentials

## Installation

1. Clone the repository:
```bash
git clone [https://github.schneider-electric.com/SESA619897/Chatbot_V-V.git](https://github.com/prathamvs/test_case_bot.git)
cd test_case_bot
```

2. Create and activate virtual environment:
```bash
python -m venv venv
source venv/bin/activate # Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Running the Application

### Start Backend Server:
```bash
cd backend
python -m uvicorn app:app
```

### Start Frontend:
```bash
cd frontend
streamlit run Home.py
```

Access the application at: [http://localhost:8501](http://localhost:8501)

## API Endpoints

| Endpoint | Method | Description | Parameters |
|----------|--------|-------------|------------|
| `/upload` | POST | Upload and process documents | `files`, `doc_type`, `new_title` |
| `/ask` | POST | Answer questions about documents | `question` |
| `/process_query/` | POST | Generate test cases/suites | `query`, `operation_type`, `generation_type`, `product_a`, `product_b`, `max_test_cases` |
| `/store-feedback` | POST | Store user feedback | `product_title`, `feature`, `feedback`, `previous_test_case` |
| `/existing-titles` | GET | List available document titles | `doc_type` (optional) |
| `/get-stored-prompts` | GET | Retrieve stored prompts | `title`, `feature` (optional) |

## Features
- **Test Case Generation**:
  - Generate detailed test cases for existing products
  - Create test cases for new products
  - Compare similar products
  - Export to Excel format

- **Test Suite Generation**:
  - Build comprehensive test suites
  - Customize number of test cases
  - Support for iterative refinement
  - Download full test suites

- **Document Q&A**:
  - Upload and query technical documents (PDF, DOCX, DOC, XLSX, CSV)
  - Maintains conversation history
  - Download conversation transcripts
  - Document filtering by type and title

## Troubleshooting

### Common Issues:
1. **MongoDB Connection Problems**
   - Verify MongoDB service is running (`sudo systemctl status mongod`)
   - Check connection string in `mongo_db.py` files

2. **API Key Errors**
   - Ensure Azure OpenAI API key is valid
   - Verify API endpoint configuration in backend code

3. **Document Processing Failures**
   - Check file permissions
   - Verify file formats (supported: PDF, DOCX, DOC,XLSX, CSV)
   - Ensure documents are not password protected

4. **Streamlit Issues**
   - Clear browser cache
   - Restart Streamlit server
   - Check port availability (8501)

### Logs:
- Backend: Console output from uvicorn
- Frontend: Streamlit console output and browser developer tools

---

### Requirements
All dependencies are specified in `requirements.txt` which includes:
- Core: `pymongo`, `python-dotenv`
- Frontend: `streamlit`, `pillow`, `requests`, `pandas`
- Backend: `fastapi`, `uvicorn`, `langchain`, `openai`, `pdfplumber`, `python-docx`, `spire.doc`

Note: The application expects MongoDB to be running locally on the default port (27017). The backend API runs on port 8000 and the frontend on port 8501.
