from typing import Dict, Any, Optional
from smolagents import OpenAIModel, tool
import os
from dotenv import load_dotenv
import re
import json

load_dotenv()

class StepScheduler:
    """Agent responsible for determining workflow step transitions and actions"""
    
    def __init__(self, model_name: str = "Qwen3-32B-AWQ"):
        self.model = OpenAIModel(
            model_id=os.getenv("MODEL_NAME", model_name),
            api_base=os.getenv("BASE_URL"),
            api_key=os.getenv("API_KEY"),
            temperature=0,
            max_tokens=500,
            top_p=0.9,
        )
    
    def determine_action(self, user_message: str, current_step: str, system_state) -> Dict[str, Any]:
        """Determine what action to take based on user message and current step"""
        
        # Define step-specific keywords and patterns
        completion_keywords = ["finish", "complete", "done", "correct", "好的", "确认", "完成", "继续"]
        modification_keywords = ["modify", "change", "update", "fix", "correct", "修改", "更改", "调整"]
        question_keywords = ["what", "how", "why", "show", "explain", "什么", "怎么", "为什么", "显示", "解释"]
        back_keywords = ["back", "return", "previous", "go back", "返回", "回到", "上一步"]
        
        # Convert message to lowercase for analysis
        message_lower = user_message.lower()
        
        # Check for step completion signals
        if any(keyword in message_lower for keyword in completion_keywords):
            if current_step in ["1-2", "2-2"]:
                return {
                    "action": "move_to_next_step",
                    "reason": "User indicated completion of current step"
                }
        
        # Check for going back to previous steps
        if any(keyword in message_lower for keyword in back_keywords):
            target_step = self._determine_target_step(user_message, current_step)
            return {
                "action": "move_to_previous_step",
                "target_step": target_step,
                "reason": "User requested to return to previous step"
            }
        
        # Check for modification requests
        if any(keyword in message_lower for keyword in modification_keywords) or "mermaid" in message_lower:
            return {
                "action": "update_parsing" if current_step.startswith("1") else "update_schema",
                "reason": "User requested modifications"
            }
        
        # Check for Q&A requests
        if any(keyword in message_lower for keyword in question_keywords):
            return {
                "action": "open_qa",
                "reason": "User asked a question"
            }
        
        # Use LLM for more complex decision making
        return self._llm_decision(user_message, current_step, system_state)
    
    def _determine_target_step(self, user_message: str, current_step: str) -> Optional[str]:
        """Determine which step user wants to return to"""
        message_lower = user_message.lower()
        
        # Look for specific step mentions
        if "parsing" in message_lower or "parse" in message_lower or "解析" in message_lower:
            return "1-2"
        elif "schema" in message_lower or "design" in message_lower or "设计" in message_lower:
            return "2-2" if current_step == "3" else None
        
        # Default previous step logic
        if current_step == "2-1" or current_step == "2-2":
            return "1-2"
        elif current_step == "3":
            return "2-2"
        
        return None
    
    def _llm_decision(self, user_message: str, current_step: str, system_state) -> Dict[str, Any]:
        """Use LLM to make complex scheduling decisions"""
        
        # Prepare context
        context = self._prepare_context(current_step, system_state)
        
        prompt = f"""
You are a workflow scheduler for an Excel analysis platform. Based on the user's message and current context, determine what action to take.

Current Step: {current_step}
Step Description: {self._get_step_description(current_step)}

Context: {context}

User Message: "{user_message}"

Available Actions:
1. "update_parsing" - User wants to modify the Excel parsing results
2. "update_schema" - User wants to modify the DB schema design
3. "open_qa" - User has questions about the data or process
4. "move_to_next_step" - User is ready to proceed to the next step
5. "move_to_previous_step" - User wants to go back to a previous step
6. "clarification_needed" - User's intent is unclear

Respond with just the action name and a brief reason.
Format: ACTION_NAME: reason
"""

        try:
            response = self.model([{"role": "user", "content": prompt}])
            
            # Parse LLM response
            if ":" in response:
                action_part, reason = response.split(":", 1)
                action = action_part.strip().lower()
                
                # Validate action
                valid_actions = ["update_parsing", "update_schema", "open_qa", 
                               "move_to_next_step", "move_to_previous_step", "clarification_needed"]
                
                if action in valid_actions:
                    return {
                        "action": action,
                        "reason": reason.strip()
                    }
            
            # Fallback to clarification
            return {
                "action": "clarification_needed",
                "reason": "Could not determine user intent clearly"
            }
            
        except Exception as e:
            # Fallback decision based on current step
            if current_step.endswith("-2"):  # Discussion steps
                return {
                    "action": "open_qa",
                    "reason": f"Default action for discussion step (LLM error: {str(e)})"
                }
            else:
                return {
                    "action": "clarification_needed",
                    "reason": f"Unable to determine action due to error: {str(e)}"
                }
    
    def _prepare_context(self, current_step: str, system_state) -> str:
        """Prepare context string for LLM"""
        context_parts = []
        
        # Add file information
        if system_state.uploaded_files:
            context_parts.append(f"Files uploaded: {len(system_state.uploaded_files)}")
        
        # Add step-specific context
        if current_step.startswith("1"):
            if system_state.parsed_result_of_excel:
                context_parts.append("Excel parsing completed")
            context_parts.append(f"QA records: {len(system_state.free_QA_records.get('understand_excel', []))}")
        elif current_step.startswith("2"):
            if system_state.designedDBschema_mapExcel:
                context_parts.append("DB schema designed")
            context_parts.append(f"QA records: {len(system_state.free_QA_records.get('design_schema', []))}")

        # current conv_history
        formatted_history = json.dumps(system_state.conv_history[-15:], indent=2, ensure_ascii=False)  # last 15 messages

        return " | ".join(context_parts) + f" \n\nConversation History: {formatted_history}" if context_parts else "No specific context"

    def _get_step_description(self, step: str) -> str:
        """Get description for a workflow step"""
        descriptions = {
            "1-1": "System parsing Excel files",
            "1-2": "Discussing and refining Excel parsing results",
            "2-1": "System designing database schema",
            "2-2": "Discussing and refining database schema design",
            "3": "Creating SQLite database file"
        }
        return descriptions.get(step, "Unknown step")