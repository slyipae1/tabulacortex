from typing import Dict, List, Any, Optional
import threading
from datetime import datetime

class SystemState:
    """Singleton class to manage global system state"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(SystemState, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # Initialize state attributes
        self.reset_session()
        self._initialized = True
    
    def reset_session(self):
        """Reset the session state"""
        # File management
        self.uploaded_files: List[Dict[str, Any]] = []
        
        # Workflow state
        self.current_procedure_step: str = "initialization"  # "1-1", "1-2", "2-1", "2-2", "3"
        
        # Conversation history
        self.conv_history: List[Dict[str, Any]] = []
        
        # Step 1: Parse and Understand excel
        self.parsed_result_of_excel: Optional[Dict[str, Any]] = None
        self.Mermaid_code_excel: Optional[str] = None # won't be change once assigned

        # Step 2: Design DB schema and map with excel
        self.designedDBschema_mapExcel: Optional[Dict[str, Any]] = None
        self.allHistory_of_designedDBschema_mapExcel: List[Dict[str, Any]] = [] # to support "撤销" 
        self.cur_vis: Optional[Dict] = {
            "excel_info_vis": None,
            "mermaid_code": None,
            "ERschema_code": None,
            "schema_file_map_code": None,
            "mermaid_preview_markdown": None
        }
        self.merge_advice: Optional[Dict[str, Any]] = None
        
        # Free Q&A records for different steps
        self.free_QA_records: Dict[str, List[Dict[str, Any]]] = {
            "design_schema": []
        }
        
        # Session metadata
        self.session_id: str = self._generate_session_id()
        self.session_start_time: datetime = datetime.now()
        self.last_activity_time: datetime = datetime.now()

        #######################################################
        # NL2SQL/QA Analysis attributes
        self.nl2sql_session_state: Dict[str, Any] = {}
        self.nl2sql_messages: List[Dict[str, Any]] = []
        self.available_databases: List[str] = []
        self.selected_database: Optional[str] = None
        self.current_sql_agent = None
    
    def _generate_session_id(self) -> str:
        """Generate a unique session ID"""
        return f"session_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    