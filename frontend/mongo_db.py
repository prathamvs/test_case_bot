from pymongo import MongoClient
import streamlit as st

#Initialize MongoDB connection
@st.cache_resource
def init_mongo_connection():
    try:
        client = MongoClient("mongodb://localhost:27017/") # Update with your MongoDB connection string
        db = client["main_db"]
        return db
    except Exception as e:
        st.error(f"Failed to connect to MongoDB: {e}")
        return None

def get_unique_products_from_mongo():
    db = init_mongo_connection()
    if db is None:
        return [], []
    
    try:
        # Get all distinct product titles that have test_case documents
        test_case_titles = db.documents.distinct(
            "title", 
            {"doc_type": "test_case"}
        )
        
        # Get all distinct product titles that don't have test_case documents
        non_test_case_titles = db.documents.distinct(
            "title", 
            {"title": {"$nin": test_case_titles}}
        )
        
        return sorted(test_case_titles), sorted(non_test_case_titles)
    
    except Exception as e:
        st.error(f"Failed to fetch products from MongoDB: {e}")
        return [], []