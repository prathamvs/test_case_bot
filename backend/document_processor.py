# ============================================================================
# IMPORTS
# ============================================================================
import pdfplumber
from typing import List, Dict, Optional, Union
from langchain.schema import Document
import tiktoken
import pandas as pd
from docx2pdf import convert
import os
import tempfile
import subprocess
from spire.doc import Document as SpireDocument
from spire.doc import FileFormat

class DocumentParser:
    """
    A comprehensive document parser that extracts and processes content from PDF, DOCX, and Excel files.
    
    This class handles various document types including test cases and product specifications,
    extracting both text and tabular data while maintaining proper structure and metadata.
    """
    
    def __init__(self):
        """
        Initialize the DocumentParser with tokenizer and configuration settings.
        
        Sets up the OpenAI tokenizer for token counting and defines margins for
        header/footer detection in PDF documents.
        """
        
        self.tokenizer = tiktoken.encoding_for_model("text-embedding-ada-002")
        self.HEADER_FOOTER_MARGIN = 50
        self.word_app = None

    def count_tokens(self, text: str) -> int:
        """
        Count the number of tokens in a given text string.
        
        Args:
            text (str): The input text to tokenize
            
        Returns:
            int: Number of tokens in the text
            
        Note:
            Uses OpenAI's tiktoken library for accurate token counting
            that matches their embedding models.
        """
        return len(self.tokenizer.encode(text, disallowed_special=()))

    def is_meaningful_text(self, text: str) -> bool:
        """Check if text is meaningful enough to be used as a feature"""
        text = text.strip()
        if len(text) < 10:  # Too short
            return False
        if text.isdigit():  # Just a number (likely page number)
            return False
        if len(text.split()) < 3:  # Less than 3 words
            return False
        # Filter out common non-meaningful patterns
        if text.lower() in ['table of contents', 'page', 'header', 'footer']:
            return False
        return True

    def find_best_feature_for_table(self, all_text_elements: List[Dict], table_page: int, table_top: float) -> str:
        """Find the best feature text for a table using improved strategy"""
        feature_text = ""
        
        # Strategy 1: Look for heading on same page above the table
        same_page_elements = [elem for elem in all_text_elements if elem['page'] == table_page]
        same_page_headings = [elem for elem in same_page_elements 
                            if elem['is_heading'] and elem['position'] < table_top]
        
        if same_page_headings:
            # Get the closest heading above the table
            closest_heading = max(same_page_headings, key=lambda x: x['position'])
            feature_text = closest_heading['text']
            print(f"    Found same-page heading: '{feature_text[:50]}...'")
            return feature_text
        
        # Strategy 2: Look for any meaningful text on same page above the table
        texts_before_table = [elem for elem in same_page_elements 
                            if elem['position'] < table_top]
        if texts_before_table:
            closest_text = max(texts_before_table, key=lambda x: x['position'])
            feature_text = closest_text['text']
            print(f"    Found same-page text before table: '{feature_text[:50]}...'")
            return feature_text
        
        # Strategy 3: If no text before table on same page, get first text on same page
        if same_page_elements:
            feature_text = same_page_elements[0]['text']
            print(f"    Found first text on same page: '{feature_text[:50]}...'")
            return feature_text
        
        # Strategy 4: Look for the most recent text from previous pages
        previous_pages_elements = [elem for elem in all_text_elements if elem['page'] < table_page]
        if previous_pages_elements:
            # Sort by page and position to get the most recent text
            previous_pages_elements.sort(key=lambda x: (x['page'], x['position']))
            most_recent = previous_pages_elements[-1]  # Get the last (most recent) element
            feature_text = most_recent['text']
            print(f"    Found text from previous page {most_recent['page']}: '{feature_text[:50]}...'")
            return feature_text
        
        # Strategy 5: Look for the next available text from subsequent pages
        subsequent_pages_elements = [elem for elem in all_text_elements if elem['page'] > table_page]
        if subsequent_pages_elements:
            # Sort by page and position to get the earliest text
            subsequent_pages_elements.sort(key=lambda x: (x['page'], x['position']))
            next_text = subsequent_pages_elements[0]  # Get the first (earliest) element
            feature_text = next_text['text']
            print(f"    Found text from subsequent page {next_text['page']}: '{feature_text[:50]}...'")
            return feature_text
        
        print("    No feature text found for table")
        return "N/A"

    def extract_pdf_content(self, pdf_path: str, doc_type: str, max_pages: Optional[int] = None) -> List[Dict]:
        """
        Extract structured content (text and tables) from PDF files.
        
        This method processes PDF pages to extract text and tables while maintaining
        their relative positions and relationships. It filters out headers/footers
        and handles special document types like test cases and product specifications.
        
        Args:
            pdf_path (str): Path to the PDF file to process
            doc_type (str): Type of document ("test_case", "product_spec1", etc.)
            max_pages (Optional[int]): Maximum number of pages to process (None for all)
            
        Returns:
            List[Dict]: List of dictionaries containing page content with structure:
                {
                    "page_no": int,
                    "content": [
                        {
                            "type": "text" | "table",
                            "content": str | List[List[str]],
                            "feature": str (optional, for test cases/product specs)
                        }
                    ]
                }
        """
        documents = []
        all_text_elements = []  # Store all meaningful text across pages for this document
        
        print(f"Processing document: {pdf_path}")
        print(f"Document type: {doc_type}")
        
        # First pass: Extract all text elements from all pages
        print(f"Starting first pass - extracting text elements...")
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages[:max_pages] if max_pages else pdf.pages
            print(f"Total pages to process: {len(pages)}")
            
            for page_num, page in enumerate(pages, 1):
                print(f"Processing page {page_num} for text extraction...")
                page_height = page.height
                table_objects = page.find_tables()
                table_bboxes = [t.bbox for t in table_objects]
                
                # Extract text elements
                text_items = page.extract_words(extra_attrs=["fontname", "size"])
                
                current_paragraph = ""
                current_words = []
                prev_bottom = 0
                page_text_count = 0
                
                for item in text_items:
                    x0, top, x1, bottom = item['x0'], item['top'], item['x1'], item['bottom']
                    
                    # Skip headers/footers and content inside tables
                    if (top < self.HEADER_FOOTER_MARGIN or 
                        bottom > page_height - self.HEADER_FOOTER_MARGIN or
                        any(x0 >= tx0 and top >= ty0 and x1 <= tx1 and bottom <= ty1 
                            for tx0, ty0, tx1, ty1 in table_bboxes)):
                        continue
                    
                    # Detect paragraph breaks
                    if not current_paragraph or (item['top'] - prev_bottom > 5):
                        if current_paragraph and self.is_meaningful_text(current_paragraph):
                            # Check if this looks like a heading
                            is_heading = (any(w.get('size', 0) > 10 for w in current_words) or 
                                        any("bold" in w.get('fontname', '').lower() for w in current_words) or 
                                        current_paragraph.isupper())
                            
                            all_text_elements.append({
                                'text': current_paragraph,
                                'page': page_num,
                                'position': prev_bottom,
                                'is_heading': is_heading
                            })
                            page_text_count += 1
                            print(f"  Found meaningful text {page_text_count}: '{current_paragraph[:50]}...' (heading: {is_heading})")
                        
                        current_paragraph = item['text']
                        current_words = [item]
                    else:
                        current_paragraph += " " + item['text']
                        current_words.append(item)
                    
                    prev_bottom = bottom
                
                # Add final paragraph
                if current_paragraph and self.is_meaningful_text(current_paragraph):
                    is_heading = (any(w.get('size', 0) > 10 for w in current_words) or 
                                any("bold" in w.get('fontname', '').lower() for w in current_words) or 
                                current_paragraph.isupper())
                    
                    all_text_elements.append({
                        'text': current_paragraph,
                        'page': page_num,
                        'position': prev_bottom,
                        'is_heading': is_heading
                    })
                    page_text_count += 1
                    print(f"  Found meaningful text {page_text_count}: '{current_paragraph[:50]}...' (heading: {is_heading})")
                
                print(f"Page {page_num}: Found {page_text_count} meaningful text elements")

        print(f"First pass complete. Total text elements found: {len(all_text_elements)}")

        # Second pass: Process pages and assign features to tables
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages[:max_pages] if max_pages else pdf.pages
            
            for page_num, page in enumerate(pages, 1):
                print(f"\nProcessing page {page_num} for table extraction...")
                page_height = page.height
                tables = page.extract_tables()
                table_objects = page.find_tables()
                elements = []
                
                # Process text elements on current page
                page_text_elements = [elem for elem in all_text_elements if elem['page'] == page_num]
                print(f"  Found {len(page_text_elements)} text elements on page {page_num}")
                print(f"  Found {len(tables)} tables on page {page_num}")
                
                # Process tables and assign features
                for table_idx, (table_obj, table_data) in enumerate(zip(table_objects, tables)):
                    if table_data:  # Only process non-empty tables
                        table_top = table_obj.bbox[1]
                        print(f"  Processing table {table_idx + 1} at position {table_top}")
                        
                        # Use the improved feature finding method
                        feature_text = self.find_best_feature_for_table(all_text_elements, page_num, table_top)
                        
                        table_element = {
                            "type": "table",
                            "content": [[str(cell) if cell is not None else "" for cell in row] 
                                      for row in table_data],
                            "feature": feature_text
                        }
                        
                        elements.append(table_element)
                        print(f"  Table {table_idx + 1} assigned feature: '{feature_text[:50]}...'")
                
                # Add text elements to the page
                for text_elem in page_text_elements:
                    elements.append({
                        "type": "text",
                        "content": text_elem['text'],
                        "is_heading": text_elem['is_heading']
                    })
                
                # Only add page if it has content
                if elements:
                    documents.append({
                        "page_no": page_num,
                        "content": elements
                    })
                    print(f"  Added page {page_num} with {len(elements)} elements")
        
        print(f"\nDocument processing complete. Total pages with content: {len(documents)}")
        return documents

    def convert_doc_to_pdf(self, doc_path: str) -> str:
        """Convert .doc to PDF using Spire.Doc"""
        try:
            # Create temp output directory
            temp_dir = tempfile.mkdtemp()
            pdf_path = os.path.join(temp_dir, "converted.pdf")
            
            # Load the .doc file
            doc = SpireDocument()
            print(doc_path)
            doc.LoadFromFile(doc_path)
            
            # Save as PDF
            doc.SaveToFile(pdf_path, FileFormat.PDF)
            doc.Close()
            
            return pdf_path
        except Exception as e:
            raise Exception(f"Failed to convert .doc to PDF using Spire.Doc: {str(e)}")
        finally:
            if 'doc' in locals():
                doc.Close()

    def process_doc(self, doc_path: str, doc_type: str, max_pages: Optional[int] = None) -> List[Dict]:
       """
        Process DOC files by converting them to PDF first, then extracting content.
        
        This method handles DOC files by leveraging the existing PDF processing pipeline.
        It converts the DOC to a temporary PDF file, processes it, and cleans up.
        
        Args:
            doc_path (str): Path to the DOC file to process
            doc_type (str): Type of document for processing logic
            max_pages (Optional[int]): Maximum number of pages to process
            
        Returns:
            List[Dict]: Same structure as extract_pdf_content, with added original_filename
            
        Raises:
            Exception: If DOC to PDF conversion fails
        """
        try:
            # Convert .doc to PDF
            pdf_path = self.convert_doc_to_pdf(doc_path)
            
            # Process the converted PDF
            pdf_content = self.extract_pdf_content(pdf_path, doc_type, max_pages)
            
            print("docx_path", doc_path)
            # Add original filename to each page
            original_filename = os.path.basename(doc_path)
            for page in pdf_content:
                page['original_filename'] = original_filename
            
            return pdf_content
        except Exception as e:
            raise Exception(f"Error processing .doc file: {str(e)}")
        finally:
            # Clean up temporary PDF file
            if 'pdf_path' in locals() and os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                    # Remove the temp directory if empty
                except Exception as e:
                    print(f"Warning: Could not clean up temp PDF file: {str(e)}")

    def process_docx(self, docx_path: str, doc_type: str, max_pages: Optional[int] = None) -> List[Dict]:
        """
        Process DOCX files by converting them to PDF first, then extracting content.
        
        This method handles DOCX files by leveraging the existing PDF processing pipeline.
        It converts the DOCX to a temporary PDF file, processes it, and cleans up.
        
        Args:
            docx_path (str): Path to the DOCX file to process
            doc_type (str): Type of document for processing logic
            max_pages (Optional[int]): Maximum number of pages to process
            
        Returns:
            List[Dict]: Same structure as extract_pdf_content, with added original_filename
            
        Raises:
            Exception: If DOCX to PDF conversion fails
        """
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_pdf:
            temp_pdf_path = temp_pdf.name
        
        try:
            # Convert DOCX to PDF
            convert(docx_path, temp_pdf_path)
            
            # Process the converted PDF
            pdf_content = self.extract_pdf_content(temp_pdf_path, doc_type, max_pages)
            
            # Add original filename to each page
            original_filename = os.path.basename(docx_path)
            for page in pdf_content:
                page['original_filename'] = original_filename
            
            return pdf_content
        finally:
            # Clean up temporary PDF file
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)

    def process_excel(self, excel_path: str) -> List[Dict]:
        """
        Process Excel and CSV files into the standard document format.
        
        This method reads tabular data from Excel (.xlsx, .xls) or CSV files
        and converts them into the same document structure used for PDFs.
        
        Args:
            excel_path (str): Path to the Excel or CSV file
            
        Returns:
            List[Dict]: Single-page document containing the entire spreadsheet as a table
            Structure:
                [{
                    "page_no": 1,
                    "content": [{
                        "type": "table",
                        "content": [headers_row, data_row1, data_row2, ...]
                    }],
                    "original_filename": str
                }]
        """
        try:
            # Read the file
            if excel_path.endswith('.csv'):
                df = pd.read_csv(excel_path, keep_default_na=False)
            else:
                df = pd.read_excel(excel_path, keep_default_na=False)
            
            # Convert all data to strings and clean
            cleaned_data = []
            for col in df.columns:
                # Convert column to string and clean
                cleaned_col = df[col].astype(str).str.strip()
                cleaned_data.append(cleaned_col)
            
            # Recreate dataframe with cleaned string data
            str_df = pd.concat(cleaned_data, axis=1, keys=df.columns)
            
            # Convert to list of lists with headers
            table_data = [list(str_df.columns)]
            table_data.extend([list(row) for row in str_df.values])
            
            # Create meaningful feature text
            feature_text = f"Data from {os.path.basename(excel_path)}"
            if len(str_df) > 0:
                feature_text += f" showing {len(str_df)} records"
            
            # Create document structure
            document = {
                "page_no": 1,
                "content": [{
                    "type": "table",
                    "content": table_data,
                    "feature": feature_text
                }],
                "original_filename": os.path.basename(excel_path)
            }
            
            return [document]
        except Exception as e:
            print(f"Error processing Excel file {excel_path}: {e}")
            return []


    def create_langchain_documents(self, mongo_docs: List[dict]) -> List[Document]:
        """
        Convert processed documents from MongoDB format to LangChain Document objects.
        
        This method transforms the structured document data into LangChain Document objects
        suitable for vector storage and retrieval. Each text block and table becomes a
        separate Document with rich metadata.
        
        Args:
            mongo_docs (List[dict]): List of documents in MongoDB storage format
            
        Returns:
            List[Document]: LangChain Document objects with content and metadata
            
        Document Structure:
            - page_content: The actual text or formatted table content
            - metadata: Dictionary containing doc_id, title, doc_type, page_no, 
                       element_type, feature, and original_filename
        """
        lc_docs = []
        # Process each document from the MongoDB collection
        for doc in mongo_docs:
            # Process each content element (text block or table) on the page
            for element in doc["content"]:
                if element["type"] == "text":
                    content = element["content"]
                    
                else:
                    # For tables, format them with feature context and tab-separated values
                    table_data = element["content"]
                    feature = element.get("feature", "N/A")
                    # Create formatted table content with feature header    
                    content = f"Feature: {feature}\nTable:\n" + "\n".join(
                        ["\t".join(row) for row in table_data])

                # Create LangChain Document with content and comprehensive metadata
                lc_docs.append(Document(
                    page_content=content,
                    metadata={
                        "doc_id": str(doc.get("_id", "")),# MongoDB document ID
                        "title": doc["title"],# Document title
                        "doc_type": doc["doc_type"],# Document type classification
                        "page_no": doc["page_no"],# Page number within document
                        "element_type": element["type"],# "text" or "table"
                        "feature": element.get("feature", ""), # Associated feature (if any)
                        "original_filename": doc.get("original_filename", "") # Original file name
                    }
                ))
        
        return lc_docs
