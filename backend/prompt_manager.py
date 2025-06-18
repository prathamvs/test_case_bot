from typing import Dict, Optional, List
from pymongo import MongoClient
from langchain.chat_models import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from datetime import datetime
import traceback

class PromptManager:
    def __init__(self, mongo_db):
        self.mongo_db = mongo_db
        self.llm = ChatOpenAI(
            engine="gpt-4o",
            temperature=0,
            openai_api_key="b74bf34f88b449f5b25764e363d4dd49"
        )
        
    def analyze_and_generate_prompts(self, user_prompt: str, query: str) -> Dict:
        """Analyze user prompt and query to generate precise test case generation prompts"""
        try:
            system_message = """You are a prompt engineering specialist for industrial test case generation. 
            Analyze the user's input and generate:

            1. FEATURE: A 1-2 line description based ONLY on the query (not user prompt)
            2. SYSTEM PROMPT: Detailed test case generation instructions including:
            - Your role as test case generator
            - Feature description
            - Example test case structure
            - Also add EXAMPLE in the PROMPT when given by the user
            - ANALYZE THE EXAMPLE PROPERLY
            - Analysis of example requirements
            - Specific technical requirements
            - Formatting rules
            3. HUMAN PROMPT: Focused validation instructions including:
            - Context from user prompt
            - Specific validation requirements
            - Format enforcement

            Format response EXACTLY as:

            ###FEATURE###
            [concise feature description]

            ###SYSTEM###
            [system prompt content]

            ###HUMAN###
            [human prompt content]
            """

            human_message = f"""
            USER PROMPT CONTEXT:
            {user_prompt}

            QUERY TO BASE FEATURE ON:
            {query}

            Generate outputs with these characteristics:
            1. FEATURE: 
            - Only 1-2 lines 
            - Based solely on query
            - Technical and specific
            - Example: "Verify 72EE Engine Exerciser program configuration"

            2. SYSTEM PROMPT:
            - Start with "You are a Test Case Generation Assistant"
            - Include feature description
            - Show example test case structure
            - Analyze example requirements
            - List specific technical rules
            - Detail formatting requirements
            - Include all critical elements from user prompt

            3. HUMAN PROMPT:
            - Focus on validation
            - Reference user prompt context
            - Enforce specific technical checks
            - Require exact output format
            - Include document verification rules
            """

            response = self.llm([
                SystemMessage(content=system_message),
                HumanMessage(content=human_message)
            ])

            # Enhanced parsing with validation
            content = response.content
            result = {
                "feature": "",
                "system_prompt": "",
                "human_prompt": ""
            }

            # Parse feature section
            if '###FEATURE###' in content:
                feature_part = content.split('###FEATURE###')[1]
                result["feature"] = feature_part.split('###')[0].strip()

            # Parse system prompt section
            if '###SYSTEM###' in content:
                system_part = content.split('###SYSTEM###')[1]
                result["system_prompt"] = system_part.split('###')[0].strip()

            # Parse human prompt section
            if '###HUMAN###' in content:
                human_part = content.split('###HUMAN###')[1]
                result["human_prompt"] = human_part.strip()

            # Validate all sections
            if not all(result.values()):
                raise ValueError("Incomplete prompt sections generated")

            # Post-processing to ensure quality
            if len(result["feature"].split('\n')) > 2:
                result["feature"] = '\n'.join(result["feature"].split('\n')[:2]).strip()

            # Ensure system prompt contains critical elements
            required_system_elements = [
                "Test Case Generation Assistant",
                "feature description",
                "example test case",
                "technical rules",
                "formatting requirements"
            ]
            if not all(element in result["system_prompt"].lower() for element in required_system_elements):
                result["system_prompt"] = self._enhance_system_prompt(result["system_prompt"], user_prompt)

            # Ensure human prompt contains validation focus
            if "validate" not in result["human_prompt"].lower():
                result["human_prompt"] = self._enhance_human_prompt(result["human_prompt"], user_prompt)

            return result

        except Exception as e:
            print(f"Error generating prompts: {e}\n{traceback.format_exc()}")
            return self._generate_fallback_prompts(query, user_prompt)

    def analyze_and_structure_feedback(self, product_title: str, feature: str, 
                                    raw_feedback: str, previous_test_case: str,
                                    user_prompt: Optional[str] = None) -> Dict:
        """Analyze feedback and structure it with test case context"""
        system_message = """You are a feedback analysis specialist for test case refinement. Analyze the feedback and generate:

        1. FEATURE: The exact feature being tested (from previous test case)
        2. USER CONTEXT: Brief summary of user's original requirements
        3. STRUCTURED FEEDBACK: Actionable items categorized as:
           - Technical corrections
           - Missing test scenarios
           - Format improvements
           - Documentation references
           - Previous test case analysis

        Format response EXACTLY as:

        ###FEATURE###
        [concise feature description]

        ###USER_CONTEXT###
        [user's original requirements]

        ###FEEDBACK_ANALYSIS###
        [structured feedback analysis]
        """

        human_message = f"""
        PRODUCT: {product_title}
        FEATURE: {feature}
        USER PROMPT: {user_prompt or 'Not provided'}
        PREVIOUS TEST CASE:
        {previous_test_case}

        RAW FEEDBACK:
        {raw_feedback}

        Generate outputs with these characteristics:
        1. FEATURE: 
        - Extract from previous test case
        - Only 1-2 lines 
        - Technical and specific

        2. USER CONTEXT:
        - Summarize original requirements
        - Include key technical parameters
        - 2-3 sentences max

        3. FEEDBACK ANALYSIS:
        - Categorize each feedback point
        - Include specific references to previous test case
        - Highlight what needs to change
        - Provide concrete improvement suggestions
        - Maintain technical precision
        """

        response = self.llm([
            SystemMessage(content=system_message),
            HumanMessage(content=human_message)
        ])

        # Parse the structured response
        content = response.content
        result = {
            "feature": "",
            "user_context": "",
            "feedback_analysis": ""
        }

        # Parse feature section
        if '###FEATURE###' in content:
            feature_part = content.split('###FEATURE###')[1]
            result["feature"] = feature_part.split('###')[0].strip()

        # Parse user context section
        if '###USER_CONTEXT###' in content:
            context_part = content.split('###USER_CONTEXT###')[1]
            result["user_context"] = context_part.split('###')[0].strip()

        # Parse feedback analysis section
        if '###FEEDBACK_ANALYSIS###' in content:
            feedback_part = content.split('###FEEDBACK_ANALYSIS###')[1]
            result["feedback_analysis"] = feedback_part.strip()

        return result

    def process_and_store_feedback(self, product_title: str, feature: str, 
                                raw_feedback: str, previous_test_case: str,
                                user_prompt: Optional[str] = None) -> bool:
        """Process and store structured feedback with test case context"""
        try:
            # Structure the feedback with test case analysis
            structured_data = self.analyze_and_structure_feedback(
                product_title=product_title,
                feature=feature,
                raw_feedback=raw_feedback,
                previous_test_case=previous_test_case,
                user_prompt=user_prompt
            )
            
            # Store in MongoDB
            feedback_doc = {
                "product_title": product_title,
                "feature": feature,
                "raw_feedback": raw_feedback,
                "previous_test_case": previous_test_case,
                "structured_feedback": structured_data["feedback_analysis"],
                "timestamp": datetime.utcnow(),
                "metadata": {
                    "user_context": structured_data["user_context"],
                    "feature_description": structured_data["feature"]
                }
            }
            
            result = self.mongo_db.feedback_collection.insert_one(feedback_doc)
            return result.inserted_id is not None
            
        except Exception as e:
            print(f"Error processing feedback: {e}\n{traceback.format_exc()}")
            return False

    def _enhance_system_prompt(self, base_prompt: str, user_prompt: str) -> str:
        """Enhance system prompt with required elements"""
        enhanced_prompt = f"""You are a Test Case Generation Assistant for industrial control systems.

            1. FEATURE DESCRIPTION:
                {base_prompt.split('n')[0]}

            2. EXAMPLE TEST CASE STRUCTURE:
                | Description | Pre-conditions | Action No. | Action | Expected Result |
                |-------------|----------------|------------|--------|-----------------|
                | Verify 72EE program configuration | 1. HMI operational<br>2. Modbus connected | 1 | Configure Program 1 settings | Settings accepted |
                | | | 2 | Verify Program 1 activation | Program runs as configured |

            3. TECHNICAL REQUIREMENTS:
                - Use exact register addresses from documentation
                - Include both IPv4 and IPv6 where applicable
                - Specify complete Modbus message formats
                - Validate all timing parameters
                - Test both enable/disable states

            4. FORMATTING RULES:
                - Strict 5-column table format
                - Preconditions as numbered list
                - Actions as imperative commands
                - Expected results with exact values
                - Technical details in monospace

            5. USER CONTEXT:
                {user_prompt}
            """
        return enhanced_prompt

    def _enhance_human_prompt(self, base_prompt: str, user_prompt: str) -> str:
        """Enhance human prompt with validation focus"""
        enhanced_prompt = f"""Generate test cases with STRICT validation:

            1. CONTEXT FROM USER:
                {user_prompt}

            2. VALIDATION REQUIREMENTS:
                - Verify all numerical parameters match documentation
                - Confirm register addresses are correct
                - Check timing values are within specs
                - Validate both enabled/disabled states
                - Test boundary conditions

            3. OUTPUT FORMAT:
                STRICTLY use this format:
                | Description | Pre-conditions | Action No. | Action | Expected Result |
                |-------------|----------------|------------|--------|-----------------|
                [test case content]

            4. DOCUMENT VERIFICATION:
                - Cross-check all values with source docs
                - Flag any discrepancies
                - Include document references
            """
        return enhanced_prompt

    def _generate_fallback_prompts(self, query: str, user_prompt: str) -> Dict:
        """Generate fallback prompts when primary generation fails"""
        return {
            "feature": query.split('\n')[0][:100], # First line of query, truncated
            "system_prompt": f"""You are a Test Case Generation Assistant. Generate detailed test cases for: {query}

                EXAMPLE STRUCTURE:
                | Description | Pre-conditions | Action No. | Action | Expected Result |
                |-------------|----------------|------------|--------|-----------------|
                | [Feature summary] | 1. Precond1<br>2. Precond2 | 1 | First action | Expected outcome |

                TECHNICAL REQUIREMENTS:
                - Use values from documentation
                - Include all operational states
                - Verify timing parameters

                USER CONTEXT:
                {user_prompt}""",
            "human_prompt": f"""Generate validated test cases for: {query}

                VALIDATION FOCUS:
                - Verify all technical parameters
                - Check against documentation
                - Include boundary tests

                FORMAT REQUIREMENTS:
                Strict 5-column table with:
                1. Description
                2. Preconditions
                3. Action steps
                4. Actions
                5. Expected Results
                """
        }
    
    def store_prompts(self, title: str, feature: str, system_prompt: str, human_prompt: str) -> bool:
        """Store prompts in MongoDB with proper error handling"""
        try:
            # Validate inputs
            if not all([title, feature, system_prompt, human_prompt]):
                raise ValueError("Missing required fields")
            
            # Create document to insert
            prompt_doc = {
                "title": title,
                "feature": feature,
                "system_prompt": system_prompt,
                "human_prompt": human_prompt,
                "timestamp": datetime.utcnow()
            }
            
            # Insert and verify
            result = self.mongo_db.prompts.insert_one(prompt_doc)
            if not result.inserted_id:
                raise ValueError("No document was inserted")
            
            return True
            
        except Exception as e:
            print(f"Error storing prompts: {e}\n{traceback.format_exc()}")
            return False
            
    def get_prompts(self, title: str, feature: Optional[str] = None) -> list:
        """Retrieve stored prompts with error handling"""
        try:
            query = {"title": title}
            if feature:
                query["feature"] = {"$regex": feature, "$options": "i"}
                
            cursor = self.mongo_db.prompts.find(query, {"_id": 0}).sort("timestamp", -1)
            return list(cursor)
        except Exception as e:
            print(f"Error retrieving prompts: {e}\n{traceback.format_exc()}")
            return []