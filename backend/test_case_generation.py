from typing import Dict, List, Optional
from pymongo import MongoClient
from langchain.vectorstores import FAISS
from langchain.retrievers import BM25Retriever, EnsembleRetriever
from langchain.schema import Document
from langchain.embeddings import OpenAIEmbeddings
from langchain.chat_models import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from datetime import datetime
from difflib import SequenceMatcher
import re

class TestCaseGenerator:
    def __init__(self, mongo_db):
        self.mongo_db = mongo_db
        self.embeddings = OpenAIEmbeddings(
            engine="text-embedding-ada-002",
            openai_api_key=""
        )
        self.llm = ChatOpenAI(
            engine="gpt-4o",
            temperature=0,
            openai_api_key=""
        )

    def similar(self, a: str, b: str) -> float:
        """Calculate similarity ratio between two strings"""
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def _get_relevant_prompts(self, query: str, product_title: str) -> Dict:
        """Retrieve and select the most relevant prompts from MongoDB"""
        try:
            # Get all prompts for this product
            all_prompts = list(self.mongo_db.prompts.find({"title": product_title}))
            # print("product---",all_prompts)
            if not all_prompts:
                return None
            
            # Find the most relevant prompt based on feature similarity
            best_match = None
            highest_score = 0
            
            for prompt in all_prompts:
                score = self.similar(query, prompt["feature"])
                print("SCORE---",score,prompt["feature"])
                if score > highest_score:
                    highest_score = score
                    best_match = prompt
            
            if highest_score < 0.2: # Threshold for good match
                return None

            print("FEATURE",best_match["feature"])
            # print("PROMPT",best_match["system_prompt"])
                
            return {
                "feature": best_match["feature"],
                "system_prompt": best_match["system_prompt"],
                "human_prompt": best_match["human_prompt"]
            }
            
        except Exception as e:
            print(f"Error fetching prompts: {e}")
            return None

    def _get_relevant_feedback(self, query: str, product_title: str, threshold: float = 0.2) -> List[Dict]:
        """Get relevant feedback using similarity matching, same approach as prompts"""
        try:
            # Get all feedback for this product
            all_feedback = list(self.mongo_db.feedback_collection.find(
                {"product_title": product_title},
                {"_id": 0, "feature": 1, "feedback": 1,"structured_feedback":1,"timestamp": 1}
            ))
            
            if not all_feedback:
                return []
            
            # Find the most relevant feedback based on feature similarity
            relevant_feedback = []
            for fb in all_feedback:
                score = self.similar(query, fb["feature"])
                if score >= threshold:
                    relevant_feedback.append({
                        "feedback": fb["structured_feedback"],
                        "similarity_score": score,
                        "timestamp": fb["timestamp"]
                    })
            
            # Sort by similarity score (descending) then by timestamp (newest first)
            relevant_feedback.sort(
                key=lambda x: (-x["similarity_score"], -x["timestamp"].timestamp())
            )
            
            return relevant_feedback[:3] # Return top 3 most relevant
            
        except Exception as e:
            print(f"Error retrieving feedback: {e}")
            return []

    def _get_default_prompts(self, query: str, product_title: str) -> Dict:
        """Generate default prompts with universal test case rules"""
        universal_rules = """
        DOCUMENT PROCESSING METHODOLOGY:
        1. FULL CONTEXT ANALYSIS: Analyze the entire provided context before generating test cases
        2. FEATURE IDENTIFICATION: Extract the specific feature from the query and locate all related information in context
        3. CONTEXT MAPPING: Connect scattered information across the full context to understand the complete feature scope
        4. TECHNICAL EXTRACTION: Identify all numerical values, protocols, IP addresses, ports, configurations, register addresses mentioned

        UNIVERSAL TEST CASE GENERATION RULES:

        DESCRIPTION REQUIREMENTS:
        - Write clear, specific, business-value focused descriptions based on the feature query
        - Reference the feature purpose and scope from the context
        - Make description logical and straightforward

        PRECONDITION STANDARDS (8-12 per test case):
        - Analyze the context first, then write only valid preconditions for the specific feature
        - Think logically: What are the expected preconditions for this feature?
        - Focus on product testing (turning on/off things), not services
        - Preconditions should be related to product features, not services
        - For protocols: use different IP versions (IPv4/IPv6) as preconditions when relevant
        - Use actual IP addresses from documentation when available
        - Include IPv6 discovery even if IPv4 is not in same network range
        - No preconditions for server/system verification - focus on products only
        - Include MAC addresses when required
        - Each precondition should be in proper sentence format

        STEP ACTION STANDARDS (12-20 per test case):
        - First understand the description and preconditions properly
        - Use logic to determine step actions and proper expected results
        - Actions and expected results should derive from the provided context
        - Step actions and expected results will not be directly stated - you must find and generate them
        - If numerical values, register addresses, ports, activation/deactivation points are present, explain those with proper steps
        - Gather all information then write steps in proper SEQUENCE
        - Each step action should be in proper sentence format
        - One specific action per step with one corresponding expected result
        - Include specific values, addresses, parameters from the context
        - Progress logically from basic functionality to complex scenarios
        - Test both positive (success) and negative (failure) paths
        - Include boundary conditions and edge cases

        OUTPUT FORMAT REQUIREMENTS:
        - Present in table format with 5 columns: Description | Pre-conditions | Action No. | Action | Expected Result
        - Use clear, professional technical language
        - Ensure expected results are specific and measurable
        - Number actions sequentially within each test case

        USER FEEDBACK PROCESSING:
        - All feedback points are MANDATORY requirements that must be implemented
        - Previous feedback remains active unless explicitly overridden
        - When feedback conflicts with standards, prioritize user requirements
        - If feedback is unclear, interpret comprehensively
        - Focus specifically on what the user says in feedback - those points are mandatory

        QUALITY VALIDATION:
        - Ensure test case aligns with the specific feature query
        - Verify all technical details come from the provided context
        - Test cases should be logically sequenced and complete
        - Expected results must be measurable and verifiable
        - Cover both positive and negative testing scenarios

        Preconditions and Steps Actions:- 
        - Each step action be in proper sentence format
        - There should be around 8-10 preconditions.
        - There should be around 10-18 steps actions with detailed actions and expected results.
        - The test case should be in table format with 5 columns: Description, Pre-conditions, Action No., Action, Expected Result.
        """
        
        system_prompt = f"""You are a Test Case Generation Assistant for industrial control systems.

        FEATURE DESCRIPTION:
        {query}

        {universal_rules}

        USER FEEDBACK TO INCORPORATE:
        {{feedback_instructions}}

        EXAMPLE TEST CASE STRUCTURE:
        | Description | Pre-conditions | Action No. | Action | Expected Result |
        |-------------|----------------|------------|--------|-----------------|
        | [Feature summary] | 1. Precond1<br>2. Precond2 | 1. First action | Expected outcome | Verification method |
        | | | 2. Second action | Expected outcome | Verification method |
        """
        
        human_prompt = f"""Generate comprehensive test cases for: {query}

        TECHNICAL CONTEXT:
        {{full_context}}

        USER FEEDBACK TO INCORPORATE:
        {{feedback_instructions}}

        REQUIREMENTS:
        1. Follow all universal test case generation rules
        2. Include 8-10 detailed preconditions
        3. Create 10-18 step actions with expected results
        4. Use exact technical parameters from documentation
        5. Cover both normal and error conditions
        6. Validate all boundary conditions
        7. Strictly implement all user feedback requirements

        OUTPUT FORMAT:
        Strictly use 5-column table format shown in example
        """
        
        return {
            "feature": query,
            "system_prompt": system_prompt,
            "human_prompt": human_prompt
        }

    def _get_relevant_docs(self, query: str, product_title: str, 
                         reference_product: Optional[str] = None) -> List[Document]:
        """Get relevant docs with optional reference product"""
        primary_docs = self.mongo_db.get_product_documents(product_title)
        text_docs = []
        
        for doc in primary_docs:
            for element in doc["content"]:
                if element["type"] == "text":
                    text_docs.append(Document(
                        page_content=element["content"],
                        metadata=doc.get("metadata", {})
                    ))
        
        if reference_product:
            ref_docs = self.mongo_db.get_product_documents(reference_product)
            for doc in ref_docs:
                if "test" in doc.get("doc_type", "").lower():
                    for element in doc["content"]:
                        if element["type"] == "text":
                            text_docs.append(Document(
                                page_content=element["content"],
                                metadata={"is_reference": True, **doc.get("metadata", {})}
                            ))
        
        if not text_docs:
            return []
        
        bm25_retriever = BM25Retriever.from_documents(text_docs)
        bm25_retriever.k = 5
        
        faiss_index = self._load_faiss_index(product_title)
        vector_retriever = faiss_index.as_retriever(search_kwargs={"k": 5})
        
        ensemble_retriever = EnsembleRetriever(
            retrievers=[bm25_retriever, vector_retriever],
            weights=[0.4, 0.6]
        )
        
        return ensemble_retriever.get_relevant_documents(query)

    def _load_faiss_index(self, product_title) -> FAISS:
        """Load FAISS index from MongoDB"""
        chunks = list(self.mongo_db.vector_indices.find({'title': product_title}).sort("chunk_number", 1))
        if not chunks:
            raise ValueError("No FAISS index found in database")
        
        faiss_bytes = b"".join(chunk["index_chunk"] for chunk in chunks)
        return FAISS.deserialize_from_bytes(
            embeddings=self.embeddings,
            serialized=faiss_bytes,
            allow_dangerous_deserialization=True
        )

    def _format_as_table(self, content: str) -> str:
        """Ensure output is properly formatted as a 5-column table"""
        if not content.strip():
            return content
        
        if "| Description |" in content and "| Action |" in content:
            return content
            
        # Add table header if missing
        if not content.startswith("| Description |"):
            content = (
                "| Description | Pre-conditions | Action No. | Action | Expected Result |\n"
                "|-------------|----------------|------------|--------|-----------------|\n"
                + content
            )
        
        return content

    def _generate_test_case(self, feature_description: str, product_title: str, 
                          system_prompt: str, human_prompt: str,
                          reference_product: Optional[str] = None,
                          feedback_instructions: Optional[str] = None,
                          previous_feedback: Optional[List[str]] = None) -> Dict:
        """Core test case generation logic"""
        relevant_docs = self._get_relevant_docs(
            query=feature_description,
            product_title=product_title,
            reference_product=reference_product
        )
        
        # Build technical context from documents
        full_context = []
        for doc in relevant_docs:
            doc_info = f"=== {doc.metadata.get('title', 'Unknown')} (Page {doc.metadata.get('page_no', 'N/A')}) ===\n"
            content = re.sub(r'(\b0x[0-9A-Fa-f]+\b|\b\d+\b)', r'🔹\1🔹', doc.page_content)
            doc_info += f"{content}\n"
            full_context.append(doc_info)
        full_context = "\n".join(full_context) if relevant_docs else "No documentation available"

        # Format the human prompt with context and feedback
        formatted_human_prompt = human_prompt.format(
            feature_description=feature_description,
            full_context=full_context,
            feedback_instructions=feedback_instructions or "No feedback provided"
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=formatted_human_prompt)
        ]
        
        response = self.llm(messages)
        test_case = self._format_as_table(response.content.strip())
        
        # Store this query in cache
        self.mongo_db.query_cache.update_one(
            {"query": feature_description},
            {"$set": {
                "test_case": test_case,
                "timestamp": datetime.utcnow()
            }},
            upsert=True
        )
        
        return {
            "feature": feature_description,
            "test_case": test_case,
            "sources": sorted(list(set(
                f"{d.metadata.get('title', 'Document')} (Page {d.metadata.get('page_no', 'N/A')})"
                for d in relevant_docs
            ))) if relevant_docs else ["No reference documentation"]
        }

    def store_feedback(self, feature_description: str, feedback: str):
        """Store user feedback for a test case"""
        self.mongo_db.feedback_collection.insert_one({
            "feature": feature_description,
            "feedback": feedback,
            "timestamp": datetime.utcnow()
        })

    def get_feedback_for_feature(self, feature_description: str) -> List[str]:
        """Retrieve all feedback for a specific feature"""
        feedback_records = self.mongo_db.feedback_collection.find(
            {"feature": feature_description},
            {"_id": 0, "feedback": 1}
        ).sort("timestamp", -1).limit(3) # Get last 3 feedback entries
        return [f["feedback"] for f in feedback_records]

    def generate_for_existing_product(self, feature_description: str, product_title: str) -> Dict:
        """Generate test case for existing product (has test_case docs)"""
        try:
            # Try to get prompts from DB first
            prompts = self._get_relevant_prompts(feature_description, product_title)
            
            # Fall back to defaults if no prompts found
            if not prompts:
                prompts = self._get_default_prompts(feature_description, product_title)
                print(f"Using default prompts for {product_title} - {feature_description}")
            
            return self._generate_test_case(
                feature_description=feature_description,
                product_title=product_title,
                system_prompt=prompts["system_prompt"],
                human_prompt=prompts["human_prompt"]
            )
        except Exception as e:
            print(f"Error generating test case: {e}")
            raise

    def generate_for_similar_product(self, feature_description: str, primary_product: str, 
                                   secondary_product: str, user_feedback: Optional[str] = None) -> Dict:
        """Generate test case by combining similar products"""
        if user_feedback:
            self.store_feedback(feature_description, user_feedback)
        
        # Get relevant feedback using same similarity approach
        feedback = self._get_relevant_feedback(feature_description, secondary_product)
        feedback_texts = [fb["feedback"] for fb in feedback]
        feedback_instructions = "No relevant feedback available."
        if feedback_texts:
            feedback_instructions = "Relevant feedback to incorporate:\n- " + "\n- ".join(feedback_texts)

        try:
            prompts = self._get_relevant_prompts(feature_description, secondary_product) or \
                    self._get_default_prompts(feature_description, secondary_product)
            
            return self._generate_test_case(
                feature_description=feature_description,
                product_title=secondary_product,
                system_prompt=prompts["system_prompt"],
                human_prompt=prompts["human_prompt"],
                reference_product=primary_product,
                feedback_instructions=feedback_instructions
            )
        except Exception as e:
            print(f"Error generating test case: {e}")
            raise

    def generate_for_new_product(self, feature_description: str, product_title: str, 
                               user_feedback: Optional[str] = None) -> Dict:
        """Generate test case for a completely new product (no existing docs)"""
        if user_feedback:
            self.store_feedback(feature_description, user_feedback)
        
        # Get relevant feedback using same similarity approach
        feedback = self._get_relevant_feedback(feature_description, product_title)
        feedback_texts = [fb["feedback"] for fb in feedback]
        feedback_instructions = "No relevant feedback available."
        if feedback_texts:
            feedback_instructions = "Relevant feedback to incorporate:\n- " + "\n- ".join(feedback_texts)

        print("feed",feedback_instructions)
        try:
            prompts = self._get_relevant_prompts(feature_description, product_title) or \
                    self._get_default_prompts(feature_description, product_title)
            
            return self._generate_test_case(
                feature_description=feature_description,
                product_title=product_title,
                system_prompt=prompts["system_prompt"],
                human_prompt=prompts["human_prompt"],
                feedback_instructions=feedback_instructions
            )
        except Exception as e:
            print(f"Error generating test case: {e}")
            raise
