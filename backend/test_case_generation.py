# from typing import Dict, List, Optional
# from pymongo import MongoClient
# from langchain.vectorstores import FAISS
# from langchain.retrievers import BM25Retriever, EnsembleRetriever
# from langchain.schema import Document
# from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
# from langchain.embeddings import OpenAIEmbeddings
# from langchain.chat_models import ChatOpenAI
# from langchain_core.messages import HumanMessage, SystemMessage
# from datetime import datetime
# from difflib import SequenceMatcher
# import re

# class TestCaseGenerator:
#     def __init__(self, mongo_db):
#         self.mongo_db = mongo_db
#         self.embeddings = OpenAIEmbeddings(
#             engine="text-embedding-ada-002",
#             openai_api_key="b74bf34f88b449f5b25764e363d4dd49"
#         )
#         self.llm = ChatOpenAI(
#             engine="gpt-4o",
#             temperature=0,
#             openai_api_key="b74bf34f88b449f5b25764e363d4dd49"
#         )
#         # self.feedback_collection = self.mongo_db.["test_case_feedback"] # New collection for feedback

#     def similar(self, a: str, b: str) -> float:
#         """Calculate similarity ratio between two strings"""
#         return SequenceMatcher(None, a.lower(), b.lower()).ratio()

#     def _get_relevant_docs(self, query: str, product_title: str, 
#                          reference_product: Optional[str] = None) -> List[Document]:
#         """Get relevant docs with optional reference product"""
#         primary_docs = self.mongo_db.get_product_documents(product_title)
#         text_docs = []
        
#         for doc in primary_docs:
#             for element in doc["content"]:
#                 if element["type"] == "text":
#                     text_docs.append(Document(
#                         page_content=element["content"],
#                         metadata=doc.get("metadata", {})
#                     ))
        
#         if reference_product:
#             ref_docs = self.mongo_db.get_product_documents(reference_product)
#             for doc in ref_docs:
#                 if "test" in doc.get("doc_type", "").lower():
#                     for element in doc["content"]:
#                         if element["type"] == "text":
#                             text_docs.append(Document(
#                                 page_content=element["content"],
#                                 metadata={"is_reference": True, **doc.get("metadata", {})}
#                             ))
        
#         if not text_docs:
#             return []
        
#         bm25_retriever = BM25Retriever.from_documents(text_docs)
#         bm25_retriever.k = 5
        
#         faiss_index = self._load_faiss_index(product_title)
#         vector_retriever = faiss_index.as_retriever(search_kwargs={"k": 5})
        
#         ensemble_retriever = EnsembleRetriever(
#             retrievers=[bm25_retriever, vector_retriever],
#             weights=[0.4, 0.6]
#         )
        
#         return ensemble_retriever.get_relevant_documents(query)

#     def _load_faiss_index(self, product_title) -> FAISS:
#         """Load FAISS index from MongoDB"""
#         chunks = list(self.mongo_db.vector_indices.find({'title':product_title}).sort("chunk_number", 1))
#         if not chunks:
#             raise ValueError("No FAISS index found in database")
        
#         faiss_bytes = b"".join(chunk["index_chunk"] for chunk in chunks)
#         return FAISS.deserialize_from_bytes(
#             embeddings=self.embeddings,
#             serialized=faiss_bytes,
#             allow_dangerous_deserialization=True
#         )

#     def _format_as_table(self, content: str, table_type: str) -> str:
#         """Ensure output is properly formatted as a table based on type"""
#         if not content.strip():
#             return content
        
#         if table_type == "existing":
#             if "| Description |" in content:
#                 return content
#             return (
#                 "| Description | Pre-Condition | Step Action | Step Expected Result | Step Notes |\n"
#                 "|-------------|---------------|-------------|----------------------|------------|\n"
#                 + content
#             )
#         else: # similar product
#             if "| Step |" in content:
#                 return content
#             return (
#                 "| Step | Action | Expected Result | Technical Details |\n"
#                 "|------|--------|-----------------|-------------------|\n"
#                 + content
#             )

#     def _generate_test_case(self, feature_description: str, product_title: str, 
#                           system_prompt: str, human_prompt: str,
#                           reference_product: Optional[str] = None,feedback_instructions: Optional[str] = None,previous_feedback: Optional[str] = None) -> Dict:
#         """Core test case generation logic"""
#         relevant_docs = self._get_relevant_docs(
#             query=feature_description,
#             product_title=product_title,
#             reference_product=reference_product
#         )
        
#         if not relevant_docs:
#             return {
#                 "feature": feature_description,
#                 "test_case": f"No documents found for product: {product_title}",
#                 "sources": []
#             }
        
#         # Build technical context from documents
#         full_context = []
#         for doc in relevant_docs:
#             doc_info = f"=== {doc.metadata.get('title', 'Unknown')} (Page {doc.metadata.get('page_no', 'N/A')}) ===\n"
#             content = re.sub(r'(\b0x[0-9A-Fa-f]+\b|\b\d+\b)', r'🔹\1🔹', doc.page_content)
#             doc_info += f"{content}\n"
#             full_context.append(doc_info)
#         full_context = "\n".join(full_context)

#         # Format the human prompt with context
#         formatted_human_prompt = human_prompt.format(
#             feature_description=feature_description,
#             full_context=full_context,
#             feedback_instructions=feedback_instructions,
#             previous_feedback="\n".join(previous_feedback) if previous_feedback else "No previous feedback available."
#         )

#         messages = [
#             SystemMessage(content=system_prompt),
#             HumanMessage(content=formatted_human_prompt)
#         ]
        
#         response = self.llm(messages)
#         test_case = response.content.strip()
        
#         # Determine table type based on prompt style
#         table_type = "existing" if "| Description |" in system_prompt else "similar"
#         test_case = self._format_as_table(test_case, table_type)
        
#         # Ensure technical details are present
#         if not re.search(r'(0x[0-9A-F]+|\b\d+\b)', test_case):
#             test_case += "\n[Technical details automatically included from documentation]"

#         # Store this query in cache
#         self.mongo_db.query_cache.update_one(
#             {"query": feature_description},
#             {"$set": {
#                 "test_case": test_case,
#                 "timestamp": datetime.utcnow()
#             }},
#             upsert=True
#         )
        
#         return {
#             "feature": feature_description,
#             "test_case": test_case,
#             "sources": sorted(list(set(
#                 f"{d.metadata.get('title', 'Document')} (Page {d.metadata.get('page_no', 'N/A')})"
#                 for d in relevant_docs
#             )))
#         }

#     def store_feedback(self,feature_description: str, feedback: str):
#         """Store user feedback for a test case"""
#         self.mongo_db.feedback_collection.insert_one({
#             "feature": feature_description,
#             "feedback": feedback,
#             "timestamp": datetime.datetime.now()
#         })

#     def get_feedback_for_feature(self,feature_description: str) -> List[str]:
#         """Retrieve all feedback for a specific feature"""
#         feedback_records = self.mongo_db.feedback_collection.find(
#             {"feature": feature_description},
#             {"_id": 0, "feedback": 1}
#         ).sort("timestamp", -1).limit(3) # Get last 3 feedback entries
#         return [f["feedback"] for f in feedback_records]

#     def generate_for_existing_product(self, feature_description: str, product_title: str) -> Dict:
#         """Generate test case for existing product (has test_case docs)"""
#         system_prompt = """You are a senior QA engineer creating detailed test cases for IFE systems. 
#                 Generate exactly ONE comprehensive test case following these STRICT rules:

#                 1. Use ONLY the provided reference materials.
#                 2. Format the output as a pure markdown table with NO title.
#                 3. Only use credentials explicitly mentioned in the documents (never invent credentials).
#                 4. Include these EXACT columns:
#                 Strictly follow the table

#                 | Description | Pre-Condition | Step Action | Step Expected Result | Step Notes |
#                 |-------------|---------------|-------------|----------------------|------------|
#                 [Properly formatted table rows here]
                
#                 5. Make the test case extremely detailed and specific to IFE systems.
#                 6. If no credentials are documented, state "See product documentation for credentials."
#                 7. Include all architectural considerations.
#                 8. Cover all verification points.
#                 9. Add relevant technical notes.
#                 10. Don't consider any full form of the the product like IFE is a product use the reference from provided document itself
#                 11. Never mention the terminologies that are not present in the context/Document
#                 12. Don't create answers on your own only provide valid answers from the document provided
#                 13. Never generate Duplicate testcases similar to what are present in the document
#                 """

#         human_prompt = """Generate ONE extremely detailed test case for: {feature_description}

#                 TECHNICAL DOCUMENTATION CONTEXT:
#                 {full_context}

#                 Output Format Requirements:
#                 - Pure markdown table only (no headers/titles)
#                 - Exact columns: | Description | Pre-Condition | Step Action | Step Expected Result | Step Notes |

#                 Content Requirements:

#                 1. Description Field:
#                 - Single paragraph (4-5 concise sentences)
#                 - Must specify:
#                     * Exact functionality being verified
#                     * All involved components/subsystems
#                     * Performance/security requirements
#                     * Documented system capacities (exact numbers only)

#                 2. Pre-Condition Field:
#                 - Numbered list (5-7 items)
#                 - Must include:
#                     * Specific system state requirements
#                     * Documented configuration parameters
#                     * Required dependencies
#                     * Exact session/data thresholds from docs
#                     * Only information from provided documents should be used not from your own or hallucinated
#                     * No generic statements (e.g., "system is powered on")

#                 3. Test Steps Field:
#                 - 8-9 comprehensive steps covering:
#                     * Normal operation
#                     * Error conditions
#                     * Security controls
#                     * Performance limits
#                     * Only information from provided documents should be used not from your own or hallucinated
#                     * No generic statements (e.g., "system is powered on")
#                 - For every test step, fill all three columns: Step Action, Step Expected Result, and Step Notes.
#                 - Do not merge or combine steps, results, or notes into a single cell.
#                 - Each row in the table must have a unique Step Action, its own Step Expected Result, and its own Step Notes.
#                 - Never leave any of these columns blank or combined for any step.

                    
#                 Critical Rules:
#                 1. Data Accuracy:
#                 - Use only numbers/values from provided documents
#                 - Never invent or approximate capacities
#                 - For multi-part tables: combine all fragments completely

#                 2. Credential Policy:
#                 - Never mention default credentials else asked in the query
#                 - Never reference documentation for credentials
#                 - Use only explicitly documented credentials

#                 3. Completeness:
#                 - Include all options from the documents as in IFE there are 6 languages available 
#                 - Warning messages must be quoted properly for example: "This Warning message should say : System overload detected."
#                 - Cover all architectural variants

#                 4. Prohibited Content:
#                 - No commercial references unless asked for example:- IFE(LV434001) the LV434001 is commercial reference please don't mention it
#                 - No version-specific information
#                 - No test environment details
#                 - No logout/restart cycles unless security testing
#                 - No browser/device repetition
#                 - Never mention username "SecurityAdmin" and password "AAAAAAAA".
#                 - Never say user to check the documentation. for example: Validate against documented default parameters.
#                 Instead of saying that please mention what is the default parameters when asked in the question.

#                 5. Mandatory rules:
#                 - Each Step Action should have proper Step Expected Result and Step Notes.
#                 * Only information from provided documents should be used not from your own or hallucinated
#                 * No generic statements (e.g., "system is powered on")

#                 EXAMPLE FORMAT FOR GENERATING TESTCASE:-
#                 | Description | Pre-Condition | Step Action | Step Expected Result | Notes |
#                 |-------------|---------------|-------------|----------------------|-------|
#                 | Verify Voltage Unbalance | 1. 400V<br>2. Trip=20%<br>...<br>8. Modbus | 1. Apply balanced voltages | System stable, no alarms | Multimeter |
#                 | | | 2. Create 10% unbalance | Alarm triggers within 100ms | Event log |
#                 | | | 3. Increase to 20% unbalance | Trip at specified delay | Timer |
#                 | | | 4. Restore voltages | System remains tripped | Visual |
#                 | | | 5. Send reset command | System resets | Protocol analyzer |
#                 | | | 6. Verify logs | Events recorded | Software |
#                 | | | 7. Reapply normal voltage | System operational | Functional test |
#                 | | | 8. Recreate 20% unbalance | Trip reoccurs | Consistency check |
#                 """

#         return self._generate_test_case(
#             feature_description=feature_description,
#             product_title=product_title,
#             system_prompt=system_prompt,
#             human_prompt=human_prompt
#         )

#     def generate_for_similar_product(self, feature_description: str, primary_product: str, 
#                                    secondary_product: str,user_feedback: Optional[str] = None) -> Dict:
                                   
#         """Generate test case by combining similar products"""
#         if user_feedback:
#             self.store_feedback(feature_description, user_feedback)
        
#         # Get previous feedback for this feature
#         previous_feedback = self.get_feedback_for_feature(feature_description)

#         system_prompt = """You are a test case generator that STRICTLY follows these rules:

#             ### 1. TEMPLATE SELECTION ###
#             - STARTER TEMPLATE TRIGGERS WHEN:
#             Feature contains: "DOL", "Star-Delta", "Reversing Starter", "Soft Starter", "Auto-Transformer"
#             - PRODUCT VERIFICATION TEMPLATE FOR:
#             All other features (Protections, Alarms, Communications, etc.)

#             ### 2. UNIVERSAL TEST CASE STRUCTURE ###
#             A. OBJECTIVE (DESCRIPTION):
#             - Use EXACT feature description from query
#             - Include document reference if specified (e.g., "as per EAIC/EDDG M_U09_F19")
#             - Format: "Verify [feature] functionality in Tesys Tera [specific conditions]"

#             B. PRECONDITION GENERATION:
#             1. Analyze feature description to identify:
#             a. FOR VOLTAGE UNBALANCE:
#             - Voltage requirements (400V/690V)
#             - Threshold values (trip/alarm levels with units)
#             - Timing parameters (delays, response times)
#             - Reset methodology (manual/auto)
#             - Protocol requirements (Modbus/Profibus)
#             - Equipment needed

#             b. FOR UNIVERSAL PRODUCT FEATURES:
#             - Based on the description, question, or feature write precondtions.
#             - i.e. First think What can be the expected preconditions for the feature logically?
#             - Keep in Mind that we are writing preconditions for Products, not for sevices.
#             - The preconditions should be related to the product features, not services.
#             - 8-12 preconditions are enough for product features. 
#             - When it comes for Protocols you can use different versions of IPs i.e. IPV4 and IPV6 as preconditions.
#             - But while using IP addresses, always use the help of documentation to get the actual IP address.
#             - When IPV6 is supported then it should discover even if the IPV4 is not in the same network range
#             - There should be no preconditions for server verification of system verifcaitons as we are writing test cases for Products, not services.
#             - When Required mention MAC address as well.

#             MANDATORY THINGS TO INCLUDE IN Precondtion STEPS when required:
#             - Mention all the details in the step action and expected result.
#                 For example :-
#                 MUST INCLUDE
#                 For DHCP:- Stop DHCP server.The expected result should be Tesys Tera should go to Fall back IP which is based on the MAC address of Tesys Tera 
#                 For DPWS:- Open windows explorer and the Tesys Tera device should be seen if PC and Tesys Tera are in same IPV4 network range.,If right click is done on the properties then it should show the details of serial number ,MAC address,IP address,
#                 If you double click the Icon then it should open the webpage, When IPV6 is supported then it should discover even if the IPV4 is not in the same network range
#                 For DNS: - It should be the Tera is configured to get IP from DHCP server and DNS server is configured.
#                 The steps should cover DNS testing by configuring SNTP server name and resolving the name and synching time from server like time.google.com 
#                 For Daylight Savings:-The test should have time set to 1 minute before the DST starts and then checking the time is incremented or decremented by one hour depending on DST starts or ends
#                 For NTP: - Action should be to remove the ethernet cable to NTP server or stop NTP server,should be only recoonect and then time should synch automatically 
#                 When Tera reboots then time will be set to default date and time in case of ethernet variants and in case of serial variants there is RTC available .That means even when powercycle is done the tera maintains the synched time 
#                 RSTP Redundancy:- Precodntion should be the Tera modules are connected in daisy chain and then in a ring with two switches supporting RSTP 
#                 RSTP should be enabled , All the diagnostic information for RSTP should be tested
            
#                 - No need of logs and Documenting things required while writing test cases for Products, not services.

#             2. Fill preconditions with SPECIFIC values:
#             - For starters: ALL 22 items with actual values
#             - For Voltage Unbalance: ALL 8 items with actual values
#             - For other products: 8-12 items with actual values
#             - Use documented values from specifications
#             - Use documented defaults if not specified

#             C. TEST STEP CONSTRUCTION:
#             1. Create 8-10 human-executable steps with:
#             a) Precise technical actions
#             b) Measurable expected results
#             c) Verification methods
            
#             2. WRITING TEST STEP ACTION AND EXPECTED RESULT:
#             - Understand the precondtions and the feature description thorughly.
#             - Based on the preconditions and feature description, get the necessary information from the document.
#             - Write the test step action and expected result in a way that it is human-executable.as you are writing testcase for Products, not services.
#             - Always use logic while writing step action and expected result.
#             For example, the only Reverse Starter type feature has forward start, reverse start, changeover time, and stop. while others i.e. Start Delta, DOL etc features have only start, changeover time, and stop etc.
#             - also mention all details in the step action and expected result.
#             For example if you say LED is blinking, then you should mention which LED is blinking, what is the expected blink rate, and what is the expected state of the LED after the action.
#             - Use documented values only, never use approximate values.
#             - Whenever you are mentioning IP address, always mention the IP address in the step action and expected result along with from where it is configured.
#             For example on start and restart, you can say Tesys Tera is configured to get IP address from DHCP server. etc
#             - When IPV6 is supported then it should discover even if the IPV4 is not in the same network range
#             - There should be no preconditions for server verification of system verifcaitons as we are writing test cases for Products, not services.
#             - If you are mentioning DI then mention DO as well.
#             - You can mention START / STOP / RESTART of the device in the step action and expected result.
#             - DHCP is server not scope, so you can mention DHCP server in the step action and expected result.

#             MANDATORY THINGS TO INCLUDE IN TEST CASES STEPS:
#             - Mention all the details in the step action and expected result.
#             For example :-
#             MUST INCLUDE
#             For DHCP:- Stop DHCP server.The expected result should be Tesys Tera should go to Fall back IP which is based on the MAC address of Tesys Tera 
#             For DPWS:- Open windows explorer and the Tesys Tera device should be seen if PC and Tesys Tera are in same IPV4 network range.,If right click is done on the properties then it should show the details of serial number ,MAC address,IP address,
#             If you double click the Icon then it should open the webpage 
#             When IPV6 is supported then it should discover even if the IPV4 is not in the same network range
#             For DNS: - It should be the Tera is configured to get IP from DHCP server and DNS server is configured.
#             The steps should cover DNS testing by configuring SNTP server name and resolving the name and synching time from server like time.google.com 
#             Daylight Savings:-The test should have time set to 1 minute before the DST starts and then checking the time is incremented or decremented by one hour depending on DST starts or ends
#             For NTP: - Action should be to remove the ethernet cable to NTP server or stop NTP server,should be only recoonect and then time should synch automatically 
#             When Tera reboots then time will be set to default date and time in case of ethernet variants and in case of serial variants there is RTC available .That means even when powercycle is done the tera maintains the synched time 
            
#             RSTP Redundancy:- Precodntion should be the Tera modules are connected in daisy chain and then in a ring with two switches supporting RSTP 
#             RSTP should be enabled , All the diagnostic information for RSTP should be tested

#             - No need of logs and Documenting things required while writing test cases for Products, not services.


#             ### 3. STARTER TEMPLATE (22-25 ACTUAL PRECONDITIONS) ### 
#             1. "1 TeSys Tera device with CTV sensor connected"
#             2. "Omicron device for current and voltage injection connected"
#             3. "Starter type = [DOL/Star-Delta/Reversing]"
#             4. "Mode Selection = [0:Disable/1:HMI/2:DI/3:Communication]"
#             5. "Time in Start = [X]s (from doc range)"
#             6. "Change over Time = [X]s (from doc range)"
#             7. "Local 1 Start = [HMI(Bit0)/Local DI(Bit1)/Remote DI(Bit2)/Communication(Bit3)]"
#             8. "Local 2 Start = [Same combinations]"
#             9. "Local 3 Start = [Same combinations]"
#             10. "Remote Start = [Same combinations]"
#             11. "Local 1 Stop = [Same combinations]"
#             12. "Local 2 Stop = [Same combinations]"
#             13. "Local 3 Stop = [Same combinations]"
#             14. "Remote Stop = [Same combinations]"
#             15. "DI 1 Settings: L-START> DI (Active High)"
#             16. "DI 2 Settings: LSTOP DI (Active Low)"
#             17. "DI 3 Settings: Local-start-DI (Active High)"
#             18. "DI 4 Settings: Mode Selection [1/2/1+2]"
#             19. "DO 1 Settings: CONTACTOR OUTPUT 1 (Active High)"
#             20. "DO 2 Settings: CONTACTOR OUTPUT 2 (Active High)"
#             21. "DO 3 Settings: CONTACTOR OUTPUT 3 (Active High)"
#             22. "DO 4 Settings: CONTACTOR OUTPUT 4 (Active High)"
#             ...

#             ### 4. VOLTAGE UNBALANCE PRECONDITIONS (8-10 ITEMS) ###
#             1. "Nominal voltage = [400V/690V]"
#             2. "Trip level = [X] [A/%/°C]"
#             3. "Alarm level = [X] [A/%/°C]"
#             4. "Trip time delay = [X]s"
#             5. "Reset mode = [Manual(key/DI/comm)/Auto(Xs)]"
#             6. "Test equipment = [Omicron/Relay tester]"
#             7. "Firmware version = [X.XX]"
#             8. "Protocol = [Modbus RTU/Ethernet IP]"
#             ...

#             ### 5. STARTER TEST CASE FORMAT (13-15 STEPS) ###
#             | Description | Pre-Condition | Step Action | Step Expected Result | Notes |
#             |-------------|---------------|-------------|----------------------|-------|
#             | [Objective] | Mandatory Write each and every preconditions | 1. | [Voltage application] | [All DO states] + LED state | [Method] |
#             | | | 2. [Start command] | [DO pattern] + LED change | [Method] |
#             | | | 3. [Timing validation] | [DO transition] | [Timer] |
#             | | | 4. [Changeover validation] | [Final DO pattern] | [Visual] |
#             | | | 5. [Stop command] | [All DOs inactive] | [Meter] |
#             | | | 6. [Reverse start] | [Reverse DO pattern] | [DI Monitor] |
#             | | | 7. [Reverse timing] | [DO transition] | [Timer] |
#             | | | 8. [Reverse changeover] | [Final DO pattern] | [Visual] |
#             | | | 9. [Voltage removal] | [LED OFF, inhibit active] | [Visual] |
#             | | | 10. [Parameter modification] | [Setting changed] | [HMI] |
#             | | | 11. [Repeat sequence] | [New timing validation] | [Timer] |
#             | | | 12. [Fault simulation] | [System response] | [Oscilloscope] |
#             | | | 13. [Recovery test] | [System reset] | [Log verification] |
#             ...

#             ### 6. VOLTAGE UNBALANCE TEST CASE FORMAT (8-10 STEPS) ###
#             | Description | Pre-Condition | Step Action | Step Expected Result | Notes |
#             |-------------|---------------|-------------|----------------------|-------|
#             | [Objective] | 1. 400V<br>2. Trip=20%<br>...<br>8. Modbus | 1. | [Baseline setup] | [Stable state] | [Method] |
#             | | | 2. [Normal operation test] | [Expected behavior] | [Method] |
#             | | | 3. [Threshold testing] | [Alarm/trip trigger] | [Method] |
#             | | | 4. [Fault simulation] | [System response] | [Method] |
#             | | | 5. [Timed verification] | [Response within tolerance] | [Timer] |
#             | | | 6. [Reset procedure] | [System recovery] | [Method] |
#             | | | 7. [Log verification] | [Event recorded] | [Software] |
#             | | | 8. [Consistency check] | [Repeatable behavior] | [Method] |
#             | | | 9. [Protocol validation] | [Data matches] | [Protocol analyzer] |
#             | | | 10. [Final verification] | [System stable] | [Functional test] |

#             ### 7. GENERATION RULES ###
#             1. MANDATORY ELEMENTS:
#             - Objectives must match feature description verbatim
#             - Preconditions must use ACTUAL DOCUMENTED VALUES
#             - All steps must include SPECIFIC TOLERANCES (±Xms/±X%)
#             - Verification methods must be HUMAN-EXECUTABLE

#             2. PROHIBITIONS:
#             ❌ Never omit DO states (starters)
#             ❌ Never skip timing validations
#             ❌ Never combine test scenarios
#             ❌ Never assume default behaviors
#             ❌ Never use approximate values
#             ❌ Never reference page numbers
#             ❌ Never say All preconditions are met,Precondtions as above,See preconditions above etc. Must write all precondtions within the test case table.

#             MANDATORY: - 8. USER FEEDBACK TO INCORPORATE ###
#             {feedback_instructions}

#             """

#         human_prompt = """Generate test case for: {feature_description}

#             [Product Specifications]
#             {full_context}

#             ### GENERATION INSTRUCTIONS:
#             1. DETERMINE TEMPLATE:
#             - If feature contains starter keywords → Use starter format (13 steps)
#             - Else → Use product verification format (8-10 steps)

#             2. CREATE OBJECTIVE:
#             - Use EXACT feature description from query
#             - Include reference document if specified
#             - Example: "Verify {feature_description} in Tesys Tera"

#             3. BUILD PRECONDITIONS:
#             A. FOR STARTERS:
#             - Extract values for all 22 preconditions from specs
#             - Use documented defaults where needed

#             B. FOR PRODUCTS:
#             - Analyze feature to identify:
#             - Voltage requirements → Precon 1
#             - Trip/Alarm levels → Precon 2-3
#             - Timing delays → Precon 4
#             - Reset method → Precon 5
#             - Equipment → Precon 6
#             - Firmware → Precon 7
#             - Protocol → Precon 8

#             4. GENERATE TEST STEPS:
#             A. STARTERS (13 STEPS):
#             - Follow exact sequence: Voltage → Start → Timing → Changeover → Stop → Reverse → Parameter change → Fault → Recovery

#             B. VOLTAGE UNBALANCE PRODUCTS (8-10 STEPS):
#             1. Baseline: Establish normal conditions
#             2. Operation: Test normal functionality
#             3. Threshold: Verify alarm/trip levels
#             4. Fault: Simulate error condition
#             5. Response: Validate system reaction
#             6. Reset: Execute recovery procedure
#             7. Logs: Check event recording
#             8. Protocol: Validate communication
#             9. Consistency: Repeat critical tests
#             10. Final: Confirm system stability

#             5. OUTPUT FORMATTING:
#             - Use EXACT table structures shown
#             - Include ALL columns
#             - Maintain technical precision
#             - Use documented values with tolerances
#             - Ensure human-executable steps
#             ❌ Never say All preconditions are met,Precondtions as above,See preconditions above etc. Must write all precondtions within the test case table.

#             MANDATORY: - 8. USER FEEDBACK TO INCORPORATE ###
#             {previous_feedback}

            
#             ### EXAMPLE: VOLTAGE UNBALANCE ###
#             | Description | Pre-Condition | Step Action | Step Expected Result | Notes |
#             |-------------|---------------|-------------|----------------------|-------|
#             | Verify Voltage Unbalance | 1. 400V<br>2. Trip=20%<br>...<br>8. Modbus | 1. Apply balanced voltages | System stable, no alarms | Multimeter |
#             | | | 2. Create 10% unbalance | Alarm triggers within 100ms | Event log |
#             | | | 3. Increase to 20% unbalance | Trip at specified delay | Timer |
#             | | | 4. Restore voltages | System remains tripped | Visual |
#             | | | 5. Send reset command | System resets | Protocol analyzer |
#             | | | 6. Verify logs | Events recorded | Software |
#             | | | 7. Reapply normal voltage | System operational | Functional test |
#             | | | 8. Recreate 20% unbalance | Trip reoccurs | Consistency check |
#             """

#             # Prepare feedback instructions
#         feedback_instructions = "No previous feedback available."
#         if previous_feedback:
#             feedback_instructions = "Previous user feedback to consider:\n- " + "\n- ".join(previous_feedback)

#         return self._generate_test_case(
#             feature_description=feature_description,
#             product_title=secondary_product,
#             system_prompt=system_prompt,
#             human_prompt=human_prompt,
#             reference_product=primary_product,
#             feedback_instructions=feedback_instructions,
#             previous_feedback="\n".join(previous_feedback) if previous_feedback else "No previous feedback available."
#         )

#     def generate_for_new_product(self, feature_description: str, product_title: str) -> Dict:
#         """Generate test case for a completely new product (no existing docs)"""
#         system_prompt = """You are a senior QA engineer creating test cases for a new product. 
#         Since this is a new product with no existing documentation, you'll need to:
        
#         1. Create a comprehensive test case based on standard practices
#         2. Include all necessary technical details
#         3. Follow this format:
        
#         | Description | Pre-Condition | Step Action | Step Expected Result | Step Notes |
#         |-------------|---------------|-------------|----------------------|------------|
#         [Properly formatted table rows]
        
#         Rules:
#         - Be as detailed as possible
#         - Include typical technical parameters
#         - Cover normal operation and error cases
#         - Mark all values as [TBD] where specific numbers aren't available
#         """
        
#         human_prompt = f"""Generate a detailed test case for new product: {product_title}
        
#         Feature: {feature_description}
        
#         Requirements:
#         1. Create 8-10 test steps covering:
#            - Normal operation
#            - Error conditions
#            - Performance limits
#            - Security controls
        
#         2. For each step, provide:
#            - Specific actions
#            - Measurable expected results
#            - Verification methods
        
#         3. Technical Details:
#            - Include typical parameters marked as [TBD] where needed
#            - Cover all functional aspects
#            - Add relevant technical notes
#         """
        
#         messages = [
#             SystemMessage(content=system_prompt),
#             HumanMessage(content=human_prompt)
#         ]
        
#         response = self.llm(messages)
#         test_case = response.content.strip()
        
#         # Format as table if not already
#         if not test_case.startswith("|"):
#             test_case = (
#                 "| Description | Pre-Condition | Step Action | Step Expected Result | Step Notes |\n"
#                 "|-------------|---------------|-------------|----------------------|------------|\n"
#                 + test_case
#             )
            
#         return {
#             "feature": feature_description,
#             "test_case": test_case,
#             "sources": ["New product - no existing documentation"],
#             "notes": "This test case was generated without reference documentation. All [TBD] markers should be replaced with actual values once available."
#         }

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
            openai_api_key="b74bf34f88b449f5b25764e363d4dd49"
        )
        self.llm = ChatOpenAI(
            engine="gpt-4o",
            temperature=0,
            openai_api_key="b74bf34f88b449f5b25764e363d4dd49"
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