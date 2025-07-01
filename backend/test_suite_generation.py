from typing import Dict, List, Optional
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from test_case_generation import TestCaseGenerator
from langchain.schema import Document
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.retrievers import BM25Retriever, EnsembleRetriever
from langchain.vectorstores import FAISS
import re
import time
from openai.error import RateLimitError, APIError, ServiceUnavailableError
from datetime import datetime
from difflib import SequenceMatcher

class TestSuiteGenerator(TestCaseGenerator):
    """
    A class for generating test suites by extending the TestCaseGenerator.
    It supports generating multiple test cases with retry logic, formatting, and validation.
    """
    def __init__(self, mongo_db):
        """
        Initialize the TestSuiteGenerator with MongoDB connection.
        Args:
            mongo_db: MongoDB client instance with required collections.
        """
        super().__init__(mongo_db)
        self.collection = mongo_db.collection

    def _generate_with_retry(self, messages, max_retries=5):
        """
        Generate a test case with retry logic for handling API errors.
        Args:
            messages: List of messages to send to the LLM.
            max_retries: Maximum number of retry attempts.
        Returns:
            str: The generated test case content.
        """
        """Generate test case with comprehensive retry logic"""
        last_error = None
        for attempt in range(max_retries):
            try:
                response = self.llm(messages)
                return response.content.strip()
            except RateLimitError as e:
                last_error = e
                wait_time = 60 # Wait 1 minute for rate limits
                print(f"Rate limit hit. Waiting {wait_time} seconds (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            except (APIError, ServiceUnavailableError) as e:
                last_error = e
                wait_time = min(10 * (attempt + 1), 60) # Exponential backoff max 60s
                print(f"API error. Waiting {wait_time} seconds (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            except Exception as e:
                last_error = e
                wait_time = 5 # Short wait for other errors
                print(f"Error occurred. Waiting {wait_time} seconds (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
        
        raise Exception(f"Failed after {max_retries} attempts. Last error: {str(last_error)}")

    def _format_test_case(self, test_case: str, case_number: int, total_cases: int) -> str:
        """
        Format a single test case with headers and table structure.
        Args:
            test_case: Raw test case string.
            case_number: Index of the test case.
            total_cases: Total number of test cases.
        Returns:
            str: Formatted test case string.
        """
        """Format a single test case with proper headers and separation"""
        # Clean up the test case first
        test_case = test_case.strip()
        
        # Remove any content before the first proper test case marker
        test_case_markers = ["## Test Case", "Test Case", "Test case"]
        for marker in test_case_markers:
            if marker in test_case:
                parts = test_case.split(marker, 1)
                if len(parts) > 1:
                    test_case = marker + parts[1]
                    break
        
        # Remove any duplicate table headers
        table_header = "| Description | Pre-conditions | Action No. | Action | Expected Result |"
        if table_header in test_case:
            header_pos = test_case.find(table_header)
            # Keep only the last occurrence of the header
            last_header_pos = test_case.rfind(table_header)
            if header_pos != last_header_pos:
                test_case = test_case[last_header_pos:]
        
        # Add proper test case header
        formatted = f"\n\n{'=' * 50}\n## Test Case {case_number}/{total_cases}\n{'=' * 50}\n\n"
        
        # Ensure we have proper table headers
        if not test_case.startswith(table_header):
            formatted += table_header + "\n"
            formatted += "|-------------|----------------|------------|--------|-----------------|\n"
        
        formatted += test_case
        return formatted

    def _validate_test_case(self, test_case: str) -> bool:
        """
        Validate if a test case has the required structure and content.
        Args:
            test_case: Test case string to validate.
        Returns:
            bool: True if valid, False otherwise.
        """
        """Validate the generated test case meets minimum requirements"""
        if not test_case.strip():
            return False
        
        # Find the actual test case content (after headers)
        table_header = "| Description | Pre-conditions | Action No. | Action | Expected Result |"
        header_pos = test_case.find(table_header)
        if header_pos == -1:
            return False
        
        content = test_case[header_pos + len(table_header):]
        
        # Remove any separator lines (lines with only | and - characters)
        lines = []
        for line in content.split('\n'):
            line = line.strip()
            if line and not all(c in '|- ' for c in line):
                lines.append(line)
        
        # Check for at least one complete action row with proper content
        for line in lines:
            if line.startswith("|") and line.count("|") >= 4:
                parts = [p.strip() for p in line.split("|")[1:-1]] # Skip empty first/last parts
                if len(parts) >= 4 and parts[3] and parts[4]: # Action and Expected Result exist
                    return True
        
        return False

    def _generate_test_suite(self, feature_description: str, 
                        product_title: str,
                        generation_type: str,
                        reference_product: Optional[str] = None,
                        no_testcase: Optional[int] = 2,
                        feedback_items: Optional[List[str]] = None) -> Dict:
        """
        Generate a suite of test cases for a given feature and product.
        Args:
            feature_description: Description of the feature to test.
            product_title: Title of the product.
            generation_type: Type of generation (existing, new, similar).
            reference_product: Optional reference product for similar generation.
            no_testcase: Number of test cases to generate.
            feedback_items: Optional list of feedback strings.
        Returns:
            Dict: Dictionary with feature, test suite, sources, and stats.
        """
        """Core test suite generation that guarantees complete test cases"""
        # Get relevant documents
        retrieval_query = feature_description
        if feedback_items and len(feedback_items) > 0:
            retrieval_query = feedback_items[0] # Use first feedback item for retrieval if available
        
        print("retrieval_query--", retrieval_query)
        relevant_docs = self._get_relevant_docs(
            query=retrieval_query,
            product_title=product_title,
            reference_product=reference_product
        )

        if not relevant_docs:
            return {
                "feature": feature_description,
                "test_suite": f"No documents found for product: {product_title}",
                "sources": []
            }
        
        # Get relevant feedback - using the same method as TestCaseGenerator
        stored_feedback = self._get_relevant_feedback(feature_description, product_title)
        
        print(stored_feedback , "stored_feedback--")
        # Build feedback context - same format as TestCaseGenerator
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
        
        # Get relevant prompts or use default with feedback - same as TestCaseGenerator
        prompts = self._get_relevant_prompts(feature_description, product_title) or \
                self._get_default_prompts(feature_description, product_title, no_testcase, feedback_instructions)
        
        # Build technical context - same as TestCaseGenerator
        full_context = []
        for doc in relevant_docs:
            doc_info = f"=== {doc.metadata.get('title', 'Unknown')} (Page {doc.metadata.get('page_no', 'N/A')}) ===\n"
            content = re.sub(r'(\b0x[0-9A-Fa-f]+\b|\b\d+\b)', r'🔹\1🔹', doc.page_content)
            doc_info += f"{content}\n"
            full_context.append(doc_info)
        full_context = "\n".join(full_context)

        test_cases = []
        generated_count = 0
        total_attempts = 0
        max_total_attempts = no_testcase * 5 # Allow 5 attempts per test case
        previous_test_cases = set() # To track uniqueness

        # Generate until we have valid test cases
        while generated_count < no_testcase and total_attempts < max_total_attempts:
            total_attempts += 1
            try:
                # Format the human prompt - make sure feedback is included
                formatted_human_prompt = prompts["human_prompt"].format(
                    full_context=full_context,
                    feedback_instructions=feedback_instructions
                )

                # Add explicit instruction to incorporate feedback
                formatted_human_prompt += "\n\nIMPORTANT: Strictly implement all user feedback requirements in each test case."

                messages = [
                    SystemMessage(content=prompts["system_prompt"]),
                    HumanMessage(content=formatted_human_prompt)
                ]
                
                # Generate with retry - explicitly request only one test case
                response = self._generate_with_retry(messages)
                
                # Split response into potential multiple test cases
                raw_test_cases = self._split_generated_test_cases(response)
                
                for raw_case in raw_test_cases:
                    if generated_count >= no_testcase:
                        break
                        
                    # Validate the test case before accepting
                    if not self._validate_test_case(raw_case):
                        print(f"Generated invalid test case, skipping...")
                        continue
                    
                    # Check for uniqueness against previous test cases
                    test_case_hash = hash(raw_case.strip().lower())
                    if test_case_hash in previous_test_cases:
                        print(f"Duplicate test case detected, skipping...")
                        continue
                    
                    previous_test_cases.add(test_case_hash)
                    
                    # Format the test case with proper headers and separation
                    formatted_test_case = self._format_test_case(
                        raw_case, 
                        generated_count + 1, 
                        no_testcase
                    )
                    
                    # Add to results
                    test_cases.append(formatted_test_case)
                    generated_count += 1
                    print(f"Successfully generated test case {generated_count}/{no_testcase}")
                    
            except Exception as e:
                print(f"Error generating test case: {str(e)}")
                continue
        
        # Final validation - ensure we have exactly the requested number of test cases
        if generated_count < no_testcase:
            print(f"Warning: Only generated {generated_count} test cases after {total_attempts} attempts")
            # Fill missing test cases with placeholders
            for i in range(generated_count, no_testcase):
                placeholder = self._format_test_case(
                    f"This test case could not be generated automatically.\n"
                    "Please try again or modify your query.",
                    i + 1,
                    no_testcase
                )
                test_cases.append(placeholder)
        
        # Add initial headers only once at the beginning
        full_output = "| Description | Pre-conditions | Action No. | Action | Expected Result |\n"
        full_output += "|-------------|----------------|------------|--------|-----------------|\n"
        full_output += "\n".join(test_cases)
        
        # Update both query cache and feedback collection
        self._update_data_stores(
            feature=feature_description,
            product_title=product_title,
            test_suite=full_output,
            full_context=full_context,
            relevant_docs=relevant_docs,
            feedback_items=feedback_items
        )

        return {
            "feature": feature_description,
            "test_suite": full_output,
            "sources": sorted(list(set(
                f"{d.metadata.get('title', 'Document')} (Page {d.metadata.get('page_no', 'N/A')})"
                for d in relevant_docs
            ))),
            "generated_count": generated_count,
            "total_attempts": total_attempts
        }
    
    def _update_data_stores(self, feature: str, product_title: str, test_suite: str, 
                          full_context: str, relevant_docs: List[Document],
                          feedback_items: Optional[List[str]] = None):
        """
        Update MongoDB collections with the generated test suite.
        Args:
            feature: Feature description.
            product_title: Product title.
            test_suite: Generated test suite string.
            full_context: Context used for generation.
            relevant_docs: List of relevant Document objects.
            feedback_items: Optional list of feedback strings.
        """
        """Update both query cache and feedback collection with new test suite"""
        # Update query cache
        self.mongo_db.query_cache.update_one(
            {"query": feature},
            {"$set": {
                "test_suite": test_suite,
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
                    "previous_test_case": test_suite, # Storing suite as previous test case
                    "timestamp": datetime.utcnow(),
                    "context_used": full_context
                }},
                upsert=True
            )

    def _split_generated_test_cases(self, response: str) -> List[str]:
        """
        Split a combined response into individual test cases.
        Args:
            response: Combined string containing multiple test cases.
        Returns:
            List[str]: List of individual test case strings.
        """
        """Split a generated response into individual test cases"""
        # Split by test case markers
        case_delimiters = [
            "## Test Case",
            "Test Case",
            "Test case",
            "TEST CASE",
            "Test Scenario",
            "Test scenario"
        ]
        
        # Normalize the response
        response = response.replace("\r\n", "\n").strip()
        
        # Find all split points
        split_points = []
        for delimiter in case_delimiters:
            idx = response.find(delimiter)
            while idx != -1:
                split_points.append(idx)
                idx = response.find(delimiter, idx + 1)
        
        # Sort split points and remove duplicates
        split_points = sorted(list(set(split_points)))
        
        # If no clear splits found, return the whole response as one test case
        if not split_points:
            return [response]
        
        # Split the response at each point
        test_cases = []
        prev_split = 0
        for split in split_points:
            if split > prev_split:
                test_cases.append(response[prev_split:split].strip())
            prev_split = split
        test_cases.append(response[prev_split:].strip())
        
        return [tc for tc in test_cases if tc.strip()]

    def generate_for_existing_product(self, feature_description: str, product_title: str, 
                                    no_testcase: int = 2, feedback_items: Optional[List[str]] = None) -> Dict:
        """
        Public method to generate test suite for existing product.
        Args:
            feature_description: Description of the feature to test.
            product_title: Product title.
            no_testcase: Number of test cases to generate.
            feedback_items: Optional list of feedback strings.
        Returns:
            Dict: Dictionary with feature, test suite, sources, and stats.
        """
        """Generate test suite for existing product"""
        # Store feedback if provided - same as TestCaseGenerator
        if feedback_items:
            for feedback in feedback_items:
                self.store_feedback(
                    product_title=product_title, # Product name for which feedback is being stored
                    feature=feature_description, # Feature description related to the feedback
                    feedback=feedback, # Actual feedback text provided by the user
                    previous_test_case="Test suite generation" # Label to indicate this feedback is from test suite generation
                )
                
        return self._generate_test_suite(
            feature_description=feature_description,
            product_title=product_title,
            generation_type="existing",
            no_testcase=no_testcase,
            feedback_items=feedback_items
        )

    def generate_for_similar_product(self, feature_description: str, 
                                   primary_product: str, secondary_product: str, 
                                   no_testcase: int = 2, feedback_items: Optional[List[str]] = None) -> Dict:
        """
        Public method to generate test suite for similar product.
        Args:
            feature_description: Description of the feature to test.
            product_title: Product title.
            no_testcase: Number of test cases to generate.
            feedback_items: Optional list of feedback strings.
        Returns:
            Dict: Dictionary with feature, test suite, sources, and stats.
        """
        """Generate test suite combining similar products"""
        # Store feedback if provided - same as TestCaseGenerator
        if feedback_items:
            for feedback in feedback_items:
                self.store_feedback(
                    product_title=secondary_product, # Product name for which feedback is being stored
                    feature=feature_description, # Feature description related to the feedback
                    feedback=feedback, # Actual feedback text provided by the user
                    previous_test_case="Test suite generation" # Label to indicate this feedback is from test suite generation
                )
                
        return self._generate_test_suite(
            feature_description=feature_description,
            product_title=secondary_product,
            generation_type="similar",
            reference_product=primary_product,
            no_testcase=no_testcase,
            feedback_items=feedback_items
        )

    def generate_for_new_product(self, feature_description: str, product_title: str, 
                               no_testcase: int = 2, feedback_items: Optional[List[str]] = None) -> Dict:
        """
        Public method to generate test suite for new product.
        Args:
            feature_description: Description of the feature to test.
            product_title: Product title.
            no_testcase: Number of test cases to generate.
            feedback_items: Optional list of feedback strings.
        Returns:
            Dict: Dictionary with feature, test suite, sources, and stats.
        """
        """Generate test suite for new product"""
        # Store feedback if provided - same as TestCaseGenerator
        if feedback_items:
            for feedback in feedback_items:
                self.store_feedback(
                    product_title=product_title, # Product name for which feedback is being stored
                    feature=feature_description, # Feature description related to the feedback
                    feedback=feedback, # Actual feedback text provided by the user
                    previous_test_case="Test suite generation" # Label to indicate this feedback is from test suite generation
                )
                
        return self._generate_test_suite(
            feature_description=feature_description,
            product_title=product_title,
            generation_type="new",
            no_testcase=no_testcase,
            feedback_items=feedback_items
        )

    def _get_default_prompts(self, query: str, product_title: str, no_testcase: int = 2, 
                           feedback_instructions: str = "") -> Dict:
        """Generate default prompts with universal test case rules for test suites"""
        universal_rules = f"""
        TEST SUITE GENERATION RULES:
        IMPORTANT: - The precondtions and Step action should be detailed and in proper sentence format
        The PRECONDITIONS AND STEPS ACTIONS SHOULD BE THOROUGH AND ATLEAST CONTAIN ALL THE SUFFICIENT INFORMATION TO TEST THE FEATURE
        Make sure The bit numbers and register address all should be correctly mentioned
        1. Each test case in the suite must be unique and cover different aspects of the feature
        2. The suite should include {no_testcase} distinct test cases
        3. Test cases should progress from basic functionality to complex scenarios
        4. Include both positive and negative test cases
        5. FULL CONTEXT ANALYSIS: Analyze the entire provided context before generating test cases
        6. FEATURE IDENTIFICATION: Extract the specific feature from the query and locate all related information in context
        7. CONTEXT MAPPING: Connect scattered information across the full context to understand the complete feature scope
        8. TECHNICAL EXTRACTION: Identify all numerical values, protocols, IP addresses, ports, configurations, register addresses mentioned
        9. ENGINEERING LOGIC INFERENCE: Based on engineering principles and product documentation patterns, infer logical test scenarios even if not explicitly documented
         6. ENGINEERING TERMS : FCT Digital Channel Configuration AND ICT Digital Channel Configuration are different channel register don't mention them unless at until they are explicitly asked by user or directly related with the query For Example if asked only default channels then do mention Default Channels only and also mention their default register addresses
        i.e. For Default channels the register address come from TPVD Register table which starts from 11000
        7. WHEN ASEKD OR ALL/DIFFERENT PARAMETERS, ALWAYS MENTION ALL PARAMETERS IN TEST CASES AS PER DOCUMENTATION for EXAMPLE IF USERS MENTION DIFFERENT CHANNELS THEN MENTION ALL CHANNELS PRESENT IN DOCUMENT i.e. CH 1-CH 4

        DESCRIPTION REQUIREMENTS:
            - FOR EACH TEST CASE THE DESCRIPTION SHOULD BE DIFFERENT ACCORDIN TO THE TEST CASE GENERATED
            - Write clear, specific, business-value focused descriptions based on the feature query
            - Reference the feature purpose and scope from the context
            - Make description logical and straightforward

            PRECONDITION STANDARDS:
            - Analyze the context first, then write only valid preconditions for the specific feature
            - The precondtions should be detailed and in proper sentence format 
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
        - For Tloc the BCIM Identification Information (Labels) with Orion TU table is very important and please do mention the values in testcase
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

        - Use clear, professional technical language
        - Ensure expected results are specific and measurable
        - Number actions sequentially within each test case
        
        INTELLIGENT EXPECTED RESULTS:
        - For Tloc the BCIM Identification Information (Labels) with Orion TU table is very important and please do mention the values in testcase
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

        QUALITY VALIDATION:
        - Ensure test case aligns with the specific feature query
        - Verify all technical details come from the provided context
        - Test cases should be logically sequenced and complete
        - Expected results must be measurable and verifiable
        - Cover both positive and negative testing scenarios
        - The Expected result should be in detail i.e. when it comes read in step action and in expected result when it says should be read successfully, then please do mention what value/parameter etc is read sucessfully
        - For EXAMPLE you can say Should return 0 (unlocked) when read.
        - Whenever you mention any invalid/incorrect/unvalid/out-of-range etc type of value/params etc then please do mention the value for it in numbers or strings
        - For example Attempt to write an invalid/out-of-range value - Explain the Step Action what is the Invalid value

        Preconditions and Steps Actions:- 
        - Each step action be in proper sentence format
        - The test case should be in table format with 5 columns: Description, Pre-conditions, Action No., Action, Expected Result.
        - The test case should be in table format with 5 columns: Description, Pre-conditions, Action No., Action, Expected Result.
        - Don't say to repeat steps and instead of that do write all the steps in tescase
        - The Expected result should be in detail i.e. when it comes read in step action and in expected result when it says should be read successfully, then please do mention what value/parameter etc is read sucessfully
        - The precondtions and Step action should be detailed and in proper sentence format
        
        MANDATORY:
        - ALWAYS MENTION DEFAULT VALUES IN TEST CASES AS PER DOCUMENTATION
        - ALWAYS MENTION ALL TECHNICAL PARAMETERS IN TEST CASES AS PER DOCUMENTATION
        - WHEN USER MENTION ALL/DIFFERENT PARAMETERS, ALWAYS MENTION ALL PARAMETERS IN TEST CASES AS PER DOCUMENTATION  for EXAMPLE IF USERS MENTION DIFFERENT CHANNELS THEN MENTION ALL CHANNELS PRESENT IN DOCUMENT
        - The PRECONDITIONS AND STEPS ACTIONS SHOULD BE THOROUGH AND ATLEAST CONTAIN ALL THE SUFFICIENT INFORMATION TO TEST THE FEATURE
        - The precondtions and Step action should be detailed and in proper sentence format
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
        - For Tloc the BCIM Identification Information (Labels) with Orion TU table is very important and please do mention the values in testcase
         - For example Attempt to write an invalid/out-of-range value - Explain the Step Action what is the Invalid value
        i.e. For Default channels the register address come from TPVD Register table which starts from 11000

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

        system_prompt = f"""You are a Test Suite Generation Assistant for industrial control systems.

        FEATURE DESCRIPTION:
        {query}

        {universal_rules}

        USER FEEDBACK TO INCORPORATE:
        {feedback_instructions}

        You will generate {no_testcase} distinct test cases for this feature, each covering different aspects.

        EXAMPLE TEST CASE STRUCTURE:
        | Description | Pre-conditions | Action No. | Action | Expected Result |
        |-------------|----------------|------------|--------|-----------------|
        | [Feature summary] | 1. Precond1<br>2. Precond2 | 1.| First action | Expected outcome |
        | | | 2.| Second action | Expected outcome |
        """
        
        human_prompt = f"""Generate a comprehensive test suite with {no_testcase} distinct test cases for: {query}

        TECHNICAL CONTEXT:
        {{full_context}}

        USER FEEDBACK TO INCORPORATE:
        {{feedback_instructions}}

        REQUIREMENTS:
        1. Follow all universal test case generation rules
        2. Generate exactly {no_testcase} unique test cases
        3. Each test case must cover different aspects of the feature
        4. Include detailed preconditions per test case
        5. Use exact technical parameters from documentation
        6. Cover both normal and error conditions
        7. Validate all boundary conditions
        8. Strictly implement all user feedback requirements
        9. The precondtions and Step action should be detailed and in proper sentence format
        10. IMPORTANT: - The precondtions and Step action should be detailed and in proper sentence format
        11. The PRECONDITIONS AND STEPS ACTIONS SHOULD BE THOROUGH AND ATLEAST CONTAIN ALL THE SUFFICIENT INFORMATION TO TEST THE FEATURE
        12. Make sure The bit numbers and register address all should be correctly mentioned

        MANDATORY:
        IMPORTANT: - The precondtions and Step action should be detailed and in proper sentence format
        The PRECONDITIONS AND STEPS ACTIONS SHOULD BE THOROUGH AND ATLEAST CONTAIN ALL THE SUFFICIENT INFORMATION TO TEST THE FEATURE
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
        - For Tloc the BCIM Identification Information (Labels) with Orion TU table is very important and please do mention the values in testcase
        - For example Attempt to write an invalid/out-of-range value - Explain the Step Action what is the Invalid value
        i.e. For Default channels the register address come from TPVD Register table which starts from 11000
        - Make sure The bit numbers and register address all should be correctly mentioned

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
        Strictly use 5-column table format for each test case
        Clearly separate each test case with headers
        
        EXAMPLE TEST CASE STRUCTURE:
        | Description | Pre-conditions | Action No. | Action | Expected Result |
        |-------------|----------------|------------|--------|-----------------|
        | [Feature summary] | 1. Precond1<br>2. Precond2 | 1.| First action | Expected outcome |
        | | | 2.| Second action | Expected outcome |

        """
        
        return {
            "feature": query,
            "system_prompt": system_prompt,
            "human_prompt": human_prompt
        }
