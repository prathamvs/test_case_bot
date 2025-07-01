#Creates an attractive landing page with 
# three main features presented as interactive
# cards that users can click to navigate to 
# different sections of the application.

# Import required libraries
import streamlit as st # Streamlit framework for web app development
from PIL import Image # Python Imaging Library (not used in this code but imported)

# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

# Configure page
st.set_page_config(
    page_title="AI Generative Chatbot", # Browser tab title
    page_icon="🤖", # Browser tab icon (robot emoji)
    layout="wide", # Use full width of the browser
    initial_sidebar_state="collapsed" # Start with sidebar hidden
)

# ============================================================================
# CUSTOM CSS STYLING
# ============================================================================

# Apply custom CSS for enhanced visual design
st.markdown("""
<style>
    /* Hide Streamlit default elements */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Custom styling */
    .stApp {
        background-color: #ffffff;
    }
    
    /* Header styling */
    .header {
        background: linear-gradient(90deg, #667eea 0%, #3dcd58 100%);
        color: white;
        text-align: center;
        padding: 30px;
        margin: 20px 0px;
        border-radius: 15px;
        box-shadow: 0 8px 25px rgba(0,0,0,0.1);
    }
    
    .header h1 {
        font-size: 3rem;
        margin-bottom: 10px;
        font-weight: 600;
        color: white !important;
    }
    
    .header h3 {
        font-size: 1.5rem;
        opacity: 1.9;
        color: white !important;
        margin: 0;
    }
    
    /* Card container with relative positioning */
    .card-container {
        position: relative;
        height: 100%;
        margin: 10px;
    }
    
    /* Mode card styling */
    .mode-card {
        background: white;
        padding: 50px 30px;
        border-radius: 20px;
        text-align: center;
        border: 3px solid #e0e0e0;
        box-shadow: 0 8px 25px rgba(0,0,0,0.1);
        transition: all 0.3s ease;
        cursor: pointer;
        height: 100%;
        pointer-events: none; /* Allow clicks to pass through to button */
    }
    
    .mode-card:hover {
        transform: translateY(-10px);
        box-shadow: 0 15px 35px rgba(102, 126, 234, 0.3);
        border-color: #667eea;
    }
    
    .mode-icon {
        font-size: 80px;
        margin-bottom: 25px;
        display: block;
        filter: drop-shadow(0 4px 8px rgba(0,0,0,0.1));
    }
    
    .mode-card h3 {
        font-size: 24px;
        margin-bottom: 20px;
        font-weight: 600;
        color: #333;
    }
    
    .mode-card p {
        font-size: 16px;
        line-height: 1.6;
        color: #666;
        opacity: 0.9;
        margin: 0;
    }
    
    /* Button styling - positioned absolutely to cover card */
    .stButton {
        position: absolute !important;
        top: 0;
        left: 0;
        width: 100% !important;
        height: 100% !important;
        z-index: 2;
    }
    
    .stButton > button {
        width: 600px !important;
        height: 300px !important;
        background: transparent !important;
        border: none !important;
        padding: 0 !important;
        opacity: 0 !important; /* Make button invisible */
    }
    
    /* Remove button focus outline */
    .stButton > button:focus {
        outline: none !important;
        box-shadow: none !important;
    }
    .st-key-test_case, .st-key-test_suite, .st-key-info_retrieval {
        width: 200px !important;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# PAGE HEADER
# ============================================================================

# Display main page header with gradient background
st.markdown("""
<div class="header">
    <h1>🤖 AI Generative Chatbot</h1>
    <h3>Intelligent Testing & Information Assistant</h3>
</div>
""", unsafe_allow_html=True)
# Add spacing after header
st.markdown("<br><br>", unsafe_allow_html=True)

# ============================================================================
# MAIN FEATURE CARDS
# ============================================================================

# Create three columns for mode cards
col1, col2, col3 = st.columns(3)

# COLUMN 1: Test Case Generation Feature
with col1:
    # Container with card and button
    container = st.container()
    with container:
        # Invisible button covering the entire card
        # When clicked, navigates to test case generation page
        if st.button(" ", key="test_case"):
            st.switch_page("pages/test_case_app.py")
        
        # Visible card
        st.markdown(f"""
        <div class="mode-card" style="margin-top: -60px;">
            <span class="mode-icon">💬</span>
            <h2>Test Case Generation</h2>
            <h3>Generate comprehensive test cases with detailed steps,actions and expected results</h3>
 
        </div>
        """, unsafe_allow_html=True)

# COLUMN 2: Test Suite Generation Feature
with col2:
    container = st.container()
    with container:
        # Invisible button for test suite feature
        if st.button(" ", key="test_suite"):
            st.switch_page("pages/test_suite_app.py")

        # Test suite card content
        st.markdown(f"""
        <div class="mode-card" style="margin-top: -60px;">
            <span class="mode-icon">📋</span>
            <h2>Test Suite Generation</h2>
            <h3>Generates a comprehensive test suites to ensure full coverage and reliability.</h3>
        </div>
        """, unsafe_allow_html=True)

# COLUMN 3: Q/A Assistant Feature
with col3:
    container = st.container()
    with container:
        # Invisible button for information retrieval feature
        if st.button(" ", key="info_retrieval"):
            st.switch_page("pages/information_retireval.py")
        # Q/A assistant card content
        st.markdown(f"""
        <div class="mode-card" style="margin-top: -60px;">
            <span class="mode-icon">🔍</span>
            <h2>Q/A Assistant</h2>
            <h3>An intelligent platform that delivers accurate, real-time answers to user queries</h3>
        </div>
        """, unsafe_allow_html=True)

# ============================================================================
# FOOTER SPACING
# ============================================================================

# Footer information
st.markdown("<br><br>", unsafe_allow_html=True)
