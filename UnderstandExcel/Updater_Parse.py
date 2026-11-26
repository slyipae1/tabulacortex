from typing import Dict, List, Any, Optional
from smolagents import OpenAIModel
import json
import difflib
from dotenv import load_dotenv
import os

load_dotenv()

class UpdaterParse:
    """Agent for updating Excel parsing results based on user feedback"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.model = OpenAIModel(
            model_id=os.getenv("MODEL_NAME", model_name),
            api_base=os.getenv("BASE_URL"),
            api_key=os.getenv("API_KEY"),
            temperature=0,
            max_tokens=1500,
            top_p=0.9,
        )
    
    def update_with_text(self, user_input: str, current_parsing: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Update parsing based on textual user input"""
        try:
            # Prepare prompt for LLM to generate updates
            prompt = f"""
You are updating Excel parsing results based on user feedback. 

Current parsing structure:
{json.dumps(current_parsing, indent=2, ensure_ascii=False)}

User's modification request: {user_input}

Based on the user's request, generate a list of updates. Only return changes that need to be made.

Return a JSON list of updates in this format:
[
{{
    "file_name": "exact file name", 
    "sheet_name": "exact sheet name",
    "table_name": "new table name (if updating)",
    "columns": {{ "structure": {{ ... }} }} (if updating columns),
    "meta_data": {{ ... }} (if updating metadata),
    "agg_meta_data": {{ ... }} (if updating aggregation metadata),
    "table_type": "new table type (if updating)",
    "additional_note": "new note (if updating)",
    "data_row_indices": [1, 2, 3] (if updating data row indices)
}}
]

If no changes are needed, return an empty list: []
"""
            
            # Get LLM response
            response = self.model([{"role": "user", "content": prompt}])
            
            # Parse and validate response
            try:
                if "```json" in response:
                    json_start = response.find("```json") + 7
                    json_end = response.find("```", json_start)
                    json_str = response[json_start:json_end].strip()
                else:
                    json_str = response.strip()
                
                updates = json.loads(json_str)
                
                # Validate updates
                validated_updates = self._validate_updates(updates, current_parsing)
                return validated_updates
                
            except json.JSONDecodeError:
                # Fallback: try to extract meaningful updates from text
                return []
                
        except Exception as e:
            print(f"Text update failed: {e}")
            return []
    
    def update_with_mermaid_code(self, 
                                user_input: str, 
                                mermaid_code: str, 
                                current_parsing: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Update parsing based on Mermaid code modifications"""
        try:
            # Generate current Mermaid code for comparison
            current_mermaid = self._generate_current_mermaid(current_parsing)
            
            # Find differences
            differences = self._find_mermaid_differences(current_mermaid, mermaid_code)
            
            # Prepare prompt
            prompt = f"""
You are updating Excel parsing results based on user feedback and Mermaid code changes.

Current parsing structure:
{json.dumps(current_parsing, indent=2, ensure_ascii=False)}

User's modification request: {user_input}

Mermaid code changes detected: {differences}

Based on the user's request and code changes, generate a list of updates. Only return changes that need to be made.

Return a JSON list of updates in the same format as before.
"""
            
            # Get LLM response and process same as above
            response = self.model([{"role": "user", "content": prompt}])
            print(type(response))
            
            # Parse response (same logic as update_with_text)
            try:
                if "```json" in response:
                    json_start = response.find("```json") + 7
                    json_end = response.find("```", json_start)
                    json_str = response[json_start:json_end].strip()
                else:
                    json_str = response.strip()
                
                updates = json.loads(json_str)
                validated_updates = self._validate_updates(updates, current_parsing)
                return validated_updates
                
            except json.JSONDecodeError:
                return []
                
        except Exception as e:
            print(f"Mermaid update failed: {e}")
            return []
    
    def _generate_current_mermaid(self, parsing_data: Dict[str, Any]) -> str:
        """Generate Mermaid code from current parsing data"""
        lines = ["graph TD"]
        
        for file_data in parsing_data.get("files", []):
            file_name = file_data.get("file_name", "Unknown")
            file_id = self._sanitize_id(file_name)
            
            lines.append(f"    {file_id}[{file_name}]")
            
            for sheet in file_data.get("sheets", []):
                sheet_name = sheet.get("sheet_name", "Unknown")
                table_type = sheet.get("table_type", "")
                data_rows = len(sheet.get("data_row_indices", []))
                table_name = sheet.get("table_name", "")
                
                sheet_id = self._sanitize_id(f"{file_name}_{sheet_name}")
                sheet_label = f"{sheet_name}\\n({table_type})\\n{data_rows} rows"
                
                lines.append(f"    {sheet_id}[\"{sheet_label}\"]")
                lines.append(f"    {file_id} --> {sheet_id}")
                
                if table_name:
                    table_id = self._sanitize_id(f"{file_name}_{sheet_name}_table")
                    lines.append(f"    {table_id}[Table: {table_name}]")
                    lines.append(f"    {sheet_id} --> {table_id}")
                
                # Add column structure
                columns = sheet.get("columns", {})
                if isinstance(columns, dict) and "structure" in columns:
                    self._add_column_nodes(lines, sheet_id, columns["structure"], file_name, sheet_name)
        
        return "\n".join(lines)
    
    def _add_column_nodes(self, lines: List[str], parent_id: str, columns: Dict, file_name: str, sheet_name: str):
        """Add column nodes to Mermaid diagram"""
        if not isinstance(columns, dict):
            return
        
        col_count = 0
        for col_name, col_children in columns.items():
            if col_count >= 3:  # Limit displayed columns
                break
                
            col_id = self._sanitize_id(f"{file_name}_{sheet_name}_{col_name}")
            lines.append(f"    {col_id}[{col_name}]")
            lines.append(f"    {parent_id} --> {col_id}")
            
            if isinstance(col_children, dict) and col_children:
                self._add_column_nodes(lines, col_id, col_children, file_name, sheet_name)
            
            col_count += 1
        
        if len(columns) > 3:
            more_id = self._sanitize_id(f"{file_name}_{sheet_name}_more")
            lines.append(f"    {more_id}[... {len(columns) - 3} more]")
            lines.append(f"    {parent_id} --> {more_id}")
    
    def _find_mermaid_differences(self, current_code: str, new_code: str) -> str:
        """Find differences between current and new Mermaid code"""
        current_lines = current_code.split('\n')
        new_lines = new_code.split('\n')
        
        # Calculate similarity
        matcher = difflib.SequenceMatcher(None, current_code, new_code)
        similarity = matcher.ratio()
        
        if similarity < 0.6:  # More than 40% change
            return f"Major changes detected (similarity: {similarity:.2f}). New complete structure provided."
        else:
            # Find specific differences
            diff = list(difflib.unified_diff(current_lines, new_lines, lineterm=''))
            if diff:
                return "Specific changes:\n" + "\n".join(diff)
            else:
                return "No significant differences detected"
    
    def _validate_updates(self, updates: List[Dict[str, Any]], current_parsing: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Validate that updates reference existing files and sheets"""
        validated = []
        
        # Get valid file and sheet names
        valid_files = {}
        for file_data in current_parsing.get("files", []):
            file_name = file_data.get("file_name")
            if file_name:
                valid_files[file_name] = [sheet.get("sheet_name") for sheet in file_data.get("sheets", [])]
        
        for update in updates:
            file_name = update.get("file_name")
            sheet_name = update.get("sheet_name")
            
            # Check if file exists
            if file_name not in valid_files:
                print(f"Warning: File '{file_name}' not found in current parsing")
                continue
            
            # Check if sheet exists (if specified)
            if sheet_name and sheet_name not in valid_files[file_name]:
                print(f"Warning: Sheet '{sheet_name}' not found in file '{file_name}'")
                continue
            
            # Add required fields if missing
            if file_name and not sheet_name:
                # If only file specified, skip for now
                continue
            
            validated.append(update)
        
        return validated
    
    def _sanitize_id(self, text: str) -> str:
        """Sanitize text for use as Mermaid node ID"""
        import re
        # Replace non-alphanumeric characters with underscores
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', text)
        # Remove multiple consecutive underscores
        sanitized = re.sub(r'_+', '_', sanitized)
        # Remove leading/trailing underscores
        sanitized = sanitized.strip('_')
        # Ensure it starts with a letter
        if sanitized and not sanitized[0].isalpha():
            sanitized = 'node_' + sanitized
        return sanitized or 'unknown_node'