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
import emoji
import unicodedata

# Main class responsible for generating test cases based on product documentation,
# user queries, and feedback. Integrates document retrieval, prompt generation,
# and LLM-based test case synthesis.

class TestCaseGenerator:
    """
        A class to generate test cases for industrial control systems based on product documentation,
        user queries, and feedback. It integrates document retrieval, prompt generation, and LLM-based
        test case synthesis using LangChain and OpenAI APIs.
    """
    def __init__(self, mongo_db):
        """
        Initialize the TestCaseGenerator with MongoDB connection and LLM/embedding models.
    
        Args:
            mongo_db: MongoDB client instance for accessing prompts, feedback, and document collections.
        """
        self.mongo_db = mongo_db
        self.embeddings = OpenAIEmbeddings(
            engine="text-embedding-ada-002",
            openai_api_key="b74bf34f88b449f5b25764e363d4dd49"
        )
        self.llm = ChatOpenAI(
            engine="gpt-4o",
            temperature=0,
            openai_api_key="b74bf34f88b449f5b25764e363d4dd49"
        )
        
    # Clean raw document text by removing emojis, special characters, and normalizing whitespace
    def _clean_document_content(self, text: str) -> str:
         """
        Clean document content while preserving technical details.
    
        Args:
            text (str): Raw text extracted from documents.
    
        Returns:
            str: Cleaned and normalized text suitable for processing.
        """
        if not text:
            return ""
            
        # Normalize unicode characters
        text = unicodedata.normalize('NFKD', text)
        
        # Remove emojis except our technical markers
        text = emoji.replace_emoji(text, replace='')
        
        # Remove special characters but preserve technical notation
        text = re.sub(r'[^\w\s\-.,:;!?@#$%&*+/=<>()\[\]{}\'"\n]', '', text)
        
        # Remove control characters
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        
        # Clean up whitespace but preserve newlines for structure
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n\n', text)
        
        return text.strip()

    # Highlight technical terms like hex values, IPs, and identifiers using emoji markers
    def _highlight_technical_terms(self, text: str) -> str:
         """
        Highlight technical terms such as hex values, IP addresses, and register names.
    
        Args:
            text (str): Input text to highlight.
    
        Returns:
            str: Text with technical terms wrapped in markers.
        """
        """Highlight technical terms in the document content"""
        text = re.sub(r'\b(0x[0-9A-Fa-f]+)\b', r'🔹\1🔹', text)
        text = re.sub(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b', r'🔹\1🔹', text)
        text = re.sub(r'\b([A-Z]{2,}_[A-Z0-9_]+)\b', r'🔹\1🔹', text)
        text = re.sub(r'\b([A-Z][a-z]+[A-Z][a-zA-Z]*)\b', r'🔹\1🔹', text)
        return text

    # Compute similarity ratio between two strings using SequenceMatcher
    def similar(self, a: str, b: str) -> float:
        """
        Calculate similarity ratio between two strings using SequenceMatcher.
    
        Args:
            a (str): First string.
            b (str): Second string.
    
        Returns:
            float: Similarity ratio between 0 and 1.
        """
        """Calculate similarity ratio between two strings"""
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    # Retrieve the most relevant prompt from MongoDB based on feature similarity
    def _get_relevant_prompts(self, query: str, product_title: str) -> Dict:
        """
        Retrieve the most relevant prompt from MongoDB based on feature similarity.
    
        Args:
            query (str): Feature description or query.
            product_title (str): Title of the product.
    
        Returns:
            Dict: Dictionary containing feature, system_prompt, and human_prompt.
        """
        """Retrieve and select the most relevant prompts from MongoDB"""
        try:
            all_prompts = list(self.mongo_db.prompts.find({"title": product_title}))
            if not all_prompts:
                return None
            
            best_match = None
            highest_score = 0
            
            for prompt in all_prompts:
                score = self.similar(query, prompt["feature"])
                if score > highest_score:
                    highest_score = score
                    best_match = prompt
            
            if highest_score < 0.2: # Threshold for good match
                return None
                
            return {
                "feature": best_match["feature"],
                "system_prompt": best_match["system_prompt"],
                "human_prompt": best_match["human_prompt"]
            }
        except Exception as e:
            print(f"Error fetching prompts: {e}")
            return None

    # Retrieve feedback entries from MongoDB that are similar to the given feature
    def _get_relevant_feedback(self, feature_description: str, product_title: str) -> List[Dict]:
        """
        Retrieve relevant feedback entries from MongoDB based on feature similarity.
    
        Args:
            feature_description (str): Description of the feature.
            product_title (str): Title of the product.
    
        Returns:
            List[Dict]: List of feedback entries sorted by relevance and timestamp.
        """
        """Get relevant feedback using feature description similarity"""
        try:
            all_feedback = list(self.mongo_db.feedback_collection.find(
                {"product_title": product_title},
                {"_id": 0, "feature": 1, "raw_feedback": 1, "timestamp": 1, "previous_test_case": 1}
            ))
            
            if not all_feedback:
                return []
            
            relevant_feedback = []
            for fb in all_feedback:
                score = self.similar(feature_description, fb["feature"])
                if score >= 0.2: # Similarity threshold
                    relevant_feedback.append({
                        "raw_feedback": fb["raw_feedback"],
                        "feature": fb["feature"],
                        "previous_test_case": fb.get("previous_test_case", ""),
                        "score": score,
                        "timestamp": fb["timestamp"]
                    })
            
            # Sort by score and timestamp
            relevant_feedback.sort(key=lambda x: (-x["score"], -x["timestamp"].timestamp()))
            
            return relevant_feedback[:10] # Top 10 most relevant
        except Exception as e:
            print(f"Error retrieving feedback: {e}")    
            return []

    def _get_default_prompts(self, query: str, product_title: str, feedback_instructions: str) -> Dict:
         """
        Generate default prompts using universal test case generation rules and feedback.
    
        Args:
            query (str): Feature description.
            product_title (str): Product title.
            feedback_instructions (str): Combined feedback context.
    
        Returns:
            Dict: Dictionary with system_prompt and human_prompt.
        """
        """Generate default prompts with universal test case rules"""
        universal_rules = """
        SINGLE TESTCASE GENERATION
        DOCUMENT PROCESSING METHODOLOGY:
        1. FULL CONTEXT ANALYSIS: Analyze the entire provided context before generating test cases
        2. FEATURE IDENTIFICATION: Extract the specific feature from the query and locate all related information in context
        3. CONTEXT MAPPING: Connect scattered information across the full context to understand the complete feature scope
        4. TECHNICAL EXTRACTION: Identify all numerical values, protocols, IP addresses, ports, configurations, register addresses mentioned
        5. ENGINEERING LOGIC INFERENCE: Based on engineering principles and product documentation patterns, infer logical test scenarios even if not explicitly documented
        6. ENGINEERING TERMS : FCT Digital Channel Configuration AND ICT Digital Channel Configuration are different channel register don't mention them unless at until they are explicitly asked by user or directly related with the query For Example if asked only default channels then do mention Default Channels only and also mention their default register addresses
        i.e. For Default channels the register address come from TPVD Register table which starts from 11000
        7. WHEN ASEKD OR ALL/DIFFERENT PARAMETERS, ALWAYS MENTION ALL PARAMETERS IN TEST CASES AS PER DOCUMENTATION for EXAMPLE IF USERS MENTION DIFFERENT CHANNELS THEN MENTION ALL CHANNELS PRESENT IN DOCUMENT i.e. CH 1-CH 4
        UNIVERSAL TEST CASE GENERATION RULES:

        DESCRIPTION REQUIREMENTS:
        - Write clear, specific, business-value focused descriptions based on the feature query
        - Reference the feature purpose and scope from the context
        - Make description logical and straightforward

        PRECONDITION STANDARDS:
        - Analyze the context first, then write only valid preconditions for the specific feature
        - Think logically: What are the expected preconditions for this feature?
        - Focus on product testing (turning on/off things), not services
        - Preconditions should be related to product features, not services
        - No preconditions for server/system verification - focus on products only
        - Include MAC addresses when required
        - Include hex and decimal values when required
        - Include register addresses when required
        - Each precondition should be in proper sentence format

        STEP ACTION STANDARDS:
        - The ICT/FCT are different channel register don't mention them unless at until they are explicitly asked by user or directly related with the query For Example if asked only default channels then do mention Default Channels only and also mention their default register addresses
        i.e. For Default channels the register address come from TPVD Register table which starts from 11000
        - The above point should work for other type of queries as well
        - For Tloc the BCIM Identification Information (Labels) with Orion TU table is very important and please do mention the values in testcase when asked
        - Man I told you to mention register address i.e. decimal address always and please read the document properly 
        - Don't miss or make one as read/write or R/W command as one for example the FOR EXAMPLE BECAUSE THE SOFT RESET CAN BE INTIATED OR STATRTED WHEN Write '0' to the Reset Command register 11064 IS MADE
        - Always mention in every first step the the Register number sould be mentioned when required
        - The Exit/End these commands can never be in first step
        - Whenever you mention any invalid/incorrect/unvalid/out-of-range etc type of value/params etc then please do mention the value for it in numbers or strings
        - For example Attempt to write an invalid/out-of-range value - Explain the Step Action what is the Invalid value like in numbers or parameters
        - First understand the description and preconditions properly
        - Use engineering logic to determine comprehensive test scenarios such as sending commands and all when required
        - Actions should simulate real engineering testing using remote shell commands
        - Use logic to determine step actions and proper expected results
        - Actions and expected results should derive from the provided context
        - When needed Use proper command syntax like: "Send command 'tpvd read [register] [parameter]'" here tpvd is as per document present i.e. for BCIM only
        - Step actions and expected results will not be directly stated - you must find and generate them
        - If numerical values, register addresses, ports, activation/deactivation points are present, explain those with proper steps
        - Gather all information then write steps in proper SEQUENCE
        - Each step action should be in proper sentence format
        - One specific action per step with one corresponding expected result
        - Include specific values, addresses, parameters from the context
        - Progress logically from basic functionality to complex scenarios
        - Test both positive (success) and negative (failure) paths
        - Include boundary conditions and edge cases
        - Include hex and decimal values when required
        - Include register addresses when required
        - Don't mention any wrong values if it isn't present in the document
        - Please don't provide the values in ranges if it is not there in the document
        - Don't say to repeat steps and instead of that do write all the steps in tescase

        OUTPUT FORMAT REQUIREMENTS:
        ONLY ONE COMPLETE TESTCASE SHOULD BE THERE
        - Present in table format with 5 columns: 
        | Description | Pre-conditions | Action No. | Action | Expected Result |
        |-------------|----------------|------------|--------|-----------------|
        | [Feature summary] | 1. Precond1<br>2. Precond2 | 1.| First action | Expected outcome | Verification method |
        | | | 2.| Second action | Expected outcome | Verification method |

        - Use clear, professional technical language
        - Ensure expected results are specific and measurable
        - Number actions sequentially within each test case

        INTELLIGENT EXPECTED RESULTS:
        i.e. For Default channels the register address come from TPVD Register table which starts from 11000
        - For Tloc the BCIM Identification Information (Labels) with Orion TU table is very important and please do mention the values in testcase when asked
        - Don't miss or make one as read/write or R/W command as one FOR EXAMPLE BECAUSE THE SOFT RESET CAN BE INTIATED OR STATRTED WHEN Write '0' to the Reset Command register 11064 IS MADE
        - The Exit/End these commands can never be in first step
        - Include hex and decimal values when required
        - Include register addresses when required
        - The Expected result should be in detail i.e. when it comes read in step action and in expected result when it says should be read successfully, then please do mention what value/parameter etc is read sucessfully
        - For EXAMPLE you can say Should return 0 (unlocked) when read.
        - For undocumented but logical operations: Infer correct expected results based on:
          * Register type (read-only, write-only, read-write)
          * If in document it is stated to as R then it is read only , if R W then only it is read write so keep this logic in mind and if there is not W operation then just the expected result should be like the command should be rejected
          * Data type constraints
          * Engineering principles
          * Product behavior patterns
        - For invalid operations: Expected result should be proper error/rejection message
        - For boundary testing: Expected results should reflect limit behavior
        - Expected results must be technically accurate and realistic
        - Include verification methods where applicable
        - Don't mention any wrong values if it isn't present in the document
        - Please don't provide the values in ranges if it is not there in the document
        - Don't say to repeat steps and instead of that do write all the steps in tescase
        - Never add feedbacks query in the test steps use logic and include the needed steps
        - Do consider answer from multiple tables when needed
        - Include all the addresses, ports, parameters, and values as per the document for particalur feature


        USER FEEDBACK PROCESSING:
        - All feedback points are MANDATORY requirements that must be implemented
        - Previous feedback remains active unless explicitly overridden
        - When feedback conflicts with standards, prioritize user requirements
        - If feedback is unclear, interpret comprehensively
        - Focus specifically on what the user says in feedback - those points are mandatory
        - Never add feedbacks query in the test steps use logic and include the needed steps

        QUALITY VALIDATION:
        - For Tloc the BCIM Identification Information (Labels) with Orion TU table is very important and please do mention the values in testcase when asked
        - Ensure test case aligns with the specific feature query
        - Verify all technical details come from the provided context
        - Test cases should be logically sequenced and complete
        - Expected results must be measurable and verifiable
        - Cover both positive and negative testing scenarios
        - The Expected result should be in detail i.e. when it comes read in step action and in expected result when it says should be read successfully, then please do mention what value/parameter etc is read sucessfully
        - For EXAMPLE you can say Should return 0 (unlocked) when read.
        - Whenever you mention any invalid/incorrect/unvalid/out-of-range etc type of value/params etc then please do mention the value for it in numbers or strings
        - For example Attempt to write an invalid/out-of-range value - Explain the Step Action what is the Invalid value
        i.e. For Default channels the register address come from TPVD Register table which starts from 11000

        Preconditions and Steps Actions:- 
        - For Tloc the BCIM Identification Information (Labels) with Orion TU table is very important and please do mention the values in testcase when asked
        - Each step action be in proper sentence format
        - The test case should be in table format with 5 columns: Description, Pre-conditions, Action No., Action, Expected Result.
        - Don't say to repeat steps and instead of that do write all the steps in tescase
        - The Expected result should be in detail i.e. when it comes read in step action and in expected result when it says should be read successfully, then please do mention what value/parameter etc is read sucessfully


        MANDATORY:
        - Include hex and decimal values when required
        - Include register addresses when required
        - ALWAYS MENTION DEFAULT VALUES IN TEST CASES AS PER DOCUMENTATION
        - ALWAYS MENTION ALL TECHNICAL PARAMETERS IN TEST CASES AS PER DOCUMENTATION
        - WHEN USER MENTION ALL/DIFFERENT PARAMETERS, ALWAYS MENTION ALL PARAMETERS IN TEST CASES AS PER DOCUMENTATION  for EXAMPLE IF USERS MENTION DIFFERENT CHANNELS THEN MENTION ALL CHANNELS PRESENT IN DOCUMENT
        - Don't say to repeat steps and instead of that do write all the steps in tescase
        - Do consider answer from multiple tables when needed
        - Please add the steps in elaborative way the step actions can be of any number i.e. it can got upto 20 or more than that
        - Include all the addresses, ports, parameters, and values as per the document for particalur feature
        - The Expected result should be in detail i.e. when it comes read in step action and in expected result when it says should be read successfully, then please do mention what value/parameter etc is read sucessfully
        - For EXAMPLE you can say Should return 0 (unlocked) when read.
        - Whenever you mention any invalid/incorrect/unvalid/out-of-range etc type of value/params etc then please do mention the value for it in numbers or strings
        - For example Attempt to write an invalid/out-of-range value - Explain the Step Action what is the Invalid value like in numbers or parameters
        - Man I told you to mention registe address i.e. decimal address always and please read the document properly 
        - Don't miss or make one as read/write or R/W command as one FOR EXAMPLE BECAUSE THE SOFT RESET CAN BE INTIATED OR STATRTED WHEN Write '0' to the Reset Command register 11064 IS MADE
        - For Tloc the BCIM Identification Information (Labels) with Orion TU table is very important and please do mention the values in testcase when asked
        - The ICT/FCT are different channel register don't mention them unless at until they are explicitly asked by user or directly related with the query For Example if asked only default channels then do mention Default Channels only and also mention their default register addresses
        i.e. For Default channels the register address come from TPVD Register table which starts from 11000
        - The above point should work for other type of queries as well


        PROHIBITED CONTENT:
        - Never say user to check documentation
        - Never say user to check default values as per Documentation
        - Don't say to repeat steps
        - Don't mention any wrong values if it isn't present in the document
        - Please don't provide the values in ranges if it is not there in the document
        - Never add feedbacks query in the test steps use logic and include the needed steps
        - Never use wrong Register/Decimal Addresses ranges and mention them incorrectly
        - The Exit/End these commands can never be in first step
        - Please STOP MENTIONING INCORRECT/IRRELEVANT INFORMATION INT HE TESTCASES AND WHICH IS NOT RELATED TO THE QUERY THE USER GAVE
        - NEVER MENTION WHICH IS NOT RELATED TO THE QUERY THE USER GAVE

        """
        
        system_prompt = f"""You are a Test Case Generation Assistant for industrial control systems.

        FEATURE DESCRIPTION:
        {query}

        {universal_rules}

        USER FEEDBACK TO INCORPORATE:
        {feedback_instructions}

        EXAMPLE TEST CASE STRUCTURE:
        | Description | Pre-conditions | Action No. | Action | Expected Result |
        |-------------|----------------|------------|--------|-----------------|
        | [Feature summary] | 1. Precond1<br>2. Precond2 | 1.| First action | Expected outcome | Verification method |
        | | | 2.| Second action | Expected outcome | Verification method |
        """
        
        human_prompt = f"""Generate comprehensive test cases for: {query}

        TECHNICAL CONTEXT:
        {{full_context}}

        USER FEEDBACK TO INCORPORATE:
        {feedback_instructions}

        REQUIREMENTS:
        1. Follow all universal test case generation rules
        2. Use exact technical parameters from documentation
        3. Cover both normal and error conditions
        4. Validate all boundary conditions
        5. Strictly implement all user feedback requirements

        MANDATORY:
        - Include hex and decimal values when required
        - Include register addresses when required
        - ALWAYS MENTION DEFAULT VALUES IN TEST CASES AS PER DOCUMENTATION
        - ALWAYS MENTION ALL TECHNICAL PARAMETERS IN TEST CASES AS PER DOCUMENTATION
        - Don't say to repeat steps and instead of that do write all the steps in tescase
        - Please add the steps in elaborative way the step actions can be of any number i.e. it can got upto 20 or more than that
        - Do consider answer from multiple tables when needed
        - Include all the addresses, ports, parameters, and values as per the document for particalur feature and add in testcase
        - The Expected result should be in detail i.e. when it comes read in step action and in expected result when it says should be read successfully, 
        then please do mention what value/parameter etc is read sucessfully
        - For EXAMPLE you can say Should return 0 (unlocked) when read.
        - Whenever you mention any invalid/incorrect/unvalid/out-of-range etc type of value/params etc then please do mention the value for it in numbers or strings
        - For example Attempt to write an invalid/out-of-range value - Explain the Step Action what is the Invalid value like in numbers or parameters
        - Man I told you to mention registe address i.e. decimal address always and please read the document properly 
        - Don't miss or make one as read/write or R/W command as one for example the FOR EXAMPLE BECAUSE THE SOFT RESET CAN BE INTIATED OR STATRTED WHEN Write '0' to the Reset Command register 11064 IS MADE
        - For Tloc the BCIM Identification Information (Labels) with Orion TU table is very important and please do mention the values in testcase when asked
        - The ICT/FCT are different channel register don't mention them unless at until they are explicitly asked by user or directly related with the query 
        For Example if asked only default channels then do mention Default Channels only and also mention their default register addresses 
        i.e. For Default channels the register address come from TPVD Register table which starts from 11000
        - The above point should work for other type of queries as well

        PROHIBITED CONTENT:
        - Never say user to check documentation
        - Never say user to check default values as per Documentation
        - Don't say to repeat steps i.e. Repeat step from Step number this to Step number that NO DON'T DO THIS THING
        - Don't mention any wrong values if it isn't present in the document
        - Please don't provide the values in ranges if it is not there in the document
        - Never add feedbacks query in the test steps use logic and include the needed steps
        - Never use wrong Register/Decimal Addresses ranges and mention them incorrectly
        - The Exit/End these commands can never be in first step
        - Please STOP MENTIONING INCORRECT/IRRELEVANT INFORMATION IN THE TESTCASES AND WHICH IS NOT RELATED TO THE QUERY THE USER GAVE
        - NEVER MENTION WHICH IS NOT RELATED TO THE QUERY THE USER GAVE

        OUTPUT FORMAT:
        GENERATE EXACTLY ONE COMPREHENSIVE TESTCASE
        Strictly use 5-column table format shown in example

        | Description | Pre-conditions | Action No. | Action | Expected Result |
        |-------------|----------------|------------|--------|-----------------|
        | [Feature summary] | 1. Precond1<br>2. Precond2 | 1.| First action | Expected outcome | Verification method |
        | | | 2.| Second action | Expected outcome | Verification method |

        """

        return {
            "feature": query,
            "system_prompt": system_prompt,
            "human_prompt": human_prompt
        }

    def _get_relevant_docs(self, query: str, product_title: str, reference_product: Optional[str] = None) -> List[Document]:
        """
        Retrieve relevant documents using BM25 and FAISS ensemble retriever.
    
        Args:
            query (str): Query string for retrieval.
            product_title (str): Title of the product.
            reference_product (Optional[str]): Optional reference product for additional context.
    
        Returns:
            List[Document]: List of relevant LangChain Document objects.
        """
        """Get relevant docs using the query (either feature or feedback text)"""
        try:
            primary_docs = self.mongo_db.get_product_documents(product_title)
            text_docs = []
            
            for doc in primary_docs:
                current_text = ""
                current_tables = []
                
                for element in doc["content"]:
                    if element["type"] == "text":
                        # Clean the document content while preserving structure
                        cleaned_content = self._clean_document_content(element["content"])
                        if cleaned_content.strip(): # Only add if there's actual content
                            current_text += cleaned_content + "\n"
                    
                    elif element["type"] == "table":
                        # Process table content
                        table_content = self._format_table_content(element["content"])
                        if table_content.strip():
                            current_tables.append(table_content)
                
                # Combine text with all its associated tables
                combined_content = current_text
                if current_tables:
                    combined_content += "\n\n=== RELATED TABLES ===\n"
                    combined_content += "\n".join(current_tables)
                
                if combined_content.strip():
                    text_docs.append(Document(
                        page_content=combined_content,
                        metadata=doc.get("metadata", {})
                    ))

            if reference_product:
                ref_docs = self.mongo_db.get_product_documents(reference_product)
                for doc in ref_docs:
                    if "test" in doc.get("doc_type", "").lower():
                        current_text = ""
                        current_tables = []
                        
                        for element in doc["content"]:
                            if element["type"] == "text":
                                cleaned_content = self._clean_document_content(element["content"])
                                if cleaned_content.strip():
                                    current_text += cleaned_content + "\n"
                            
                            elif element["type"] == "table":
                                table_content = self._format_table_content(element["content"])
                                if table_content.strip():
                                    current_tables.append(table_content)
                        
                        combined_content = current_text
                        if current_tables:
                            combined_content += "\n\n=== REFERENCE TABLES ===\n"
                            combined_content += "\n".join(current_tables)
                        
                        if combined_content.strip():
                            text_docs.append(Document(
                                page_content=combined_content,
                                metadata={"is_reference": True, **doc.get("metadata", {})}
                            ))

            if not text_docs:
                return []

            bm25_retriever = BM25Retriever.from_documents(text_docs)
            bm25_retriever.k = 150
            
            faiss_index = self._load_faiss_index(product_title)
            vector_retriever = faiss_index.as_retriever(search_kwargs={"k": 150})
            
            ensemble_retriever = EnsembleRetriever(
                retrievers=[bm25_retriever, vector_retriever],
                weights=[0.4, 0.6]
            )
            
            return ensemble_retriever.get_relevant_documents(query)
        except Exception as e:
            print(f"Error retrieving documents: {e}")
            return []
        
    def _format_table_content(self, table_data: List[List[str]]) -> str:
        """
        Convert table data into a readable string format.
    
        Args:
            table_data (List[List[str]]): 2D list representing table rows and columns.
    
        Returns:
            str: Formatted string representation of the table.
        """
        """Convert table data into a readable string format"""
        if not table_data:
            return ""
        
        # Determine column widths
        col_widths = [max(len(str(cell)) for cell in row) for row in zip(*table_data)]
        
        formatted_lines = []
        for row in table_data:
            # Format each row with consistent spacing
            formatted_row = " | ".join(str(cell).ljust(width) for cell, width in zip(row, col_widths))
            formatted_lines.append(formatted_row)
        
        return "\n".join(formatted_lines)

    def _generate_test_case(self, feature_description: str, product_title: str, 
                          system_prompt: str, human_prompt: str,
                          reference_product: Optional[str] = None,
                          feedback_items: Optional[List[str]] = None) -> Dict:
         """
        Generate a test case using LLM based on feature description, prompts, and documents.
    
        Args:
            feature_description (str): Description of the feature.
            product_title (str): Product title.
            system_prompt (str): System prompt for LLM.
            human_prompt (str): Human prompt for LLM.
            reference_product (Optional[str]): Optional reference product for context.
            feedback_items (Optional[List[str]]): Optional list of feedback strings.
    
        Returns:
            Dict: Dictionary containing feature, test_case, and sources.
        """
        """Core generation with flexible document retrieval"""
        # Determine if this is a feedback-driven generation
        is_feedback = feedback_items is not None and len(feedback_items) > 0
        
        # Use first feedback item for retrieval if available, otherwise use feature description
        retrieval_query = feedback_items[0] if is_feedback else feature_description
        
        relevant_docs = self._get_relevant_docs(
            query=retrieval_query,
            product_title=product_title,
            reference_product=reference_product
        )
        
        full_context = []
        for doc in relevant_docs:
            doc_info = f"=== {doc.metadata.get('title', 'Unknown')} (Page {doc.metadata.get('page_no', 'N/A')}) ===\n"
            # Highlight technical terms in the cleaned content
            highlighted_content = self._highlight_technical_terms(doc.page_content)
            doc_info += f"{highlighted_content}\n"
            full_context.append(doc_info)
        
        full_context = "\n".join(full_context) if relevant_docs else "No documentation available"

        print("fulllllllllll---",full_context, "full_context---")
        
        # Specify the filename
        filename = "my_context.txt"

        # Write the context to the file
        with open(filename, "w",encoding="utf-8") as file:
            file.write(full_context)


        # Add strict formatting instructions
        human_prompt += "\n\nIMPORTANT:\n"
        human_prompt += "1. GENERATE EXACTLY ONE COMPREHENSIVE TESTCASE\n"
        human_prompt += "2. OUTPUT MUST BE IN 5-COLUMN TABLE FORMAT SHOWN BELOW\n"
        human_prompt += "3. INCLUDE ALL TECHNICAL PARAMETERS FROM CONTEXT\n"
        human_prompt += "4. DO NOT INCLUDE ANY MARKDOWN FORMATTING SYMBOLS LIKE ```\n\n"

        formatted_human_prompt = human_prompt.format(
            full_context=full_context
        )

        response = self.llm([
            SystemMessage(content=system_prompt),
            HumanMessage(content=formatted_human_prompt)
        ])
        
        test_case = self._format_as_table(response.content.strip())
        
        # Update both query cache and feedback collection
        self._update_data_stores(
            feature=feature_description,
            product_title=product_title,
            test_case=test_case,
            full_context=full_context,
            relevant_docs=relevant_docs,
            feedback_items=feedback_items
        )
        
        return {
            "feature": feature_description,
            "test_case": test_case,
            "sources": list(set(
                f"{d.metadata.get('title', 'Document')} (Page {d.metadata.get('page_no', 'N/A')})"
                for d in relevant_docs
            )) if relevant_docs else ["No reference documentation"]
        }
    
    def _update_data_stores(self, feature: str, product_title: str, test_case: str, 
                          full_context: str, relevant_docs: List[Document],
                          feedback_items: Optional[List[str]] = None):
        """
        Update MongoDB collections with generated test case and context.
    
        Args:
            feature (str): Feature description.
            product_title (str): Product title.
            test_case (str): Generated test case.
            full_context (str): Full context used for generation.
            relevant_docs (List[Document]): List of relevant documents.
            feedback_items (Optional[List[str]]): Optional feedback items.
        """
        """Update both query cache and feedback collection with new test case"""
        # Update query cache
        self.mongo_db.query_cache.update_one(
            {"query": feature},
            {"$set": {
                "test_case": test_case,
                "timestamp": datetime.utcnow(),
                "context_used": full_context,
                "sources": [f"{d.metadata.get('title', 'Document')} (Page {d.metadata.get('page_no', 'N/A')})" 
                for d in relevant_docs]
            }},
            upsert=True
        )
        
        # Update feedback collection if this is a feedback-driven generation
        if feedback_items and len(feedback_items) > 0:
            self.mongo_db.feedback_collection.update_one(
                {
                    "product_title": product_title,
                    "feature": feature
                },
                {"$set": {
                    "previous_test_case": test_case,
                    "timestamp": datetime.utcnow(),
                    "context_used": full_context
                }},
                upsert=True
            )

    def store_feedback(self, product_title: str, feature: str, feedback: str, previous_test_case: str):
            """
            Store user feedback and update both feedback and query cache collections.
        
            Args:
                product_title (str): Product title.
                feature (str): Feature name.
                feedback (str): Feedback text.
                previous_test_case (str): Previous test case associated with the feedback.
            """
            """Store feedback with test case context and update both collections"""
            # Update feedback collection
            self.mongo_db.feedback_collection.update_one(
                {"product_title": product_title, "feature": feature},
                {"$set": {
                    "raw_feedback": feedback,
                    "previous_test_case": previous_test_case,
                    "timestamp": datetime.utcnow()
                }},
                upsert=True
            )
            
            # Also update the query cache with the feedback
            self.mongo_db.query_cache.update_one(
                {"query": feature},
                {"$set": {
                    "last_feedback": feedback,
                    "feedback_timestamp": datetime.utcnow()
                }},
                upsert=True
            )

    def _load_faiss_index(self, product_title) -> FAISS:
        """
        Load FAISS index from MongoDB for vector-based retrieval.
    
        Args:
            product_title (str): Title of the product.
    
        Returns:
            FAISS: Deserialized FAISS index.
        """
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
        """
        Format raw LLM output into a structured test case table.
    
        Args:
            content (str): Raw content from LLM.
    
        Returns:
            str: Formatted table string.
        """
        """Ensure output is properly formatted as a test case table"""
        if not content.strip():
            return content
            
        # Remove any markdown formatting
        content = content.replace("```", "").strip()
        
        # If already in table format, just return it
        if "| Description |" in content and "| Expected Result |" in content:
            return content
            
        # Otherwise try to parse and reformat
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        formatted_lines = []
        
        # Add table header if missing
        if not any("Description" in line and "Expected Result" in line for line in lines):
            formatted_lines.append("| Description | Pre-conditions | Action No. | Action | Expected Result |")
            formatted_lines.append("|-------------|----------------|------------|--------|-----------------|")
        
        # Process each line
        for line in lines:
            if line.startswith("|") and line.endswith("|"):
                formatted_lines.append(line)
            else:
                # Try to split into columns
                parts = [part.strip() for part in re.split(r'\t|\|', line) if part.strip()]
                if len(parts) >= 5:
                    formatted_lines.append(f"| {' | '.join(parts[:5])} |")
                elif len(parts) == 1:
                    # Single column - treat as description
                    formatted_lines.append(f"| {parts[0]} | | | | |")
        
        return '\n'.join(formatted_lines)

    def generate_for_existing_product(self, feature_description: str, product_title: str, feedback_items: Optional[List[str]] = None) -> Dict:
        """
        Generate a test case for an existing product using stored feedback and prompts.
    
        Args:
            feature_description (str): Feature description.
            product_title (str): Product title.
            feedback_items (Optional[List[str]]): Optional feedback items.
    
        Returns:
            Dict: Generated test case and metadata.
        """
        """Generate test case for existing product"""
        try:
            # Get relevant feedback and previous test cases
            stored_feedback = self._get_relevant_feedback(feature_description, product_title)
            
            # Build feedback context
            feedback_context = []
            if stored_feedback:
                feedback_context = [
                    f"Previous feature: {fb['feature']}\n"
                    f"Feedback: {fb['raw_feedback']}\n"
                    f"Previous test case:\n{fb['previous_test_case']}"
                    for fb in stored_feedback
                ]
            
            # Add any immediate feedback items from the request
            if feedback_items:
                feedback_context.extend(feedback_items)
            
            feedback_instructions = "\n\n".join(feedback_context) if feedback_context else "No feedback available"
            
            # Get prompts (custom or default with feedback)
            prompts = self._get_relevant_prompts(feature_description, product_title) or \
                    self._get_default_prompts(feature_description, product_title, feedback_instructions)
            
            return self._generate_test_case(
                feature_description=feature_description,
                product_title=product_title,
                system_prompt=prompts["system_prompt"],
                human_prompt=prompts["human_prompt"],
                feedback_items=feedback_items
            )
        except Exception as e:
            print(f"Error generating test case: {e}")
            raise

    def generate_for_similar_product(self, feature_description: str, 
                                   primary_product: str, secondary_product: str, feedback_items: Optional[List[str]] = None) -> Dict:
        """
        Generate a test case for a similar product using reference product context.
    
        Args:
            feature_description (str): Feature description.
            primary_product (str): Reference product.
            secondary_product (str): Target product.
            feedback_items (Optional[List[str]]): Optional feedback items.
    
        Returns:
            Dict: Generated test case and metadata.
        """
        """Generate test case by combining similar products"""
        try:
            # Get feedback from secondary product
            stored_feedback = self._get_relevant_feedback(feature_description, secondary_product)
            
            # Build feedback context
            feedback_context = []
            if stored_feedback:
                feedback_context = [
                    f"Previous feature: {fb['feature']}\n"
                    f"Feedback: {fb['raw_feedback']}\n"
                    f"Previous test case:\n{fb['previous_test_case']}"
                    for fb in stored_feedback
                ]
            
            # Add any immediate feedback items from the request
            if feedback_items:
                feedback_context.extend(feedback_items)
            
            feedback_instructions = "\n\n".join(feedback_context) if feedback_context else "No feedback available"
            
            prompts = self._get_relevant_prompts(feature_description, secondary_product) or \
                    self._get_default_prompts(feature_description, secondary_product, feedback_instructions)
            
            return self._generate_test_case(
                feature_description=feature_description,
                product_title=secondary_product,
                system_prompt=prompts["system_prompt"],
                human_prompt=prompts["human_prompt"],
                reference_product=primary_product,
                feedback_items=feedback_items
            )
        except Exception as e:
            print(f"Error generating test case: {e}")
            raise

    def generate_for_new_product(self, feature_description: str, product_title: str, feedback_items: Optional[List[str]] = None) -> Dict:
        """
        Generate a test case for a new product using default prompts and feedback.
    
        Args:
            feature_description (str): Feature description.
            product_title (str): Product title.
            feedback_items (Optional[List[str]]): Optional feedback items.
    
        Returns:
            Dict: Generated test case and metadata.
        """
        """Generate test case for new product"""
        try:
            # Get any relevant feedback
            stored_feedback = self._get_relevant_feedback(feature_description, product_title)
            
            # Build feedback context
            feedback_context = []
            if stored_feedback:
                feedback_context = [
                    f"Previous feature: {fb['feature']}\n"
                    f"Feedback: {fb['raw_feedback']}\n"
                    f"Previous test case:\n{fb['previous_test_case']}"
                    for fb in stored_feedback
                ]
            
            # Add any immediate feedback items from the request
            if feedback_items:
                feedback_context.extend(feedback_items)
            
            feedback_instructions = "\n\n".join(feedback_context) if feedback_context else "No feedback available"
            
            prompts = self._get_relevant_prompts(feature_description, product_title) or \
                    self._get_default_prompts(feature_description, product_title, feedback_instructions)
            
            return self._generate_test_case(
                feature_description=feature_description,
                product_title=product_title,
                system_prompt=prompts["system_prompt"],
                human_prompt=prompts["human_prompt"],
                feedback_items=feedback_items
            )
        except Exception as e:
            print(f"Error generating test case: {e}")
            raise
