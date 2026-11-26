from typing import Dict, List, Any, Optional
from smolagents import CodeAgent, OpenAIModel, tool
import os
import pandas as pd
import openpyxl
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

@tool
def read_excel_tool(file_path: str, sheet_name: Optional[str] = None, max_rows: int = 10) -> str:
    """
    Read Excel file and return sample data
    
    Args:
        file_path: Path to Excel file
        sheet_name: Specific sheet name (optional, if None reads all sheets)
        max_rows: Maximum number of rows to return
        
    Returns:
        String representation of the Excel data
    """
    try:
        if sheet_name:
            df = pd.read_excel(file_path, sheet_name=sheet_name, nrows=max_rows)
            return f"Sample data from {sheet_name}:\n{df.to_string()}"
        else:
            # Read all sheets
            xl_file = pd.ExcelFile(file_path)
            result = f"Sheets in {file_path}: {xl_file.sheet_names}\n\n"
            
            for sheet in xl_file.sheet_names:
                df = pd.read_excel(file_path, sheet_name=sheet, nrows=max_rows)
                result += f"\nSheet '{sheet}':\n{df.to_string()}\n"
            
            return result
    except Exception as e:
        return f"Error reading Excel file: {str(e)}"

@tool 
def read_csv_tool(file_path: str, max_rows: int = 10) -> str:
    """
    Read CSV file and return sample data
    
    Args:
        file_path: Path to CSV file
        max_rows: Maximum number of rows to return
        
    Returns:
        String representation of the CSV data
    """
    try:
        df = pd.read_csv(file_path, nrows=max_rows)
        return f"Sample data from {file_path}:\n{df.to_string()}"
    except Exception as e:
        return f"Error reading CSV file: {str(e)}"

@tool
def analyze_data_tool(file_path: str, analysis_type: str = "info") -> str:
    """
    Perform data analysis on file
    
    Args:
        file_path: Path to file
        analysis_type: Type of analysis (info, describe, columns)
        
    Returns:
        Analysis results as string
    """
    try:
        file_ext = Path(file_path).suffix.lower()
        
        if file_ext in ['.xlsx', '.xls']:
            # For Excel, analyze all sheets
            xl_file = pd.ExcelFile(file_path)
            result = ""
            
            for sheet_name in xl_file.sheet_names:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
                result += f"\n=== Sheet: {sheet_name} ===\n"
                
                if analysis_type == "info":
                    result += f"Shape: {df.shape}\n"
                    result += f"Columns: {list(df.columns)}\n"
                    result += f"Data types:\n{df.dtypes}\n"
                elif analysis_type == "describe":
                    result += f"Statistical summary:\n{df.describe()}\n"
                elif analysis_type == "columns":
                    result += f"Column details:\n"
                    for col in df.columns:
                        non_null = df[col].count()
                        total = len(df)
                        result += f"  {col}: {non_null}/{total} non-null values\n"
            
            return result
        
        elif file_ext == '.csv':
            df = pd.read_csv(file_path)
            
            if analysis_type == "info":
                return f"Shape: {df.shape}\nColumns: {list(df.columns)}\nData types:\n{df.dtypes}"
            elif analysis_type == "describe":
                return f"Statistical summary:\n{df.describe()}"
            elif analysis_type == "columns":
                result = "Column details:\n"
                for col in df.columns:
                    non_null = df[col].count()
                    total = len(df)
                    result += f"  {col}: {non_null}/{total} non-null values\n"
                return result
        
        return "Unsupported file format"
        
    except Exception as e:
        return f"Error analyzing file: {str(e)}"

class OpenQAHandler:
    """Agent for handling open-ended questions about the data and files"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.model = OpenAIModel(
            model_id=model_name,
            api_base=os.getenv("BASE_URL"),
            api_key=os.getenv("API_KEY"),
            temperature=0,
            max_tokens=8192,
            top_p=0.9,
        )
        
        # Initialize code agent with the corrected tools
        self.code_agent = CodeAgent(
            tools=[read_excel_tool, read_csv_tool, analyze_data_tool],
            model=self.model,
            additional_authorized_imports=["pandas", "openpyxl", "json", "os"],
            name="data_analyzer",
            description="Agent that can read and analyze Excel/CSV files to answer questions"
        )
    
    def answer_question(self, 
                       question: str, 
                       uploaded_files: List[Dict[str, Any]], 
                       parsed_data: Optional[Dict[str, Any]] = None) -> str:
        """Answer user question about the data"""
        
        try:
            # Prepare context for the agent
            context_info = self._prepare_context(uploaded_files, parsed_data)
            
            # Enhance question with context
            enhanced_question = f"""
Context: I have uploaded Excel/CSV files for analysis. Here's what I know:

{context_info}

User Question: {question}

Please help answer this question by analyzing the actual data files if needed. 
You can use the available tools to read files and examine their content.
"""
            
            # Use code agent to answer the question
            response = self.code_agent.run(enhanced_question)
            
            return self._format_response(response)
            
        except Exception as e:
            return f"I encountered an error while trying to answer your question: {str(e)}\n\nCould you please rephrase your question or be more specific about what you'd like to know?"
    
    def _prepare_context(self, 
                        uploaded_files: List[Dict[str, Any]], 
                        parsed_data: Optional[Dict[str, Any]]) -> str:
        """Prepare context information for the agent"""
        context_parts = []
        
        # Add uploaded files info
        if uploaded_files:
            context_parts.append("Uploaded Files:")
            for file_info in uploaded_files:
                file_name = file_info.get("name", "Unknown")
                file_path = file_info.get("path", "")
                size_mb = file_info.get("size", 0) / (1024 * 1024)
                
                context_parts.append(f"- {file_name} ({size_mb:.1f} MB) at {file_path}")
        
        # Add parsed data summary if available
        if parsed_data and "files" in parsed_data:
            context_parts.append("\nParsed Structure:")
            
            for file_data in parsed_data["files"]:
                file_name = file_data.get("file_name", "Unknown")
                context_parts.append(f"- File: {file_name}")
                
                for sheet in file_data.get("sheets", []):
                    sheet_name = sheet.get("sheet_name", "Unknown")
                    table_type = sheet.get("table_type", "")
                    data_rows = len(sheet.get("data_row_indices", []))
                    table_name = sheet.get("table_name", "")
                    
                    context_parts.append(f"  - Sheet: {sheet_name} ({table_type}, {data_rows} data rows)")
                    if table_name:
                        context_parts.append(f"    Table: {table_name}")
                    
                    # Add column info
                    columns = sheet.get("columns", {})
                    if isinstance(columns, dict) and "structure" in columns:
                        columns = columns["structure"]
                    
                    if isinstance(columns, dict) and columns:
                        col_names = list(columns.keys())[:5]  # Show first 5 columns
                        context_parts.append(f"    Columns: {', '.join(col_names)}")
                        if len(columns) > 5:
                            context_parts.append(f"    ... and {len(columns) - 5} more columns")
        
        return "\n".join(context_parts) if context_parts else "No context available"
    
    def _format_response(self, agent_response: str) -> str:
        """Format the agent response for better readability"""
        
        # If response is very long, truncate it
        if len(agent_response) > 2000:
            agent_response = agent_response[:1900] + "\n\n... (response truncated for readability)"
        
        # Clean up common formatting issues
        formatted_response = agent_response.strip()
        
        # Remove excessive newlines
        formatted_response = re.sub(r'\n{3,}', '\n\n', formatted_response)
        
        # Add helpful suffix for data-related questions
        if any(keyword in formatted_response.lower() for keyword in ['dataframe', 'excel', 'csv', 'columns', 'rows']):
            formatted_response += "\n\n💡 **Tip:** Feel free to ask follow-up questions about the data, such as specific column details, data patterns, or request to see different parts of the files."
        
        return formatted_response