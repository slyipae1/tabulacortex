from typing import Dict, List, Any, Optional
from smolagents import OpenAIModel
import os
from dotenv import load_dotenv
import json

load_dotenv()

class Responser:
    """Agent responsible for formatting responses to users"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.model = OpenAIModel(
            model_id=os.getenv("MODEL_NAME", model_name),
            api_base=os.getenv("BASE_URL"),
            api_key=os.getenv("API_KEY"),
            temperature=0,
            max_tokens=8192,
            top_p=0.9,
        )
    
    def format_initial_construction_response(self,
                                    parsing_result: Dict[str, Any],
                                    schema_result: Dict[str, Any], 
                                    merge_advice: Dict[str, Any]) -> str:
        """Format response for initial construction completion"""
        
        response_parts = []
        
        # Header
        response_parts.append("## 🎉 Database Construction Complete!")
        response_parts.append("")
        
        # Summary
        schema_result = schema_result["schema"]
        files_data = parsing_result.get("files", [])
        total_sheets = sum(len(f.get("sheets", [])) for f in files_data)
        db_tables = schema_result.get("db_tables", [])
        
        response_parts.append("✅ **Construction Summary:**")
        response_parts.append(f"- Files processed: **{len(files_data)}**")
        response_parts.append(f"- Sheets analyzed: **{total_sheets}**")
        response_parts.append(f"- Database tables created: **{len(db_tables)}**")
        response_parts.append(f"- Database name: **{schema_result.get('db_name', '')}**")
        response_parts.append("")
        
        # Database Schema Summary
        response_parts.append("## 🗃️ Database Schema Summary")
        response_parts.append("")
        for table in db_tables:
            table_name = table.get("table_name", "Unknown")
            columns = table.get("columns_mapping", [])
            source_files = set()
            
            for col in columns:
                for orig_col_info in col.get("original_column_xlsx", []):
                    col_path = orig_col_info.get("col_path", [])
                    if len(col_path) >= 2:
                        source_files.add(f"{col_path[0]}::{col_path[1]}")
            
            response_parts.append(f"### 📊 Table: `{table_name}`")
            response_parts.append(f"- **Columns:** {len(columns)}")
            response_parts.append(f"- **Source sheets:** {', '.join(source_files)}")
            
            # Show key columns
            key_columns = [col.get("column_name", "") for col in columns[:5]]
            if len(columns) > 5:
                key_columns.append(f"... and {len(columns) - 5} more")
            response_parts.append(f"- **Key columns:** {', '.join(key_columns)}")
            response_parts.append("")
        
        # Merge Suggestions
        merge_suggestions = merge_advice.get("merge_suggestions", [])
        
        if merge_suggestions:
            response_parts.append("## 🔄 Optimization Opportunities")
            response_parts.append("")
            response_parts.append(merge_advice.get("overall_assessment", "Analysis complete."))
            response_parts.append("")
            
            # Group suggestions by type
            table_merges = [s for s in merge_suggestions if s.get("merge_type") == "merge table"]
            column_merges = [s for s in merge_suggestions if s.get("merge_type") == "merge column"]
            
            # Table merge suggestions
            if table_merges:
                response_parts.append("### 📋 Table Merge Recommendations:")
                for i, suggestion in enumerate(table_merges, 1):
                    sheets = suggestion.get("sheets", [])
                    db_tables = suggestion.get("db_tables", [])
                    suggestion_text = suggestion.get("suggestion", "")
                    
                    response_parts.append(f"**{i}. Merge Tables: {', '.join(db_tables)}**")
                    response_parts.append(f"   - **Affected sheets:** {', '.join([f'{s[0]}::{s[1]}' for s in sheets])}")
                    response_parts.append(f"   - **Strategy:** {suggestion_text}")
                    response_parts.append("")
            
            # Column merge suggestions  
            if column_merges:
                response_parts.append("### 🔗 Column Merge Recommendations:")
                for i, suggestion in enumerate(column_merges, 1):
                    raw_col_paths = suggestion.get("raw_col_paths", [])
                    db_columns = suggestion.get("db_columns", [])
                    suggestion_text = suggestion.get("suggestion", "")
                    
                    # Extract unique sheets and tables
                    sheets = set()
                    tables = set()
                    for path in raw_col_paths:
                        if len(path) >= 2:
                            sheets.add(f"{path[0]}::{path[1]}")
                    for db_col in db_columns:
                        if "." in db_col:
                            tables.add(db_col.split(".")[0])
                    
                    response_parts.append(f"**{i}. Merge Columns: {', '.join(db_columns)}**")
                    response_parts.append(f"   - **In tables:** {', '.join(tables)}")
                    response_parts.append(f"   - **Source sheets:** {', '.join(sheets)}")
                    response_parts.append(f"   - **Strategy:** {suggestion_text}")
                    response_parts.append("")
        else:
            response_parts.append("## ✅ Schema Optimization")
            response_parts.append("")
            response_parts.append("No specific merge recommendations found. The current schema structure appears well-organized.")
            response_parts.append("")
        
        # Next Steps
        response_parts.append("## 🚀 What's Next?")
        response_parts.append("")
        response_parts.append("**You can now:**")
        response_parts.append("- 🔧 **Update the schema design**: Edit the schema using the Mermaid editor above or describe changes in the message box.")
        response_parts.append("- ✅ **Finalize the database** by clicking: Create DB")
        return "\n".join(response_parts)
    
    def format_schema_update_response(self, 
                                    user_prompt: str, 
                                    update_records: List[str], 
                                    updated_schema: Dict[str, Any]) -> str:
        """Format response for schema update operations with List[str] update_records"""
        
        response_parts = []
        
        # Header
        response_parts.append("## ✅ Schema Update Complete!")
        response_parts.append("")
        
        # Summary
        if update_records:
            response_parts.append("### 📝 Actions Performed:")
            response_parts.append("")
            response_parts.extend(update_records)
            
            # Schema summary
            db_name = updated_schema.get("db_name", "")
            db_tables = updated_schema.get("db_tables", [])
            foreign_keys = updated_schema.get("foreign_keys", [])
            
            response_parts.append("### 🗃️ Updated Schema Summary:")
            response_parts.append(f"- **Database:** {db_name}")
            response_parts.append(f"- **Tables:** {len(db_tables)}")
            response_parts.append(f"- **Foreign Keys:** {len(foreign_keys)}")
            response_parts.append("")
            
            # Table list with details
            if db_tables:
                response_parts.append("**Tables:**")
                for table in db_tables:
                    table_name = table.get("table_name", "Unknown")
                    columns_count = len(table.get("columns_mapping", []))
                    response_parts.append(f"- `{table_name}` ({columns_count} columns)")
                response_parts.append("")
            
        else:
            response_parts.append("No changes were needed based on your request.")
            response_parts.append("")
        
        # Next steps
        response_parts.append("### 🚀 What's Next?")
        response_parts.append("You can:")
        response_parts.append("- 🔧 **Make additional changes** by editing the diagram or describing modifications")
        response_parts.append("- ✅ **Create the database** when you're satisfied with the design")
        
        return "\n".join(response_parts)
    
    def format_createDB_response(self, creation_result: Dict[str, Any], schema_design: Dict[str, Any]) -> str:
        """Format response for database creation completion"""
        
        response_parts = []
        
        # Header
        response_parts.append("## 🎉 Database Creation Complete!")
        response_parts.append("")
        
        # Success summary
        if creation_result.get("status") == "success":
            response_parts.append("✅ **Database Successfully Created!**")
            response_parts.append("")
            
            # Database details
            db_name = creation_result.get("db_name", "Unknown")
            db_path = creation_result.get("db_path", "")
            tables_created = creation_result.get("tables_created", 0)
            records_processed = creation_result.get("records_processed", 0)
            records_failed = creation_result.get("records_failed", 0)
            
            response_parts.append("### 📊 Database Summary:")
            response_parts.append(f"- **Database Name:** `{db_name}`")
            response_parts.append(f"- **Location:** `{db_path}`")
            response_parts.append(f"- **Tables Created:** {tables_created}")
            response_parts.append(f"- **Records Processed:** {records_processed:,}")
            if records_failed > 0:
                response_parts.append(f"- **Records Failed:** {records_failed:,}")
            response_parts.append("")
            
            # Table details
            schema = schema_design.get("schema", {})
            db_tables = schema.get("db_tables", [])
            
            if db_tables:
                response_parts.append("### 🗃️ Created Tables:")
                response_parts.append("")
                
                for table in db_tables:
                    table_name = table.get("table_name", "Unknown")
                    columns = table.get("columns_mapping", [])
                    
                    response_parts.append(f"#### 📋 Table: `{table_name}`")
                    response_parts.append(f"- **Columns:** {len(columns)}")
                    
                    # Show column details
                    column_details = []
                    for col in columns[:5]:  # Show first 5 columns
                        col_name = col.get("column_name", "")
                        datatype = col.get("datatype", "TEXT")
                        column_details.append(f"`{col_name}` ({datatype})")
                    
                    if len(columns) > 5:
                        column_details.append(f"... and {len(columns) - 5} more")
                    
                    response_parts.append(f"- **Schema:** {', '.join(column_details)}")
                    response_parts.append("")
            
            # Foreign keys
            foreign_keys = schema.get("foreign_keys", [])
            if foreign_keys:
                response_parts.append("### 🔗 Foreign Key Relationships:")
                for i, fk in enumerate(foreign_keys, 1):
                    if len(fk) >= 4:
                        response_parts.append(f"{i}. `{fk[0]}.{fk[1]}` → `{fk[2]}.{fk[3]}`")
                response_parts.append("")
            
            # Raw files saved
            raw_files = creation_result.get("raw_files_saved", [])
            if raw_files:
                response_parts.append("### 📁 Raw Files Preserved:")
                for i, file_path in enumerate(raw_files, 1):
                    file_name = os.path.basename(file_path)
                    response_parts.append(f"{i}. `{file_name}`")
                response_parts.append("")
            
            # Warnings
            warnings = creation_result.get("warnings", [])
            if warnings:
                response_parts.append("### ⚠️ Processing Warnings:")
                response_parts.append("")
                for warning in warnings[:10]:  # Show first 10 warnings
                    response_parts.append(f"- {warning}")
                if len(warnings) > 10:
                    response_parts.append(f"- ... and {len(warnings) - 10} more warnings")
                response_parts.append("")
            
            # Success rate
            if records_processed > 0:
                success_rate = ((records_processed - records_failed) / records_processed) * 100
                response_parts.append(f"### 📈 Processing Success Rate: {success_rate:.1f}%")
                response_parts.append("")
            
            # Next steps
            response_parts.append("## 🚀 What's Next?")
            response_parts.append("")
            response_parts.append("**Your database is ready! You can now:**")
            response_parts.append("- 🔍 **Switch to the 'Analysis with QA' tab** to query your data")
            response_parts.append("- 📊 **Continue to update schema** by editing code or describing changes")
            response_parts.append("")
            response_parts.append("The database file is saved and ready for use!")
            
        else:
            # Error case
            response_parts.append("❌ **Database Creation Failed**")
            response_parts.append("")
            response_parts.append("An error occurred during database creation. Please check the schema design and try again.")
            
            # Show any available error details
            if "error" in creation_result:
                response_parts.append(f"**Error:** {creation_result['error']}")
        
        return "\n".join(response_parts)
    
    def format_nl2sql_response(self, result: Dict[str, Any], question: str) -> str:
        """Format response for NL2SQL analysis results"""
        
        response_parts = []
        
        # Check status
        if result.get("status") == "error":
            response_parts.append("## ❌ Analysis Failed")
            response_parts.append("")
            response_parts.append(f"**Error:** {result.get('error', 'Unknown error occurred')}")
            
            # Show partial execution history if available
            execution_history = result.get("execution_history", [])
            if execution_history:
                response_parts.append("")
                response_parts.append("### 📈 Partial Execution History:")
                response_parts.extend(self._format_execution_history(execution_history))
            
            return "\n".join(response_parts)
        
        # Success case
        execution_history = result.get("execution_history", [])
        final_answer = result.get("final_answer", "")
        
        # Format execution history
        if execution_history:
            response_parts.append("## 📈 Execution History")
            response_parts.append("")
            response_parts.extend(self._format_execution_history(execution_history))
            response_parts.append("")
        
        # Add final answer
        if final_answer:
            response_parts.append("## 📋 Final Answer")
            response_parts.append("")
            response_parts.append(final_answer)
        else:
            response_parts.append("## 📋 Analysis Complete")
            response_parts.append("")
            response_parts.append("The analysis has been completed. Please check the execution history above for detailed results.")
        
        return "\n".join(response_parts)
    
    def _format_execution_history(self, execution_history: List[Dict[str, Any]]) -> List[str]:
        """Format execution history for display"""
        formatted = []
        
        for i, step in enumerate(execution_history, 1):
            tool = step.get("tool", "unknown")
            kwargs = step.get("kwargs", {})
            result = step.get("result", "")
            
            if tool == "exec_sql":
                sql_query = kwargs.get("sql_query", "")
                formatted.append(f"**Step {i}: SQL Execution**")
                formatted.append(f"```sql\n{sql_query}\n```")
                
                # Format result
                if result.startswith("```csv"):
                    formatted.append(f"**Result:**")
                    formatted.append(result)
                elif "Total" in result and "rows" in result:
                    # Summary result
                    formatted.append(f"**Result Summary:**")
                    formatted.append(f"```\n{result}\n```")
                else:
                    formatted.append(f"**Result:** {result}")
                formatted.append("")
                
            elif tool == "read_nofordb_files":
                file_names = kwargs.get("file_names", [])
                formatted.append(f"**Step {i}: File Reading**")
                formatted.append(f"**Files:** {', '.join(file_names)}")
                
                # Format file content result
                formatted.append(f"**Content:**")
                if len(result) > 1000:
                    # Truncate very long results
                    formatted.append(result[:1000] + "\n... (content truncated)")
                else:
                    formatted.append(result)
                formatted.append("")
        
        return formatted