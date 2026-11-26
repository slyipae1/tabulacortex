import pandas as pd
import json
import os
import sqlite3
import shutil
from typing import Dict, List, Any, Optional
from pathlib import Path
from collections import defaultdict
from .reformat_helpers import create_data_transformer
from SystemState import SystemState

class SQLiteCreator:
    """Create SQLite database from designed schema and Excel data"""
    
    def __init__(self):
        self.data_transformer = create_data_transformer()
        self.created_dbs_path = Path("./created_DBs")
        self.created_dbs_path.mkdir(exist_ok=True)
        self.systemstate = SystemState()
        self.current_schema = None  # Cache schema for column info lookup
    
    def create_database(self, schema_design: Dict[str, Any], parsed_excel_data: Dict[str, Any], 
                       uploaded_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Main method to create SQLite database"""
        
        # Cache schema for later use
        self.current_schema = schema_design
        
        # Step 0: Clean identifiers and exclude special sheets
        cleaned_schema, not_for_db_sheets, cleaned_parsed_data = self._clean_and_filter_data(schema_design, parsed_excel_data)
        
        # Step 1: Read all sheets into dataframes
        file_dataframes = self._read_sheets_to_dataframes(uploaded_files, cleaned_parsed_data)
        # print("Read sheets into dataframes:", list(file_dataframes.keys()))
        # for key, df in file_dataframes.items():
        #     print(f"Dataframe for {key}:")
        #     print(df)

        # Step 2: Prepare sheet columns data
        sheet_columns_data = self._prepare_sheet_columns_data(cleaned_parsed_data, file_dataframes)
        # print("Prepared sheet columns data for sheets:", json.dumps(sheet_columns_data, indent=2, ensure_ascii=False))

        # Step 3: Initialize database content structure
        database_content = self._initialize_database_content(cleaned_schema)
        # print("Initialized database content structure:", json.dumps(database_content, indent=2, ensure_ascii=False))
        
        # Step 4: Build column mapping structures
        sheet_column_dbcol, sheet_discol_dbcol = self._build_column_mappings(cleaned_schema, cleaned_parsed_data)
        # print("Built sheet to DB column mappings:", json.dumps(sheet_column_dbcol, indent=2, ensure_ascii=False))
        # print("Built distinguishing column mappings:", json.dumps(sheet_discol_dbcol, indent=2, ensure_ascii=False))

        # Step 5: Process data and populate database content
        processing_stats = self._process_sheet_data(
            sheet_columns_data, sheet_column_dbcol, sheet_discol_dbcol, 
            database_content, cleaned_parsed_data
        )
        # print("Processed sheet data and populated database content. Stats:", json.dumps(processing_stats, indent=2, ensure_ascii=False))
        # print("Final database content structure:", json.dumps({k: len(v) for k, v in database_content.items()}, indent=2, ensure_ascii=False))
        
        # Step 6: Create SQLite file and save raw files
        db_path, saved_files = self._create_sqlite_and_save_files(
            cleaned_schema, database_content, not_for_db_sheets, file_dataframes
        )
        
        return {
            "db_path": str(db_path),
            "db_name": cleaned_schema["schema"]["db_name"],
            "tables_created": len(cleaned_schema["schema"]["db_tables"]),
            "records_processed": processing_stats["total_records"],
            "records_failed": processing_stats["failed_records"],
            "warnings": processing_stats["warnings"],
            "raw_files_saved": saved_files,
            "status": "success"
        }
    
    def _clean_and_filter_data(self, schema_design: Dict[str, Any], 
                              parsed_excel_data: Dict[str, Any]) -> tuple:
        """Step 0: Clean identifiers and find not_for_db sheets"""
        
        # Clean schema column paths
        cleaned_schema = self._deep_clean_schema(schema_design)
        # print("Database name:", cleaned_schema["schema"]["db_name"])
        # print("Cleaned schema design:", json.dumps(cleaned_schema, indent=2, ensure_ascii=False))
        
        # Clean parsed Excel column names
        cleaned_parsed_data = self._clean_parsed_excel_names(parsed_excel_data)
        
        # Find not_for_db sheets
        not_for_db_sheets = []
        temp_data = schema_design.get("temp_data", {})
        sheet_groups = temp_data.get("sheet_groups", [])
        
        for group in sheet_groups:
            if group.get("sheet_group_type") == "not_to_db":
                not_for_db_sheets.extend(group.get("sheet_table_s", []))
        
        return cleaned_schema, not_for_db_sheets, cleaned_parsed_data
    
    
    def _deep_clean_schema(self, schema_design: Dict[str, Any]) -> Dict[str, Any]:
        """Deep clean schema design column paths"""
        cleaned = json.loads(json.dumps(schema_design))  # Deep copy
        
        for table in cleaned["schema"]["db_tables"]:
            for column in table["columns_mapping"]:
                for orig_col in column["original_column_xlsx"]:
                    if "col_path" in orig_col and len(orig_col["col_path"]) > 2:
                        # Clean column path elements (skip file_name and sheet_name)
                        orig_col["col_path"][2:] = [
                            self.data_transformer.clean_column_name(name) 
                            for name in orig_col["col_path"][2:]
                        ]
        
        return cleaned
    
    def _clean_parsed_excel_names(self, parsed_excel_data: Dict[str, Any]) -> Dict[str, Any]:
        """Clean parsed Excel data column names"""
        cleaned = json.loads(json.dumps(parsed_excel_data))  # Deep copy
        
        for file_data in cleaned.get("files", []):
            for sheet in file_data.get("sheets", []):
                if "columns" in sheet:
                    sheet["columns"] = self._clean_column_structure(sheet["columns"])
        
        return cleaned
    
    def _clean_column_structure(self, structure: Any) -> Any:
        """Recursively clean column structure"""
        if isinstance(structure, dict):
            cleaned = {}
            for key, value in structure.items():
                cleaned_key = self.data_transformer.clean_column_name(key)
                cleaned[cleaned_key] = self._clean_column_structure(value)
            return cleaned
        elif isinstance(structure, list):
            return [self._clean_column_structure(item) for item in structure]
        else:
            return structure
    
    def _read_sheets_to_dataframes(self, uploaded_files: List[Dict[str, Any]], 
                                  parsed_excel_data: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        """Step 1: Read all sheets into dataframes"""
        file_dataframes = {}
        
        # Create mapping from file names to file paths
        file_path_map = {file_info["name"]: file_info["path"] for file_info in uploaded_files}
        
        for file_data in parsed_excel_data.get("files", []):
            file_name = file_data.get("file_name", "")
            file_path = file_path_map.get(file_name)
            
            if not file_path or not os.path.exists(file_path):
                print(f"Warning: File {file_name} not found")
                continue
            
            try:
                if file_name.endswith('.csv'):
                    # For CSV files
                    df = pd.read_csv(file_path, encoding='utf-8')
                    file_dataframes[f"{file_name}__Sheet1"] = df
                else:
                    # For Excel files
                    excel_file = pd.ExcelFile(file_path)
                    for sheet_name in excel_file.sheet_names:
                        df = pd.read_excel(file_path, sheet_name=sheet_name)
                        file_dataframes[f"{file_name}__{sheet_name}"] = df
                        
            except Exception as e:
                print(f"Error reading file {file_name}: {e}")
        
        return file_dataframes
    
    def _prepare_sheet_columns_data(self, parsed_excel_data: Dict[str, Any], 
                                   file_dataframes: Dict[str, pd.DataFrame]) -> Dict[str, Dict]:
        """Step 2: Prepare sheet columns data structure"""
        sheet_columns_data = {}
        
        for file_data in parsed_excel_data.get("files", []):
            file_name = file_data.get("file_name", "")
            
            for sheet in file_data.get("sheets", []):
                sheet_name = sheet.get("sheet_name", "")
                sheet_key = f"{file_name}__{sheet_name}"
                
                if sheet_key not in file_dataframes:
                    continue
                
                df = file_dataframes[sheet_key]
                # Fix: Access the "structure" key to get actual columns
                columns_info = sheet.get("columns", {})
                columns_structure = columns_info.get("structure", {}) if "structure" in columns_info else columns_info
                data_row_indices = sheet.get("data_row_indices", [])
                column_idx = columns_info.get("column_idx", [])
                
                # Build nested column data
                sheet_columns_data[sheet_key] = self._build_nested_column_data(
                    df, columns_structure, data_row_indices, column_idx
                )
        
        return sheet_columns_data
    
    def _build_nested_column_data(self, df: pd.DataFrame, columns_structure: Dict, 
                                 data_row_indices: List[int], column_idx: List[int]) -> Dict:
        """Build nested column data structure from dataframe"""
        
        def extract_data_from_df(structure, col_offset=0):
            if isinstance(structure, dict):
                result = {"structure": {}}
                for key, value in structure.items():
                    if value is None:
                        # This is an innermost column - extract data
                        try:
                            col_data = []
                            if col_offset < len(df.columns):
                                for row_idx in data_row_indices:
                                    if row_idx < len(df):
                                        cell_value = df.iloc[row_idx, col_offset]
                                        # Handle NaN values
                                        if pd.isna(cell_value):
                                            col_data.append(None)
                                        else:
                                            col_data.append(cell_value)
                                    else:
                                        col_data.append(None)
                            result["structure"][key] = col_data
                            col_offset += 1
                        except Exception as e:
                            print(f"Error extracting data for column {key}: {e}")
                            result["structure"][key] = []
                            col_offset += 1
                    else:
                        # Nested structure
                        nested_result, col_offset = extract_data_from_df(value, col_offset)
                        result["structure"][key] = nested_result["structure"]
                        
                # Copy column_idx if it exists
                if hasattr(structure, 'get'):
                    result["column_idx"] = structure.get("column_idx", [])
                        
                return result, col_offset
            else:
                return structure, col_offset
        
        result, _ = extract_data_from_df(columns_structure)
        # Add column_idx at root level
        result["column_idx"] = column_idx
        return result
    
    def _initialize_database_content(self, cleaned_schema: Dict[str, Any]) -> Dict[str, List]:
        """Step 3: Initialize database content structure"""
        database_content = {}
        
        for table in cleaned_schema["schema"]["db_tables"]:
            table_name = table["table_name"]
            for column in table["columns_mapping"]:
                column_name = column["column_name"]
                database_content[f"{table_name}.{column_name}"] = []
        
        return database_content
    
    def _build_column_mappings(self, cleaned_schema: Dict[str, Any], 
                              parsed_excel_data: Dict[str, Any]) -> tuple:
        """Step 4: Build column mapping structures"""
        
        # Initialize structures
        sheet_column_dbcol = {}
        sheet_discol_dbcol = defaultdict(list)
        
        # Build base structure for each sheet
        for file_data in parsed_excel_data.get("files", []):
            file_name = file_data.get("file_name", "")
            for sheet in file_data.get("sheets", []):
                sheet_name = sheet.get("sheet_name", "")
                sheet_key = f"{file_name}__{sheet_name}"
                columns_info = sheet.get("columns", {})
                columns_structure = columns_info.get("structure", {}) if "structure" in columns_info else columns_info
                
                # Initialize with None values and copy other info
                base_structure = self._init_column_structure_with_none(columns_structure)
                sheet_column_dbcol[sheet_key] = {
                    "structure": base_structure,
                    "column_idx": columns_info.get("column_idx", [])
                }
        
        # Map database columns to sheet columns
        for table in cleaned_schema["schema"]["db_tables"]:
            table_name = table["table_name"]
            
            for column in table["columns_mapping"]:
                column_name = column["column_name"]
                db_column = f"{table_name}.{column_name}"
                
                for orig_col_info in column["original_column_xlsx"]:
                    col_path = orig_col_info["col_path"]
                    transform_for_DB = orig_col_info["transform_for_DB"]
                    
                    if len(col_path) == 2:
                        # This is a distinguishing column
                        file_name, sheet_name = col_path
                        sheet_key = f"{file_name}__{sheet_name}"
                        sheet_discol_dbcol[sheet_key].append({
                            "db_column": db_column,
                            "transform_for_DB": transform_for_DB
                        })
                    elif len(col_path) > 2:
                        # Regular column mapping
                        file_name, sheet_name = col_path[:2]
                        column_path = col_path[2:]
                        sheet_key = f"{file_name}__{sheet_name}"
                        
                        # Set the mapping in nested structure
                        if sheet_key in sheet_column_dbcol:
                            mapping = {
                                "db_column": db_column,
                                "transform_for_DB": transform_for_DB
                            }
                            self._set_nested_column_mapping(
                                sheet_column_dbcol[sheet_key]["structure"], 
                                column_path, 
                                mapping
                            )
        
        # Validation
        self._validate_column_mappings(sheet_column_dbcol, cleaned_schema)
        
        return sheet_column_dbcol, dict(sheet_discol_dbcol)
    
    def _init_column_structure_with_none(self, structure: Any) -> Any:
        """Initialize column structure with None values for innermost columns"""
        if isinstance(structure, dict):
            result = {}
            for key, value in structure.items():
                if value is None:
                    result[key] = None
                else:
                    result[key] = self._init_column_structure_with_none(value)
            return result
        return structure
    
    def _set_nested_column_mapping(self, structure: Dict, path: List[str], mapping: Dict):
        """Set mapping in nested column structure"""
        if len(path) == 1:
            # Last level
            if structure.get(path[0]) is not None:
                print(f"Warning: Overwriting existing mapping for column {path[0]}")
            structure[path[0]] = mapping
        else:
            # Navigate deeper
            if path[0] in structure and isinstance(structure[path[0]], dict):
                self._set_nested_column_mapping(structure[path[0]], path[1:], mapping)
    
    def _validate_column_mappings(self, sheet_column_dbcol: Dict, cleaned_schema: Dict[str, Any]):
        """Validate column mappings"""
        for sheet_key, column_info in sheet_column_dbcol.items():
            column_structure = column_info.get("structure", {})
            # Check that each innermost column maps to at most one DB column
            innermost_mappings = self._extract_innermost_mappings(column_structure)
            
            # Check that all DB tables are the same for each sheet
            db_tables = set()
            for mapping in innermost_mappings:
                if mapping and "db_column" in mapping:
                    db_table = mapping["db_column"].split(".")[0]
                    db_tables.add(db_table)
            
            if len(db_tables) > 1:
                print(f"Warning: Sheet {sheet_key} maps to multiple tables: {db_tables}")
    
    def _extract_innermost_mappings(self, structure: Any) -> List:
        """Extract all innermost column mappings from nested structure"""
        mappings = []
        if isinstance(structure, dict):
            for key, value in structure.items():
                if value is None or (isinstance(value, dict) and "db_column" in value):
                    mappings.append(value)
                elif isinstance(value, dict):
                    mappings.extend(self._extract_innermost_mappings(value))
        return mappings
    
    def _get_data_row_indices(self, sheet_key: str, parsed_excel_data: Dict[str, Any]) -> List[int]:
        """Get data row indices for a sheet"""
        file_name, sheet_name = sheet_key.split("__", 1)
        
        for file_data in parsed_excel_data.get("files", []):
            if file_data.get("file_name") == file_name:
                for sheet in file_data.get("sheets", []):
                    if sheet.get("sheet_name") == sheet_name:
                        return sheet.get("data_row_indices", [])
        
        return []
    
    def _prepare_date_formatters_for_sheet(self, sheet_key: str, sheet_columns_data: Dict, sheet_column_dbcol: Dict):
        """Pre-create date formatters for DATE columns in a sheet"""
        try:
            # Find all DATE columns in this sheet
            date_columns = []
            
            def find_date_columns(col_struct, data_struct, path=[]):
                if isinstance(col_struct, dict):
                    for key, value in col_struct.items():
                        if value is not None and isinstance(value, dict) and "db_column" in value:
                            db_column = value["db_column"]
                            datatype, _ = self._get_column_type_constraints(db_column)
                            if datatype == "DATE":
                                # Get sample data for this column
                                if key in data_struct and isinstance(data_struct[key], list):
                                    sample_data = [x for x in data_struct[key] if x is not None]
                                    if sample_data:
                                        date_columns.append((key, sample_data))
                        elif isinstance(value, dict) and key in data_struct:
                            find_date_columns(value, data_struct[key], path + [key])
            
            find_date_columns(
                sheet_column_dbcol[sheet_key]["structure"],
                sheet_columns_data[sheet_key]["structure"]
            )
            
            # Create formatters for each DATE column
            for column_name, sample_data in date_columns:
                self.data_transformer.get_date_formatter(sheet_key, column_name, sample_data)
                
        except Exception as e:
            print(f"Error preparing date formatters for {sheet_key}: {e}")
    
    def _process_sheet_data(self, sheet_columns_data: Dict, sheet_column_dbcol: Dict, 
                        sheet_discol_dbcol: Dict, database_content: Dict, 
                        parsed_excel_data: Dict[str, Any]) -> Dict[str, Any]:
        """Step 5: Process sheet data and populate database content"""
        
        stats = {
            "total_records": 0,
            "failed_records": 0,
            "warnings": []
        }
        
        for sheet_key in sheet_columns_data:
            if sheet_key not in sheet_column_dbcol:
                continue
            
            # Get data row indices for this sheet
            data_row_indices = self._get_data_row_indices(sheet_key, parsed_excel_data)
            
            # Pre-create date formatters for this sheet
            self._prepare_date_formatters_for_sheet(sheet_key, sheet_columns_data, sheet_column_dbcol)
            
            # Process each data row
            for row_idx in range(len(data_row_indices)):
                try:
                    stats["total_records"] += 1
                    
                    # First pass: validate all constraints
                    row_data = {}
                    no_violation = True
                    
                    # Process regular columns
                    column_mappings = self._extract_column_mappings_with_data(
                        sheet_column_dbcol[sheet_key]["structure"], 
                        sheet_columns_data[sheet_key]["structure"], 
                        row_idx,
                        sheet_key
                    )
                    
                    for db_column, raw_value, transform_for_DB, datatype, constraints, column_name in column_mappings:
                        try:
                            # Transform value
                            transformed_value = self.data_transformer.transform_value(raw_value, transform_for_DB)
                            
                            # Convert to datatype with sheet and column info
                            final_value = self.data_transformer.convert_to_datatype(
                                transformed_value, datatype, sheet_key, column_name)
                            
                            # Verify constraints
                            if not self.data_transformer.verify_constraints(final_value, constraints):
                                no_violation = False
                                stats["warnings"].append(f"Constraint violation for {db_column} in row {row_idx}")
                                break
                                
                            row_data[db_column] = final_value
                            
                        except Exception as e:
                            no_violation = False
                            stats["warnings"].append(f"Error processing {db_column} in row {row_idx}: {str(e)}")
                            break
                    
                    # Process distinguishing columns
                    if sheet_key in sheet_discol_dbcol:
                        for discol_info in sheet_discol_dbcol[sheet_key]:
                            db_column = discol_info["db_column"]
                            transform_for_DB = discol_info["transform_for_DB"]
                            
                            try:
                                # For distinguishing columns, we typically use fixed values
                                transformed_value = self.data_transformer.transform_value(None, transform_for_DB)
                                datatype, constraints = self._get_column_type_constraints(db_column)
                                final_value = self.data_transformer.convert_to_datatype(
                                    transformed_value, datatype, sheet_key, None)
                                
                                if not self.data_transformer.verify_constraints(final_value, constraints):
                                    no_violation = False
                                    break
                                    
                                row_data[db_column] = final_value
                                
                            except Exception as e:
                                no_violation = False
                                stats["warnings"].append(f"Error processing distinguishing column {db_column}: {str(e)}")
                                break
                    
                    # Second pass: add data if no violations
                    if no_violation:
                        for db_column, value in row_data.items():
                            database_content[db_column].append(value)
                    else:
                        stats["failed_records"] += 1
                        
                except Exception as e:
                    stats["failed_records"] += 1
                    stats["warnings"].append(f"Error processing row {row_idx} in {sheet_key}: {str(e)}")
        
        return stats
    
    def _extract_column_mappings_with_data(self, column_structure: Dict, data_structure: Dict, 
                                      row_idx: int, sheet_key: str) -> List[tuple]:
        """Extract column mappings with data values"""
        mappings = []
        
        def extract_recursive(col_struct, data_struct, path=[]):
            if isinstance(col_struct, dict):
                for key, value in col_struct.items():
                    if value is not None and isinstance(value, dict) and "db_column" in value:
                        # This is a mapped column
                        db_column = value["db_column"]
                        transform_for_DB = value["transform_for_DB"]
                        
                        # Get raw data value
                        raw_value = None
                        if key in data_struct and isinstance(data_struct[key], list):
                            if row_idx < len(data_struct[key]):
                                raw_value = data_struct[key][row_idx]
                        
                        # Get datatype and constraints from schema
                        datatype, constraints = self._get_column_type_constraints(db_column)
                        
                        mappings.append((db_column, raw_value, transform_for_DB, datatype, constraints, key))
                        
                    elif isinstance(value, dict) and key in data_struct:
                        extract_recursive(value, data_struct[key], path + [key])
        
        extract_recursive(column_structure, data_structure)
        return mappings
    
    def _get_column_type_constraints(self, db_column: str) -> tuple:
        """Get datatype and constraints for a database column"""
        if not hasattr(self, '_column_info_cache'):
            self._column_info_cache = {}
            
            # Build cache from current schema
            if self.current_schema:
                for table in self.current_schema["schema"]["db_tables"]:
                    for column in table["columns_mapping"]:
                        col_key = f"{table['table_name']}.{column['column_name']}"
                        self._column_info_cache[col_key] = (
                            column.get("datatype", "TEXT"),
                            column.get("col_constraints", [])
                        )
        
        return self._column_info_cache.get(db_column, ("TEXT", []))
    
    def _create_sqlite_and_save_files(self, cleaned_schema: Dict[str, Any], 
                                     database_content: Dict[str, List], 
                                     not_for_db_sheets: List, 
                                     file_dataframes: Dict[str, pd.DataFrame]) -> tuple:
        """Step 6: Create SQLite file and save raw files"""
        
        schema = cleaned_schema["schema"]
        db_name = schema["db_name"]
        
        # Create database directory
        db_dir = self.created_dbs_path / db_name
        if os.path.exists(db_dir): # remove old one
            shutil.rmtree(db_dir)
        db_dir.mkdir(exist_ok=True)
        # create for_db and not_for_db subdirectories
        (db_dir / "for_db").mkdir(exist_ok=True)
        (db_dir / "not_for_db").mkdir(exist_ok=True)
        
        # Create SQLite database
        db_path = db_dir / f"{db_name}.sqlite"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        try:
            # Create tables
            for table in schema["db_tables"]:
                table_name = table["table_name"]
                columns_mapping = table["columns_mapping"]
                
                # Build CREATE TABLE statement
                column_defs = []
                for column in columns_mapping:
                    col_name = column["column_name"]
                    datatype = column.get("datatype", "TEXT")
                    constraints = column.get("col_constraints", [])
                    
                    col_def = f"{col_name} {datatype}"
                    if constraints:
                        col_def += " " + " ".join(constraints)
                    
                    column_defs.append(col_def)
                
                create_sql = f"CREATE TABLE {table_name} ({', '.join(column_defs)})"
                print(create_sql[:30])
                cursor.execute(create_sql)
                
                # Insert data
                column_names = [col["column_name"] for col in columns_mapping]
                if column_names and database_content:
                    # Prepare data rows
                    data_rows = []
                    max_rows = max(len(database_content.get(f"{table_name}.{col}", [])) 
                                  for col in column_names)
                    
                    for row_idx in range(max_rows):
                        row = []
                        for col in column_names:
                            col_data = database_content.get(f"{table_name}.{col}", [])
                            if row_idx < len(col_data):
                                row.append(col_data[row_idx])
                            else:
                                row.append(None)
                        data_rows.append(tuple(row))
                    
                    # Insert data
                    if data_rows:
                        placeholders = ", ".join(["?" for _ in column_names])
                        insert_sql = f"INSERT INTO {table_name} ({', '.join(column_names)}) VALUES ({placeholders})"
                        cursor.executemany(insert_sql, data_rows)
                        print(f"Inserted {len(data_rows)} rows into {table_name}")
            
            # Create foreign key relationships
            for fk in schema.get("foreign_keys", []):
                if len(fk) >= 4:
                    # Note: SQLite foreign key constraints need to be enabled
                    # and are best created during table creation
                    pass
            
            conn.commit()

            # debug: execute a SELECT * from each table and save to ./temp/{table_name}_debug.csv
            for table in schema["db_tables"]:
                table_name = table["table_name"]
                try:
                    df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
                    df.to_csv(db_dir / f"{table_name}.csv", index=False)
                except Exception as e:
                    print(f"Error querying table {table_name}: {e}")
            
            # Save not_for_db sheets as raw files
            saved_files = []
            for file_name, sheet_name, _, _ in not_for_db_sheets:
                sheet_key = f"{file_name}__{sheet_name}"
                if sheet_key in file_dataframes:
                    df = file_dataframes[sheet_key]
                    file_path = db_dir / f"not_for_db/{file_name}__{sheet_name}.csv"
                    df.to_csv(file_path, index=False)
                    saved_files.append(str(file_path))

            # save the for_db files as well for reference
            for sheet_key, df in file_dataframes.items():
                file_name, sheet_name = sheet_key.split("__", 1)
                file_path = db_dir / f"for_db/{file_name}__{sheet_name}.csv"
                df.to_csv(file_path, index=False)
                saved_files.append(str(file_path))

            # save the parsed result of excel for reference
            with open(db_dir / "parsed_result_of_excel.json", "w", encoding="utf-8") as f:
                json.dump(self.systemstate.parsed_result_of_excel, f, indent=2, ensure_ascii=False)

            # save the cleaned schema design and parsed excel data for reference
            with open(db_dir / "designedDBschema_mapExcel.json", "w", encoding="utf-8") as f:
                json.dump(self.systemstate.designedDBschema_mapExcel, f, indent=2, ensure_ascii=False)
            
            return db_path, saved_files
            
        finally:
            conn.close()