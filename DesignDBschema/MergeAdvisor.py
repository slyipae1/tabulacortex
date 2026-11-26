from typing import Dict, List, Any, Optional
from smolagents import OpenAIModel
import os
import json
from dotenv import load_dotenv

load_dotenv()

class MergeAdvisor:
    """Agent that provides suggestions for merging tables based on DB schema analysis"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.model = OpenAIModel(
            model_id=os.getenv("MODEL_NAME", model_name),
            api_base=os.getenv("BASE_URL"),
            api_key=os.getenv("API_KEY"),
            temperature=0,
            max_tokens=8192,
            top_p=0.9,
        )
    
    def generate_merge_advice(self, db_schema: Dict[str, Any], parsed_excel_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate merge suggestions based on the current DB schema"""
        try:
            # Load template
            template = self._load_merge_advice_template()
            
            # Prepare context data
            context_data = {
                "db_schema": self._format_schema(db_schema.copy()),
                "file_summary": self._prepare_file_summary(parsed_excel_data),
                "table_analysis": self._analyze_table_structures(db_schema)
            }
            
            # Format prompt
            prompt = template.replace("{db_schema}", 
                                    context_data["db_schema"])
            prompt = prompt.replace("{file_summary}", 
                                  json.dumps(context_data["file_summary"], ensure_ascii=False, indent=2))
            prompt = prompt.replace("{table_analysis}", 
                                  json.dumps(context_data["table_analysis"], ensure_ascii=False, indent=2))
            
            # Call LLM
            response = self.model([{"role": "user", "content": prompt}])
            
            # Parse JSON response
            try:
                if hasattr(response, 'content'):
                    response_text = response.content
                else:
                    response_text = str(response)
                
                if "```json" in response_text:
                    json_start = response_text.find("```json") + 7
                    json_end = response_text.find("```", json_start)
                    json_str = response_text[json_start:json_end].strip()
                else:
                    json_str = response_text.strip()
                
                merge_advice = json.loads(json_str)
                return merge_advice
                
            except json.JSONDecodeError as e:
                print(f"JSON parsing failed for merge advice: {e}")
                print(f"Raw response: {response_text[:500]}...")
                return self._create_default_merge_advice()
                
        except Exception as e:
            print(f"Error generating merge advice: {e}")
            return self._create_default_merge_advice()
    
    def _format_schema(self, db_schema: Dict[str, Any]) -> str:
        """Format schema for LLM by removing IDs and returning JSON string"""
        if not db_schema:
            return "{}"
        
        # Create a clean copy without IDs
        formatted_schema = {}
        
        # Copy basic fields
        if "db_name" in db_schema:
            formatted_schema["db_name"] = db_schema["db_name"]
        
        # Format tables without IDs
        if "db_tables" in db_schema:
            formatted_schema["db_tables"] = []
            
            for table in db_schema["db_tables"]:
                clean_table = {
                    "table_name": table.get("table_name", ""),
                    "columns_mapping": []
                }
                
                # Format columns without IDs
                for column in table.get("columns_mapping", []):
                    clean_column = {
                        "column_name": column.get("column_name", ""),
                        "original_column_xlsx": column.get("original_column_xlsx", []),
                        "datatype": column.get("datatype", "TEXT"),
                        "col_constraints": column.get("col_constraints", [])
                    }
                    clean_table["columns_mapping"].append(clean_column)
                
                formatted_schema["db_tables"].append(clean_table)
        
        # Copy foreign keys as-is
        if "foreign_keys" in db_schema:
            formatted_schema["foreign_keys"] = db_schema["foreign_keys"]
        
        # Return JSON string
        return json.dumps(formatted_schema, ensure_ascii=False, indent=2)
    
    def _prepare_file_summary(self, parsed_excel_data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare summary of files and sheets for analysis"""
        summary = {
            "total_files": len(parsed_excel_data.get("files", [])),
            "files_overview": []
        }
        
        for file_data in parsed_excel_data.get("files", []):
            file_name = file_data.get("file_name", "Unknown")
            sheets = file_data.get("sheets", [])
            
            file_summary = {
                "file_name": file_name,
                "total_sheets": len(sheets),
                "sheets_summary": []
            }
            
            for sheet in sheets:
                sheet_summary = {
                    "sheet_name": sheet.get("sheet_name", "Unknown"),
                    "table_name": sheet.get("table_name", ""),
                    "table_type": sheet.get("table_type", ""),
                    "data_rows": len(sheet.get("data_row_indices", [])),
                    "columns_count": len(sheet.get("columns", {}).get("structure", {}))
                }
                file_summary["sheets_summary"].append(sheet_summary)
            
            summary["files_overview"].append(file_summary)
        
        return summary
    
    def _analyze_table_structures(self, db_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze table structures for similarity detection"""
        tables = db_schema.get("db_tables", [])
        analysis = {
            "total_tables": len(tables),
            "table_signatures": {},
            "similar_structures": []
        }
        
        # Create structure signatures for each table
        for table in tables:
            table_name = table.get("table_name", "")
            columns = table.get("columns_mapping", [])
            
            # Create column signature
            column_names = [col.get("column_name", "") for col in columns]
            column_types = [col.get("datatype", "") for col in columns]
            
            signature = {
                "column_names": sorted(column_names),
                "column_count": len(column_names),
                "data_types": sorted(set(column_types)),
                "source_sheets": []
            }
            
            # Extract source sheet information
            for col in columns:
                original_path = col.get("original_column_xlsx", [])
                if len(original_path) >= 2:
                    sheet_key = f"{original_path[0]}::{original_path[1]}"
                    if sheet_key not in signature["source_sheets"]:
                        signature["source_sheets"].append(sheet_key)
            
            analysis["table_signatures"][table_name] = signature
        
        # Find similar structures
        table_names = list(analysis["table_signatures"].keys())
        for i in range(len(table_names)):
            for j in range(i + 1, len(table_names)):
                table1, table2 = table_names[i], table_names[j]
                sig1, sig2 = analysis["table_signatures"][table1], analysis["table_signatures"][table2]
                
                similarity = self._calculate_similarity(sig1, sig2)
                if similarity > 0.7:  # 70% similarity threshold
                    analysis["similar_structures"].append({
                        "table1": table1,
                        "table2": table2,
                        "similarity": similarity,
                        "common_columns": list(set(sig1["column_names"]) & set(sig2["column_names"])),
                        "different_columns": {
                            "table1_unique": list(set(sig1["column_names"]) - set(sig2["column_names"])),
                            "table2_unique": list(set(sig2["column_names"]) - set(sig1["column_names"]))
                        }
                    })
        
        return analysis
    
    def _calculate_similarity(self, sig1: Dict, sig2: Dict) -> float:
        """Calculate similarity between two table signatures"""
        columns1 = set(sig1["column_names"])
        columns2 = set(sig2["column_names"])
        
        if not columns1 and not columns2:
            return 1.0
        
        intersection = len(columns1 & columns2)
        union = len(columns1 | columns2)
        
        return intersection / union if union > 0 else 0.0
    
    def _create_default_merge_advice(self) -> Dict[str, Any]:
        """Create default merge advice when analysis fails"""
        return {
            "merge_suggestions": [],
            "column_merge_suggestions": [],
            "overall_assessment": "No specific merge recommendations at this time.",
            "confidence": "low",
            "reasoning": "Analysis could not be completed due to technical issues."
        }
    
    def _load_merge_advice_template(self) -> str:
        """Load the merge advice template"""
        template_path = "templates/template_MergeAdvice.txt"
        with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()