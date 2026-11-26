import gradio as gr
import os
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Any
from workflow_DBconstruct import DBConstructionWorkflow, _generate_file_structure_markdown
from workflow_NL2SQL import nl2sql_workflow
from SystemState import SystemState
import json
from ProgressLogger import progress_logger


# File upload folder
UPLOAD_FOLDER = Path("./uploads")
if not UPLOAD_FOLDER.exists():
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

# Set proper temp directory permissions
temp_dir = Path("./temp")
temp_dir.mkdir(exist_ok=True, parents=True)
os.environ["GRADIO_TEMP_DIR"] = str(temp_dir)

class ExcelAnalysisPlatform:
    def __init__(self):
        self.db_workflow = DBConstructionWorkflow()
        self.system_state = SystemState()
        
    def handle_file_upload(self, files):
        """Handle multiple file uploads"""
        if not files or len(files) == 0:
            return "No files selected", "No files uploaded yet."
            
        uploaded_files = []
        
        for file in files:
            try:
                if file is None:
                    continue
                    
                # Get original filename
                if hasattr(file, 'name'):
                    original_name = os.path.basename(file.name)
                else:
                    original_name = "uploaded_file"
                
                # Sanitize filename
                sanitized_name = "".join(c for c in original_name if c.isalnum() or c in "._-() ")
                if not sanitized_name:
                    sanitized_name = "uploaded_file.xlsx"
                
                # Ensure unique filename
                counter = 1
                final_name = sanitized_name
                while (UPLOAD_FOLDER / final_name).exists():
                    name_parts = sanitized_name.rsplit('.', 1)
                    if len(name_parts) == 2:
                        final_name = f"{name_parts[0]}_{counter}.{name_parts[1]}"
                    else:
                        final_name = f"{sanitized_name}_{counter}"
                    counter += 1
                
                # Save the file
                file_path = UPLOAD_FOLDER / final_name
                
                if hasattr(file, 'name') and os.path.exists(file.name):
                    # Copy from temp location
                    shutil.copy2(file.name, file_path)
                else:
                    # This shouldn't happen with proper file handling
                    continue
                
                file_info = {
                    "name": final_name,
                    "path": str(file_path),
                    "size": file_path.stat().st_size
                }
                uploaded_files.append(file_info)
                
                size_mb = file_info["size"] / (1024 * 1024)
                print(f"File uploaded: {final_name} ({size_mb:.2f} MB)")
                
            except Exception as e:
                print(f"File upload error: {e}")
        
        # Update system state
        if uploaded_files:
            self.system_state.uploaded_files = uploaded_files
        
        status_text = "✅ Files uploaded successfully!" if uploaded_files else "No valid files uploaded."
        file_list = self.format_file_list(uploaded_files)
        
        return status_text, file_list
    
    def format_file_list(self, files: List[Dict]) -> str:
        """Format uploaded files for display"""
        if not files:
            return "No files uploaded yet."
        
        formatted = "**Uploaded Files:**\n\n"
        for i, file_info in enumerate(files, 1):
            size_mb = file_info["size"] / (1024 * 1024)
            formatted += f"{i}. **{file_info['name']}** ({size_mb:.2f} MB)\n"
        
        return formatted
    
    def start_conversation(self, initial_description: str):
        """Start the DB construction process with progress logging"""
        if not hasattr(self.system_state, 'uploaded_files') or not self.system_state.uploaded_files:
            return (
                "❌ Please upload files first!", 
                "",
                [],
                "",  # ER schema code
                "",  # schema file map code
                "<div style='text-align: center; padding: 50px; color: #666;'>Preview will appear here after starting construction</div>",  # mermaid preview
                gr.Button(interactive=True),   # start button (keep enabled for retry)
                gr.Button(interactive=False),  # update changes
                gr.Button(interactive=False),  # createDB
                ""  # progress logs
            )
        
        try:
            # Clear previous logs and start capturing
            progress_logger.clear_logs()
            progress_logger.start_capture()
            
            # Initialize the construction workflow
            result = self.db_workflow.start_construction(
                uploaded_files=self.system_state.uploaded_files,
                initial_description=initial_description
            )
            
            # Stop capturing
            progress_logger.stop_capture()
            
            # Format messages for chatbot
            messages = [
                {"role": "user", "content": f"**Start Initial Design** \n\n Initial description: {initial_description if initial_description.strip() else 'Please analyze and construct the database based on these files.'}"},
                {"role": "assistant", "content": result["response"]}
            ]
            
            # Get Mermaid code and create preview
            excel_info_vis = result.get("excel_info_vis", "")
            mermaid_code = result.get("mermaid_code", "")
            ERschema_code = result.get("ERschema_code", "")
            schema_file_map_code = result.get("schema_file_map_code", "")
            mermaid_preview_markdown = self._create_mermaid_preview_markdown(mermaid_code)
            self.system_state.cur_vis = {
                "excel_info_vis": excel_info_vis,
                "mermaid_code": mermaid_code,
                "ERschema_code": ERschema_code,
                "schema_file_map_code": schema_file_map_code,
                "mermaid_preview_markdown": mermaid_preview_markdown
            }

            return (
                "",
                excel_info_vis,
                messages,
                ERschema_code,
                schema_file_map_code,
                mermaid_preview_markdown,
                gr.Button(interactive=False),  # start button (disable after success)
                gr.Button(interactive=True),   # update changes
                gr.Button(interactive=True),   # createDB
                progress_logger.get_logs_text()  # progress logs
            )
            
        except Exception as e:
            progress_logger.stop_capture()
            error_msg = f"❌ Error starting construction: {str(e)}"
            print(f"Construction error: {e}")
            return (
                error_msg, 
                "",
                [], 
                "", 
                "", 
                "<div style='text-align: center; padding: 50px; color: #ff6b6b;'>Error occurred during construction</div>", 
                gr.Button(interactive=True),   # start button (keep enabled for retry)
                gr.Button(interactive=False),   # update changes
                gr.Button(interactive=False),   # createDB
                progress_logger.get_logs_text()  # progress logs
            )
    
    def update_changes(self, message: str, ERschema_code: str, map_editor_content: str, messages: List):
        """Handle Mermaid code updates with progress logging"""
        message = message or "Update changes based on modified Mermaid code"
        try:
            # Clear previous logs and start capturing
            progress_logger.clear_logs()
            progress_logger.start_capture()
            
            # Process message with Mermaid code through workflow
            result = self.db_workflow.update_schema(
                message=message,
                ERschema_code=ERschema_code.strip() if ERschema_code.strip() else None,
                schema_file_map_code=map_editor_content.strip() if map_editor_content.strip() else None
            )
            
            # Stop capturing
            progress_logger.stop_capture()
            
            # Add to messages
            messages.append({"role": "user", "content": message})
            messages.append({"role": "assistant", "content": result["response"]})
            
            # Get updated Mermaid code
            current_parsing = getattr(self.db_workflow.system_state, 'parsed_result_of_excel', None)
            current_schema = getattr(self.db_workflow.system_state, 'designedDBschema_mapExcel', None)
            res_vis = self._generate_schema_mermaid(current_schema, current_parsing)
            mermaid_code = res_vis.get("mermaid_code", "")
            ERschema_code = res_vis.get("ERschema_code", "")
            schema_file_map_code = res_vis.get("schema_file_map_code", "")
            mermaid_preview_markdown = self._create_mermaid_preview_markdown(mermaid_code)
            self.system_state.cur_vis.update({
                "mermaid_code": mermaid_code,
                "ERschema_code": ERschema_code,
                "schema_file_map_code": schema_file_map_code,
                "mermaid_preview_markdown": mermaid_preview_markdown
            })
            interactive = len(self.system_state.allHistory_of_designedDBschema_mapExcel) > 1  # Enable undo if there's history
            
            return messages, "", ERschema_code, schema_file_map_code, mermaid_preview_markdown, gr.Button(interactive=interactive), progress_logger.get_logs_text()
            
        except Exception as e:
            progress_logger.stop_capture()
            error_response = f"❌ Error updating changes: {str(e)}"
            if message.strip():
                messages.append({"role": "user", "content": message})
            else:
                messages.append({"role": "user", "content": "Update changes"})
            messages.append({"role": "assistant", "content": error_response})
            interactive = len(getattr(self.system_state, 'allHistory_of_designedDBschema_mapExcel', [])) > 1
            return messages, "", "", "", "", gr.Button(interactive=interactive), progress_logger.get_logs_text()

    def undo_last_change(self):
        """Undo the last change by reverting to previous schema design"""
        try:
            progress_logger.clear_logs()
            progress_logger.log_progress("Processing undo request...")
            
            # Check if there's history to undo to
            if (not hasattr(self.db_workflow.system_state, 'allHistory_of_designedDBschema_mapExcel') or 
                len(self.db_workflow.system_state.allHistory_of_designedDBschema_mapExcel) <= 1):
                
                progress_logger.log_progress("No previous changes found to undo")
                
                # No previous state to revert to
                current_messages = getattr(self.system_state, 'conv_history', [])
                current_messages.append({"role": "user", "content": "Undo Last Change"})
                current_messages.append({"role": "assistant", "content": "❌ No previous changes to undo."})
                
                # Return current state without changes
                current_vis = getattr(self.system_state, 'cur_vis', {})
                return (
                    current_messages,
                    "",  # Clear user input
                    current_vis.get("ERschema_code", ""),
                    current_vis.get("schema_file_map_code", ""),
                    current_vis.get("mermaid_preview_markdown", ""),
                    gr.Button(interactive=False),  # Keep undo button disabled
                    progress_logger.get_logs_text()
                )
            
            # Remove the last (current) state from history
            history = self.db_workflow.system_state.allHistory_of_designedDBschema_mapExcel
            history.pop()  # Remove the current state
            progress_logger.log_progress("Reverted to previous schema state")
            
            # Set the previous state as current
            if history:
                previous_state = history[-1]  # Get the new last item
                self.db_workflow.system_state.designedDBschema_mapExcel = previous_state
            
            # Regenerate visualization with the reverted schema
            progress_logger.log_progress("Regenerating visualization...")
            current_parsing = getattr(self.db_workflow.system_state, 'parsed_result_of_excel', None)
            current_schema = getattr(self.db_workflow.system_state, 'designedDBschema_mapExcel', None)
            
            if current_schema and current_parsing:
                res_vis = self._generate_schema_mermaid(current_schema, current_parsing)
                mermaid_code = res_vis.get("mermaid_code", "")
                ERschema_code = res_vis.get("ERschema_code", "")
                schema_file_map_code = res_vis.get("schema_file_map_code", "")
                mermaid_preview_markdown = self._create_mermaid_preview_markdown(mermaid_code)
                
                # Update system state visualization
                self.system_state.cur_vis.update({
                    "mermaid_code": mermaid_code,
                    "ERschema_code": ERschema_code,
                    "schema_file_map_code": schema_file_map_code,
                    "mermaid_preview_markdown": mermaid_preview_markdown
                })
                progress_logger.log_progress("Visualization regenerated successfully")
            else:
                # Fallback if regeneration fails
                ERschema_code = ""
                schema_file_map_code = ""
                mermaid_preview_markdown = "📊 *Unable to regenerate visualization after undo*"
                progress_logger.log_progress("Warning: Could not regenerate visualization")
            
            # Update conversation history
            current_messages = getattr(self.system_state, 'conv_history', [])
            current_messages.append({"role": "user", "content": "Undo Last Change"})
            current_messages.append({"role": "assistant", "content": "✅ Successfully reverted to previous schema design."})
            
            # Check if undo should still be available
            undo_interactive = len(self.db_workflow.system_state.allHistory_of_designedDBschema_mapExcel) > 1
            
            return (
                current_messages,
                "",  # Clear user input
                ERschema_code,
                schema_file_map_code,
                mermaid_preview_markdown,
                gr.Button(interactive=undo_interactive),
                progress_logger.get_logs_text()
            )
            
        except Exception as e:
            # Handle any errors during undo
            progress_logger.log_progress(f"Error during undo operation: {str(e)}")
            error_msg = f"❌ Error during undo operation: {str(e)}"
            current_messages = getattr(self.system_state, 'conv_history', [])
            current_messages.append({"role": "user", "content": "Undo Last Change"})
            current_messages.append({"role": "assistant", "content": error_msg})
            
            # Return current state in case of error
            current_vis = getattr(self.system_state, 'cur_vis', {})
            return (
                current_messages,
                "",  # Clear user input
                current_vis.get("ERschema_code", ""),
                current_vis.get("schema_file_map_code", ""),
                current_vis.get("mermaid_preview_markdown", ""),
                gr.Button(interactive=False),  # Disable undo button on error
                progress_logger.get_logs_text()
            )

    def create_database(self, messages: List, db_dropdown):
        """Create the SQLite database from the designed schema with progress logging"""
        try:
            # Clear previous logs and start capturing
            progress_logger.clear_logs()
            progress_logger.start_capture()
            
            # Check if schema is available
            if not hasattr(self.db_workflow.system_state, 'designedDBschema_mapExcel') or \
            not self.db_workflow.system_state.designedDBschema_mapExcel:
                progress_logger.stop_capture()
                error_msg = "❌ No database schema available. Please complete schema design first."
                messages.append({"role": "user", "content": "Create Database"})
                messages.append({"role": "assistant", "content": error_msg})
                return messages, gr.Dropdown(), progress_logger.get_logs_text()
            
            # Execute database creation
            result = self.db_workflow.process_create_DB()
            
            # Stop capturing
            progress_logger.stop_capture()
            
            # Add messages to chat
            messages.append({"role": "user", "content": "Create Database"})
            messages.append({"role": "assistant", "content": result["response"]})

            # Update available databases in NL2SQL workflow
            available_dbs = nl2sql_workflow.get_available_databases()
            new_db_name = result.get("creation_summary", {}).get("db_name", "")
            
            # Create updated dropdown with empty option first
            dropdown_choices = [""] + available_dbs
            updated_dropdown = gr.Dropdown(
                choices=dropdown_choices,
                value=new_db_name if new_db_name in available_dbs else "",  # Select the new DB or empty
                label="Select Database"
            )

            return messages, updated_dropdown, progress_logger.get_logs_text()

        except Exception as e:
            progress_logger.stop_capture()
            progress_logger.log_progress(f"Error creating database: {str(e)}")
            error_msg = f"❌ Error creating database: {str(e)}"
            messages.append({"role": "user", "content": "Create Database"})
            messages.append({"role": "assistant", "content": error_msg})
            return messages, gr.Dropdown(), progress_logger.get_logs_text()
        
    # NL2SQL Tab Functions
    def select_database_for_qa(self, db_name: str):
        """Select database for Q&A analysis"""
        if not db_name:
            return (
                "Please select a database first.",
                gr.Textbox(interactive=False),  # text input
                gr.Button(interactive=False),   # submit button  
                gr.Button(interactive=False),   # clear button
                []                              # messages
            )
        
        result = nl2sql_workflow.select_database(db_name)
        
        if result["status"] == "success":
            status_msg = f"✅ {result['message']}\n\n**Database Path:** `{result['db_path']}`"
            return (
                status_msg,
                gr.Textbox(interactive=True),   # text input - NOW ENABLED
                gr.Button(interactive=True),    # submit button
                gr.Button(interactive=True),    # clear button
                []                              # clear messages
            )
        else:
            return (
                f"❌ {result['message']}",
                gr.Textbox(interactive=False),  # text input
                gr.Button(interactive=False),   # submit button
                gr.Button(interactive=False),   # clear button
                []
            )
    
    def refresh_downloadable_files(self):
        """Refresh list of downloadable files"""
        files = nl2sql_workflow.get_downloadable_files()
        if not files:
            return "No result files available for download."
        
        file_list = "**Available Result Files:**\n\n"
        for file_info in files:
            size_mb = file_info["size"] / (1024 * 1024)
            file_list += f"• **{file_info['name']}** ({size_mb:.2f} MB)\n"
        
        return file_list
    
    def preview_result_file(self, file_path: str):
        """Preview result file"""
        if not file_path or not os.path.exists(file_path):
            return "Please select a valid file to preview."
        
        return nl2sql_workflow.preview_csv_file(file_path)

    def interact_with_sql_agent(self, prompt: str, messages: list, session_state: dict):
        """Handle interaction with SQL agent with progress logging"""
        print("len of messages:", len(messages))
        if not prompt.strip():
            return messages, messages, session_state, ""  # Add empty progress logs
        
        try:
            # Clear previous logs and start capturing for QA
            progress_logger.clear_logs()
            progress_logger.start_capture()
            progress_logger.log_progress(f"Processing question: {prompt[:50]}{'...' if len(prompt) > 50 else ''}")
            
            # Call the workflow
            updated_messages, updated_session = nl2sql_workflow.interact_with_agent(prompt, messages, session_state)
            
            # Stop capturing
            progress_logger.stop_capture()
            progress_logger.log_progress("Question processing completed")
            
            return updated_messages, updated_messages, updated_session, progress_logger.get_logs_text()
            
        except Exception as e:
            progress_logger.stop_capture()
            progress_logger.log_progress(f"Error processing question: {str(e)}")
            return messages, messages, session_state, progress_logger.get_logs_text()

    def clear_qa_progress_logs(self):
        """Clear QA progress logs"""
        progress_logger.clear_logs()
        return "QA logs cleared."

    def refresh_qa_progress_logs(self):
        """Refresh QA progress logs display"""
        return progress_logger.get_logs_text()
    
    def clear_chat(self):
        """Clear chat history"""
        # also clean the history in the SystemState to avoid confusion
        # keep all till the first assistant entry (i.e. history for initial DB construction)
        if hasattr(self.system_state, 'conv_history'):
            initial_history = []
            for msg in self.system_state.conv_history:
                initial_history.append(msg)
                if msg["role"] == "assistant":
                    break
            self.system_state.conv_history = initial_history

        return [], ""

    def _create_mermaid_preview_markdown(self, mermaid_code: str) -> str:
        """Create Mermaid preview using Markdown format"""
        if not mermaid_code.strip():
            return "📊 *Diagram preview will appear here after starting construction*"
        else:
            return mermaid_code
    
    def _generate_schema_mermaid(self, schema_design: Dict[str, Any], parsing_result: Dict[str, Any]):
        """Generate current Mermaid code from schema design"""
        return self.db_workflow._generate_visualization_schema(schema_design, parsing_result)
    
    def get_database_visualization(self, db_name: str):
        """Get database visualization for selected database"""
        if not db_name:
            return (
                "📊 *No database selected*",
                "",
                "",
                gr.update(visible=False),
                "Select a database to view the file structure analysis."
            )
        
        try:
            db_folder = Path("./created_DBs") / db_name
            
            # Try to load saved schema design and parsed result
            schema_file = db_folder / "designedDBschema_mapExcel.json"
            parsed_file = db_folder / "parsed_result_of_excel.json"
            
            if schema_file.exists() and parsed_file.exists():
                # Load from saved files
                with open(schema_file, 'r', encoding='utf-8') as f:
                    schema_design = json.load(f)
                with open(parsed_file, 'r', encoding='utf-8') as f:
                    parsed_excel_data = json.load(f)
                
                # Generate visualization using existing function
                res_vis = self._generate_schema_mermaid(schema_design, parsed_excel_data)
                mermaid_code = res_vis.get("mermaid_code", "")
                ERschema_code = res_vis.get("ERschema_code", "")
                schema_file_map_code = res_vis.get("schema_file_map_code", "")
                
                # Generate file structure visualization
                file_structure_vis = _generate_file_structure_markdown(parsed_excel_data)
                
                return (
                    mermaid_code if mermaid_code else "📊 *Database visualization generated*",
                    ERschema_code,
                    schema_file_map_code,
                    gr.update(visible=True),
                    file_structure_vis
                )
            else:
                # Fallback: get schema from SQLite database directly
                sqlite_files = list(db_folder.glob("*.sqlite"))
                if sqlite_files:
                    db_path = str(sqlite_files[0])
                    schema_info = self._get_schema_from_sqlite(db_path)
                    
                    return (
                        f"## 🗄️ Database Schema: {db_name}\n\n```\n{schema_info}\n```",
                        schema_info,
                        "# No file mapping available (schema extracted from SQLite)",
                        gr.update(visible=True),
                        "*File structure data not available for this database.*"
                    )
                else:
                    return (
                        "❌ *No database files found*",
                        "",
                        "",
                        gr.update(visible=False),
                        ""
                    )
                    
        except Exception as e:
            return (
                f"❌ *Error loading database visualization: {str(e)}*",
                "",
                "",
                gr.update(visible=False),
                ""
            )

    def _get_schema_from_sqlite(self, db_path: str) -> str:
        """Get schema information directly from SQLite database"""
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            schema_info = []
            
            # Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = cursor.fetchall()
            
            for (table_name,) in tables:
                schema_info.append(f"\nTable: {table_name}")
                schema_info.append("-" * (len(table_name) + 7))
                
                # Get column information
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()
                
                for col_info in columns:
                    cid, name, dtype, notnull, default_val, pk = col_info
                    col_desc = f"  {name}: {dtype}"
                    if pk:
                        col_desc += " (PRIMARY KEY)"
                    if notnull:
                        col_desc += " NOT NULL"
                    if default_val is not None:
                        col_desc += f" DEFAULT {default_val}"
                    schema_info.append(col_desc)
                
                # Get foreign keys
                cursor.execute(f"PRAGMA foreign_key_list({table_name})")
                fkeys = cursor.fetchall()
                if fkeys:
                    schema_info.append("  Foreign Keys:")
                    for fk in fkeys:
                        schema_info.append(f"    {fk[3]} -> {fk[2]}.{fk[4]}")
            
            conn.close()
            return "\n".join(schema_info)
            
        except Exception as e:
            return f"Error reading database schema: {str(e)}"

    def toggle_visualization_visibility(self, current_visibility: bool):
        """Toggle visualization section visibility"""
        return gr.update(visible=not current_visibility)

    def get_progress_logs(self):
        """Get current progress logs"""
        return progress_logger.get_logs_text()

    def clear_progress_logs(self):
        """Clear progress logs"""
        progress_logger.clear_logs()
        return "Logs cleared."

    def refresh_progress_logs(self):
        """Refresh progress logs display"""
        return progress_logger.get_logs_text()
    
    def create_app(self):
        """Create the Gradio interface with progress logging"""
        with gr.Blocks(
            title="Conversational Excel Analysis Platform",
            css="""
            .mermaid-editor {
                font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                font-size: 14px;
            }
            .progress-logs {
                font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
                font-size: 12px;
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 10px;
                white-space: pre-wrap;
                overflow-y: auto;
                max-height: 400px;
            }
            .collapsed-panel {
                display: none !important;
            }
            .mermaid {
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 200px;
            }
            .mermaid svg {
                max-width: 100%;
                height: auto;
            }
            .file-info {
                background-color: #f8f9fa;
                padding: 10px;
                border-left: 4px solid #007bff;
                margin-bottom: 10px;
            }
            .table {
                font-size: 12px;
            }
            .schema-visualization {
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 15px;
                margin: 10px 0;
                background-color: #fafafa;
            }
            """
        ) as demo:
            gr.Markdown("""
            # 📊 **TabulaCortex**: Conversational Excel Analysis Platform
            
            Transform your Excel files into queryable databases through conversational interaction.
            """)
            
            # Add Timer for auto-refresh functionality
            db_progress_timer = gr.Timer(
                value=2.0,  # 2 seconds interval
                active=True  # Start active for auto-refresh
            )

            qa_progress_timer = gr.Timer(
                value=2.0,  # 2 seconds interval
                active=True  # Start active for auto-refresh
            )
            
            with gr.Tabs() as tabs:
                # Tab 1: DB Construction
                with gr.Tab("🏗️ DB Construction", id="db_construction"):
                    
                    with gr.Row():
                        # Left panel - File upload
                        with gr.Column(scale=1, visible=True) as file_panel:
                            gr.Markdown("### 📁 File Upload")
                            file_upload = gr.File(
                                label="Upload Excel/CSV Files",
                                file_count="multiple",
                                file_types=[".xlsx", ".xls", ".csv"]
                            )
                            upload_status = gr.Markdown(value="No files uploaded yet.")
                            
                            gr.Markdown("### 📊 Progress Logs")
                            progress_display = gr.Textbox(
                                label="Processing Progress",
                                value="Progress will appear here during processing...",
                                lines=1,
                                max_lines=12,
                                interactive=False,
                                elem_classes="progress-logs"
                            )
                            with gr.Row():
                                clear_logs_btn = gr.Button("🗑️ Clear Logs", variant="secondary", size="sm")
                                refresh_logs_btn = gr.Button("🔄 Refresh", variant="secondary", size="sm")

                            file_list_display = gr.Markdown(
                                value="",
                                max_height=400,
                            )

                        
                        # Middle panel - Main content
                        with gr.Column(scale=4):
                            gr.Markdown("""### 📊 Diagram Editor & Preview
    💡 **Tips:** Edit the code in the left panel and click "**Update Changes**" below. Can copy code to [Mermaid Live](https://mermaid.live) for advanced editing.""")
                            
                            # Upper: Mermaid Preview
                            mermaid_preview = gr.Markdown(
                                    value="📊 *Preview will appear here after starting construction*",
                                    elem_id="mermaid-preview"
                                )
                            # Lower: Mermaid Code Editor
                            gr.Markdown("**Mermaid Code Editor**")
                            mermaid_editor = gr.Textbox(
                                label="Mermaid Code",
                                placeholder="Mermaid code will appear here after starting construction. You can edit it and click 'Update Changes' to apply.",
                                lines=1,
                                max_lines=14,
                                scale=1,
                                elem_classes="mermaid-editor"
                            )
                            map_editor = gr.Textbox(
                                label="Schema-File Mapping",
                                placeholder="This panel shows the mapping between designed schema and source files if there has been merging. You can edit it and click 'Update Changes' to apply.",
                                lines=1,
                                max_lines=8,
                                scale=1,
                                elem_classes="mermaid-editor"
                            )
                                
                            # Lower - Chat interface
                            gr.Markdown("### 💬 Conversation")
                            
                            chatbot = gr.Chatbot(
                                label="DB construction Conversation",
                                height=500
                            )
                            
                            with gr.Row():
                                user_input = gr.Textbox(
                                    label="Description or Messages",
                                    placeholder="Describe your files and what you want to achieve, or type messages...",
                                    lines=1,
                                    max_lines=4,
                                    scale=4
                                )
                            
                            with gr.Row():
                                start_btn = gr.Button("🚀 Start Initial Design", variant="primary", scale=1)
                                update_btn = gr.Button("🔄 Update Changes", interactive=False, scale=1)
                                undo_btn = gr.Button("↩️ Undo Last Change", variant="secondary", interactive=False, scale=1)
                                createDB_btn = gr.Button("🗄️ Create Database", interactive=False, scale=1)
                                clear_btn = gr.Button("🗑️ Clear Chat", variant="secondary", scale=1)
                            
                
                # Tab 2: Database Visualization
                with gr.Tab("📊 Database Visualization", id="db_visualization"):
                    with gr.Row():
                        with gr.Column(scale=1):
                            gr.Markdown("### 🗄️ Database Selection")
                            
                            # Database dropdown for visualization
                            available_dbs_viz = nl2sql_workflow.get_available_databases()
                            dropdown_choices_viz = [""] + available_dbs_viz
                            viz_db_dropdown = gr.Dropdown(
                                choices=dropdown_choices_viz,
                                value="",
                                label="Select Database for Visualization",
                                info="Choose from available databases in ./created_DBs/"
                            )
                            
                            viz_db_status = gr.Markdown("Please select a database to view its schema visualization.")
                            
                            refresh_viz_db_btn = gr.Button("🔄 Refresh Database List", variant="secondary")
                            
                            gr.Markdown("---")
                            
                            gr.Markdown("### �💡 Tips")
                            gr.Markdown("""
                            - Select a database from the dropdown above
                            - View the database structure and relationships
                            - Copy code to [Mermaid Live](https://mermaid.live) for interactive editing
                            - Use the raw code sections for detailed schema information
                            """)

                            gr.Markdown("---")
                            
                            gr.Markdown("### � File Structure Analysis")
                            viz_file_structure = gr.Markdown(
                                value="Select a database to view the file structure analysis.",
                                max_height=500
                            )

                        with gr.Column(scale=2):
                            gr.Markdown("### 📊 Database Schema Visualization")
                            
                            # Visualization preview
                            viz_schema_preview = gr.Markdown(
                                value="📊 *Select a database to view schema visualization*",
                                elem_id="viz-schema-preview"
                            )
                            
                            # Raw code sections (read-only)
                            with gr.Accordion("📋 Raw Schema Code", open=False):
                                viz_er_schema_display = gr.Textbox(
                                    label="ER Schema Code",
                                    placeholder="ER diagram code will appear here...",
                                    lines=1,
                                    max_lines=10,
                                    interactive=False,
                                    elem_classes="mermaid-editor"
                                )
                                
                                viz_file_mapping_display = gr.Textbox(
                                    label="File Mapping Code",
                                    placeholder="File to schema mapping will appear here...",
                                    lines=1,
                                    max_lines=8,
                                    interactive=False,
                                    elem_classes="mermaid-editor"
                                )

                # Tab 3: Question Answering Analysis
                with gr.Tab("❓ Analysis with QA", id="qa"):
                    # Session state for SQL agent
                    sql_session_state = gr.State({})
                    sql_messages = gr.State([])
                    
                    with gr.Row():
                        with gr.Column(scale=1):
                            gr.Markdown("### 🗄️ Database Selection")
                            
                            # Database dropdown - Always include empty option
                            available_dbs = nl2sql_workflow.get_available_databases()
                            # Add empty option at the beginning
                            dropdown_choices = [""] + available_dbs
                            db_dropdown = gr.Dropdown(
                                choices=dropdown_choices,
                                value="",  # Always start with empty selection
                                label="Select Database",
                                info="Choose from available databases in ./created_DBs/"
                            )
                            
                            db_status = gr.Markdown("Please select a database to start analysis.")
                            
                            refresh_db_btn = gr.Button("🔄 Refresh Database List", variant="secondary")
                            
                            gr.Markdown("---")
                            
                            # Add QA Progress Logs section
                            gr.Markdown("### 📊 QA Progress Logs")
                            qa_progress_display = gr.Textbox(
                                label="QA Processing Progress",
                                value="QA progress will appear here during question processing...",
                                lines=1,
                                max_lines=10,
                                interactive=False,
                                elem_classes="progress-logs"
                            )
                            with gr.Row():
                                qa_clear_logs_btn = gr.Button("🗑️ Clear QA Logs", variant="secondary", size="sm")
                                qa_refresh_logs_btn = gr.Button("🔄 Refresh QA Logs", variant="secondary", size="sm")
                            
                            gr.Markdown("---")
                            
                            gr.Markdown("### 📥 Result Files")
                            downloadable_files = gr.Markdown("No result files available.")
                            refresh_files_btn = gr.Button("🔄 Refresh Files", variant="secondary")
                            
                            # File preview section
                            gr.Markdown("### 👀 File Preview")
                            file_path_input = gr.Textbox(
                                label="File Path",
                                placeholder="Enter path to preview (e.g., result.csv)",
                                value="result.csv"
                            )
                            preview_btn = gr.Button("👁️ Preview File", variant="secondary")

                        with gr.Column(scale=2):
                            gr.Markdown("### 💬 Chat with Database")
                            
                            sql_chatbot = gr.Chatbot(
                                label="NL2SQL Agent Conversation",
                                height=600
                            )
                            
                            sql_text_input = gr.Textbox(
                                lines=1,
                                max_lines=4,
                                label="Your Question",
                                placeholder="Ask questions about your data, e.g., 'What are the top 10 products by revenue?' or 'Show me customers from 2023'",
                                interactive=False  # Will be enabled when database is selected
                            )
                            
                            with gr.Row():
                                sql_submit_btn = gr.Button("🚀 Submit Question", variant="primary", interactive=False)
                                sql_clear_btn = gr.Button("🗑️ Clear Chat", variant="secondary", interactive=False)
                            
                            # Examples section (fully synthetic data only)
                            gr.Markdown("""
                            ### 💡 Example Questions (for the synthetic `sales.xlsx`)
                            - **总销售额最高的 5 个地区是哪些？** EN: Which 5 regions have the highest total revenue?
                            - **2025 年每个月的订单数量是多少？** EN: How many orders were placed in each month of 2025?
                            - **线上渠道和线下渠道的销售额分别为多少？** EN: What is the revenue from online and offline channels?
                            - **销售额最高的产品是什么？** EN: Which product has the highest total revenue?
                            """)

                            # File preview area
                            file_preview = gr.HTML(
                                label="File Preview",
                                value="<div style='text-align: center; padding: 50px; color: #666;'>File preview will appear here</div>"
                            )
            
            # Event handlers
            file_upload.upload(
                fn=self.handle_file_upload,
                inputs=[file_upload],
                outputs=[upload_status, file_list_display]
            )
            
            start_btn.click(
                fn=self.start_conversation,
                inputs=[user_input],
                outputs=[upload_status, file_list_display, chatbot, mermaid_editor, map_editor, mermaid_preview, start_btn, update_btn, createDB_btn, progress_display]
            )
            
            update_btn.click(
                fn=self.update_changes,
                inputs=[user_input, mermaid_editor, map_editor, chatbot],
                outputs=[chatbot, user_input, mermaid_editor, map_editor, mermaid_preview, undo_btn, progress_display]
            )
            
            user_input.submit(
                fn=self.update_changes,
                inputs=[user_input, mermaid_editor, map_editor, chatbot],
                outputs=[chatbot, user_input, mermaid_editor, map_editor, mermaid_preview, undo_btn, progress_display]
            )

            createDB_btn.click(
                fn=self.create_database,
                inputs=[chatbot, db_dropdown],
                outputs=[chatbot, db_dropdown, progress_display]
            )

            undo_btn.click(
                fn=self.undo_last_change,
                inputs=[],
                outputs=[chatbot, user_input, mermaid_editor, map_editor, mermaid_preview, undo_btn, progress_display]
            )

            clear_btn.click(
                fn=self.clear_chat,
                inputs=[],
                outputs=[chatbot, progress_display]
            )
            
            # Progress log controls
            clear_logs_btn.click(
                fn=self.clear_progress_logs,
                outputs=[progress_display]
            )
            
            refresh_logs_btn.click(
                fn=self.refresh_progress_logs,
                outputs=[progress_display]
            )
            
            # Timer tick event for auto-refresh progress logs
            db_progress_timer.tick(
                fn=self.get_progress_logs,
                outputs=[progress_display]
            )

            qa_progress_timer.tick(
                fn=self.refresh_qa_progress_logs,
                outputs=[qa_progress_display]
            )
            
            # Event handlers for Database Visualization tab
            viz_db_dropdown.change(
                fn=self.get_database_visualization,
                inputs=[viz_db_dropdown],
                outputs=[viz_schema_preview, viz_er_schema_display, viz_file_mapping_display, viz_db_status, viz_file_structure]
            )
            
            refresh_viz_db_btn.click(
                fn=lambda: gr.Dropdown(
                    choices=[""] + nl2sql_workflow.get_available_databases(),
                    value=""
                ),
                outputs=[viz_db_dropdown]
            )
        
            # Event handlers for QA tab
            db_dropdown.change(
                fn=self.select_database_for_qa,
                inputs=[db_dropdown],
                outputs=[db_status, sql_text_input, sql_submit_btn, sql_clear_btn, sql_messages]
            ).then(
                lambda: [],
                outputs=[sql_chatbot]
            )

            refresh_db_btn.click(
                fn=lambda: gr.Dropdown(
                    choices=[""] + nl2sql_workflow.get_available_databases(),
                    value=""  # Reset to empty when refreshing
                ),
                outputs=[db_dropdown]
            )

            # Updated SQL Agent interaction handlers (no streaming)
            sql_submit_btn.click(
                fn=self.interact_with_sql_agent,
                inputs=[sql_text_input, sql_messages, sql_session_state],
                outputs=[sql_chatbot, sql_messages, sql_session_state, qa_progress_display],  # Add qa_progress_display
            ).then(
                lambda: "",  # Clear input after submission
                outputs=[sql_text_input]
            ).then(
                # Auto-refresh files after query
                fn=self.refresh_downloadable_files,
                outputs=[downloadable_files]
            )

            sql_text_input.submit(
                fn=self.interact_with_sql_agent,
                inputs=[sql_text_input, sql_messages, sql_session_state],
                outputs=[sql_chatbot, sql_messages, sql_session_state, qa_progress_display],  # Add qa_progress_display
            ).then(
                lambda: "",  # Clear input after submission
                outputs=[sql_text_input]
            ).then(
                # Auto-refresh files after query
                fn=self.refresh_downloadable_files,
                outputs=[downloadable_files]
            )

            sql_clear_btn.click(
                lambda: ([], [], "QA logs cleared."),  # Clear chatbot, messages, and logs
                None,
                [sql_chatbot, sql_messages, qa_progress_display],  # Add qa_progress_display
            )

            # QA Progress log controls
            qa_clear_logs_btn.click(
                fn=self.clear_qa_progress_logs,
                outputs=[qa_progress_display]
            )

            qa_refresh_logs_btn.click(
                fn=self.refresh_qa_progress_logs,
                outputs=[qa_progress_display]
            )
            # File management handlers
            refresh_files_btn.click(
                fn=self.refresh_downloadable_files,
                outputs=[downloadable_files]
            )

            preview_btn.click(
                fn=self.preview_result_file,
                inputs=[file_path_input],
                outputs=[file_preview]
            )
        
        return demo

def main():
    platform = ExcelAnalysisPlatform()
    demo = platform.create_app()
    demo.launch(server_name="0.0.0.0", server_port=7860) # share=True, 

if __name__ == "__main__":
    main()