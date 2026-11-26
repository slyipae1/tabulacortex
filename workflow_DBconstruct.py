from typing import Dict, List, Any, Optional, Tuple
from SystemState import SystemState
from general_agents.Responser import Responser
from UnderstandExcel.InitialParser import InitialParser
from UnderstandExcel.Updater_Parse import UpdaterParse
from DesignDBschema.InitialDesigner import InitialDesigner
from DesignDBschema.MergeAdvisor import MergeAdvisor
from DesignDBschema.Updater_Schema import UpdaterSchema
from CreateDB.Prepare_sqlite import SQLiteCreator
import json

class DBConstructionWorkflow:
    """Main workflow handler for DB construction"""
    
    def __init__(self):
        self.system_state = SystemState()
        self.responser = Responser()
        self.initial_parser = InitialParser()
        self.updater_parse = UpdaterParse()
        # Add the new schema-related agents
        self.initial_designer = InitialDesigner()
        self.merge_advisor = MergeAdvisor()
        self.updater_schema = UpdaterSchema()
        
    def start_construction(self, uploaded_files: List[Dict], initial_description: str) -> Dict[str, Any]:
        """Start the DB construction process with simplified workflow"""
        # Initialize system state
        self.system_state.uploaded_files = uploaded_files
        self.system_state.current_procedure_step = "1-1"  # Parse and Understand excel
        self.system_state.conv_history = []
        
        # Add initial description to conversation history
        if initial_description.strip():
            self.system_state.conv_history.append({
                "role": "user",
                "content": f"Initial description: {initial_description}",
                "step": "initialization"
            })
        else: 
            self.system_state.conv_history.append({
                "role": "user",
                "content": "Initial description: here are some files.",
                "step": "initialization"
            })
        
        # Step 1-1: System Internal - Parse and Understand excel
        try:
            parsing_result = self._execute_step_1_1()

            with open("parsed_excel_debug.json", "w") as f:
                json.dump(parsing_result, f, indent=2, ensure_ascii=False)
            
            # Update system state
            self.system_state.parsed_result_of_excel = parsing_result
            self.system_state.current_procedure_step = "2-1"  # Move to schema design
            
            # Add to conversation history
            self.system_state.conv_history.append({
                "role": "system",
                "content": "Completed initial parsing of Excel files",
                "step": "1-1"
            })
            
        except Exception as e:
            error_response = f"❌ Error during initial parsing: {str(e)}"
            print(error_response)
            return {
                "response": error_response,
                "current_step": self.system_state.current_procedure_step,
                "status": "error"
            }

        # Step 2-1: System Internal - Design DB schema
        try:
            schema_result = self._execute_step_2_1()
            self.system_state.designedDBschema_mapExcel = schema_result
            self.system_state.allHistory_of_designedDBschema_mapExcel.append(schema_result.copy())  # Store initial design in history
            
            with open("designed_schema_debug.json", "w") as f:
                json.dump(schema_result, f, indent=2, ensure_ascii=False)

            # Add to conversation history
            self.system_state.conv_history.append({
                "role": "system", 
                "content": "Completed initial database schema design",
                "step": "2-1"
            })
        except Exception as e:
            error_response = f"❌ Error during schema design: {str(e)}"
            print(error_response)
            return {
                "response": error_response,
                "current_step": self.system_state.current_procedure_step,
                "status": "error"
            }

        # Step 2-2: System Internal - Prepare Merging Advice
        try:
            merge_advice = self.merge_advisor.generate_merge_advice(
                db_schema=self.system_state.designedDBschema_mapExcel,
                parsed_excel_data=self.system_state.parsed_result_of_excel
            )
            
            # Store merge advice in system state
            self.system_state.merge_advice = merge_advice
            self.system_state.current_procedure_step = "2-2"  # Move to discussion phase
            
            # Add to conversation history
            self.system_state.conv_history.append({
                "role": "system",
                "content": "Generated merge suggestions for database optimization",
                "step": "2-2"
            })
            
        except Exception as e:
            error_response = f"❌ Error during merge advice generation: {str(e)}"
            print(error_response)
            # Continue without merge advice
            self.system_state.merge_advice = {"merge_suggestions": [], "column_merge_suggestions": []}
            self.system_state.current_procedure_step = "2-2"

        # Generate visualizations
        try:
            # Generate file structure visualization (plain text)
            file_structure_vis = _generate_file_structure_markdown(parsing_result)
            
            # Generate schema visualization (Mermaid code for editor)
            res = self._generate_visualization_schema(
                self.system_state.designedDBschema_mapExcel, 
                parsing_result
            )
            ERschema_code = res["ERschema_code"]
            schema_file_map_code = res["schema_file_map_code"]
            mermaid_code = res["mermaid_code"]

        except Exception as e:
            print(f"Visualization generation error: {e}")
            mermaid_code = "// Error generating schema visualization"
            ERschema_code = "// Error generating ER schema visualization"
            schema_file_map_code = "// Error generating schema file map visualization"

        # Format comprehensive response
        response = self.responser.format_initial_construction_response(
            parsing_result=parsing_result,
            schema_result=self.system_state.designedDBschema_mapExcel,
            merge_advice=self.system_state.merge_advice
        )

        # Add assistant response to history
        self.system_state.conv_history.append({
            "role": "assistant",
            "content": response,
            "step": self.system_state.current_procedure_step,
        })

        return {
            "response": response,
            "excel_info_vis": file_structure_vis,
            "mermaid_code": mermaid_code,
            "ERschema_code": ERschema_code,
            "schema_file_map_code": schema_file_map_code,
            "current_step": self.system_state.current_procedure_step,
            "status": "success"
        }
    
    def update_schema(self, message: str, ERschema_code: Optional[str] = None, schema_file_map_code: Optional[str] = None) -> Dict[str, Any]:
        """Update schema based on user message and/or Mermaid code changes"""
        try:
            # Add user message to history
            self.system_state.conv_history.append({
                "role": "user",
                "content": message,
                "step": self.system_state.current_procedure_step,
                "ERschema_code": ERschema_code,
                "schema_file_map_code": schema_file_map_code
            })
            
            # Use UpdaterSchema to process the update
            schema_updates, update_records = self.updater_schema.update_schema_with_agent(
                user_message=message,
                ERschema_code=ERschema_code,
                schema_file_map_code=schema_file_map_code,
                current_schema=self.system_state.designedDBschema_mapExcel["schema"].copy(),
                conversation_history=self.system_state.conv_history
            )
            
            # Apply updates to system state
            if schema_updates:
                self.system_state.designedDBschema_mapExcel["schema"] = schema_updates
                self.system_state.allHistory_of_designedDBschema_mapExcel.append(schema_updates.copy())  # Store updated design in history
            with open("updated_schema_debug.json", "w") as f:
                json.dump(self.system_state.designedDBschema_mapExcel, f, indent=2, ensure_ascii=False)
            
            # Format response with update records
            response = self.responser.format_schema_update_response(
                user_prompt=message,
                update_records=update_records,
                updated_schema=schema_updates
            )
            
            # Add assistant response to history
            self.system_state.conv_history.append({
                "role": "assistant", 
                "content": response,
                "step": self.system_state.current_procedure_step,
                "update_records": update_records
            })
            
            return {
                "response": response,
                "current_step": self.system_state.current_procedure_step,
                "status": "success",
                "update_records": update_records,
                "updated_schema": schema_updates
            }
            
        except Exception as e:
            error_response = f"❌ Error updating schema: {str(e)}"
            return {
                "response": error_response,
                "current_step": self.system_state.current_procedure_step,
                "status": "error"
            }
        
    def process_create_DB(self) -> Dict[str, Any]:
        """Process database creation - Step 3"""
        try:
            self.system_state.current_procedure_step = "3"
            
            # Check if we have the necessary data
            if not self.system_state.designedDBschema_mapExcel:
                raise ValueError("No database schema available")
            if not self.system_state.parsed_result_of_excel:
                raise ValueError("No parsed Excel data available")
            
            # Create SQLite database
            sqlite_creator = SQLiteCreator()
            creation_result = sqlite_creator.create_database(
                schema_design=self.system_state.designedDBschema_mapExcel,
                parsed_excel_data=self.system_state.parsed_result_of_excel,
                uploaded_files=self.system_state.uploaded_files
            )
            
            # Format response
            response = self.responser.format_createDB_response(
                creation_result=creation_result,
                schema_design=self.system_state.designedDBschema_mapExcel
            )
            
            # Add to conversation history
            self.system_state.conv_history.append({
                "role": "system",
                "content": "Database creation completed",
                "step": "3"
            })
            
            self.system_state.conv_history.append({
                "role": "system",
                "content": response,
                "step": "3"
            })
            
            return {
                "response": response,
                "current_step": self.system_state.current_procedure_step,
                "status": "success",
                "db_path": creation_result.get("db_path"),
                "creation_summary": creation_result
            }
            
        except Exception as e:
            error_response = f"❌ Error creating database: {str(e)}"
            return {
                "response": error_response,
                "current_step": self.system_state.current_procedure_step,
                "status": "error"
            }
    
    def _execute_step_1_1(self) -> Dict[str, Any]:
        """Execute Step 1-1: Parse and Understand excel with parallel processing"""
        print(f"Starting parallel processing of {len(self.system_state.uploaded_files)} files...")
        
        # Prepare file info list
        file_infos = []
        for file_info in self.system_state.uploaded_files:
            file_infos.append({
                "path": file_info["path"],
                "name": file_info["name"]
            })
        
        # Get initial description from conversation history
        initial_description = ""
        for entry in self.system_state.conv_history:
            if entry.get("role") == "user" and "Initial description:" in entry.get("content", ""):
                initial_description = entry["content"].replace("Initial description:", "").strip()
                break
        
        # Use parallel processing
        parsing_result = self.initial_parser.parse_files_parallel(file_infos, initial_description)
        
        print(f"Completed processing {parsing_result['summary']['total_files']} files with {parsing_result['summary']['total_sheets']} sheets")
        
        return parsing_result

    def _execute_step_2_1(self) -> Dict[str, Any]:
        """Execute Step 2-1: Design DB schema"""
        if not self.system_state.parsed_result_of_excel:
            raise Exception("No parsed Excel data available")
        
        schema_design = self.initial_designer.design_database_schema(
            self.system_state.parsed_result_of_excel
        )
        
        return schema_design
    
    def _generate_visualization_schema(self, schema_design: Dict[str, Any], parsed_excel_data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate Mermaid visualization for schema design using mixed ER and flowchart syntax"""
        schema_design = schema_design["schema"].copy() 
        lines = []
        lines.append("## 🗄️ Database Schema Design")
        lines.append("```mermaid")

        ERschema_code = _gen_ERschema_code(schema_design)
        lines.append(ERschema_code)
        lines.append("```")
        schema_file_map_code = _gen_schema_file_map_code(schema_design, parsed_excel_data)

        if schema_file_map_code:
            lines.append("")  
            lines.append("---")  # Separator
            lines.append("")  
            lines.append("## 🔗 File to Database Mapping (with merging)")
            lines.append("```mermaid")
            lines.append(schema_file_map_code)
            lines.append("```")

        mermaid_code = "\n".join(lines)

        return {
            "ERschema_code": ERschema_code,
            "schema_file_map_code": schema_file_map_code,
            "mermaid_code": mermaid_code,
            "type": "schema_design"
        }
    

## fiel info vis
def _generate_file_structure_markdown(parsing_result: Dict[str, Any]) -> str:
    """Generate plain text markdown representation of file structure"""
    lines = ["## 📁 File Structure Analysis\n"]
    
    for file_data in parsing_result.get("files", []):
        file_name = file_data.get("file_name", "Unknown")
        lines.append(f"### 📄 **{file_name}**\n")
        
        for sheet in file_data.get("sheets", []):
            sheet_name = sheet.get("sheet_name", "Unknown")
            table_name = sheet.get("table_name", "")
            table_type = sheet.get("table_type", "")
            data_rows = len(sheet.get("data_row_indices", []))
            
            # Format data row range
            data_indices = sheet.get("data_row_indices", [])
            if data_indices:
                if len(data_indices) > 3:
                    row_range = f"{min(data_indices)}...{max(data_indices)}"
                else:
                    row_range = ",".join(map(str, data_indices))
            else:
                row_range = "none"
            
            # Sheet header
            table_info = f": {table_name}" if table_name else ""
            lines.append(f"- 📋 **{sheet_name}**{table_info} (rows: [{row_range}] | type: {table_type})")
            
            # Columns structure
            columns = sheet.get("columns", {})
            if isinstance(columns, dict) and "structure" in columns:
                columns_struct = columns["structure"]
            else:
                columns_struct = columns
                
            if columns_struct:
                lines.append("  ```")
                lines.append("  <COLUMNS>")
                _add_column_structure_text(lines, columns_struct, "  ")
                lines.append("  ```")
            
            # Metadata
            meta_data = sheet.get("meta_data", {})
            if meta_data and any(v for v in meta_data.values() if v):
                lines.append("  ```")
                lines.append("  <METADATA>")
                for key, value in meta_data.items():
                    if value and str(value).strip():
                        lines.append(f"  - {key}: {value}")
                lines.append("  ```")
            
            # Aggregation metadata
            agg_meta = sheet.get("agg_meta_data", {})
            if agg_meta and any(v for v in agg_meta.values() if v):
                lines.append("  ```")
                lines.append("  <AGG_METADATA>")
                for key, value in agg_meta.items():
                    if value and str(value).strip():
                        lines.append(f"  - {key}: {value}")
                lines.append("  ```")
            
            lines.append("")  # Empty line between sheets
    
    return "\n".join(lines)

def _add_column_structure_text(lines: List[str], structure: Any, indent: str):
    """Recursively add column structure as plain text"""
    if isinstance(structure, dict):
        for key, value in structure.items():
            if value is None or (isinstance(value, dict) and not value):
                lines.append(f"{indent}- {key}")
            elif isinstance(value, dict):
                lines.append(f"{indent}- {key}:")
                _add_column_structure_text(lines, value, indent + "  ")
            elif isinstance(value, list) and value:
                lines.append(f"{indent}- {key}: {', '.join(str(v) for v in value[:3])}")
            else:
                lines.append(f"{indent}- {key}: {value}")
    elif isinstance(structure, list):
        for item in structure:
            lines.append(f"{indent}- {item}")


## Mermaid code generation functions
def _gen_ERschema_code(schema_design: Dict[str, Any]) -> str:
    """Generate Mermaid ER diagram code for the database schema design"""
    lines = []
    
    lines.append("erDiagram")
    # Part 1: ER Diagram for database structure
    
    db_name = schema_design.get("db_name", "")
    db_tables = schema_design.get("db_tables", [])
    foreign_keys = schema_design.get("foreign_keys", [])
    
    # Add tables with columns
    for table in db_tables:
        table_name = table.get("table_name", "")
        table_id = table_name
        
        lines.append(f"    {table_id} {{")
        
        # Add columns
        for col in table.get("columns_mapping", []):
            col_name = col.get("column_name", "")
            datatype = col.get("datatype", "TEXT")
            constraints = col.get("col_constraints", [])
            
            constraint_str = " ".join(constraints) if constraints else ""
            constraint_display = f" \"{constraint_str}\"" if constraint_str else ""
            lines.append(f"        {datatype} {col_name}{constraint_display}")
        
        lines.append("    }")
    
    # Add foreign key relationships
    for fk in foreign_keys:
        if len(fk) >= 4:
            source_table = fk[0]
            target_table = fk[2]
            lines.append(f"    {source_table} ||--o| {target_table} : {fk[1]}_refers_{fk[3]}")

    return "\n".join(lines)

def _gen_schema_file_map_code(schema_design: Dict[str, Any], parsed_excel_data: Dict[str, Any]) -> str:
    """Generate Mermaid flowchart code for file-sheet-table mapping"""
    lines = []
    lines.append("graph TB")

    # Create ID tracking dictionaries
    db_table_id = {}
    db_column_id = {}
    ori_file_id = {}
    ori_sheet_id = {}
    ori_col_id_dicts = [{}]  # Start with one dict for outermost columns

    id_counter = 0
    
    def get_or_create_id(name: str, id_dict: dict, prefix: str, id_counter: int) -> Tuple[str, int]:
        """Get existing ID or create new one"""
        if name not in id_dict:
            id_dict[name] = f"{prefix}_{id_counter}"
            id_counter += 1
        return id_dict[name], id_counter

    def get_column_id_at_level(col_name: str, level: int, id_counter: int) -> Tuple[str, int]:
        """Get column ID at specific nesting level"""
        # Ensure we have enough dictionaries for this level
        while len(ori_col_id_dicts) <= level:
            ori_col_id_dicts.append({})
        
        return get_or_create_id(col_name, ori_col_id_dicts[level], f"col_L{level}", id_counter)
    
    def split_transform_comment(transform_text: str, block_size: int = 10) -> str:
        """Split transform comment into multiple lines"""
        if not transform_text or transform_text == "ORIGINAL":
            return ""
        if "FIXED: " in transform_text:
            transform_text = transform_text.replace("FIXED: ", "")

        words = transform_text.split()
        lines = []
        current_line = []
        
        for word in words:
            if len(' '.join(current_line + [word])) > block_size:
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                else:
                    lines.append(word)
            else:
                current_line.append(word)
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return '<br/>'.join(lines)
    
    # Process each database table
    for table in schema_design.get("db_tables", []):
        table_name = table.get("table_name", "")
        table_id, id_counter = get_or_create_id(table_name, db_table_id, "tbl", id_counter)
        
        # Create table node with table icon
        # for simplicity, only visualize if exist column has multiple entries
        has_multiple = False
        for column in table.get("columns_mapping", []):
            num = [en for en in column.get("original_column_xlsx", []) if en.get("transform_for_DB", "ORIGINAL") != "ORIGINAL"]
            if len(num) > 1:
                has_multiple = True
                break
        if not has_multiple:
            continue
        lines.append(f"    {table_id}[📊 DB Table: <br/> {table_name}]")
        
        # Process each column in the table
        for column in table.get("columns_mapping", []):
            col_name = column.get("column_name", "")
            col_id, id_counter = get_or_create_id(f"{table_name}_{col_name}", db_column_id, "dbcol", id_counter)

            # Process original column mappings
            # for simplicity, only visualize if have multiple entries
            num = [en for en in column.get("original_column_xlsx", []) if en.get("transform_for_DB", "ORIGINAL") != "ORIGINAL"]
            if len(num) <= 1:
                continue
            
            # Create column node and link to table
            lines.append(f"    {col_id}[📊 Column: <br/> {col_name}]")
            lines.append(f"    {table_id} --> {col_id}")
            
            for orig_col_info in column.get("original_column_xlsx", []):
                col_path = orig_col_info.get("col_path", [])
                transform_for_db = orig_col_info.get("transform_for_DB", "ORIGINAL")
                
                if len(col_path) >= 2:
                    file_name = col_path[0]
                    sheet_name = col_path[1]
                    
                    # Create file node if needed
                    if file_name not in ori_file_id:  # if exist, must have been created
                        file_id, id_counter = get_or_create_id(file_name, ori_file_id, "file", id_counter)
                        lines.append(f"    {file_id}[📁 File: <br/> {file_name}]")

                    # Create sheet node if needed
                    sheet_key = f"{file_name}_{sheet_name}"
                    if sheet_key not in ori_sheet_id:  # if exist, must have been linked
                        sheet_id, id_counter = get_or_create_id(sheet_key, ori_sheet_id, "sheet", id_counter)
                        lines.append(f"    {sheet_id}[📋 Sheet: <br/> {sheet_name}]")
                        lines.append(f"    {file_id} --> {sheet_id}")
                    
                    if len(col_path) == 2:
                        # Sheet distinguishing column - link directly to sheet
                        edge_comment = split_transform_comment(transform_for_db)
                        if edge_comment:
                            edge_label = "Value: " + edge_comment
                            lines.append(f"    {sheet_id} -- {edge_label} --> {col_id}")
                        else:
                            lines.append(f"    {sheet_id} --> {col_id}")
                    
                    elif len(col_path) > 2:
                        # Mapped from original columns - create column hierarchy
                        current_parent_id = sheet_id
                        
                        # Create nodes for each level of column nesting
                        for i, col_level_name in enumerate(col_path[2:], start=0):
                            while len(ori_col_id_dicts) <= i:
                                ori_col_id_dicts.append({})
                            if f"{sheet_key}_{col_level_name}_L{i}" not in ori_col_id_dicts[i]:  # if exist, must have been created
                                col_level_id, id_counter = get_column_id_at_level(
                                    f"{sheet_key}_{col_level_name}_L{i}", i, id_counter
                                )
                                # Create column node
                                lines.append(f"    {col_level_id}[{col_level_name}]")
                                lines.append(f"    {current_parent_id} --> {col_level_id}")
                                current_parent_id = col_level_id
                        
                        # Link final column to DB column
                        edge_comment = split_transform_comment(transform_for_db) if transform_for_db != "ORIGINAL" else ""
                        if edge_comment:
                            edge_label = "Value: " + edge_comment
                            lines.append(f"    {current_parent_id} -- {edge_label} --> {col_id}")
                        else:
                            lines.append(f"    {current_parent_id} --> {col_id}")
    
    # if now info need to show, return empty string
    if len(lines) <= 1:  # Only header lines exist
        return ""

    # Add style definitions
    lines.append("")
    lines.append("    %% Style definitions")
    lines.append("    classDef dbTable fill:#e1f5fe,stroke:#01579b,stroke-width:2px")
    lines.append("    classDef dbColumn fill:#f3e5f5,stroke:#4a148c,stroke-width:2px")
    lines.append("    classDef origFile fill:#e8f5e8,stroke:#2e7d32,stroke-width:2px")
    lines.append("    classDef origSheet fill:#fff3e0,stroke:#ef6c00,stroke-width:2px")
    lines.append("    classDef origColumn fill:#fafafa,stroke:#616161,stroke-width:1px")
    
    # Apply styles to nodes
    db_table_nodes = ",".join(db_table_id.values())
    db_column_nodes = ",".join(db_column_id.values())
    file_nodes = ",".join(ori_file_id.values())
    sheet_nodes = ",".join(ori_sheet_id.values())
    
    # Collect all column nodes from all levels
    all_col_nodes = []
    for col_dict in ori_col_id_dicts:
        all_col_nodes.extend(col_dict.values())
    col_nodes = ",".join(all_col_nodes)
    
    if db_table_nodes:
        lines.append(f"    class {db_table_nodes} dbTable")
    if db_column_nodes:
        lines.append(f"    class {db_column_nodes} dbColumn")
    if file_nodes:
        lines.append(f"    class {file_nodes} origFile")
    if sheet_nodes:
        lines.append(f"    class {sheet_nodes} origSheet")
    if col_nodes:
        lines.append(f"    class {col_nodes} origColumn")
    
    return "\n".join(lines)


