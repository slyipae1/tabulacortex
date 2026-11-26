from typing import Dict, List, Any, Optional, Tuple
from smolagents import OpenAIModel, tool
import os
import json
from datetime import datetime
from collections import defaultdict
import re
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import copy


load_dotenv()

class SheetGroupAnalyzer:
    """Analyze sheets for grouping based on column structure similarity"""
    
    def __init__(self):
        pass
    
    def extract_column_signature(self, columns: Dict[str, Any]) -> str:
        """Extract column signature for comparison"""
        if isinstance(columns, dict):
            if "structure" in columns:
                return self._flatten_column_structure(columns["structure"])
            else:
                return self._flatten_column_structure(columns)
        return str(columns)
    
    def _flatten_column_structure(self, structure: Any, prefix: str = "") -> str:
        """Flatten nested column structure into a signature string"""
        if isinstance(structure, dict):
            items = []
            for key, value in structure.items():
                if value is None:
                    items.append(f"{prefix}{key}" if prefix else key)
                elif isinstance(value, dict):
                    items.append(self._flatten_column_structure(value, f"{prefix}{key}."))
                else:
                    items.append(f"{prefix}{key}" if prefix else key)
            return "|".join(sorted(items))
        return str(structure)
    
    def find_sheet_groups(self, parsed_excel_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find sheet groups within the parsed Excel data"""
        sheet_groups = []
        
        # Collect all sheets from all files
        all_sheets = {}
        for file_data in parsed_excel_data.get("files", []):
            file_name = file_data.get("file_name", "")
            for sheet in file_data.get("sheets", []):
                sheet_name = sheet.get("sheet_name", "")
                sheet_key = f"{file_name}_{sheet_name}"
                all_sheets[sheet_key] = {
                    "file_name": file_name,
                    "sheet_name": sheet_name,
                    "sheet_data": sheet
                }
        
        # Group by signatures
        identical_groups = defaultdict(list)
        column_groups = defaultdict(list)
        not_to_db_sheets = []
        processed_sheets = set()
        
        for sheet_key, sheet_info in all_sheets.items():
            sheet_data = sheet_info["sheet_data"]
            table_name = sheet_data.get("table_name", "")
            table_type = sheet_data.get("table_type", "")
            columns = sheet_data.get("columns", {})
            
            # Check if not suitable for database (not 1D)
            if "1D" not in table_type:
                not_to_db_sheets.append(sheet_info)
                continue
            
            # Create signatures
            column_sig = self.extract_column_signature(columns)
            identical_sig = f"{table_name}||{column_sig}"
            
            identical_groups[identical_sig].append(sheet_info)
            column_groups[column_sig].append(sheet_info)
        
        group_count = 0
        
        # Process identical groups
        for sig, sheets in identical_groups.items():
            if len(sheets) > 1:
                group_count += 1
                sheet_groups.append({
                    "sheet_group_id": f"identical_{group_count}",
                    "sheet_group_type": "identical",
                    "sheet_table_s": [(s["file_name"], s["sheet_name"], s["sheet_name"], 
                                     s["sheet_data"].get("table_name", "")) for s in sheets],
                    "columns_structure": sheets[0]["sheet_data"].get("columns", {})
                })
                processed_sheets.update([f"{s['file_name']}_{s['sheet_name']}" for s in sheets])
        
        # Process same_columns_structure groups (excluding already processed)
        for sig, sheets in column_groups.items():
            remaining_sheets = [s for s in sheets 
                              if f"{s['file_name']}_{s['sheet_name']}" not in processed_sheets]
            if len(remaining_sheets) > 1:
                group_count += 1
                sheet_groups.append({
                    "sheet_group_id": f"same_columns_structure_{group_count}",
                    "sheet_group_type": "same_columns_structure",
                    "sheet_table_s": [(s["file_name"], s["sheet_name"], s["sheet_name"],
                                     s["sheet_data"].get("table_name", "")) for s in remaining_sheets],
                    "columns_structure": remaining_sheets[0]["sheet_data"].get("columns", {})
                })
                processed_sheets.update([f"{s['file_name']}_{s['sheet_name']}" for s in remaining_sheets])
        
        # Process individual sheets
        for sheet_key, sheet_info in all_sheets.items():
            if sheet_key not in processed_sheets and "1D" in sheet_info["sheet_data"].get("table_type", ""):
                group_count += 1
                sheet_groups.append({
                    "sheet_group_id": f"individual_{group_count}",
                    "sheet_group_type": "individual",
                    "sheet_table_s": [(sheet_info["file_name"], sheet_info["sheet_name"], 
                                     sheet_info["sheet_name"], sheet_info["sheet_data"].get("table_name", ""))],
                    "columns_structure": sheet_info["sheet_data"].get("columns", {})
                })
        
        # Process not_to_db sheets
        if not_to_db_sheets:
            group_count += 1
            sheet_groups.append({
                "sheet_group_id": f"not_to_db_{group_count}",
                "sheet_group_type": "not_to_db",
                "sheet_table_s": [(s["file_name"], s["sheet_name"], s["sheet_name"],
                                 s["sheet_data"].get("table_name", "")) for s in not_to_db_sheets],
                "columns_structure": {}
            })
        
        return sheet_groups


class DatabaseSchemaDesigner:
    """Design database schemas using LLM"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.model = OpenAIModel(
            model_id=os.getenv("MODEL_NAME", model_name),
            api_base=os.getenv("BASE_URL"),
            api_key=os.getenv("API_KEY"),
            temperature=0,
            max_tokens=16384,
            top_p=0.9,
        )
    
    def enrich_sheet_names(self, sheet_groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enrich meaningless sheet names using LLM"""
        enriched_groups = []
        
        for group in sheet_groups:
            if group["sheet_group_type"] == "not_to_db":
                enriched_groups.append(group)
                continue
                
            enriched_sheet_tables = []
            for file_name, original_sheet_name, redesigned_sheet_name, table_name in group["sheet_table_s"]:
                # Check if sheet name is meaningless (like "Sheet1", "Sheet2", etc.)
                if False: # skip this
                # if re.match(r'^Sheet\d*$', original_sheet_name, re.IGNORECASE):
                    try:
                        prompt_template = """
您正在帮助将一个无意义的Excel工作表名称重新设计为更有意义的名称。

给定信息：
- 文件名：{file_name}
- 原始工作表名称：{original_sheet_name}
- Table name：{table_name}
- Column structure：
```json
{columns_structure}
```

请根据上下文建议一个有意义的工作表名称。以JSON对象响应：
```json
{{
    "redesigned_sheet_name": "更有意义的名称"
}}
```

名称应符合以下要求：
- 反映工作表的内容/目的
- 简洁明了
- 使用与原始内容**相同的语言**（例如，若原表大部分为中文，使用中文命名；if English is dorminant, use English；其他语言类似）
- 避免使用诸如"Sheet"、"Table"等通用术语
"""
                        prompt = prompt_template.format(
                            file_name=file_name,
                            original_sheet_name=original_sheet_name,
                            table_name=table_name or "N/A",
                            columns_structure=json.dumps(group["columns_structure"], ensure_ascii=False, indent=2)
                        )
                        
                        response = self.model([{"role": "user", "content": prompt}])

                        # Extract content from ChatMessage object
                        if hasattr(response, 'content'):
                            response_text = response.content
                        else:
                            response_text = str(response)
                        
                        # Parse JSON response
                        try:
                            if "```json" in response_text:
                                json_start = response_text.find("```json") + 7
                                json_end = response_text.find("```", json_start)
                                json_str = response_text[json_start:json_end].strip()
                            else:
                                json_str = response_text.strip()

                            result = json.loads(json_str)
                            redesigned_sheet_name = result.get("redesigned_sheet_name", original_sheet_name)
                            
                        except json.JSONDecodeError:
                            redesigned_sheet_name = original_sheet_name
                            
                    except Exception as e:
                        print(f"Error enriching sheet name for {original_sheet_name}: {e}")
                        redesigned_sheet_name = original_sheet_name
                else:
                    redesigned_sheet_name = original_sheet_name
                
                enriched_sheet_tables.append((file_name, original_sheet_name, redesigned_sheet_name, table_name))
            
            enriched_group = group.copy()
            enriched_group["sheet_table_s"] = enriched_sheet_tables
            enriched_groups.append(enriched_group)
        
        return enriched_groups
    
    def design_sheet_group_schema(self, sheet_group: Dict[str, Any]) -> Dict[str, Any]:
        """Design database schema for a sheet group using the columns mapping template"""
        try:
            # Load template
            template = self._load_columns_mapping_template()
            
            # Prepare prompt
            prompt = template.replace("{sheet_group}", 
                                    json.dumps(sheet_group, ensure_ascii=False, indent=2))
            
            # Call LLM
            response = self.model([{"role": "user", "content": prompt}])

            # Extract content from ChatMessage object
            if hasattr(response, 'content'):
                response_text = response.content
            else:
                response_text = str(response)
            
            # Parse JSON response
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
                print(f"JSON parsing failed for schema design: {e}")
                raise Exception(f"Schema design JSON parsing failed: {str(e)}")
            
        except Exception as e:
            print(f"Error designing schema for group {sheet_group['sheet_group_id']}: {e}")
            raise Exception(f"Schema design failed for group {sheet_group['sheet_group_id']}: {str(e)}")
    
    def design_foreign_keys(self, db_tables: List[Dict[str, Any]], file_tables: Dict[str, List[str]]) -> List[List[str]]:
        """Design foreign keys for tables within same files"""
        all_foreign_keys = []
        
        # Group tables by file
        for file_name, table_names in file_tables.items():
            if len(table_names) <= 1:
                continue  # No foreign keys needed for single table
            
            try:
                # Create DDLs for tables in this file
                file_ddls = []
                for table_name in table_names:
                    # Find the table schema
                    for table_data in db_tables:
                        if table_data.get("table_name") == table_name:
                            ddl = self._create_ddl_for_table(table_data)
                            file_ddls.append(ddl)
                            break
                
                if len(file_ddls) > 1:
                    foreign_keys = self._design_file_foreign_keys(file_ddls, file_name)
                    all_foreign_keys.extend(foreign_keys)
                    
            except Exception as e:
                print(f"Error designing foreign keys for file {file_name}: {e}")
                continue
        
        return all_foreign_keys
    
    def design_database_name(self, db_schema: Dict[str, Any], parsed_excel_data: Dict[str, Any]) -> str:
        """Design database name based on the schema and file data"""
        try:
            # Prepare context for DB name generation
            file_names = []
            for file_data in parsed_excel_data.get("files", []):
                file_names.append(file_data.get("file_name", ""))
            
            prompt = f"""
Based on the following database schema and source files, suggest a meaningful database name.

Source Files: {', '.join(file_names)}

Database Schema Summary:
- Number of tables: {len(db_schema.get('db_tables', []))}
- Table names: {[t.get('table_name', '') for t in db_schema.get('db_tables', [])]}

Please respond with a JSON object:
```json
{{
    "db_name": "meaningful_database_name"
}}
```

Requirements:
- Reflect the purpose/content of the database
- Be concise and clear
- Use appropriate language (same as source content)
- Avoid generic terms like "database", "db", etc.
"""
            
            response = self.model([{"role": "user", "content": prompt}])

            # Extract content from ChatMessage object
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
                return result.get("db_name", "excel_analysis_db")
                
            except json.JSONDecodeError:
                return "excel_analysis_db"
                
        except Exception as e:
            print(f"Error designing database name: {e}")
            return "excel_analysis_db"

    def design_table_names(self, db_tables: List[Dict[str, Any]]) -> List[List[str]]:
        """Redesign table names via LLM and enforce SQLite-safe unique names in-place."""
        if not db_tables:
            return []

        en_prompt = f"""
You are redesigning SQLite table names.

Input db_tables JSON:
```json
{json.dumps(db_tables, ensure_ascii=False, indent=2)}
```

Task:
1) Propose better table names only for tables that need modification.
2) Names must fit table content.
3) All names must be mutually exclusive (unique).
4) All names must be valid SQLite identifier names and contain no spaces.

Return JSON only in this shape:
```json
{{
  "renamed_tables": [
    ["table_id", "new_table_name"]
  ]
}}
```

Rules:
- Include only tables that need renaming.
- Any table names cannot contain spaces.
- Use letters, digits, and underscore only.
- Use the original language of the content for naming (e.g., if original table has Chinese content, use Chinese for the name; if English is dominant, use English; similar for other languages).
"""
        # chinese version
        prompt = """
你是一个数据库专家，负责重新设计SQLite表的名称。

输入的db_tables JSON格式如下：
```json
{{
  "db_tables": [
    {{
      "table_id": "table_1",
      "table_name": "原始表名",
      "columns_mapping": [ ... ]
    }},
    ...
  ]
}}
```

任务：
1) 仅为需要修改的表提出更好的名称建议。
2) 名称必须符合表的内容。
3) 所有名称必须相互独立（唯一）。
4) 所有名称必须是有效的SQLite标识符，并且不能包含空格。
返回的JSON格式必须严格遵守以下格式：
```json
{{
  "renamed_tables": [
    ["table_id", "new_table_name"]
  ]
}}
```

规则：
- 仅包含需要重命名的表。
- 任何表名都不能包含空格。
- 只能使用字母、数字和下划线。
- 使用内容的原始语言进行命名（例如，如果原始表包含中文内容，则使用中文命名；如果英文占主导，则使用英文；其他语言类似）。
- 本任务不需太多思考，直接根据表的内容和原始名称进行合理的命名建议即可。
"""
        renamed_pairs: List[List[str]] = []
        try:
            response = self.model([{"role": "user", "content": prompt}])
            if hasattr(response, "content"):
                response_text = response.content
            else:
                response_text = str(response)

            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                json_str = response_text[json_start:json_end].strip()
            else:
                json_str = response_text.strip()

            parsed = json.loads(json_str)
            maybe_pairs = parsed.get("renamed_tables", [])
            if isinstance(maybe_pairs, list):
                for item in maybe_pairs:
                    if isinstance(item, list) and len(item) == 2:
                        renamed_pairs.append([str(item[0]), str(item[1])])
        except Exception as e:
            print(f"Error redesigning table names by LLM, fallback to local sanitize: {e}")

        id_to_table = {str(t.get("table_id", "")): t for t in db_tables}

        def _sanitize_name(raw_name: str, fallback_id: str) -> str:
            name = (raw_name or "").strip().replace(" ", "_")
            name = re.sub(r"[^0-9A-Za-z_]", "_", name)
            name = re.sub(r"_+", "_", name).strip("_")
            if not name:
                name = f"table_{fallback_id}"
            if re.match(r"^[0-9]", name):
                name = f"t_{name}"
            return name.lower()

        # Apply only LLM-requested updates first (as requested: only modified tables are returned).
        for table_id, new_name in renamed_pairs:
            table = id_to_table.get(table_id)
            if not table:
                continue
            table["table_name"] = _sanitize_name(new_name, table_id)

        # Final pass: enforce valid SQLite identifiers + global uniqueness for all tables.
        used_names = set()
        for table in db_tables:
            table_id = str(table["table_id"])
            base_name = _sanitize_name(str(table.get("table_name", "")), table_id)

            candidate = base_name
            suffix = 1
            while candidate in used_names:
                suffix += 1
                candidate = f"{base_name}_{suffix}"

            table["table_name"] = candidate
            used_names.add(candidate)

        return renamed_pairs
    
    def _load_columns_mapping_template(self) -> str:
        """Load the columns mapping template"""
        template_path = "templates/template_columns_mapping.txt"
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def _create_ddl_for_table(self, table_data: Dict[str, Any]) -> str:
        """Create DDL statement for a table"""
        table_name = table_data.get("table_name", "unknown_table")
        columns = table_data.get("columns_mapping", [])
        
        ddl_parts = [f"CREATE TABLE {table_name} ("]
        
        for col in columns:
            col_name = col.get("column_name", "unknown_col")
            datatype = col.get("datatype", "TEXT")
            constraints = " ".join(col.get("col_constraints", []))
            
            col_def = f"    {col_name} {datatype}"
            if constraints:
                col_def += f" {constraints}"
            ddl_parts.append(col_def + ",")
        
        # Remove last comma and close
        if ddl_parts[-1].endswith(","):
            ddl_parts[-1] = ddl_parts[-1][:-1]
        ddl_parts.append(");")
        
        return "\n".join(ddl_parts)
    
    def _design_file_foreign_keys(self, ddls: List[str], file_name: str) -> List[List[str]]:
        """Design foreign keys for tables within a single file"""
        try:
            # Load foreign key template
            template = self._load_foreign_key_template()
            
            prompt = template.format(
                file_name=file_name,
                ddls="\n\n".join(ddls)
            )
            
            response = self.model([{"role": "user", "content": prompt}])

            # Extract content from ChatMessage object
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
                return result.get("foreign_keys", [])
                
            except json.JSONDecodeError:
                return []
                
        except Exception as e:
            print(f"Error designing foreign keys for file {file_name}: {e}")
            return []
    
    def _load_foreign_key_template(self) -> str:
        """Load foreign key template"""
        template_path = "templates/template_foreign_key.txt"
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            return """
# Instruction

Analyze database tables to identify foreign key relationships.

File: {file_name}

DDL Statements: 
```sql
{ddls}
```

Return foreign key relationships in JSON format:
```json
{{
    "foreign_keys": [
        ["table_name_1", "column_name_1", "table_name_2", "column_name_2"],
        ...
    ]
}}
```
"""


class InitialDesigner:
    """Main designer class for initial database schema design"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.sheet_analyzer = SheetGroupAnalyzer()
        self.schema_designer = DatabaseSchemaDesigner(model_name)
        self._lock = threading.Lock()  # For thread-safe operations
    
    def design_database_schema(self, parsed_excel_data: Dict[str, Any]) -> Dict[str, Any]:
        """Main method to design database schema from parsed Excel data"""
        print("Starting database schema design...")
        
        try:
            # Step 1: Find sheet groups
            sheet_groups = self.sheet_analyzer.find_sheet_groups(parsed_excel_data)
            print(f"Found {len(sheet_groups)} sheet groups")
            
            # Step 2: Enrich sheet names
            enriched_groups = self.schema_designer.enrich_sheet_names(sheet_groups)
            print("Enriched sheet names")
            
            # Step 3: Design schemas for each group concurrently
            db_tables = []
            table_id_counter = 1
            file_table_mapping = defaultdict(list)
            
            # Filter groups that need schema design
            design_groups = [group for group in enriched_groups 
                           if group["sheet_group_type"] != "not_to_db"]
            
            if not design_groups:
                print("No groups require database schema design")
                raise Exception("No valid sheet groups for schema design")
            
            # Process groups concurrently
            print(f"Processing {len(design_groups)} groups concurrently...")
            schema_results = self._design_schemas_concurrently(design_groups)

            # to ensure uniqueness of table name
            used_table_names = set()
            conclict_count = defaultdict(int)
            
            # Convert schema results to our format
            for group, schema_result in schema_results:
                if "tables" in schema_result and schema_result["tables"]:
                    for table_info in schema_result["tables"]:
                        file_name = table_info[0]
                        designed_table_name = table_info[4] if len(table_info) > 4 else table_info[2]
                        designed_table_name = designed_table_name.strip().replace(" ", "_") # ensure no spaces
                        if designed_table_name in used_table_names:
                            conclict_count[designed_table_name] += 1
                            designed_table_name += f"_{table_id_counter}"
                        used_table_names.add(designed_table_name)
                        
                        # Create table entry
                        table_entry = {
                            "table_id": f"table_{table_id_counter}",
                            "table_name": designed_table_name,
                            "columns_mapping": []
                        }
                        
                        # Add column mappings
                        column_id_counter = 1
                        for col_mapping in schema_result.get("columns_mapping", []):
                            column_path = self._build_full_column_path(
                                        file_name,
                                        table_info[1],  # original_sheet_name
                                        col_mapping.get("original_column_xlsx", [])
                                    )
                            column_entry = {
                                "column_id": f"col_{table_id_counter}_{column_id_counter}",
                                "column_name": col_mapping["column_name"].strip().replace(" ", "_"),
                                # original_column_xlsx: a list of column entries
                                # col_path: can be a path to a column, i.e. the last item is a inntermost column in the original excel file
                                #           can be a path to a sheet, i.e. the last item is the sheet name, this is when two sheet are merged into one table and need a distinguishing column
                                # transform_for_DB: how they will be formatted when creating DB, can be
                                #                    - "ORIGINAL": will directly use original content in the raw excel
                                #                    - "FIXED": will be a value according to the source, this is when two columns merged into one column OR two sheets merged into one table
                                #                   - "COMPLEX": will be a sentence describing how the value should be given the source, served as instruction when creating DB sqlite file (exclude this because too complicated)
                                "original_column_xlsx": [ 
                                    {
                                        "col_path": column_path,
                                        "transform_for_DB": "ORIGINAL" # will directly use original content in the raw excel
                                    }
                                ],
                                "datatype": col_mapping.get("datatype", "TEXT"),
                                "col_constraints": col_mapping.get("col_constraints", [])
                            }
                            table_entry["columns_mapping"].append(column_entry)
                            column_id_counter += 1
                        
                        db_tables.append(table_entry)
                        file_table_mapping[file_name].append(designed_table_name)
                        table_id_counter += 1
            
            # Redesign table_name of has conflict tables
            if conclict_count:
                print(f"Table name conflicts detected for: {dict(conclict_count)}. Attempting redesign...")
                redesign_count = 0
                original_db_tables = copy.deepcopy(db_tables)
                while conclict_count:
                    self.schema_designer.design_table_names(db_tables)
                    redesign_count += 1
                    conclict_count = len(db_tables) - len(set([t["table_name"] for t in db_tables]))

                    if redesign_count > 5:  # avoid infinite loop
                        #use orginal version
                        db_tables = original_db_tables
                        print("⚠️ Too many redesign attempts for table names, using original names to avoid infinite loop")
                        break

            # Step 4: Design foreign keys
            foreign_keys = self.schema_designer.design_foreign_keys(db_tables, dict(file_table_mapping))
            print(f"Designed {len(foreign_keys)} foreign key relationships")
            
            # Step 5: Design database name
            db_name = self.schema_designer.design_database_name({
                "db_tables": db_tables,
                "foreign_keys": foreign_keys
            }, parsed_excel_data)
            print(f"Database name: {db_name}")
            
            # Compile final result
            result = {
                "db_name": db_name,
                "db_tables": db_tables,
                "foreign_keys": foreign_keys
            }
            
            # Save intermediate results
            temp_result = {
                "sheet_groups": enriched_groups,
                "file_table_mapping": dict(file_table_mapping),
                "design_timestamp": datetime.now().isoformat()
            }
            
            return {"schema": result, "temp_data": temp_result}
            
        except Exception as e:
            print(f"Error in database schema design: {e}")
            raise Exception(f"Database schema design failed: {str(e)}")
    
    def _design_schemas_concurrently(self, design_groups: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Design schemas for multiple groups concurrently"""
        results = []
        
        with ThreadPoolExecutor(max_workers=min(len(design_groups), 4)) as executor:
            # Submit all schema design tasks
            future_to_group = {
                executor.submit(self._design_single_group_schema, group): group 
                for group in design_groups
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_group):
                group = future_to_group[future]
                try:
                    schema_result = future.result(timeout=300)  # 5 minute timeout per group
                    results.append((group, schema_result))
                    print(f"✅ Completed schema design for group: {group['sheet_group_id']}")
                except Exception as e:
                    print(f"❌ Failed schema design for group {group['sheet_group_id']}: {e}")
                    raise Exception(f"Schema design failed for group {group['sheet_group_id']}: {str(e)}")
        
        return results
    
    def _design_single_group_schema(self, group: Dict[str, Any]) -> Dict[str, Any]:
        """Design schema for a single group - thread-safe wrapper"""
        try:
            print(f"🔄 Processing group: {group['sheet_group_id']}")
            return self.schema_designer.design_sheet_group_schema(group)
        except Exception as e:
            print(f"Error in group {group['sheet_group_id']}: {e}")
            raise
    
    def _build_full_column_path(self, file_name: str, sheet_name: str, original_path: List[str]) -> List[str]:
        """Build full column path including file and sheet name"""
        full_path = [file_name, sheet_name]
        if isinstance(original_path, list):
            full_path.extend(original_path)
        elif isinstance(original_path, str):
            full_path.append(original_path)
        return full_path
    
    def get_timestamp(self) -> str:
        """Get current timestamp"""
        return datetime.now().isoformat()

