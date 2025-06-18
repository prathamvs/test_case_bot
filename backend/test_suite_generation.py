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
    def __init__(self, mongo_db):
        super().__init__(mongo_db)
        self.collection = mongo_db.collection

    def _generate_with_retry(self, messages, max_retries=5):
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

    def _validate_test_case(self, test_case: str) -> bool:
        """Validate the generated test case meets minimum requirements"""
        if not test_case.strip():
            return False
        # Check if it has at least a basic table structure
        if "|" not in test_case and "-" not in test_case:
            return False
        return True

    def _format_test_case(self, test_case: str, case_number: int, total_cases: int) -> str:
        """Format a single test case with proper headers and separation"""
        # Clean up the test case first
        test_case = test_case.strip()
        
        # Add proper headers
        formatted = f"\n\n{'=' * 50}\n## Test Case {case_number}/{total_cases}\n{'=' * 50}\n\n"
        
        # Ensure the test case has proper table formatting
        if not test_case.startswith("|"):
            # If not in table format, convert it
            lines = test_case.split('\n')
            formatted += "| Description | Pre-conditions | Action No. | Action | Expected Result |\n"
            formatted += "|-------------|----------------|------------|--------|-----------------|\n"
            formatted += "\n".join(lines)
        else:
            formatted += test_case
            
        formatted += f"\n\n{'=' * 50}"
        return formatted

    def _generate_test_suite(self, feature_description: str, 
                           product_title: str,
                           generation_type: str,
                           reference_product: Optional[str] = None,
                           no_testcase: Optional[int] = 3,
                           feedback_items: Optional[List[str]] = None) -> Dict:
        """Core test suite generation that guarantees complete test cases"""
        # Get relevant documents
        relevant_docs = self._get_relevant_docs(
            query=feature_description,
            product_title=product_title,
            reference_product=reference_product
        )

        if not relevant_docs:
            return {
                "feature": feature_description,
                "test_suite": f"No documents found for product: {product_title}",
                "sources": []
            }
        
        # Get relevant prompts or use default
        prompts = self._get_relevant_prompts(feature_description, product_title)
        
        if not prompts:
            prompts = self._get_default_prompts(feature_description, product_title, no_testcase)
        
        # Get relevant feedback
        relevant_feedback = self._get_relevant_feedback(feature_description, product_title)
        if feedback_items:
            relevant_feedback.extend([{"feedback": fb} for fb in feedback_items])
        
        # Build technical context
        full_context = []
        for doc in relevant_docs:
            doc_info = f"=== {doc.metadata.get('title', 'Unknown')} (Page {doc.metadata.get('page_no', 'N/A')}) ===\n"
            content = re.sub(r'(\b0x[0-9A-Fa-f]+\b|\b\d+\b)', r'🔹\1🔹', doc.page_content)
            doc_info += f"{content}\n"
            full_context.append(doc_info)
        full_context = "\n".join(full_context)

        # Build feedback instructions
        feedback_instructions = ""
        if relevant_feedback:
            feedback_instructions = "USER FEEDBACK TO IMPLEMENT:\n"
            for fb in relevant_feedback:
                feedback_instructions += f"- {fb['feedback']}\n"

        test_cases = []
        generated_count = 0
        total_attempts = 0
        max_total_attempts = no_testcase * 5 # Allow 5 attempts per test case
        previous_test_cases = set() # To track uniqueness

        # Generate until we have valid test cases
        while generated_count < no_testcase and total_attempts < max_total_attempts:
            total_attempts += 1
            try:
                # Format the human prompt
                formatted_human_prompt = prompts["human_prompt"].format(
                    full_context=full_context,
                    feature_description=feature_description,
                    feedback_instructions=feedback_instructions
                )

                messages = [
                    SystemMessage(content=prompts["system_prompt"]),
                    HumanMessage(content=formatted_human_prompt)
                ]
                
                # Generate with retry
                test_case = self._generate_with_retry(messages)
                
                # Validate the test case before accepting
                if not self._validate_test_case(test_case):
                    print(f"Generated invalid test case, retrying...")
                    continue
                
                # Check for uniqueness against previous test cases
                test_case_hash = hash(test_case.strip().lower())
                if test_case_hash in previous_test_cases:
                    print(f"Duplicate test case detected, retrying...")
                    continue
                
                previous_test_cases.add(test_case_hash)
                
                # Format the test case with proper headers and separation
                formatted_test_case = self._format_test_case(
                    test_case, 
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
        
        return {
            "feature": feature_description,
            "test_suite": "\n".join(test_cases),
            "sources": sorted(list(set(
                f"{d.metadata.get('title', 'Document')} (Page {d.metadata.get('page_no', 'N/A')})"
                for d in relevant_docs
            ))),
            "generated_count": generated_count,
            "total_attempts": total_attempts
        }

    def generate_for_existing_product(self, feature_description: str, product_title: str, no_testcase: int = 2) -> Dict:
        """Generate test suite for existing product"""
        return self._generate_test_suite(
            feature_description=feature_description,
            product_title=product_title,
            generation_type="existing",
            no_testcase=no_testcase
        )

    def generate_for_similar_product(self, feature_description: str, 
                                   primary_product: str, secondary_product: str, 
                                   no_testcase: int = 2) -> Dict:
        """Generate test suite combining similar products"""
        
        # print("feature--",feature_description)
        return self._generate_test_suite(
            feature_description=feature_description,
            product_title=secondary_product,
            generation_type="similar",
            reference_product=primary_product,
            no_testcase=no_testcase
        )

    def generate_for_new_product(self, feature_description: str, product_title: str, 
                               no_testcase: int = 2) -> Dict:
        """Generate test suite for new product"""
        return self._generate_test_suite(
            feature_description=feature_description,
            product_title=product_title,
            generation_type="new",
            no_testcase=no_testcase
        )

    def _get_default_prompts(self, query: str, product_title: str,no_testcase: int = 2) -> Dict:
        """Generate default prompts with universal test case rules for test suites"""
        universal_rules = f"""
        TEST SUITE GENERATION RULES:
        1. Each test case in the suite must be unique and cover different aspects of the feature
        2. The suite should include {no_testcase} distinct test cases
        3. Test cases should progress from basic functionality to complex scenarios
        4. Include both positive and negative test cases
        5. Each test case must have:
           - Clear description of what's being tested
           - 8-12 relevant preconditions
           - 12-20 detailed step actions with expected results
           - Technical parameters from documentation
        
        DOCUMENT PROCESSING METHODOLOGY:
        1. FULL CONTEXT ANALYSIS: Analyze the entire provided context before generating test cases
        2. FEATURE IDENTIFICATION: Extract the specific feature from the query and locate all related information in context
        3. CONTEXT MAPPING: Connect scattered information across the full context to understand the complete feature scope
        4. TECHNICAL EXTRACTION: Identify all numerical values, protocols, IP addresses, ports, configurations, register addresses mentioned

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

        OUTPUT FORMAT REQUIREMENTS:
        - Present in table format with 5 columns: Description | Pre-conditions | Action No. | Action | Expected Result
        - Use clear, professional technical language
        - Ensure expected results are specific and measurable
        - Number actions sequentially within each test case
        - Each test case in the suite must be clearly separated and numbered
        """
        
        system_prompt = f"""You are a Test Suite Generation Assistant for industrial control systems.

        FEATURE DESCRIPTION:
        {query}

        {universal_rules}

         USER FEEDBACK TO INCORPORATE:
        {{feedback_instructions}}

        You will generate {no_testcase} distinct test cases for this feature, each covering different aspects.

        EXAMPLE TEST CASE STRUCTURE:
        | Description | Pre-conditions | Action No. | Action | Expected Result |
        |-------------|----------------|------------|--------|-----------------|
        | [Feature summary] | 1. Precond1<br>2. Precond2 | 1. First action | Expected outcome | Verification method |
        | | | 2. Second action | Expected outcome | Verification method |

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
        4. Include 8-12 detailed preconditions per test case
        5. Create 12-20 step actions with expected results per test case
        6. Use exact technical parameters from documentation
        7. Cover both normal and error conditions
        8. Validate all boundary conditions
        9. Strictly implement all user feedback requirements

        OUTPUT FORMAT:
        Strictly use 5-column table format for each test case
        Clearly separate each test case with headers
        """
        
        return {
            "feature": query,
            "system_prompt": system_prompt,
            "human_prompt": human_prompt
        }
