from typing import Dict, List, Any, Optional, Tuple
from smolagents import OpenAIModel, ToolCallingAgent, tool
import json
import difflib
import re
from dotenv import load_dotenv
import os
import tempfile
from pathlib import Path
from SystemState import SystemState

load_dotenv()

class ActionPlanner:
    """First LLM agent to plan update actions"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.model = OpenAIModel(
            model_id=os.getenv("MODEL_NAME", model_name),
            api_base=os.getenv("BASE_URL"),
            api_key=os.getenv("API_KEY"),
            temperature=0,
            max_tokens=8192,
            top_p=0.9,
        )
    
    def plan_actions(self, 
                    user_message: str,
                    conversation_history: List[Dict[str, Any]],
                    differences_ER: str,
                    differences_map: str,
                    current_schema: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Plan the sequence of actions needed to fulfill the user request"""
        
        # Load planning template
        template_path = "templates/template_Updater_planner.txt"
        with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
        selected_conv_his = [conv for conv in conversation_history if conv.get("role") in ["user", "assistant"]][-10:]
        # Format template
        formatted_prompt = template.format(
            user_message=user_message,
            conversation_history=json.dumps(selected_conv_his, indent=2, ensure_ascii=False),
            differences_ER=differences_ER,
            differences_map=differences_map,
            current_schema=json.dumps(current_schema, indent=2, ensure_ascii=False)
        )
        
        # Call LLM for planning
        response = self.model([{"role": "user", "content": formatted_prompt}])
        
        # Extract content
        if hasattr(response, 'content'):
            response_text = response.content
        else:
            response_text = str(response)
        
        # Parse response
        try:
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                json_str = response_text[json_start:json_end].strip()
            else:
                json_str = response_text.strip()
            
            result = json.loads(json_str)
            return result
            
        except json.JSONDecodeError as e:
            print(f"Planning JSON parsing failed: {e}")
            return []
    
class ActionExecutor:
    """Second LLM agent to execute planned actions using direct function calls"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.model = OpenAIModel(
            model_id=os.getenv("MODEL_NAME", model_name),
            api_base=os.getenv("BASE_URL"),
            api_key=os.getenv("API_KEY"),
            temperature=0,
            max_tokens=8192,
            top_p=0.9,
        )
        
        # Initialize available tools as methods
        self.tools = {
            "delete_table_tool": self._delete_table_tool,
            "create_table_tool": self._create_table_tool,
            "merge_table_tool": self._merge_table_tool,
            "delete_column_tool": self._delete_column_tool,
            "create_column_tool": self._create_column_tool,
            "merge_column_tool": self._merge_column_tool,
            "add_foreign_keys_tool": self._add_foreign_keys_tool,
            "update_whole_foreign_keys_tool": self._update_whole_foreign_keys_tool,
            "update_db_name_tool": self._update_db_name_tool,
            "update_table_name_tool": self._update_table_name_tool,
            "update_column_tool": self._update_column_tool
        }
    
    def execute_action(self, 
                      action_block: Dict[str, Any], 
                      current_schema: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """Execute a single action block and return updated schema + records"""
        
        # Load execution template
        template_path = "templates/template_Updater_executor.txt"
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()
        
        # Format template
        formatted_prompt = template.format(
            action_content=json.dumps(action_block, indent=2, ensure_ascii=False),
            current_schema=json.dumps(current_schema, indent=2, ensure_ascii=False)
        )
        # Call LLM to get execution plan
        response = self.model([{"role": "user", "content": formatted_prompt}])
        
        # Extract content
        if hasattr(response, 'content'):
            response_text = response.content
        else:
            response_text = str(response)
        
        # Parse execution blocks
        execution_blocks = self._parse_execution_response(response_text)
        # print("Parsed execution blocks:", json.dumps(execution_blocks, indent=2, ensure_ascii=False))

        if not execution_blocks:
            return current_schema, [f"No execution blocks parsed from action: {action_block.get('action', 'unknown')}"]
        
        # Execute each tool call sequentially
        updated_schema = current_schema.copy()
        execution_records = []
        
        for i, exec_block in enumerate(execution_blocks, 1):
            try:
                tool_name = exec_block.get("tool", "")
                kwargs = exec_block.get("kwargs", {})
                
                if tool_name not in self.tools:
                    error_msg = f"Unknown tool: {tool_name}"
                    execution_records.append(error_msg)
                    print(error_msg)
                    continue

                # print(f"Executing tool: {tool_name} with arguments: {json.dumps(kwargs, ensure_ascii=False)}")

                # Execute tool with current schema
                tool_func = self.tools[tool_name]
                updated_schema, record = tool_func(updated_schema, **kwargs)
                execution_records.append(f"Step {i}: {record}")
                
            except Exception as e:
                error_msg = f"Step {i} failed: {str(e)}"
                execution_records.append(error_msg)
                print(f"Tool execution error: {e}")
        
        return updated_schema, execution_records
    
    def _parse_execution_response(self, response_text: str) -> List[Dict[str, Any]]:
        """Parse LLM response to extract execution blocks"""
        try:
            # Try to find JSON in response
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                json_str = response_text[json_start:json_end].strip()
            else:
                # Try to find JSON array pattern
                json_str = response_text.strip()
                
            result = json.loads(json_str)
            
            # Ensure result is a list
            if isinstance(result, dict):
                return [result]
            elif isinstance(result, list):
                return result
            else:
                return []
                
        except json.JSONDecodeError as e:
            print(f"Execution JSON parsing failed: {e}")
            return []

    # Tool implementations
    def _delete_table_tool(self, cur_schema: Dict[str, Any], table_identifier: str) -> Tuple[Dict[str, Any], str]:
        """Delete a table from schema by table_id or table_name"""
        db_tables = cur_schema.get("db_tables", [])
        updated_tables = []
        deleted_table_name = None
        
        for table in db_tables:
            if (table.get("table_id") != table_identifier and 
                table.get("table_name") != table_identifier):
                updated_tables.append(table)
            else:
                deleted_table_name = table.get("table_name", table_identifier)
        
        cur_schema["db_tables"] = updated_tables
        
        # Remove related foreign keys
        foreign_keys = cur_schema.get("foreign_keys", [])
        updated_fks = []
        for fk in foreign_keys:
            if len(fk) >= 4 and fk[0] != table_identifier and fk[2] != table_identifier:
                updated_fks.append(fk)
        cur_schema["foreign_keys"] = updated_fks
        
        return cur_schema, f"Deleted table: {deleted_table_name or table_identifier}"
    
    def _create_table_tool(self, cur_schema: Dict[str, Any], table_entry: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        """Create a new table in schema"""
        if "db_tables" not in cur_schema:
            cur_schema["db_tables"] = []
        
        cur_schema["db_tables"].append(table_entry)
        
        table_name = table_entry.get("table_name", "Unknown")
        column_count = len(table_entry.get("columns_mapping", []))
        
        return cur_schema, f"Created table: {table_name} with {column_count} columns"
    
    def _merge_table_tool(self, cur_schema: Dict[str, Any], table_identifier1: str, table_identifier2: str, table_identifier_new: str) -> Tuple[Dict[str, Any], str]:
        """Merge two tables into a new table"""
        # Find the two tables to merge
        table1, table2 = None, None
        remaining_tables = []
        
        for table in cur_schema.get("db_tables", []):
            if (table.get("table_id") == table_identifier1 or 
                table.get("table_name") == table_identifier1):
                table1 = table
            elif (table.get("table_id") == table_identifier2 or 
                  table.get("table_name") == table_identifier2):
                table2 = table
            else:
                remaining_tables.append(table)
        
        if not table1 or not table2:
            return cur_schema, f"Could not find tables to merge: {table_identifier1}, {table_identifier2}"
        
        # Create merged table
        merged_columns = []
        column_names_seen = {}
        
        # Process table1 columns
        for col in table1.get("columns_mapping", []):
            col_name = col.get("column_name", "")
            if col_name in column_names_seen:
                # Merge with existing column
                existing_col = column_names_seen[col_name]
                existing_col["original_column_xlsx"].extend(col.get("original_column_xlsx", []))
            else:
                new_col = col.copy()
                merged_columns.append(new_col)
                column_names_seen[col_name] = new_col
        
        # Process table2 columns
        for col in table2.get("columns_mapping", []):
            col_name = col.get("column_name", "")
            if col_name in column_names_seen:
                # Merge with existing column
                existing_col = column_names_seen[col_name]
                existing_col["original_column_xlsx"].extend(col.get("original_column_xlsx", []))
            else:
                new_col = col.copy()
                merged_columns.append(new_col)
                column_names_seen[col_name] = new_col
        
        # Create new table entry
        merged_table = {
            "table_id": f"merged_{len(remaining_tables) + 1}",
            "table_name": table_identifier_new,
            "columns_mapping": merged_columns
        }
        
        # Update schema
        remaining_tables.append(merged_table)
        cur_schema["db_tables"] = remaining_tables
        
        # Update foreign keys
        foreign_keys = cur_schema.get("foreign_keys", [])
        updated_fks = []
        for fk in foreign_keys:
            if len(fk) >= 4:
                source_table, source_col, target_table, target_col = fk
                # Update table references
                if source_table == table_identifier1 or source_table == table_identifier2:
                    source_table = table_identifier_new
                if target_table == table_identifier1 or target_table == table_identifier2:
                    target_table = table_identifier_new
                updated_fks.append([source_table, source_col, target_table, target_col])
            else:
                updated_fks.append(fk)
        cur_schema["foreign_keys"] = updated_fks
        
        return cur_schema, f"Merged tables {table_identifier1} and {table_identifier2} into {table_identifier_new}"
    
    def _delete_column_tool(self, cur_schema: Dict[str, Any], table_identifier: str, column_identifier: str) -> Tuple[Dict[str, Any], str]:
        """Delete a column from a table"""
        for table in cur_schema.get("db_tables", []):
            if (table.get("table_id") == table_identifier or 
                table.get("table_name") == table_identifier):
                
                columns = table.get("columns_mapping", [])
                updated_columns = []
                
                for col in columns:
                    if (col.get("column_id") != column_identifier and 
                        col.get("column_name") != column_identifier):
                        updated_columns.append(col)
                
                table["columns_mapping"] = updated_columns
                break

        # Remove related foreign keys
        foreign_keys = cur_schema.get("foreign_keys", [])
        updated_fks = []
        for fk in foreign_keys:
            if len(fk) >= 4 and not (
                (fk[0] == table_identifier and fk[1] == column_identifier) or 
                (fk[2] == table_identifier and fk[3] == column_identifier)
            ):
                updated_fks.append(fk)
        cur_schema["foreign_keys"] = updated_fks
        
        return cur_schema, f"Deleted column: {column_identifier} from table {table_identifier}"
    
    def _create_column_tool(self, cur_schema: Dict[str, Any], table_identifier: str, column_entry: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        """Create a new column in a table"""
        for table in cur_schema.get("db_tables", []):
            if (table.get("table_id") == table_identifier or 
                table.get("table_name") == table_identifier):
                
                if "columns_mapping" not in table:
                    table["columns_mapping"] = []
                
                table["columns_mapping"].append(column_entry)
                break
        
        column_name = column_entry.get("column_name", "Unknown")
        return cur_schema, f"Created column: {column_name} in table {table_identifier}"
    
    def _merge_column_tool(self, cur_schema: Dict[str, Any], table_identifier: str, column_identifier1: str, column_identifier2: str, column_identifier_new: str, transform_for_DB1: str = "ORIGINAL", transform_for_DB2: str = "ORIGINAL") -> Tuple[Dict[str, Any], str]:
        """Merge two columns into a new column with customizable transform_for_DB values"""
        for table in cur_schema.get("db_tables", []):
            if (table.get("table_id") == table_identifier or 
                table.get("table_name") == table_identifier):
                
                columns = table.get("columns_mapping", [])
                col1, col2 = None, None
                remaining_columns = []
                
                # Find columns to merge
                for col in columns:
                    if (col.get("column_id") == column_identifier1 or 
                        col.get("column_name") == column_identifier1):
                        col1 = col
                    elif (col.get("column_id") == column_identifier2 or 
                        col.get("column_name") == column_identifier2):
                        col2 = col
                    else:
                        remaining_columns.append(col)
                
                if col1 and col2:
                    # Update transform_for_DB for original columns
                    updated_col1_xlsx = []
                    for xlsx_entry in col1.get("original_column_xlsx", []):
                        updated_entry = xlsx_entry.copy()
                        updated_entry["transform_for_DB"] = transform_for_DB1
                        updated_col1_xlsx.append(updated_entry)
                    
                    updated_col2_xlsx = []
                    for xlsx_entry in col2.get("original_column_xlsx", []):
                        updated_entry = xlsx_entry.copy()
                        updated_entry["transform_for_DB"] = transform_for_DB2
                        updated_col2_xlsx.append(updated_entry)
                    
                    # Create merged column
                    merged_column = {
                        "column_id": f"merged_{len(remaining_columns) + 1}",
                        "column_name": column_identifier_new,
                        "original_column_xlsx": updated_col1_xlsx + updated_col2_xlsx,
                        "datatype": col1.get("datatype", "TEXT"),
                        "col_constraints": col1.get("col_constraints", [])
                    }
                    
                    remaining_columns.append(merged_column)
                    table["columns_mapping"] = remaining_columns
                
                break
        
        return cur_schema, f"Merged columns {column_identifier1} and {column_identifier2} into {column_identifier_new} with transforms: '{transform_for_DB1}' and '{transform_for_DB2}'"

    def _add_foreign_keys_tool(self, cur_schema: Dict[str, Any], new_foreign_keys: List[List[str]]) -> Tuple[Dict[str, Any], str]:
        """Add new foreign keys to the schema"""
        if "foreign_keys" not in cur_schema:
            cur_schema["foreign_keys"] = []
            
        cur_schema["foreign_keys"].extend(new_foreign_keys)
        
        # Remove duplicates    
        seen = set()
        unique_fks = []
        for fk in cur_schema["foreign_keys"]:
            fk_tuple = tuple(fk)
            if fk_tuple not in seen:
                seen.add(fk_tuple)
                unique_fks.append(fk)
        cur_schema["foreign_keys"] = unique_fks
        
        return cur_schema, f"Added {len(new_foreign_keys)} foreign key relationship(s)"
    
    def _update_whole_foreign_keys_tool(self, cur_schema: Dict[str, Any], new_whole_foreign_keys: List[List[str]]) -> Tuple[Dict[str, Any], str]:
        """Replace the entire foreign keys with new ones"""
        cur_schema["foreign_keys"] = new_whole_foreign_keys
        return cur_schema, f"Updated foreign keys to {len(new_whole_foreign_keys)} relationship(s)"
    
    def _update_db_name_tool(self, cur_schema: Dict[str, Any], new_db_name: str) -> Tuple[Dict[str, Any], str]:
        """Update database name"""
        old_name = cur_schema.get("db_name", "Unknown")
        cur_schema["db_name"] = new_db_name
        return cur_schema, f"Updated database name from '{old_name}' to '{new_db_name}'"

    def _update_table_name_tool(self, cur_schema: Dict[str, Any], table_identifier: str, new_table_name: str) -> Tuple[Dict[str, Any], str]:
        """Update table name"""
        old_table_name = None
        
        # Find and update the table
        for table in cur_schema.get("db_tables", []):
            if (table.get("table_id") == table_identifier or 
                table.get("table_name") == table_identifier):
                old_table_name = table.get("table_name", table_identifier)
                table["table_name"] = new_table_name
                break
        
        # Update foreign key references
        foreign_keys = cur_schema.get("foreign_keys", [])
        for fk in foreign_keys:
            if len(fk) >= 4:
                if fk[0] == table_identifier or fk[0] == old_table_name:
                    fk[0] = new_table_name
                if fk[2] == table_identifier or fk[2] == old_table_name:
                    fk[2] = new_table_name
        
        return cur_schema, f"Updated table name from '{old_table_name or table_identifier}' to '{new_table_name}'"

    def _update_column_tool(self, cur_schema: Dict[str, Any], table_identifier: str, column_identifier: str, field_name: str, new_value: str | List[str] | List[Dict]) -> Tuple[Dict[str, Any], str]:
        """Update column name, constraint, or datatype based on field_name.
        Accepts either a single string or a list of strings for new_value.
        """
        if field_name not in ["column_name", "col_constraints", "datatype", "original_column_xlsx"]:
            raise ValueError(f"Invalid field_name: {field_name}")

        # Find and update the column
        for table in cur_schema.get("db_tables", []):
            if (table.get("table_id") == table_identifier or 
                table.get("table_name") == table_identifier):

                for col in table.get("columns_mapping", []):
                    if (col.get("column_id") == column_identifier or 
                        col.get("column_name") == column_identifier):
                        old_value = col.get(field_name, None)
                        col[field_name] = new_value
                        return cur_schema, f"Updated {field_name} from '{old_value}' to '{new_value}' in column '{column_identifier}' of table '{table_identifier}'"
                break

        return cur_schema, f"Column '{column_identifier}' not found in table '{table_identifier}'"

class UpdaterSchema:
    """Main schema updater using two-stage approach: planner + executor"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.planner = ActionPlanner(model_name)
        self.executor = ActionExecutor(model_name)
        self.system_state = SystemState()  
    
    def update_schema_with_agent(self, 
                            user_message: str,
                            ERschema_code: Optional[str] = None,
                            schema_file_map_code: Optional[str] = None,
                            current_schema: Dict[str, Any] = None,
                            conversation_history: List[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], List[str]]:
        """
        Update schema using two-stage approach: plan then execute.
        
        Returns:
            Tuple of (updated_schema, update_records) where update_records is List[str]
        """
        try:
            # Generate differences if mermaid code provided
            differences_ER = ""
            differences_map = ""
            print("Starting schema update process...")
            if ERschema_code:
                current_ERschema_mermaid = self.system_state.cur_vis.get("ERschema_code", "")
                differences_ER = self._find_mermaid_differences(current_ERschema_mermaid, ERschema_code)
            # if differences_ER:
            #     print("ER schema differences: \n", differences_ER)
            if schema_file_map_code:
                current_map_code = self.system_state.cur_vis.get("schema_file_map_code", "")
                differences_map = self._find_mermaid_differences(current_map_code, schema_file_map_code)
            # if differences_map:
            #     print("Schema-file mapping differences: \n", differences_map)

            # Stage 1: Plan actions
            action_blocks = self.planner.plan_actions(
                user_message=user_message,
                conversation_history=conversation_history or [],
                differences_ER=differences_ER,
                differences_map=differences_map,
                current_schema=current_schema
            )
            # print("Planned action blocks:", json.dumps(action_blocks, indent=2, ensure_ascii=False))
            
            if not action_blocks:
                return current_schema, ["No actions planned based on the request"]
            
            # Stage 2: Execute actions sequentially
            updated_schema = current_schema.copy()
            all_update_records = []
            
            for i, action_block in enumerate(action_blocks, 1):
                try:
                    updated_schema, execution_records = self.executor.execute_action(
                        action_block, updated_schema
                    )
                    
                    # Format records with action context
                    targets_text = "; ".join(action_block.get("targets", []))
                    action_summary = f"Action {i}: {action_block.get('action', 'unknown')} - Affected: {targets_text}"
                    all_update_records.append(action_summary)
                    print(action_summary)
                    
                    # Add execution details
                    for record in execution_records:
                        all_update_records.append(f"  - {record}")
                        print(f"  - {record}")
                    
                except Exception as e:
                    error_record = f"Action {i} failed: {str(e)}"
                    all_update_records.append(error_record)
                    print(f"Action execution error: {e}")
            
            return updated_schema, all_update_records
            
        except Exception as e:
            print(f"Schema update failed: {e}")
            return current_schema, [f"Error: {str(e)}"]
    

    def _find_mermaid_differences(self, current_code: str, new_code: str) -> str:
        """Find differences between current and new Mermaid code"""
        # Calculate similarity
        matcher = difflib.SequenceMatcher(None, current_code, new_code)
        similarity = matcher.ratio()
        
        if similarity < 0.7:  # More than 30% change
            return f"Major changes detected (similarity: {similarity:.2f}). Full code comparison needed.\n\nPrevious:\n{current_code}\n\nNew:\n{new_code}"
        else:
            # Find specific differences
            current_lines = current_code.split('\n')
            new_lines = new_code.split('\n')
            diff = list(difflib.unified_diff(current_lines, new_lines, lineterm='', n=3))
            
            if diff:
                return f"Specific changes detected:\n" + str(diff)
            else:
                return "No significant differences detected in Mermaid code"