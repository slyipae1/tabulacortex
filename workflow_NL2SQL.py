from smolagents import OpenAIModel
from dotenv import load_dotenv
import os
import sqlite3
import gradio as gr
from pathlib import Path
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
import json
import tempfile
from general_agents.Responser import Responser
from SystemState import SystemState

load_dotenv()

class NL2SQLAgent:
    """Custom NL2SQL agent using OpenAI model for tool calling"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.model = OpenAIModel(
            model_id=os.getenv("MODEL_NAME", model_name),
            api_base=os.getenv("BASE_URL"),
            api_key=os.getenv("API_KEY"),
            temperature=0,
            max_tokens=4096,
            top_p=0.9,
        )
        self.execution_history = []
        self.current_db_path = None
        self.db_name = None
        self.not_for_db_files = []
        self.schema_ddl = ""
    
    def set_database(self, db_path: str, not_for_db_files: List[str] = None):
        """Set the database path and initialize schema"""
        self.current_db_path = db_path
        self.db_name = os.path.basename(db_path) if db_path else "Unknown"
        self.not_for_db_files = not_for_db_files or []
        self.schema_ddl = self._get_schema_ddl()
        self.execution_history = []  # Reset history for new database

    def process_question(self, question: str, history_messages) -> Dict[str, Any]:
        """
        Process a question and return final result
        Returns a dict with execution history and final answer
        """
        result = {
            "question": question,
            "execution_history": [],
            "final_answer": "",
            "status": "success",
            "error": None
        }
        
        # clean self.execution_history before processing new question
        self.execution_history = []
        try:
            max_iterations = 10
            iterations = 0
            
            while iterations < max_iterations:
                iterations += 1
                
                # Get next tool call from agent
                tool_call_response = self._get_next_tool_call(question, history_messages)
                
                if not tool_call_response:
                    result["status"] = "error"
                    result["error"] = "Could not determine next action"
                    return result
                
                tool_name = tool_call_response.get("tool")
                kwargs = tool_call_response.get("kwargs", {})
                print(f"Iteration {iterations}: Tool call - {tool_name}")
                if kwargs:
                    for k, v in kwargs.items():
                        print(f"  {k}: {v}")

                # Execute tool
                if tool_name == "exec_sql":
                    tool_result = self._exec_sql_tool(**kwargs)
                    self.execution_history.append({
                        "tool": "exec_sql",
                        "kwargs": kwargs,
                        "result": tool_result
                    })
                    
                elif tool_name == "read_nofordb_files":
                    tool_result = self._read_nofordb_files_tool(**kwargs)
                    self.execution_history.append({
                        "tool": "read_nofordb_files", 
                        "kwargs": kwargs,
                        "result": tool_result
                    })
                    
                elif tool_name == "prepare_answer":
                    # Final step - prepare comprehensive answer
                    final_answer = self._prepare_answer_tool(question, history_messages)
                    result["execution_history"] = self.execution_history.copy()
                    result["final_answer"] = final_answer
                    result["status"] = "success"
                    return result
                    
                else:
                    result["status"] = "error"
                    result["error"] = f"Unknown tool: {tool_name}"
                    return result
            
            # Max iterations reached
            result["status"] = "error"
            result["error"] = "Maximum iterations reached without completing analysis"
            result["execution_history"] = self.execution_history.copy()
            
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            result["execution_history"] = self.execution_history.copy()
        
        return result

    def _get_next_tool_call(self, question: str, history_messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Get next tool call from the agent"""
        # Load template
        template_path = "templates/template_NL2SQL_agent.txt"
        with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
        
        # Format template
        formatted_prompt = template.format(
            question=question,
            db_name=self.db_name,
            schema_ddl=self.schema_ddl,
            execution_history=json.dumps(self.execution_history, indent=2) if self.execution_history else "No previous steps",
            not_for_db_files=str(self.not_for_db_files) if self.not_for_db_files else "No additional files"
        )
        
        # Get response from model
        response = self.model(history_messages + [{"role": "user", "content": formatted_prompt}])
        
        if hasattr(response, 'content'):
            response_text = response.content
        else:
            response_text = str(response)
        
        # Parse tool call from response
        return self._parse_tool_call(response_text)
    
    def _parse_tool_call(self, response_text: str) -> Dict[str, Any]:
        """Parse tool call from agent response"""
        try:
            # Find JSON in response
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                json_str = response_text[json_start:json_end].strip()
            else:
                # Try to find JSON object pattern
                import re
                json_pattern = r'\{[^{}]*"tool"[^{}]*\}'
                match = re.search(json_pattern, response_text)
                if match:
                    json_str = match.group(0)
                else:
                    json_str = response_text.strip()
            
            return json.loads(json_str)
            
        except json.JSONDecodeError:
            # Fallback: try to extract tool and parameters manually
            if "exec_sql" in response_text:
                sql_start = response_text.find("SELECT")
                if sql_start == -1:
                    sql_start = response_text.find("select")
                if sql_start != -1:
                    sql_end = response_text.find(";", sql_start)
                    if sql_end == -1:
                        sql_end = len(response_text)
                    sql_query = response_text[sql_start:sql_end].strip()
                    return {"tool": "exec_sql", "kwargs": {"sql_query": sql_query}}
            
            if "prepare_answer" in response_text:
                return {"tool": "prepare_answer", "kwargs": {}}
            
            return {}
    
    def _exec_sql_tool(self, sql_query: str) -> str:
        """Execute SQL query and return results"""
        if not self.current_db_path or not os.path.exists(self.current_db_path):
            return "Error: No database connected"
        
        try:
            conn = sqlite3.connect(self.current_db_path)
            df = pd.read_sql_query(sql_query, conn)
            conn.close()
            
            # Save raw results to CSV
            df.to_csv("result.csv", index=False)
            
            # Check if results should be summarized
            if len(df) > 50 or len(str(df)) > 2000:
                # Create summary
                summary_parts = [f"Total {len(df)} rows, {len(df.columns)} columns"]
                
                for col in df.columns:
                    unique_count = df[col].nunique()
                    missing_count = df[col].isnull().sum()
                    summary_parts.append(f"{col} (unique: {unique_count}, missing: {missing_count})")
                
                return "\n".join(summary_parts)
            else:
                # Return raw table
                return f"```csv\n{df.to_csv(index=False)}\n```"
                
        except Exception as e:
            return f"SQL Error: {str(e)}"
    
    def _read_nofordb_files_tool(self, file_names: List[str]) -> str:
        """Read not-for-db files and return content"""
        if not self.current_db_path:
            return "Error: No database context"
        
        # Find the database directory
        db_dir = Path(self.current_db_path).parent
        not_for_db_dir = db_dir / "not_for_db"
        
        if not not_for_db_dir.exists():
            return "Error: No not_for_db directory found"
        
        results = []
        for file_name in file_names:
            file_path = not_for_db_dir / file_name
            if not file_path.exists():
                # Try with different extensions
                csv_path = not_for_db_dir / f"{file_name}.csv"
                if csv_path.exists():
                    file_path = csv_path
                else:
                    results.append(f"File not found: {file_name}")
                    continue
            
            try:
                if file_path.suffix.lower() == '.csv':
                    df = pd.read_csv(file_path)
                    results.append(f"**File: {file_name}**\n```csv\n{df.to_csv(index=False)}\n```")
                else:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    results.append(f"**File: {file_name}**\n```\n{content}\n```")
                        
            except Exception as e:
                results.append(f"Error reading {file_name}: {str(e)}")
        
        return "\n\n".join(results)

    def _prepare_answer_tool(self, question: str, history_messages: List[Dict[str, str]]) -> str:
        """Prepare final natural language answer"""
        # Get the last execution result for context
        last_result = ""
        if self.execution_history:
            last_execution = self.execution_history[-1]
            last_result = last_execution.get("result", "")
        
        # Use model to generate natural language response
        answer_prompt = f"""
Based on the execution history and results, provide a comprehensive natural language answer to the user's question. 
If the history clearly show unanswerability, explain why the question cannot be answered with the given database and information.

Question: {question}

Latest Result: {last_result}

Execution History: 
```json
{json.dumps(self.execution_history, indent=2) if self.execution_history else "No execution history"} 
```

Provide a clear, informative answer that directly addresses the user's question based on the data analysis performed.
"""
        
        response = self.model(history_messages + [{"role": "user", "content": answer_prompt}])
        
        if hasattr(response, 'content'):
            return response.content
        else:
            return str(response)
    
    def _get_schema_ddl(self) -> str:
        """Get database schema as DDL with sample values for each column"""
        if not self.current_db_path or not os.path.exists(self.current_db_path):
            return ""
        
        try:
            conn = sqlite3.connect(self.current_db_path)
            cursor = conn.cursor()
            
            # Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = cursor.fetchall()
            
            enhanced_ddl_parts = []
            
            for (table_name,) in tables:
                # Get CREATE TABLE statement
                cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}'")
                create_sql_result = cursor.fetchone()
                
                if not create_sql_result:
                    continue
                    
                original_ddl = create_sql_result[0]
                
                # Get column information
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns_info = cursor.fetchall()
                
                # Build enhanced DDL with sample values
                enhanced_ddl = self._enhance_ddl_with_samples(original_ddl, table_name, columns_info, cursor)
                enhanced_ddl_parts.append(enhanced_ddl)
            
            conn.close()
            return ";\n\n".join(enhanced_ddl_parts) + ";"
            
        except Exception as e:
            return f"Error reading schema: {str(e)}"

    def _enhance_ddl_with_samples(self, original_ddl: str, table_name: str, columns_info: list, cursor) -> str:
        """Enhance DDL statement with sample values for each column"""
        try:
            # Extract column definitions from original DDL
            # Find the part between parentheses
            start_paren = original_ddl.find('(')
            end_paren = original_ddl.rfind(')')
            
            if start_paren == -1 or end_paren == -1:
                return original_ddl
            
            table_def_start = original_ddl[:start_paren + 1]
            table_def_end = original_ddl[end_paren:]
            column_definitions = original_ddl[start_paren + 1:end_paren].strip()
            
            # Split column definitions - handle commas carefully
            column_lines = []
            current_line = ""
            paren_depth = 0
            
            for char in column_definitions:
                if char == '(':
                    paren_depth += 1
                elif char == ')':
                    paren_depth -= 1
                elif char == ',' and paren_depth == 0:
                    column_lines.append(current_line.strip())
                    current_line = ""
                    continue
                current_line += char
            
            if current_line.strip():
                column_lines.append(current_line.strip())
            
            # Process each column line
            enhanced_lines = []
            
            for line in column_lines:
                line = line.strip()
                
                # Skip foreign key constraints and other non-column definitions
                if (line.upper().startswith('FOREIGN KEY') or 
                    line.upper().startswith('PRIMARY KEY') or 
                    line.upper().startswith('UNIQUE') or
                    line.upper().startswith('CHECK') or
                    line.upper().startswith('CONSTRAINT')):
                    enhanced_lines.append(line)
                    continue
                
                # Extract column name (first word/quoted identifier)
                column_name = self._extract_column_name(line)
                
                if column_name:
                    # Get sample values for this column
                    sample_values = self._get_column_samples(cursor, table_name, column_name)
                    
                    # Add samples as comment if we have any
                    if sample_values:
                        samples_comment = f" -- Examples: {', '.join(sample_values)}"
                        enhanced_line = line + samples_comment
                    else:
                        enhanced_line = line
                else:
                    enhanced_line = line
                
                enhanced_lines.append(enhanced_line)
            
            # Reconstruct the DDL
            enhanced_ddl = table_def_start + '\n    ' + ',\n    '.join(enhanced_lines) + '\n' + table_def_end
            return enhanced_ddl
            
        except Exception as e:
            # If enhancement fails, return original DDL
            return original_ddl

    def _extract_column_name(self, column_definition: str) -> str:
        """Extract column name from column definition line"""
        try:
            # Handle quoted identifiers
            if column_definition.startswith('"'):
                end_quote = column_definition.find('"', 1)
                if end_quote != -1:
                    return column_definition[1:end_quote]
            elif column_definition.startswith('['):
                end_bracket = column_definition.find(']', 1)
                if end_bracket != -1:
                    return column_definition[1:end_bracket]
            elif column_definition.startswith('`'):
                end_backtick = column_definition.find('`', 1)
                if end_backtick != -1:
                    return column_definition[1:end_backtick]
            else:
                # Unquoted identifier - take first word
                parts = column_definition.split()
                if parts:
                    return parts[0]
            
            return ""
        except Exception:
            return ""

    def _get_column_samples(self, cursor, table_name: str, column_name: str, max_samples: int = 5) -> List[str]:
        """Get sample values for a specific column"""
        try:
            # Use double quotes to handle column names with special characters
            quoted_column = f'"{column_name}"'
            quoted_table = f'"{table_name}"'
            
            # Get unique non-null values, limited to max_samples
            query = f"""
            SELECT DISTINCT {quoted_column}
            FROM {quoted_table} 
            WHERE {quoted_column} IS NOT NULL 
            AND TRIM(CAST({quoted_column} AS TEXT)) != ''
            LIMIT {max_samples}
            """
            
            cursor.execute(query)
            results = cursor.fetchall()
            
            # Convert to string and clean up
            samples = []
            for (value,) in results:
                if value is not None:
                    # Convert to string and clean up
                    str_value = str(value).strip()
                    
                    # Truncate very long values
                    if len(str_value) > 50:
                        str_value = str_value[:47] + "..."
                    
                    # Escape special characters for comment
                    str_value = str_value.replace('\n', ' ').replace('\r', ' ')
                    
                    if str_value and str_value not in samples:
                        samples.append(str_value)
            
            return samples[:max_samples]
            
        except Exception as e:
            # If we can't get samples, return empty list
            return []
    

class NL2SQLWorkflow:
    """Workflow handler for NL2SQL Analysis with QA"""
    
    def __init__(self):
        self.system_state = SystemState()
        self.current_db_path = None
        self.current_agent = None
        self.responser = Responser()
        
        # Initialize SQL agent attributes in SystemState if not present
        if not hasattr(self.system_state, 'nl2sql_session_state'):
            self.system_state.nl2sql_session_state = {}
        if not hasattr(self.system_state, 'nl2sql_messages'):
            self.system_state.nl2sql_messages = []
        if not hasattr(self.system_state, 'available_databases'):
            self.system_state.available_databases = []
        if not hasattr(self.system_state, 'selected_database'):
            self.system_state.selected_database = None
    
    def get_available_databases(self) -> List[str]:
        """Get list of available databases from ./created_DBs/"""
        db_folder = Path("./created_DBs")
        databases = []
        
        if db_folder.exists():
            for db_dir in db_folder.iterdir():
                if db_dir.is_dir():
                    # Check if directory contains a .sqlite file
                    sqlite_files = list(db_dir.glob("*.sqlite"))
                    if sqlite_files:
                        databases.append(db_dir.name)
        
        # Update system state
        self.system_state.available_databases = databases
        return databases
    
    def select_database(self, db_name: str) -> Dict[str, Any]:
        """Select a database and initialize the agent"""
        if not db_name:
            return {
                "status": "error",
                "message": "No database selected"
            }
        
        db_folder = Path("./created_DBs") / db_name
        sqlite_files = list(db_folder.glob("*.sqlite"))
        
        if not sqlite_files:
            return {
                "status": "error",
                "message": f"No SQLite file found in {db_name}"
            }
        
        self.current_db_path = str(sqlite_files[0])
        self.system_state.selected_database = db_name
        
        # Get not_for_db files
        not_for_db_dir = db_folder / "not_for_db"
        not_for_db_files = []
        if not_for_db_dir.exists():
            for file_path in not_for_db_dir.glob("*"):
                if file_path.is_file():
                    not_for_db_files.append(file_path.name)
        
        # Initialize the NL2SQL agent
        self.current_agent = NL2SQLAgent()
        self.current_agent.set_database(self.current_db_path, not_for_db_files)
        
        # Reset session state for new database
        self.system_state.nl2sql_session_state = {"agent": self.current_agent}
        self.system_state.nl2sql_messages = []
        
        return {
            "status": "success",
            "message": f"Database '{db_name}' selected successfully",
            "db_path": self.current_db_path,
            "not_for_db_files": not_for_db_files
        }
    
    def interact_with_agent(self, prompt: str, messages: list, session_state: dict) -> Tuple[list, dict]:
        """Handle interaction with the NL2SQL agent - returns updated messages"""
        if not self.current_agent or not self.current_db_path:
            error_response = {"role": "assistant", "content": "❌ Please select a database first."}
            messages.append({"role": "user", "content": prompt})
            messages.append(error_response)
            return messages, session_state
        
        try:
            
            # Process question and get result
            result = self.current_agent.process_question(prompt, messages)

            # Add user message
            messages.append({"role": "user", "content": prompt})
            
            # Format response using Responser
            formatted_response = self.responser.format_nl2sql_response(result, prompt)
            
            # Add assistant response
            messages.append({"role": "assistant", "content": formatted_response})
            
            # Update system state
            self.system_state.nl2sql_messages = messages.copy()
            
            return messages, session_state
            
        except Exception as e:
            error_response = {"role": "assistant", "content": f"❌ Error in analysis: {str(e)}"}
            messages.append(error_response)
            return messages, session_state
    
    def get_downloadable_files(self) -> List[Dict[str, str]]:
        """Get list of downloadable result files"""
        result_files = []
        
        # Look for result.csv in current directory
        if os.path.exists("result.csv"):
            result_files.append({
                "name": "result.csv", 
                "path": "result.csv",
                "size": os.path.getsize("result.csv")
            })
        
        # Look for other CSV files that might be generated
        csv_files = Path(".").glob("*.csv")
        for csv_file in csv_files:
            if csv_file.name != "result.csv":  # Avoid duplicates
                result_files.append({
                    "name": csv_file.name,
                    "path": str(csv_file),
                    "size": csv_file.stat().st_size
                })
        
        return result_files
    
    def preview_csv_file(self, file_path: str) -> str:
        """Preview CSV file content as HTML table"""
        try:
            if not os.path.exists(file_path):
                return "File not found."
            
            df = pd.read_csv(file_path)
            
            # Limit preview to first 100 rows and 10 columns for performance
            preview_df = df.head(100).iloc[:, :10]
            
            html_table = preview_df.to_html(
                classes="table table-striped",
                escape=False,
                index=False,
                max_rows=100
            )
            
            info = f"<div class='file-info'><strong>File:</strong> {os.path.basename(file_path)}<br>"
            info += f"<strong>Shape:</strong> {df.shape[0]} rows × {df.shape[1]} columns<br>"
            info += f"<strong>Size:</strong> {os.path.getsize(file_path)} bytes</div><br>"
            
            return info + html_table
            
        except Exception as e:
            return f"Error previewing file: {str(e)}"
    
    def clear_chat(self):
        """Clear chat history"""
        self.system_state.nl2sql_messages = []
        return []

# Create global instance
nl2sql_workflow = NL2SQLWorkflow()