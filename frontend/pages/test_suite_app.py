"""
Test Suite Generation Assistant - Streamlit Application
======================================================

This application provides an AI-powered test suite generation system with feedback workflow.
Users can upload documents, generate test suites, provide feedback, and download results.

Key Features:
- Document upload and processing
- AI-powered test suite generation
- Interactive feedback workflow
- Excel export functionality
- Session state management for workflow continuity
"""

import streamlit as st
import time
import requests
from bs4 import BeautifulSoup
import pandas as pd
from mongo_db import get_unique_products_from_mongo
import re
from io import BytesIO
import json
from datetime import datetime
import uuid

# ============================================================================
# CONFIGURATION AND CONSTANTS
# ============================================================================

# Constants
DOCUMENT_TYPES = ['test_case', 'product_spec', 'userguide']
GENERATION_TYPES = ["Existing Products", "Similar Products","New Products"]
OPERATION_TYPES = ["test_suite_generation"]

# API Base URL
API_BASE_URL = "http://127.0.0.1:8000"

# ============================================================================
# STREAMLIT PAGE SETUP
# ============================================================================

# Configure the Streamlit page with title, icon, and layout
st.set_page_config(
    page_title="Test Suite Generation Assistant",
    page_icon="🧪",
    layout="wide"
)

# ============================================================================
# CUSTOM CSS STYLES
# ============================================================================

# Define custom CSS for enhanced UI styling
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 15px;
        text-align: center;
        color: white;
        margin-bottom: 2rem;
    }
    .test-case-separator {
        border-top: 2px dashed #667eea;
        margin: 1rem 0;
    }
    .feedback-success {
        background: #d4edda;
        color: #155724;
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid #c3e6cb;
        margin: 1rem 0;
        text-align: center;
        font-weight: bold;
    }
    .workflow-box {
        background: #f8f9fa;
        border: 2px solid #dee2e6;
        border-radius: 10px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .workflow-title {
        color: #495057;
        font-size: 1.2em;
        font-weight: bold;
        margin-bottom: 1rem;
        text-align: center;
        border-bottom: 2px solid #dee2e6;
        padding-bottom: 0.5rem;
    }
    .generate-box {
        background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
        border: 2px solid #2196f3;
    }
    .workflow-step {
        display: flex;
        align-items: center;
        margin: 0.5rem 0;
        font-weight: 500;
    }
    .step-number {
        background: #007bff;
        color: white;
        border-radius: 50%;
        width: 25px;
        height: 25px;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-right: 10px;
        font-size: 0.9em;
    }
</style>
<div class="main-header">
    <h1>🧪 Test Suite Generation Assistant</h1>
    <p>Generate comprehensive test suites with AI-powered feedback workflow</p>
</div>
""", unsafe_allow_html=True)

# ============================================================================
# SESSION STATE MANAGEMENT
# ============================================================================

# Initialize session state
def init_session_state():
    """Initialize all session state variables""" 
    defaults = {
        'custom_doc_name': '', #User-entered custom document name
        'uploaded_docs': False, #Boolean flag for document upload status
        'generated_test_suite_text': '', #Raw text of generated test suite
        'generated_content': '', #Additional generated content
        'processing': False, #Boolean flag for processing status
        'feedback_submitted': False, #Boolean flag for feedback submission status
        'feedback_data': [], #List to store feedback data
        'workflow_step': 0,  # 0: initial, 1: test_suite_generated, 2+: feedback_iterations
        'current_test_suite': '',  # Store the latest version of test suite
        'current_query': '', #Current user query
        'current_generation_type': '', #Selected generation type
        'current_product_a': '', #Selected first product
        'current_product_b': '', #Selected second product (for similar products)
        'current_max_test_cases': 10, #Maximum number of test cases to generate
        'feedback_text': '', #Current feedback text  
        'current_excel': None,  # Store the latest Excel file
        'feedback_history': []  # Store all feedback iterations
    }

    # Initialize each session state variable if it doesn't exist
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

# ============================================================================
# EXCEL EXPORT FUNCTIONALITY
# ============================================================================
def create_excel_from_test_suite(test_suite, title_filter, custom_doc_name, max_test_cases):
    """Create Excel file from test suite"""
    try:
        # Split the test suite text into individual test cases
        # Uses regex to find test case headers and split accordingly
        test_cases = re.split(r"=+\s*## Test Case \d+/\d+\s*=+", test_suite)
        test_cases = [tc.strip() for tc in test_cases if tc.strip()]

        # Determine the product title for Excel export
        product_title = (
            custom_doc_name
            if title_filter == 'None of The above'
            else title_filter
        )

        # Create Excel file in memory using BytesIO
        excel_output = BytesIO()
        with pd.ExcelWriter(excel_output, engine='xlsxwriter') as writer:
            row_cursor = 0
            # Process each test case
            for idx, case in enumerate(test_cases, start=1):
                lines = case.splitlines()
                # Extract table lines (markdown table format)
                # Filter lines that start with '|' but exclude separator lines
                table_lines = [line for line in lines if line.strip().startswith('|') and not line.strip().startswith('|-')]

                rows = []
                for line in table_lines:
                    # Split by '|' and remove first/last empty cells
                    cells = [cell.strip() for cell in line.strip().split('|')[1:-1]]
                    if cells:
                        rows.append(cells)
                # Create DataFrame if valid table data exists
                if len(rows) > 1:
                    headers = rows[0] #First row contains headers
                    data = rows[1:]   # Remaining rows contain data
                    df = pd.DataFrame(data, columns=headers)
                    # Add product title column at the beginning
                    df.insert(0, "Product Title", [product_title] + [""] * (len(df) - 1))
                    # Write to Excel with proper row positioning
                    df.to_excel(writer, sheet_name="Test_Suite", startrow=row_cursor, index=False)
                    row_cursor += len(df) + 3 # Gap of 2 rows between tables

        return excel_output.getvalue()
    except Exception as e:
        st.warning(f"Could not create Excel format: {str(e)}")
        return None

# ============================================================================
# API COMMUNICATION FUNCTIONS
# ============================================================================

# Generate initial test suite using simplified API
def generate_initial_test_suite(query, generation_type, product_a, max_test_cases, product_b=None):
    """Generate initial test suite using the simplified API structure"""
    try:
        # Prepare API payload
        payload = {
            "query": query,
            "operation_type": "test_suite_generation",
            "generation_type": generation_type,
            "product_a": product_a,
            "max_test_cases": max_test_cases
        }

        # Add product_b for similar products generation
        if generation_type == "Similar Products" and product_b:
            # Make API request
            payload["product_b"] = product_b
            
        response = requests.post(
            f"{API_BASE_URL}/process_query/",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        # Process response
        if response.status_code == 200:
            result = response.json()
            # Generate a unique session ID for tracking
            session_id = str(uuid.uuid4())
            return session_id, result.get("test_suite", "")
        else:
            st.error(f"Error generating test suite: {response.text}")
            return None, None
            
    except Exception as e:
        st.error(f"Failed to generate test suite: {str(e)}")
        return None, None

# Submit feedback and get refined test suite using simplified API
def submit_feedback_and_refine(query, generation_type, product_a, feedback_text, product_b=None):
    """Submit feedback and get refined test suite using the simplified API structure"""
    try:
        # Prepare feedback payload
        payload = {
            "feedback_text": feedback_text,
            "query": query,
            "generation_type": generation_type,
            "product_a": product_a
        }

        # Add product_b for similar products
        if generation_type == "Similar Products" and product_b:
            payload["product_b"] = product_b
        # Submit feedback to API
        response = requests.post(
            f"{API_BASE_URL}/feedback_suite/",
            json=payload,
            headers={"Content-Type": "application/json"}
        )

         # Process response
        if response.status_code == 200:
            result = response.json()
            return True, result.get("test_suite", "")
        else:
            st.error(f"Error submitting feedback: {response.text}")
            return False, None
            
    except Exception as e:
        st.error(f"Failed to submit feedback: {str(e)}")
        return False, None

# ============================================================================
# APPLICATION INITIALIZATION
# ============================================================================

# Initialize session state
init_session_state()

# Fetch product titles from MongoDB
# Returns two lists: test_case_titles and non_test_case_titles
test_case_titles, non_test_case_titles = get_unique_products_from_mongo()

# ============================================================================
# SIDEBAR CONFIGURATION
# ============================================================================

with st.sidebar:
    st.markdown("## Suite Configuration")
    # Test case count configuration
    # Only allow changes in initial workflow state
    if st.session_state.workflow_step == 0:
        # Only allow changing max_test_cases in initial state
        max_test_cases = st.slider("Number of Test Cases", min_value=2, max_value=20, value=10)
        st.session_state.current_max_test_cases = max_test_cases
    else:
        # Show current value but don't allow changes during workflow
        st.markdown(f"**Current Test Cases:** {st.session_state.current_max_test_cases}")
        
        # Show workflow info
        with st.expander("📊 Workflow Info"):
            st.json({
                "Query": st.session_state.current_query[:50] + "..." if len(st.session_state.current_query) > 50 else st.session_state.current_query,
                "Generation Type": st.session_state.current_generation_type,
                "Product A": st.session_state.current_product_a,
                "Product B": st.session_state.current_product_b if st.session_state.current_product_b else "N/A",
                "Feedback Iterations": len(st.session_state.feedback_history),
                "Workflow Step": st.session_state.workflow_step
            })

# ============================================================================
# MAIN APPLICATION LAYOUT
# ============================================================================

# ============================================================================
# LEFT COLUMN: DOCUMENT UPLOAD AND CONFIGURATION
# ============================================================================

col1, col2 = st.columns([2, 3])

with col1:
    # Document Upload Section
    st.markdown("### 📁 Upload Documents")
    uploaded_files = st.file_uploader(
        "Drag & drop files here or browse",
        type=['pdf', 'docx','doc', 'xlsx', 'xls', 'csv'],
        accept_multiple_files=True,
        key="file_uploader"
    )

    # Smart Filters Section
    st.markdown("### 🔍 Smart Filters")
    # Document title selection
    title_filter = st.selectbox("Document Title", test_case_titles + non_test_case_titles + ['None of The above'])
    # Custom document name input (appears when "None of The above" is selected)
    if title_filter == 'None of The above':
        st.session_state.custom_doc_name = st.text_input("✏️ Enter Document Name", value=st.session_state.custom_doc_name)

    # Document type selection
    type_filter = st.selectbox("Document Type", DOCUMENT_TYPES)

    # Document Actions Section
    st.markdown("### ⚡ Document Actions")
    col_btn1, col_btn2 = st.columns(2)

     # Process Documents Button
    with col_btn1:
        if st.button("🔄 Process Docs"):
            if not uploaded_files:
                st.warning("Please upload documents first!")
            else:
                # Set processing flag to show spinner
                st.session_state.processing = True
                with st.spinner("Processing documents..."):
                    try:
                        # Determine document name for processing
                        document_name = (
                            st.session_state.custom_doc_name
                            if title_filter == 'None of The above'
                            else title_filter
                        )
                        files = [("files", (file.name, file.getvalue(), file.type)) for file in uploaded_files]
                        data = {"doc_type": type_filter, "new_title": document_name}
                        # Submit to document processing API
                        response = requests.post(f"{API_BASE_URL}/upload", files=files, data=data)
                        # Handle response
                        if response.status_code == 200:
                            st.success("Documents processed successfully!")
                        else:
                            st.error(f"Error: {response.text}")
                    except Exception as e:
                        st.error(f"An error occurred: {str(e)}")
                    finally:
                        st.session_state.processing = False
    # Clear All Button                 
    with col_btn2:
        if st.button("🗑️ Clear All"):
            # Reset all workflow-related session state variables
            for key in ['uploaded_docs', 'custom_doc_name', 'generated_test_suite_text', 'generated_content',
                       'workflow_step', 'current_test_suite', 'feedback_submitted',
                       'current_excel', 'feedback_history']:
                if key in st.session_state:
                    if key == 'workflow_step':
                        st.session_state[key] = 0
                    elif key in ['feedback_history']:
                        st.session_state[key] = []
                    else:
                        st.session_state[key] = "" if key != 'current_excel' else None
            # Trigger page rerun to reflect changes
            st.rerun()

    # Generation Parameters Section
    st.markdown("### ⚙️ Generation Parameters")

    # Generation type selection
    generation_type = st.selectbox(
        "Generation Type", 
        GENERATION_TYPES,
        key="generation_type_select"
    )

    # Product selection based on generation type
    # Different UI elements for different generation strategies
    if generation_type == "Existing Products":
        # Single product selection from test case titles
        product_a = st.selectbox(
            "Select Product", 
            test_case_titles,
            key="existing_product_select"
        )
        product_b = None

    elif generation_type == "New Products":
        # Single product selection from non-test case titles
        product_a = st.selectbox(
            "Select Product", 
            non_test_case_titles,
            key="new_product_select"
        )
        product_b = None

    else: # Similar Products
        col_sim1, col_sim2 = st.columns(2)
        # Two-column layout for selecting both products
        with col_sim1:
            product_a = st.selectbox(
                "Product A (Existing)", 
                test_case_titles,
                key="similar_product_a_select"
            )
        with col_sim2:
            product_b = st.selectbox(
                "Product B (New)", 
                non_test_case_titles,
                key="similar_product_b_select"
            )

# ============================================================================
# RIGHT COLUMN: QUERY INPUT AND RESULTS
# ============================================================================
with col2:
    st.markdown("### 💬 Enter Your Query")
    
    # Use session state to preserve query text across interactions
    if 'query_text' not in st.session_state:
        st.session_state.query_text = ''
    
    query_text = st.text_area(
        "Describe the test suite you'd like to generate...",
        placeholder='Example: "Generate test suite for login functionality covering all scenarios"',
        height=150,
        value=st.session_state.query_text,
        key="query_input"
    )
    
    # Update session state when query changes
    st.session_state.query_text = query_text

    # ========================================================================
    # WORKFLOW IMPLEMENTATION
    # ========================================================================
    
    # Initial Test Suite Generation
    # Only show generate button in initial workflow state
    if query_text.strip() and st.session_state.workflow_step == 0:
        if st.button("🚀 Generate Initial Test Suite", use_container_width=True, type="primary"):
            with st.spinner(f"Generating initial test suite with {st.session_state.current_max_test_cases} cases..."):
                session_id, test_suite = generate_initial_test_suite(
                    query_text, generation_type, product_a, st.session_state.current_max_test_cases, product_b
                )
                
                if session_id and test_suite:
                    # Update session state with generated data
                    st.session_state.current_test_suite = test_suite
                    st.session_state.generated_test_suite_text = test_suite
                    st.session_state.current_query = query_text
                    st.session_state.current_generation_type = generation_type
                    st.session_state.current_product_a = product_a
                    st.session_state.current_product_b = product_b
                    st.session_state.workflow_step = 1
                    
                    #Create Excel file for download
                    excel_data = create_excel_from_test_suite(
                        test_suite, title_filter, st.session_state.custom_doc_name, st.session_state.current_max_test_cases
                    )
                    if excel_data:
                        st.session_state.current_excel = excel_data
                    
                    st.rerun()

     # Generated Test Suite Display Section
    st.markdown("### 🎯 Generated Test Suite")
    
    # Display generated test suite
    if st.session_state.workflow_step >= 1 and st.session_state.current_test_suite:
        st.success(f"✅ Test suite generated successfully with {st.session_state.current_max_test_cases} test cases!")
        
        # Display test suite in table format
        raw_text = st.session_state.current_test_suite

        # Split the text into sections based on test case headers
        test_cases = re.split(r"=+\s*## Test Case \d+/\d+\s*=+", raw_text)
        test_cases = [tc.strip() for tc in test_cases if tc.strip()]

        # Collect all HTML tables
        all_tables_html = ""

        for idx, case in enumerate(test_cases, start=1):
            lines = case.splitlines()
            table_lines = [line for line in lines if line.strip().startswith('|') and not line.strip().startswith('|-')]

            rows = []
            for line in table_lines:
                cells = [cell.strip() for cell in line.strip().split('|')[1:-1]]
                if cells:
                    rows.append(cells)

            if len(rows) > 1:
                headers = rows[0]
                data = rows[1:]
                df = pd.DataFrame(data, columns=headers)
                table_html = df.to_html(index=False, escape=False)
                all_tables_html += f"<h4>🧪 Test Case {idx}</h4>{table_html}<br>"
            else:
                all_tables_html += f"<h4>🧪 Test Case {idx}</h4><p>No valid table found.</p><br>"

        # Display all tables in one scrollable box
        st.markdown(
            f"""
            <div style="border:1px solid #ccc; padding:10px; max-height:400px; overflow:auto;">
                {all_tables_html}
            </div>
            """,
            unsafe_allow_html=True
        )

        # Download Excel button (moved above feedback section)
        if st.session_state.get("current_excel"):
            st.download_button(
                label="📥 Download Test Suite as Excel",
                data=st.session_state.current_excel,
                file_name=f"test_suite_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    else:
        st.markdown("No test suite generated yet.")

   # ========================================================================
    # FEEDBACK MECHANISM
    # ========================================================================
    
    # Feedback section - visible after initial generation
    if st.session_state.workflow_step >= 1:
        st.markdown("### 💬 Provide Your Feedback")
        
        # Show feedback history if any
        if st.session_state.feedback_history:
            with st.expander(f"📝 Previous Feedback History ({len(st.session_state.feedback_history)} iterations)"):
                for i, feedback in enumerate(st.session_state.feedback_history, 1):
                    st.markdown(f"**Iteration {i}:** {feedback['feedback']}")
        
        with st.form("feedback_form", clear_on_submit=True):
            feedback_text = st.text_area(
                "What improvements would you like to see?",
                placeholder="Example: 'Add more edge cases for error handling', 'Include boundary value testing scenarios'",
                height=120,
                help="Be specific about what you'd like to see improved or added",
                key="feedback_input"
            )
            
            submitted = st.form_submit_button("🎯 Generate Refined Test Suite", use_container_width=True, type="primary")
            
            if submitted and feedback_text.strip():
                with st.spinner("Processing feedback and generating refined test suite..."):
                    try:
                        # First store the feedback with previous test suite
                        feedback_response = requests.post(
                            "http://127.0.0.1:8000/store-feedback",
                            data={
                                "product_title": st.session_state.current_product_a,
                                "feature": st.session_state.current_query,
                                "feedback": feedback_text,
                                "previous_test_case": st.session_state.current_test_suite,
                                "user_prompt": st.session_state.current_query
                            }
                        )
                        
                        if feedback_response.status_code != 200:
                            st.error(f"Failed to store feedback: {feedback_response.text}")
                            st.stop()
                        
                        # Then generate refined test suite with the feedback
                        refined_response = requests.post(
                            "http://127.0.0.1:8000/process_query/",
                            data={
                                "query": st.session_state.current_query,
                                "operation_type": "test_suite_generation",
                                "generation_type": st.session_state.current_generation_type,
                                "product_a": st.session_state.current_product_a,
                                "product_b": st.session_state.current_product_b,
                                "feedback_items": [feedback_text],
                                "previous_test_case": st.session_state.current_test_suite,
                                "max_test_cases": st.session_state.current_max_test_cases
                            }
                        )
                        
                        if refined_response.status_code == 200:
                            refined_data = refined_response.json()
                            refined_test_suite = refined_data.get("test_suite", "")
                            
                            # Update session state
                            st.session_state.current_test_suite = refined_test_suite
                            st.session_state.feedback_history.append({
                                "feedback": feedback_text,
                                "timestamp": datetime.now().isoformat()
                            })
                            
                            # Update Excel file
                            excel_data = create_excel_from_test_suite(
                                refined_test_suite, 
                                title_filter, 
                                st.session_state.custom_doc_name,
                                st.session_state.current_max_test_cases
                            )
                            if excel_data:
                                st.session_state.current_excel = excel_data
                            
                            st.success("✅ Test suite refined successfully!")
                            st.rerun()
                        else:
                            st.error(f"❌ Failed to generate refined test suite: {refined_response.text}")
                    except Exception as e:
                        st.error(f"An error occurred: {str(e)}")
    
        # Display refined test suite inside the feedback section (after form submission)
        if len(st.session_state.feedback_history) > 0:
            st.markdown("#### 🎯 Refined Test Suite")
            
            # Display refined test suite in table format
            raw_text = st.session_state.current_test_suite
            test_cases = re.split(r"=+\s*## Test Case \d+/\d+\s*=+", raw_text)
            test_cases = [tc.strip() for tc in test_cases if tc.strip()]

            # Collect all HTML tables
            all_tables_html = ""

            for idx, case in enumerate(test_cases, start=1):
                lines = case.splitlines()
                table_lines = [line for line in lines if line.strip().startswith('|') and not line.strip().startswith('|-')]

                rows = []
                for line in table_lines:
                    cells = [cell.strip() for cell in line.strip().split('|')[1:-1]]
                    if cells:
                        rows.append(cells)

                if len(rows) > 1:
                    headers = rows[0]
                    data = rows[1:]
                    df = pd.DataFrame(data, columns=headers)
                    table_html = df.to_html(index=False, escape=False)
                    all_tables_html += f"<h4>🧪 Test Case {idx}</h4>{table_html}<br>"
                else:
                    all_tables_html += f"<h4>🧪 Test Case {idx}</h4><p>No valid table found.</p><br>"

            # Display refined tables
            st.markdown(
                f"""
                <div style="border:1px solid #ccc; padding:10px; max-height:400px; overflow:auto;">
                    {all_tables_html}
                </div>
                """,
                unsafe_allow_html=True
            )
            
            # Download button for refined test suite inside feedback section
            if st.session_state.get("current_excel"):
                st.download_button(
                    label="📥 Download Refined Test Suite as Excel",
                    data=st.session_state.current_excel,
                    file_name=f"refined_test_suite_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="download_refined_in_feedback"
                )


    # Reset Workflow Button
    if st.session_state.workflow_step > 0:
        st.markdown("---")
        if st.button("🔄 Start New Workflow", use_container_width=True):
            # Reset all workflow states
            st.session_state.workflow_step = 0
            st.session_state.current_test_suite = ''
            st.session_state.feedback_submitted = False
            st.session_state.current_feedback_text = ''
            st.session_state.generated_test_suite_text = ''
            st.session_state.current_excel = None
            st.session_state.feedback_history = []
            st.session_state.current_max_test_cases = 10  # Reset to default
            st.session_state.query_text = ''  # Reset query text
            st.rerun()

    # Navigation
    st.markdown("---")
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        if st.button("🏠 Go to Main Menu", use_container_width=True):
            st.switch_page("Home.py")
    
    with col_nav2:
        if st.button("📊 View Feedback Files", use_container_width=True):
            # Display feedback data from local files
            feedback_files = ['feedback_data_suite.json', 'feedback_data.json']
            
            for file_name in feedback_files:
                try:
                    with open(file_name, 'r') as f:
                        feedback_data = json.load(f)
                    
                    if feedback_data:
                        st.markdown(f"### 📄 {file_name}")
                        for i, feedback in enumerate(feedback_data[-5:], 1):  # Show last 5 entries
                            with st.expander(f"Entry {i} - {feedback.get('timestamp', '')[:10]}"):
                                st.markdown(f"**Query:** {feedback.get('query', 'N/A')}")
                                st.markdown(f"**Feedback:** {feedback.get('feedback_text', 'N/A')}")
                                st.markdown(f"**Generation Type:** {feedback.get('generation_type', 'N/A')}")
                                st.markdown(f"**Product A:** {feedback.get('product_a', 'N/A')}")
                                st.markdown(f"**Product B:** {feedback.get('product_b', 'N/A')}")
                        st.markdown(f"**Total Entries:** {len(feedback_data)}")
                    
                except FileNotFoundError:
                    st.info(f"No {file_name} found.")
                except Exception as e:
                    st.error(f"Error reading {file_name}: {str(e)}")
