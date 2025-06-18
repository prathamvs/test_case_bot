import pdfplumber
from typing import List, Dict, Optional, Union
from langchain.schema import Document
import tiktoken
import numpy as np
import pandas as pd
from docx2pdf import convert
import os
import tempfile
import subprocess
from spire.doc import Document as SpireDocument
from spire.doc import FileFormat

class DocumentParser:
    def __init__(self):
        self.tokenizer = tiktoken.encoding_for_model("text-embedding-ada-002")
        self.HEADER_FOOTER_MARGIN = 50
        self.word_app = None


    def count_tokens(self, text: str) -> int:
        """Optimized token counting"""
        return len(self.tokenizer.encode(text, disallowed_special=()))

    def extract_pdf_content(self, pdf_path: str, doc_type: str, max_pages: Optional[int] = None) -> List[Dict]:
        """Extract text and tables from PDF based on document type"""
        documents = []
        last_feature = ""
        
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages[:max_pages] if max_pages else pdf.pages
            
            for page_num, page in enumerate(pages, 1):
                page_height = page.height
                tables = page.extract_tables()
                table_objects = page.find_tables()
                table_bboxes = [t.bbox for t in table_objects]
                elements = []
                current_text = ""
                table_index = 0 # Track which table we're processing
                
                # Combine and sort all page elements by vertical position
                items = sorted(
                    page.extract_words() + table_objects,
                    key=lambda x: x['top'] if isinstance(x, dict) else x.bbox[1]
                )
                
                for item in items:
                    if isinstance(item, dict): # Text element
                        x0, top, x1, bottom = item['x0'], item['top'], item['x1'], item['bottom']
                        
                        # Skip headers/footers and content inside tables
                        if (top < self.HEADER_FOOTER_MARGIN or 
                            bottom > page_height - self.HEADER_FOOTER_MARGIN or
                            any(x0 >= tx0 and top >= ty0 and x1 <= tx1 and bottom <= ty1 
                                for tx0, ty0, tx1, ty1 in table_bboxes)):
                            continue
                        
                        current_text += item['text'] + " "
                        
                    else: # Table element
                        if current_text.strip():
                            elements.append({"type": "text", "content": current_text.strip()})
                            if doc_type == "test_case" or "product_spec1":
                                last_feature = current_text.strip()
                            current_text = ""
                        
                        # Get the corresponding table data
                        if table_index < len(tables):
                            table_data = tables[table_index]
                            table_element = {
                                "type": "table", 
                                "content": [[str(cell) if cell is not None else "" for cell in row] 
                                           for row in table_data]
                            }
                            if doc_type == "test_case" or "product_spec1":
                                table_element["feature"] = last_feature
                            elements.append(table_element)
                            table_index += 1
                
                if current_text.strip():
                    elements.append({"type": "text", "content": current_text.strip()})
                
                documents.append({
                    "page_no": page_num,
                    "content": elements
                })
        
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
        """Process .doc file by converting to PDF first"""
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
        """Convert DOCX to PDF and process it"""
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
        """Process Excel/CSV file into document format"""
        try:
            if excel_path.endswith('.csv'):
                df = pd.read_csv(excel_path)
            else:
                df = pd.read_excel(excel_path)
            
            # Convert dataframe to list of dictionaries
            records = df.to_dict('records')
            
            # Create a single document with all data
            document = {
                "page_no": 1,
                "content": [{
                    "type": "table",
                    "content": [list(df.columns)] + [list(row.values()) for row in records]
                }],
                "original_filename": os.path.basename(excel_path)
            }
            
            return [document]
        except Exception as e:
            print(f"Error processing Excel file {excel_path}: {e}")
            return []

    def create_langchain_documents(self, mongo_docs: List[dict]) -> List[Document]:
        """Convert MongoDB documents to LangChain format"""
        lc_docs = []
        
        for doc in mongo_docs:
            for element in doc["content"]:
                if element["type"] == "text":
                    content = element["content"]
                else:
                    table_data = element["content"]
                    feature = element.get("feature", "N/A")
                    content = f"Feature: {feature}\nTable:\n" + "\n".join(
                        ["\t".join(row) for row in table_data])
                
                lc_docs.append(Document(
                    page_content=content,
                    metadata={
                        "doc_id": str(doc.get("_id", "")),
                        "title": doc["title"],
                        "doc_type": doc["doc_type"],
                        "page_no": doc["page_no"],
                        "element_type": element["type"],
                        "feature": element.get("feature", ""),
                        "original_filename": doc.get("original_filename", "")
                    }
                ))
        
        return lc_docs
