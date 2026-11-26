from typing import Dict, List, Any, Optional
from pathlib import Path
import os
import json
import openpyxl
import pandas as pd
from datetime import datetime
from smolagents import OpenAIModel
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

load_dotenv()

class ExcelStyleAnalyzer:
    """Extract special styles and formatting from Excel files using openpyxl"""
    
    def __init__(self):
        self.workbook = None
        
    def analyze_workbook(self, filepath: str) -> Dict[str, Any]:
        """Analyze an Excel workbook and extract style information"""
        try:
            self.workbook = openpyxl.load_workbook(filepath, data_only=False)
            workbook_info = {
                "file_name": os.path.basename(filepath),
                "sheets": {}
            }
            
            # Pre-extract sheet objects to avoid concurrent access
            sheet_objects = {name: self.workbook[name] for name in self.workbook.sheetnames}
            
            # Use ThreadPoolExecutor for parallel sheet processing
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_sheet = {
                    executor.submit(self.analyze_sheet, sheet_objects[sheet_name]): sheet_name
                    for sheet_name in self.workbook.sheetnames
                }
                
                for future in as_completed(future_to_sheet):
                    sheet_name = future_to_sheet[future]
                    try:
                        sheet_data = future.result()
                        workbook_info["sheets"][sheet_name] = sheet_data
                    except Exception as e:
                        print(f"Error analyzing sheet {sheet_name}: {e}")
                        workbook_info["sheets"][sheet_name] = self._create_error_sheet_info(str(e))
                        
            return workbook_info
        except Exception as e:
            raise Exception(f"Failed to analyze Excel file {filepath}: {str(e)}")

    def _create_error_sheet_info(self, error_msg: str) -> Dict[str, Any]:
        """Create error sheet info when sheet analysis fails"""
        return {
            "dimensions": {"max_row": 0, "max_column": 0},
            "merged_cells": [],
            "formulas": [],
            "data": [],
            "style_info": [],
            "error": error_msg
        }
    
    def analyze_sheet(self, sheet) -> Dict[str, Any]:
        """Analyze a single worksheet"""
        sheet_info = {
            "dimensions": {
                "max_row": sheet.max_row,
                "max_column": sheet.max_column
            },
            "merged_cells": [],
            "formulas": [],
            "data": [],
            "style_info": []
        }
        
        # Extract merged cells
        for merged_range in sheet.merged_cells.ranges:
            sheet_info["merged_cells"].append({
                "range": str(merged_range),
                "start_row": merged_range.min_row,
                "start_col": merged_range.min_col,
                "end_row": merged_range.max_row,
                "end_col": merged_range.max_col
            })
        
        # Extract data, formulas, and basic style info
        for row_idx in range(1, sheet.max_row + 1):
            row_data = []
            for col_idx in range(1, sheet.max_column + 1):
                cell = sheet.cell(row_idx, col_idx)
                cell_info = self.analyze_cell(cell, row_idx, col_idx)
                row_data.append(cell_info)
                
                # Collect formulas
                if cell_info.get("has_formula"):
                    sheet_info["formulas"].append({
                        "row": row_idx,
                        "col": col_idx,
                        "formula": cell_info["formula"]
                    })
            
            sheet_info["data"].append(row_data)
            
        return sheet_info
    
    def analyze_cell(self, cell, row: int, col: int) -> Dict[str, Any]:
        """Analyze individual cell properties"""
        cell_info = {
            "row": row,
            "col": col,
            "value": cell.value,
            "display_value": str(cell.value) if cell.value is not None else "",
            "has_formula": False,
            "formula": None,
            "is_merged": False,
            "font_bold": False,
            "alignment": None
        }
        
        # Check for formula
        if hasattr(cell, 'formula') and cell.formula:
            cell_info["has_formula"] = True
            cell_info["formula"] = cell.formula
        elif str(cell.value).startswith('=') if cell.value else False:
            cell_info["has_formula"] = True
            cell_info["formula"] = str(cell.value)
            
        # Check formatting
        if cell.font and cell.font.bold:
            cell_info["font_bold"] = True
            
        if cell.alignment:
            cell_info["alignment"] = {
                "horizontal": cell.alignment.horizontal,
                "vertical": cell.alignment.vertical
            }
            
        return cell_info


class LLMTableAnalyzer:
    """Use LLM to analyze table structure with thread safety"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.model_name = model_name
        self.model_config = {
            "model_id": os.getenv("MODEL_NAME", model_name),
            "api_base": os.getenv("BASE_URL"),
            "api_key": os.getenv("API_KEY"),
            "temperature": 0,
            "max_tokens": 16384,
            "top_p": 0.9,
        }
        # Thread-local storage for model instances
        self._local = threading.local()
    
    def _get_model(self):
        """Get thread-local model instance"""
        if not hasattr(self._local, 'model'):
            self._local.model = OpenAIModel(**self.model_config)
        return self._local.model
        
    def prepare_sheet_data(self, sheet_data: List[List[Dict]], style_info: Dict) -> str:
        """Prepare sheet data for LLM analysis"""
        # Convert cell data to readable format
        rows = []
        for row_data in sheet_data:
            row_values = []
            for cell in row_data:
                value = cell.get("display_value", "")
                if cell.get("has_formula"):
                    value += f" [FORMULA: {cell.get('formula', '')}]"
                if cell.get("font_bold"):
                    value = f"**{value}**"
                row_values.append(value)
            rows.append(row_values)
        
        # Remove completely empty rows
        non_empty_rows = []
        for i, row in enumerate(rows):
            if any(cell.strip() for cell in row):
                non_empty_rows.append((i + 1, row))  # 1-indexed for user readability
        
        # Select rows for LLM (first 8 and last 6 if > 20 rows)
        if len(non_empty_rows) <= 20:
            selected_rows = non_empty_rows
        else:
            selected_rows = non_empty_rows[:8] + [("...", ["..."] * len(non_empty_rows[0][1]))] + non_empty_rows[-6:]
        
        # Format for LLM
        formatted_data = []
        for row_idx, row_data in selected_rows:
            if row_idx == "...":
                formatted_data.append("... (rows omitted) ...")
            else:
                row_str = ",".join(f'"{str(cell)}"' for cell in row_data)
                formatted_data.append(f"Row {row_idx}: {row_str}")
        
        # Add style information
        style_summary = []
        if style_info.get("merged_cells"):
            style_summary.append("Merged cells detected:")
            for merge in style_info["merged_cells"][:5]:  # Limit to first 5
                style_summary.append(f"  - {merge['range']}")
        
        if style_info.get("formulas"):
            style_summary.append("Formulas detected:")
            for formula in style_info["formulas"][:5]:  # Limit to first 5
                style_summary.append(f"  - Row {formula['row']}, Col {formula['col']}: {formula['formula']}")
        
        result = "\n".join(formatted_data)
        if style_summary:
            result += "\n\nStyle Information:\n" + "\n".join(style_summary)
        
        return result
    
    def analyze_with_llm(self, sheet_data: str, initial_description: str = "") -> Dict[str, Any]:
        """Send data to LLM for analysis (thread-safe)"""
        try:
            # Prepare the prompt
            template = self._load_template()
            
            # Enhanced sheet data with initial description
            enhanced_data = sheet_data
            if initial_description.strip():
                enhanced_data = f"User's description: {initial_description}\n\n{sheet_data}"
            
            prompt = template.replace("{sheet_data}", enhanced_data)
            
            # Call LLM with thread-local model
            model = self._get_model()
            response = model([{"role": "user", "content": prompt}])
            
            # Extract content from ChatMessage object
            if hasattr(response, 'content'):
                response_text = response.content
            else:
                response_text = str(response)
            
            # Parse JSON response
            try:
                # Extract JSON from response if it's wrapped in markdown
                if "```json" in response_text:
                    json_start = response_text.find("```json") + 7
                    json_end = response_text.find("```", json_start)
                    json_str = response_text[json_start:json_end].strip()
                else:
                    json_str = response_text.strip()
                
                parsed_result = json.loads(json_str)
                return parsed_result
                
            except json.JSONDecodeError as e:
                print(f"JSON parsing failed: {e}")
                print(f"Raw response: {response_text[:500]}...")
                return self._create_default_structure()
        
        except Exception as e:
            print(f"LLM analysis failed: {e}")
            return self._create_default_structure()

    def _load_template(self) -> str:
        """Load the extractSchema template"""
        template_path = "templates/template_extractSchema.txt"
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            # Fallback template
            return """
# Instruction 

You are analyzing an Excel sheet to extract table structure information. Based on the provided data and style information, please identify the table components and return a JSON object with the following structure:

```json
{
    "table_name": "string or null - the title/name of the table if present",
    "table_idx": [list of row indices where table name appears],
    "columns": {
        "structure": "nested dict representing column hierarchy if nested, simple dict if flat",
        "column_idx": [list of row indices that contain column names]
    },
    "meta_data": {
        "key1": "value1 or null if empty",
        "key2": "value2 or null if empty"
    },
    "meta_idx": [list of row indices containing metadata],
    "agg_meta_data": {
        "key1": "value1, formula, or null if empty - aggregation metadata"
    },
    "agg_meta_idx": [list of row indices containing aggregation metadata with formulas],
    "table_type": "one of: 1D, 1D_2level, 1D_3level, 2D, 2D_converted_1D, complex, etc.",
    "additional_note": "optional description for complex structures"
}
```

# Current Task:
{sheet_data}
"""
    
    def _create_default_structure(self) -> Dict[str, Any]:
        """Create a default structure when LLM fails"""
        return {
            "table_name": None,
            "table_idx": [],
            "columns": {
                "structure": {},
                "column_idx": []
            },
            "meta_data": {},
            "meta_idx": [],
            "agg_meta_data": {},
            "agg_meta_idx": [],
            "table_type": "1D",
            "additional_note": "Default structure created due to analysis failure"
        }


class InitialParser:
    """Main parser class for initial Excel analysis with parallel processing"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.style_analyzer = ExcelStyleAnalyzer()
        self.llm_analyzer = LLMTableAnalyzer(model_name)
        
    def parse_files_parallel(self, file_infos: List[Dict[str, str]], initial_description: str = "") -> Dict[str, Any]:
        """Parse multiple files in parallel"""
        file_results = []
        
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_file = {
                executor.submit(self.parse_file, file_info["path"], file_info["name"], initial_description): file_info
                for file_info in file_infos
            }
            
            for future in as_completed(future_to_file):
                file_info = future_to_file[future]
                try:
                    result = future.result()
                    file_results.append(result)
                    print(f"✓ Completed: {file_info['name']}")
                except Exception as e:
                    print(f"✗ Failed: {file_info['name']} - {e}")
                    error_result = {
                        "file_name": file_info["name"],
                        "sheets": [],
                        "error": str(e)
                    }
                    file_results.append(error_result)
        
        return {
            "files": file_results,
            "summary": {
                "total_files": len(file_results),
                "total_sheets": sum(len(f.get("sheets", [])) for f in file_results),
                "parsing_timestamp": self.get_timestamp()
            }
        }
        
    def parse_file(self, file_path: str, file_name: str, initial_description: str = "") -> Dict[str, Any]:
        """Parse a single Excel or CSV file"""
        print(f"Processing: {file_name}")
        
        try:
            # Handle different file types
            if file_path.lower().endswith('.csv'):
                return self._parse_csv_file(file_path, file_name, initial_description)
            elif file_path.lower().endswith(('.xlsx', '.xls')):
                return self._parse_excel_file_parallel(file_path, file_name, initial_description)
            else:
                raise ValueError(f"Unsupported file format: {file_path}")
                
        except Exception as e:
            print(f"Error processing {file_name}: {str(e)}")
            return {
                "file_name": file_name,
                "sheets": [],
                "error": str(e)
            }
    
    def _parse_excel_file_parallel(self, file_path: str, file_name: str, initial_description: str) -> Dict[str, Any]:
        """Parse Excel file with parallel sheet processing"""
        # Step 1: Extract style information (already parallelized in ExcelStyleAnalyzer)
        style_info = self.style_analyzer.analyze_workbook(file_path)
        print(f"  Extracted style info for {len(style_info['sheets'])} sheets")
        
        # Step 2: Analyze each sheet with LLM in parallel
        file_result = {
            "file_name": file_name,
            "sheets": []
        }
        
        sheets_data = list(style_info["sheets"].items())
        
        with ThreadPoolExecutor(max_workers=3) as executor:  
            future_to_sheet = {
                executor.submit(self._analyze_sheet_with_llm, sheet_name, sheet_data, initial_description): sheet_name
                for sheet_name, sheet_data in sheets_data
            }
            
            for future in as_completed(future_to_sheet):
                sheet_name = future_to_sheet[future]
                try:
                    enhanced_result = future.result()
                    enhanced_result["sheet_name"] = sheet_name
                    file_result["sheets"].append(enhanced_result)
                    print(f"    ✓ Completed sheet: {sheet_name}")
                except Exception as e:
                    print(f"    ✗ Failed sheet: {sheet_name} - {e}")
                    error_sheet = {
                        "sheet_name": sheet_name,
                        "error": str(e),
                        "table_type": "error",
                        "additional_note": f"Analysis failed: {str(e)}"
                    }
                    file_result["sheets"].append(error_sheet)
        
        # Sort sheets to maintain consistent order
        file_result["sheets"].sort(key=lambda x: x.get("sheet_name", ""))
        
        return file_result
    
    def _analyze_sheet_with_llm(self, sheet_name: str, sheet_data: Dict, initial_description: str) -> Dict[str, Any]:
        """Analyze a single sheet with LLM (designed for parallel execution)"""
        # Skip sheets with errors
        if "error" in sheet_data:
            raise Exception(f"Sheet has style analysis error: {sheet_data['error']}")
        
        print(f"    Analyzing sheet: {sheet_name}")
        
        # Prepare data for LLM
        prepared_data = self.llm_analyzer.prepare_sheet_data(
            sheet_data["data"], 
            sheet_data
        )
        
        # Get LLM analysis
        llm_result = self.llm_analyzer.analyze_with_llm(prepared_data, initial_description)
        
        # Step 3: Enhance with additional statistics
        enhanced_result = self._enhance_analysis(llm_result, sheet_data)
        enhanced_result["raw_style_info"] = {
            "dimensions": sheet_data["dimensions"],
            "merged_cells": sheet_data["merged_cells"],
            "formulas": sheet_data["formulas"]
        }
        
        return enhanced_result
    
    def _parse_csv_file(self, file_path: str, file_name: str, initial_description: str) -> Dict[str, Any]:
        """Parse CSV file"""
        try:
            # Read CSV data
            df = pd.read_csv(file_path, nrows=100)  # Read first 100 rows for analysis
            
            # Convert to sheet-like structure
            sheet_data = []
            for idx, row in df.iterrows():
                row_data = []
                for col_idx, value in enumerate(row):
                    cell_info = {
                        "row": idx + 2,  # Account for header
                        "col": col_idx + 1,
                        "value": value,
                        "display_value": str(value) if pd.notna(value) else "",
                        "has_formula": False,
                        "formula": None,
                        "font_bold": False
                    }
                    row_data.append(cell_info)
                sheet_data.append(row_data)
            
            # Add header row
            header_row = []
            for col_idx, col_name in enumerate(df.columns):
                header_cell = {
                    "row": 1,
                    "col": col_idx + 1,
                    "value": col_name,
                    "display_value": str(col_name),
                    "has_formula": False,
                    "formula": None,
                    "font_bold": True
                }
                header_row.append(header_cell)
            sheet_data.insert(0, header_row)
            
            # Prepare data for LLM
            style_info = {
                "dimensions": {"max_row": len(sheet_data), "max_column": len(df.columns)},
                "merged_cells": [],
                "formulas": []
            }
            
            prepared_data = self.llm_analyzer.prepare_sheet_data(sheet_data, style_info)
            llm_result = self.llm_analyzer.analyze_with_llm(prepared_data, initial_description)
            
            # Enhance with CSV-specific data
            llm_result["sheet_name"] = "Sheet1"
            llm_result["data_row_indices"] = list(range(2, len(sheet_data) + 1))  # All rows except header
            
            return {
                "file_name": file_name,
                "sheets": [llm_result]
            }
            
        except Exception as e:
            raise Exception(f"CSV parsing failed: {str(e)}")
    
    def _enhance_analysis(self, llm_result: Dict, sheet_data: Dict) -> Dict:
        """Enhance LLM analysis with additional statistics"""
        enhanced = llm_result.copy()
        
        # Count data rows for 1D tables
        if llm_result.get("table_type", "").startswith("1D"):
            schema_rows = set()
            schema_rows.update(llm_result.get("table_idx", []))
            
            # Handle nested column structure
            column_info = llm_result.get("columns", {})
            if isinstance(column_info, dict) and "column_idx" in column_info:
                schema_rows.update(column_info["column_idx"])
                
            schema_rows.update(llm_result.get("meta_idx", []))
            schema_rows.update(llm_result.get("agg_meta_idx", []))
            
            total_rows = sheet_data["dimensions"]["max_row"]
            data_rows = []
            
            for i in range(1, total_rows + 1):
                if i not in schema_rows:
                    row_data = sheet_data["data"][i-1]
                    has_data = any(cell.get("display_value", "").strip() for cell in row_data)
                    if has_data:
                        data_rows.append(i)
            
            enhanced["data_row_indices"] = data_rows
        
        return enhanced
    
    def get_timestamp(self) -> str:
        """Get current timestamp"""
        return datetime.now().isoformat()