#This is a Streamlit-based Document Q&A application that 
#allows users to upload documents and ask questions 
# about their content using AI. Here's what it does:

# ============================================================================
# IMPORTS
# ============================================================================
import streamlit as st # Streamlit framework for web app development
import pandas as pd # Data manipulation library (not used in this code)
from typing import List, Dict # Type hints for better code documentation
import time # Time utilities (not used in this code)
import requests # HTTP library for API calls to backend
from mongo_db import get_unique_products_from_mongo # Custom MongoDB integration function

# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

# Configure the Streamlit page settings
st.set_page_config(
    page_title="DocuBot - AI Document Q&A", # Browser tab title
    page_icon="🤖",                          # Browser tab icon
    layout="wide", # Use full browser width
    initial_sidebar_state="collapsed" # Start with sidebar hidden
)

# ============================================================================
# CUSTOM CSS STYLING
# ============================================================================

# Apply custom CSS for enhanced visual design
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 10px;
        margin-bottom: 2rem;
        text-align: center;
        color: white;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .main-header h1 { font-size: 2.5rem; font-weight: 700; }
    .main-header p { font-size: 1.2rem; opacity: 0.9; }
    .upload-section, .filter-section {
        padding: 1.5rem; border-radius: 10px; margin-bottom: 1rem;
    }
    .upload-section { background: #f8f9fa; border: 2px dashed #e9ecef; }
    .filter-section {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    }
    .chat-container {
        background: white; border-radius: 10px; padding: 1rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1); min-height: 400px;
    }
    .user-message, .bot-message {
        color: white; padding: 0.8rem 1rem; border-radius: 18px;
        margin: 0.5rem 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .user-message {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        margin-left: 20%;
    }
    .bot-message {
        background: linear-gradient(90deg, #f093fb 0%, #f5576c 100%);
        margin-right: 20%;
    }
    .stButton > button {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white; border: none; border-radius: 25px;
        padding: 0.5rem 2rem; font-weight: 600;
    }
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

# Initialize session state variables to persist data across interactions
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'uploaded_docs' not in st.session_state:
    st.session_state.uploaded_docs = []
if 'processing' not in st.session_state:
    st.session_state.processing = False
if 'custom_doc_name' not in st.session_state:
    st.session_state.custom_doc_name = ""

# ============================================================================
# PAGE HEADER
# ============================================================================

# Display main application header
st.markdown("""
<div class="main-header">
    <h1>🤖 Q&A DocuBot Prompt</h1>
    <p>Intelligent Document Q&A Assistant</p>
</div>
""", unsafe_allow_html=True)

# ============================================================================
# DATA RETRIEVAL
# ============================================================================

# Fetch available document titles from MongoDB
# Returns two lists: documents with test cases and documents without test cases

test_case_titles, non_test_case_titles = get_unique_products_from_mongo()
# ============================================================================
# MAIN LAYOUT - TWO COLUMN DESIGN
# ============================================================================

# Create two-column layout: controls on left, chat on right
col1, col2 = st.columns([1, 2])

# ============================================================================
# LEFT COLUMN - DOCUMENT UPLOAD AND FILTERS
# ============================================================================

with col1:
    # DOCUMENT UPLOAD SECTION
    st.markdown("### 📁 Upload Documents")
    
    # File uploader widget supporting multiple files and specific types
    uploaded_files = st.file_uploader("Upload files", 
                                    accept_multiple_files=True, 
                                    type=['pdf', 'docx', 'doc',"xlsx","csx",'xls'],
                                    key="file_uploader")

     # DOCUMENT FILTERING SECTION
    st.markdown("### 🔍 Smart Filters")
    # Document type selection dropdown   
    doc_types = ['test_case', 'product_spec', 'userguide']
    selected_doc_type = st.selectbox("📋 Document Type", doc_types)

    # Document name selection dropdown (combines MongoDB data with custom option)
    title_filter = st.selectbox("📄 Document Title", test_case_titles + non_test_case_titles + ['None of The above'])
    
    # Custom document name input (shown only when "None of The above" is selected)
    if title_filter == 'None of The above':
        st.session_state.custom_doc_name = st.text_input("✏️ Enter Document Name", value=st.session_state.custom_doc_name)

    # ACTION BUTTONS SECTION
    st.markdown("### ⚡ Actions")
    col_btn1, col_btn2 = st.columns(2)

    with col_btn1:
        if st.button("🔄 Process Docs", use_container_width=True):
            # Validation: Check if files are uploaded
            if not uploaded_files:
                st.warning("Please upload documents first!")
            else:
                st.session_state.processing = True
                # Show processing spinner while making API call
                with st.spinner("Processing documents..."):
                    try:
                        # Determine document name (custom or selected)
                        document_name = (
                            st.session_state.custom_doc_name
                            if title_filter == 'None of The above'
                            else title_filter
                        )
                        # Prepare files for API upload
                        files = [("files", (file.name, file.getvalue(), file.type)) for file in uploaded_files]
                        # Prepare metadata for API
                        data = {"doc_type": selected_doc_type, "new_title": document_name}
                        # Make API call to backend for document processing
                        response = requests.post("http://127.0.0.1:8000/upload", files=files, data=data)
                        # Handle API response
                        if response.status_code == 200:
                            st.success("Documents processed successfully!")
                            # Update uploaded files list
                            current_uploaded_names = [doc['name'] for doc in st.session_state.uploaded_docs]
                            for file in uploaded_files:
                                if file.name not in current_uploaded_names:
                                    st.session_state.uploaded_docs.append({
                                        'name': file.name, 
                                        'type': file.type, 
                                        'size': file.size
                                    })
                        else:
                            st.error(f"Error: {response.text}")
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
                    finally:
                        st.session_state.processing = False

    # CLEAR ALL BUTTON
    with col_btn2:
        if st.button("🗑️ Clear All", use_container_width=True):
            # Reset all session state variables
            st.session_state.chat_history = []
            st.session_state.uploaded_docs = []
            st.session_state.custom_doc_name = ""
            st.rerun()# Refresh the page to reflect changes

    # Display uploaded files
    if st.session_state.uploaded_docs:
        st.markdown("**Uploaded Files:**")
        for doc in st.session_state.uploaded_docs:
            st.markdown(f"- {doc['name']} ({doc['type']}, {doc['size']/1024:.2f} KB)")

# ============================================================================
# RIGHT COLUMN - CHAT INTERFACE
# ============================================================================

with col2:
    # QUERY INPUT SECTION
    st.markdown("### 💬 Ask DocuBot Anything!")
    # Text area for user questions
    query_input = st.text_area(
        "", placeholder="Ask about your documents...", height=120, key="query_input"
    )

     # ACTION BUTTONS ROW
    col_submit, col_clear, col_download = st.columns([2, 1, 1])

    # SUBMIT QUERY BUTTON
    with col_submit:
        if st.button("✨ Ask DocuBot", use_container_width=True):
            if query_input.strip():
                    with st.spinner("🧠 Analyzing..."):
                        try:
                            # Make API call to backend for question answering
                            response = requests.post(
                                "http://127.0.0.1:8000/ask",
                                data={"question": query_input}
                            )
                            # Handle API response
                            if response.status_code == 200:
                                answer = response.json()["answer"]
                                # Add successful Q&A pair to chat history
                                st.session_state.chat_history.append((query_input, answer))
                            else:
                                st.session_state.chat_history.append((query_input, f"❌ API Error: {response.text}"))
                        except Exception as e:
                            # Add exception error to chat history
                            st.session_state.chat_history.append((query_input, f"❌ Error: {str(e)}"))
                        st.rerun()# Refresh page to show new message
            else:
                st.warning("⚠️ Enter a question!")

    # CLEAR INPUT BUTTON
    with col_clear:
        if st.button("🧹 Clear", use_container_width=True):
            st.session_state.query_input = ""
            st.rerun()

    # DOWNLOAD CONVERSATION BUTTON
    with col_download:
        if st.session_state.chat_history:
            # Prepare conversation data for download
            data = "\n\n".join([f"Q{i+1}: {q}\nA{i+1}: {a}" for i, (q, a) in enumerate(st.session_state.chat_history)])
            st.download_button("📥 Download", data=data, file_name="docubot_conversation.txt", mime="text/plain", use_container_width=True)
        else:
            # Show disabled button when no conversation exists
            st.button("📥 Download", use_container_width=True, disabled=True)

    # CONVERSATION HISTORY DISPLAY
    if st.session_state.chat_history:
        st.markdown("### 💬 Conversation History")
        # Display each question-answer pair as chat bubbles
        for q, a in st.session_state.chat_history:
            st.markdown(f'<div class="user-message">👤 {q}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="bot-message">🤖 {a}</div>', unsafe_allow_html=True)

# ============================================================================
# FOOTER SECTION
# ============================================================================

# Horizontal separator
st.markdown("---")
footer_col1, footer_col2 = st.columns(2)
# DOWNLOAD FULL CONVERSATION BUTTON (Footer)
with footer_col1:
    if st.session_state.chat_history:
        # Prepare full conversation for download
        download_data = "\n\n".join([f"Q{i+1}: {q}\nA{i+1}: {a}" for i, (q, a) in enumerate(st.session_state.chat_history)])
        st.download_button("📥 Download Full Conversation", data=download_data, file_name="docubot_conversation.txt", mime="text/plain", use_container_width=True)

# NAVIGATION BUTTON (Footer)
with footer_col2:
    if st.button("🏠 Go to Main Menu"):
        st.switch_page("Home.py")
