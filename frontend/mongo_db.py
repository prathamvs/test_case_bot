#The code connects to a MongoDB database and categorizes products based on whether they have test case documentation or not.
from pymongo import MongoClient # MongoDB Python driver for database operations
import streamlit as st # Streamlit framework for web app development

#Initialize MongoDB connection
#Database Connection (init_mongo_connection)
#Establishes a connection to a local MongoDB instance
#Uses @st.cache_resource to maintain a single connection across all user sessions (performance optimization)
#Connects to a database named "original_db"
#Returns the database object or None if connection fails

#Initialize MongoDB connection
@st.cache_resource # Streamlit decorator to cache the database connection across sessions
def init_mongo_connection():
    try:
        # Create MongoDB client connection
        # Update this connection string with your actual MongoDB URI
        client = MongoClient("mongodb://localhost:27017/") # Update with your MongoDB connection string
        # Select the specific database to work with
        db = client["original_db"]
        return db
    except Exception as e:
        # Display error message in Streamlit UI if connection fails
        st.error(f"Failed to connect to MongoDB: {e}")
        return None

#Product Categorization (get_unique_products_from_mongo)
#Queries a collection called "documents"
#Separates products into two categories:
#Products WITH test cases: Finds all unique product titles where doc_type = "test_case"
#Products WITHOUT test cases: Finds all other unique product titles not in the first category
#Returns both lists sorted alphabetically

def get_unique_products_from_mongo():
    # Get database connection
    db = init_mongo_connection()
    # Return empty lists if database connection failed
    if db is None:
        return [], []

    # Based on the queries, the MongoDB collection "documents" appears to have this structure:   
    try:
        # Query 1: Get all distinct product titles that have test_case documents
        # This finds unique 'title' values where 'doc_type' field equals 'test_case'
        test_case_titles = db.documents.distinct(
            "title", 
            {"doc_type": "test_case"}
        )
        
        # Query 2: Get all distinct product titles that DON'T have test_case documents
        # This finds unique 'title' values where the title is NOT in the test_case_titles list

        non_test_case_titles = db.documents.distinct(
            "title", 
            {"title": {"$nin": test_case_titles}}
        )

        # Return both lists sorted alphabetically for consistent UI display
        return sorted(test_case_titles), sorted(non_test_case_titles)
    
    except Exception as e:
         # Display error message in Streamlit UI if database query fails
        st.error(f"Failed to fetch products from MongoDB: {e}")
        return [], []
