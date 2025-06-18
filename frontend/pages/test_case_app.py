import streamlit as st
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from io import BytesIO
import json
from datetime import datetime
import uuid

from mongo_db import get_unique_products_from_mongo

# Constants
DOCUMENT_TYPES = ['test_case', 'product_spec', 'userguide']
GENERATION_TYPES = ["Existing Products", "Similar Products","New Products"]
OPERATION_TYPES = ["test_case_generation"]

# Page configuration
st.set_page_config(
    page_title="Test Case Generation Assistant",
    page_icon="🧪",
    layout="wide"
)

# Custom CSS and Header
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
    <h1>🧪 Test Case Generation Assistant</h1>  
    <p>Generate comprehensive test cases with AI-powered feedback workflow</p>  
</div>  
""", unsafe_allow_html=True)

# Initialize session state
def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        'custom_doc_name': '',
        'uploaded_docs': False,
        'generated_test_cases_text': '',
        'generated_content': '',
        'processing': False,
        'feedback_submitted': False,
        'feedback_data': [],
        'session_id': None,
        'workflow_step': 0,  # 0: initial, 1: test_cases_generated, 2+: feedback_iterations
        'initial_test_cases': '',  # Store the initial version of test cases (never changes)
        'refined_test_cases': '',  # Store the refined version of test cases
        'current_query': '',
        'current_generation_type': '',
        'current_product_a': '',
        'current_product_b': '',
        'feedback_text': '',
        'initial_excel': None,  # Store the initial Excel file
        'refined_excel': None,  # Store the refined Excel file
        'feedback_history': []  # Store all feedback iterations
    }
    
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

# Function to create Excel from test cases
def create_excel_from_test_cases(test_cases, title_filter, custom_doc_name):
    """Create Excel file from test cases"""
    try:
        markdown_table = test_cases
        html_table = markdown_table.replace("<br>", " ").replace("\\n", " ")
        
        rows = []
        for line in html_table.strip().split('\n'):
            if line.strip().startswith('|') and not line.strip().startswith('|-'):
                cells = [cell.strip() for cell in line.strip().split('|')[1:-1]]
                if cells:
                    rows.append(cells)

        if len(rows) > 1:
            headers = rows[0]
            data = rows[1:]
            df = pd.DataFrame(data, columns=headers)

            # Add Product Title column
            product_title = (
                custom_doc_name
                if title_filter == 'None of The above'
                else title_filter
            )
            product_column = [product_title] + [""] * (len(df) - 1)
            df.insert(0, "Product Title", product_column)

            # Save DataFrame as Excel in memory
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, index=False, sheet_name="Feature1_TC")
            return output.getvalue()
        else:
            return None
    except Exception as e:
        st.warning(f"Could not create Excel format: {str(e)}")
        return None

# Generate initial test cases - CORRECTED to use existing endpoint
def generate_initial_test_cases(query, generation_type, product_a, product_b=None):
    """Generate initial test cases using the existing API endpoint"""
    try:
        data = {
            "query": query,
            "operation_type": "test_case_generation",
            "generation_type": generation_type,
            "product_a": product_a
        }
        if generation_type == "Similar Products" and product_b:
            data["product_b"] = product_b
            
        # Use the correct endpoint that exists in app.py
        response = requests.post(
            "http://127.0.0.1:8000/process_query/",
            data=data  # Use form data as expected by the endpoint
        )
        
        if response.status_code == 200:
            result = response.json()
            # Generate a session ID for tracking
            session_id = str(uuid.uuid4())
            test_cases = result.get("test_case", "")
            return session_id, test_cases
        else:
            st.error(f"Error generating test cases: {response.text}")
            return None, None
            
    except Exception as e:
        st.error(f"Failed to generate test cases: {str(e)}")
        return None, None

# Save feedback to file (local storage for now)
def submit_feedback(session_id, feedback_items, additional_comments=""):
    """Submit feedback using local storage since API endpoint doesn't exist"""
    try:
        feedback_data = {
            "session_id": session_id,
            "feedback_items": feedback_items,
            "additional_comments": additional_comments,
            "timestamp": datetime.now().isoformat(),
            "query": st.session_state.current_query,
            "generation_type": st.session_state.current_generation_type,
            "product_a": st.session_state.current_product_a,
            "product_b": st.session_state.current_product_b
        }
        
        # Save to local file
        if save_feedback_to_file(feedback_data):
            return True, "Feedback submitted successfully"
        else:
            return False, "Failed to save feedback"
            
    except Exception as e:
        st.error(f"Failed to submit feedback: {str(e)}")
        return False, None

# Generate refined test cases - MODIFIED to use existing endpoint with feedback
def generate_refined_test_cases(session_id, feedback_text):
    """Generate refined test cases based on feedback using the existing endpoint"""
    try:
        # Create a modified query that includes the feedback
        original_query = st.session_state.current_query
        refined_query = f"{original_query}\n\nAdditional requirements based on feedback: {feedback_text}"
        
        data = {
            "query": refined_query,
            "operation_type": "test_case_generation",
            "generation_type": st.session_state.current_generation_type,
            "product_a": st.session_state.current_product_a,
            "feedback_items": [feedback_text] # Include feedback items in the request
        }
        
        if st.session_state.current_generation_type == "Similar Products" and st.session_state.current_product_b:
            data["product_b"] = st.session_state.current_product_b
        
        # Use the same endpoint but with refined query
        response = requests.post(
            "http://127.0.0.1:8000/process_query/",
            data=data
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("test_case", "")
        else:
            st.error(f"Error generating refined test cases: {response.text}")
            return None
            
    except Exception as e:
        st.error(f"Failed to generate refined test cases: {str(e)}")
        return None


# Save feedback to file (for local storage)
def save_feedback_to_file(feedback_data):
    """Save feedback data to a JSON file"""
    try:
        try:
            with open('feedback_data.json', 'r') as f:
                existing_feedback = json.load(f)
        except FileNotFoundError:
            existing_feedback = []
        
        existing_feedback.append(feedback_data)
        
        with open('feedback_data.json', 'w') as f:
            json.dump(existing_feedback, f, indent=2)
        
        return True
    except Exception as e:
        st.error(f"Error saving feedback: {str(e)}")
        return False

# Initialize session state
init_session_state()

# Fetch titles
test_case_titles, non_test_case_titles = get_unique_products_from_mongo()

# Layout
col1, col2 = st.columns([2, 3])

with col1:
    st.markdown("### 📁 Upload Documents")
    uploaded_files = st.file_uploader(
        "Drag & drop files here or browse",
        type=['pdf', 'docx','doc','xlsx','csv'],
        accept_multiple_files=True,
        key="file_uploader"
    )

    st.markdown("### 🔍 Smart Filters")
    title_filter = st.selectbox("Document Title", test_case_titles + non_test_case_titles + ['None of The above'])
    if title_filter == 'None of The above':
        st.session_state.custom_doc_name = st.text_input("✏️ Enter Document Name", value=st.session_state.custom_doc_name)

    type_filter = st.selectbox("Document Type", DOCUMENT_TYPES)

    st.markdown("### ⚡ Document Actions")
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 Process Docs"):
            if not uploaded_files:
                st.warning("Please upload documents first!")
            else:
                st.session_state.processing = True
                with st.spinner("Processing documents..."):
                    try:
                        document_name = (
                            st.session_state.custom_doc_name
                            if title_filter == 'None of The above'
                            else title_filter
                        )
                        files = [("files", (file.name, file.getvalue(), file.type)) for file in uploaded_files]
                        data = {"doc_type": type_filter, "new_title": document_name}
                        response = requests.post("http://127.0.0.1:8000/upload", files=files, data=data)
                        if response.status_code == 200:
                            st.success("Documents processed successfully!")
                        else:
                            st.error(f"Error: {response.text}")
                    except Exception as e:
                        st.error(f"An error occurred: {str(e)}")
                    finally:
                        st.session_state.processing = False
    with col_btn2:
        if st.button("🗑️ Clear All"):
            # Reset workflow
            for key in ['uploaded_docs', 'custom_doc_name', 'generated_test_cases_text', 'generated_content',
                       'workflow_step', 'session_id', 'initial_test_cases', 'refined_test_cases', 'feedback_submitted',
                       'initial_excel', 'refined_excel', 'feedback_history']:
                if key in st.session_state:
                    if key == 'workflow_step':
                        st.session_state[key] = 0
                    elif key in ['feedback_history']:
                        st.session_state[key] = []
                    else:
                        st.session_state[key] = "" if key not in ['initial_excel', 'refined_excel'] else None
            st.rerun()

    st.markdown("### ⚙️ Generation Parameters")

    generation_type = st.selectbox(
        "Generation Type", 
        GENERATION_TYPES,
        key="generation_type_select"
    )

    if generation_type == "Existing Products":
        product_a = st.selectbox(
            "Select Product", 
            test_case_titles,
            key="existing_product_select"
        )
        product_b = None

    elif generation_type == "New Products":
        product_a = st.selectbox(
            "Select Product", 
            non_test_case_titles,
            key="new_product_select"
        )
        product_b = None

    else:
        col_sim1, col_sim2 = st.columns(2)
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

with col2:
    st.markdown("### 💬 Enter Your Query")
    query_text = st.text_area(
        "Describe the test cases you'd like to generate...",
        placeholder='Example: "Generate test cases for login functionality including positive and negative scenarios"',
        height=150,
        key="query_input"
    )

    # WORKFLOW IMPLEMENTATION
    
    # Generate Test Cases Button
    if query_text.strip() and st.session_state.workflow_step == 0:
        if st.button("🚀 Generate Initial Test Cases", use_container_width=True, type="primary"):
            with st.spinner("Generating initial test cases..."):
                session_id, test_cases = generate_initial_test_cases(
                    query_text, generation_type, product_a, product_b
                )
                
                if session_id and test_cases:
                    st.session_state.session_id = session_id
                    st.session_state.initial_test_cases = test_cases  # Store initial test cases separately
                    st.session_state.generated_test_cases_text = test_cases
                    st.session_state.current_query = query_text
                    st.session_state.current_generation_type = generation_type
                    st.session_state.current_product_a = product_a
                    st.session_state.current_product_b = product_b
                    st.session_state.workflow_step = 1
                    
                    # Create Excel for initial test cases
                    excel_data = create_excel_from_test_cases(
                        test_cases, title_filter, st.session_state.custom_doc_name
                    )
                    if excel_data:
                        st.session_state.initial_excel = excel_data
                    
                    st.rerun()
    
    # Display INITIAL test cases (these never change)
    if st.session_state.workflow_step >= 1 and st.session_state.initial_test_cases:
        st.success("✅ Test cases generated successfully!")
        
        # Display as table if possible, otherwise as text
        try:
            markdown_table = st.session_state.initial_test_cases  # Always show initial test cases here
            html_table = markdown_table.replace("<br>", " ").replace("\\n", " ")
            
            rows = []
            for line in html_table.strip().split('\n'):
                if line.strip().startswith('|') and not line.strip().startswith('|-'):
                    cells = [cell.strip() for cell in line.strip().split('|')[1:-1]]
                    if cells:
                        rows.append(cells)

            if len(rows) > 1:
                headers = rows[0]
                data = rows[1:]
                df = pd.DataFrame(data, columns=headers)
                st.dataframe(df, use_container_width=True)
            else:
                with st.expander("📋 View Generated Test Cases", expanded=True):
                    st.markdown(st.session_state.initial_test_cases)
        except Exception:
            with st.expander("📋 View Generated Test Cases", expanded=True):
                st.markdown(st.session_state.initial_test_cases)

        # Download Excel button for initial test cases
        if st.session_state.get("initial_excel"):
            st.download_button(
                label="📥 Download Test Cases as Excel",
                data=st.session_state.initial_excel,
                file_name=f"test_cases_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    # FEEDBACK SECTION - This is where refined test cases are shown
    if st.session_state.workflow_step >= 1:
        st.markdown("### 💬 Provide Your Feedback")
        
        if st.session_state.feedback_history:
            with st.expander(f"📝 Previous Feedback History ({len(st.session_state.feedback_history)} iterations)"):
                for i, feedback in enumerate(st.session_state.feedback_history, 1):
                    st.markdown(f"**Iteration {i}:** {feedback['feedback']}")
        
        with st.form("feedback_workflow_form", clear_on_submit=True):
            feedback_text = st.text_area(
                "What improvements would you like to see?",
                placeholder="Example: 'Add more edge cases for error handling' or 'Include boundary value testing scenarios'",
                height=120,
                help="Be specific about what you'd like to see improved or added",
                key="feedback_text_area"
            )
            
            submitted = st.form_submit_button("🎯 Generate Refined Test Cases", use_container_width=True, type="primary")
            
            if submitted and feedback_text.strip():
                with st.spinner("Generating refined test cases based on your feedback..."):
                    try:
                        # Use the latest test cases (refined if available, otherwise initial)
                        current_test_cases = st.session_state.refined_test_cases if st.session_state.refined_test_cases else st.session_state.initial_test_cases
                        
                        # First store the feedback with previous test case
                        feedback_response = requests.post(
                            "http://127.0.0.1:8000/store-feedback",
                            data={
                                "product_title": st.session_state.current_product_a,
                                "feature": st.session_state.current_query,
                                "feedback": feedback_text,
                                "previous_test_case": current_test_cases,
                                "user_prompt": st.session_state.current_query
                            }
                        )
                        
                        if feedback_response.status_code != 200:
                            st.error(f"Failed to store feedback: {feedback_response.text}")
                            st.stop()
                        
                        # Then generate refined test cases with the feedback
                        refined_response = requests.post(
                            "http://127.0.0.1:8000/process_query/",
                            data={
                                "query": st.session_state.current_query,
                                "operation_type": "test_case_generation",
                                "generation_type": st.session_state.current_generation_type,
                                "product_a": st.session_state.current_product_a,
                                "product_b": st.session_state.current_product_b,
                                "feedback_items": [feedback_text],
                                "previous_test_case": current_test_cases
                            }
                        )
                        
                        if refined_response.status_code == 200:
                            refined_data = refined_response.json()
                            refined_test_cases = refined_data.get("test_case", "")
                            
                            # Update session state - store refined test cases separately
                            st.session_state.refined_test_cases = refined_test_cases
                            st.session_state.feedback_history.append({
                                "feedback": feedback_text,
                                "timestamp": datetime.now().isoformat()
                            })
                            
                            # Update Excel file for refined test cases
                            excel_data = create_excel_from_test_cases(
                                refined_test_cases, 
                                title_filter, 
                                st.session_state.custom_doc_name
                            )
                            if excel_data:
                                st.session_state.refined_excel = excel_data
                            
                            st.success("✅ Test cases refined successfully!")
                            st.rerun()
                        else:
                            st.error(f"❌ Failed to generate refined test cases: {refined_response.text}")
                    except Exception as e:
                        st.error(f"An error occurred: {str(e)}")

        
        # Display REFINED test cases inside the feedback section (only if they exist)
        if st.session_state.refined_test_cases:
            st.markdown("#### 🎯 Refined Test Cases")
            try:
                markdown_table = st.session_state.refined_test_cases  # Show refined test cases here
                html_table = markdown_table.replace("<br>", " ").replace("\\n", " ")
                
                rows = []
                for line in html_table.strip().split('\n'):
                    if line.strip().startswith('|') and not line.strip().startswith('|-'):
                        cells = [cell.strip() for cell in line.strip().split('|')[1:-1]]
                        if cells:
                            rows.append(cells)

                if len(rows) > 1:
                    headers = rows[0]
                    data = rows[1:]
                    df = pd.DataFrame(data, columns=headers)
                    st.dataframe(df, use_container_width=True, key="refined_table_in_feedback")
                else:
                    with st.expander("📋 View Refined Test Cases", expanded=True):
                        st.markdown(st.session_state.refined_test_cases)
            except Exception:
                with st.expander("📋 View Refined Test Cases", expanded=True):
                    st.markdown(st.session_state.refined_test_cases)
            
            # Download button for refined test cases inside feedback section
            if st.session_state.get("refined_excel"):
                st.download_button(
                    label="📥 Download Refined Test Cases as Excel",
                    data=st.session_state.refined_excel,
                    file_name=f"refined_test_cases_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
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
            st.session_state.session_id = None
            st.session_state.initial_test_cases = ''
            st.session_state.refined_test_cases = ''
            st.session_state.feedback_submitted = False
            st.session_state.feedback_text = ''
            st.session_state.generated_test_cases_text = ''
            st.session_state.initial_excel = None
            st.session_state.refined_excel = None
            st.session_state.feedback_history = []
            st.rerun()

    # Navigation
    st.markdown("---")
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        if st.button("🏠 Go to Main Menu", use_container_width=True):
            st.switch_page("Home.py")
    
    with col_nav2:
        if st.button("📊 View Feedback History", use_container_width=True):
            try:
                with open('feedback_data.json', 'r') as f:
                    feedback_history = json.load(f)
                    
                if feedback_history:
                    st.markdown("### 📊 Feedback History")
                    for i, feedback in enumerate(reversed(feedback_history[-5:]), 1):  # Show last 5
                        with st.expander(f"Feedback {i} - {feedback.get('timestamp', '')[:10]}"):
                            st.markdown(f"**Query:** {feedback.get('query', 'N/A')}")
                            st.markdown(f"**Feedback:** {feedback.get('feedback_items', 'N/A')}")
                            st.markdown(f"**Session ID:** {feedback.get('session_id', 'N/A')}")
                else:
                    st.info("No feedback history available.")
            except FileNotFoundError:
                st.info("No feedback history available.")