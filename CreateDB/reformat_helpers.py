from typing import Any, Optional, List, Dict, Callable
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from smolagents import OpenAIModel
import os
from dotenv import load_dotenv

load_dotenv()

class DataTransformer:
    """Helper class for data transformation and validation"""
    
    def __init__(self):
        self.model = OpenAIModel(
            model_id=os.getenv("MODEL_NAME", "Qwen3-32B-AWQ"),
            api_base=os.getenv("BASE_URL"),
            api_key=os.getenv("API_KEY"),
            temperature=0.1,
            max_tokens=16384,
            top_p=0.9,
        )
        self._date_formatters = {}  # Cache for date formatting functions
    
    def clean_column_name(self, name: str) -> str:
        """Clean column names by removing leading/trailing spaces and ** markers"""
        return name # skip cleaning
        if not name:
            return ""
        return name.strip().strip('*')
    
    def transform_value(self, value: Any, transform_for_DB: str) -> Any:
        """Transform value according to transform_for_DB specification"""
        if not transform_for_DB or transform_for_DB == "ORIGINAL":
            return value
        
        if transform_for_DB.startswith("FIXED"):
            # Extract fixed value after "FIXED:"
            fixed_value = transform_for_DB[6:].strip()
            return fixed_value
        
        if transform_for_DB == "COMPLEX":
            # Handle complex transformations using LLM
            return self._transform_complex(value, transform_for_DB)
        
        # Default: return original value
        return value
    
    def convert_to_datatype(self, value: Any, datatype: str, sheet_key: str = None, column_name: str = None) -> Any:
        """Convert value to specified datatype"""
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return None
        
        try:
            if datatype == "INTEGER":
                return self._convert_to_integer(value)
            elif datatype == "REAL":
                return self._convert_to_real(value)
            elif datatype == "TEXT":
                return self._convert_to_text(value)
            elif datatype == "DATE":
                return self._convert_to_date(value, sheet_key, column_name)
            else:
                # Default to TEXT
                print(f"Unknown datatype '{datatype}', defaulting to TEXT")
                return self._convert_to_text(value)
        except Exception as e:
            raise ValueError(f"Cannot convert value '{value}' to {datatype}: {str(e)}")
    
    def verify_constraints(self, value: Any, constraints: List[str]) -> bool:
        """Verify if value meets the specified constraints"""
        if not constraints:
            return True
        
        for constraint in constraints:
            if not self._check_constraint(value, constraint):
                return False
        
        return True
    
    def get_date_formatter(self, sheet_key: str, column_name: str, sample_data: List[Any]) -> Optional[Callable]:
        """Get or create date formatter for a specific sheet and column"""
        formatter_key = f"{sheet_key}_{column_name}"
        
        if formatter_key in self._date_formatters:
            return self._date_formatters[formatter_key]
        
        # Create new formatter using LLM
        formatter = self._create_date_formatter(sample_data)
        if not formatter:
            print(f"Failed to create date formatter for {formatter_key}, using default parsing")
        print(f"Created date formatter for {formatter_key}")
        self._date_formatters[formatter_key] = formatter
        return formatter
    
    def _convert_to_integer(self, value: Any) -> int:
        """Convert value to integer"""
        if isinstance(value, (int, float)):
            return int(value)
        
        if isinstance(value, str):
            # Remove common formatting
            cleaned = re.sub(r'[,\s]', '', value.strip())
            # Handle percentage
            if cleaned.endswith('%'):
                cleaned = cleaned[:-1]
                return int(float(cleaned))
            return int(float(cleaned))
        
        raise ValueError(f"Cannot convert {type(value)} to integer")
    
    def _convert_to_real(self, value: Any) -> float:
        """Convert value to real number"""
        if isinstance(value, (int, float)):
            return float(value)
        
        if isinstance(value, str):
            # Remove common formatting
            cleaned = re.sub(r'[,\s]', '', value.strip())
            # Handle percentage
            if cleaned.endswith('%'):
                cleaned = cleaned[:-1]
                return float(cleaned) / 100.0
            return float(cleaned)
        
        raise ValueError(f"Cannot convert {type(value)} to real")
    
    def _convert_to_text(self, value: Any) -> str:
        """Convert value to text"""
        if value is None:
            return ""
        return str(value)
    
    def _convert_to_date(self, value: Any, sheet_key: str = None, column_name: str = None) -> str:
        """Convert value to date string (database-compatible format)"""
        if isinstance(value, (datetime, date)):
            return value.strftime('%Y-%m-%d')
        
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            
            # Try to use cached date formatter first
            if sheet_key and column_name:
                formatter_key = f"{sheet_key}_{column_name}"
                if formatter_key in self._date_formatters:
                    formatter = self._date_formatters[formatter_key]
                    if formatter:
                        try:
                            result = formatter(value)
                            if result:
                                return result
                        except Exception as e:
                            print(f"Error using cached date formatter for {formatter_key}: {e}")
            
            # Fallback: try common date formats, preserving original precision
            date_formats = [
                ('%Y-%m-%d', '%Y-%m-%d'),           # Full date -> Full date
                ('%Y-%m', '%Y-%m-01'),              # Year-Month -> Year-Month-01
                ('%Y/%m/%d', '%Y-%m-%d'),           # Full date with slashes
                ('%Y/%m', '%Y-%m-01'),              # Year-Month with slashes
                ('%d/%m/%Y', '%Y-%m-%d'),           # DD/MM/YYYY
                ('%m/%d/%Y', '%Y-%m-%d'),           # MM/DD/YYYY
                ('%Y年%m月%d日', '%Y-%m-%d'),        # Chinese format
                ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S'),  # With time
                ('%Y/%m/%d %H:%M:%S', '%Y-%m-%d %H:%M:%S'),  # With time
            ]
            
            for input_fmt, output_fmt in date_formats:
                try:
                    dt = datetime.strptime(value, input_fmt)
                    return dt.strftime(output_fmt)
                except ValueError:
                    continue
            
            raise ValueError(f"Cannot parse date: {value}")
        
        raise ValueError(f"Cannot convert {type(value)} to date")
    
    def _check_constraint(self, value: Any, constraint: str) -> bool:
        """Check if value meets a specific constraint"""
        constraint = constraint.strip().upper()
        
        if constraint == "NOT NULL":
            return value is not None and str(value).strip() != ""
        
        if constraint == "UNIQUE":
            # Note: Uniqueness should be checked at higher level
            return True
        
        if constraint == "PRIMARY KEY":
            # Primary key implies NOT NULL and UNIQUE
            return value is not None and str(value).strip() != ""
        
        # Add more constraint checks as needed
        return True
    
    def _create_date_formatter(self, sample_data: List[Any]) -> Optional[Callable]:
        """Create date formatter function using LLM"""
        try:
            # Filter non-empty samples
            valid_samples = [str(item) for item in sample_data 
                        if item is not None and str(item).strip()]
            
            if not valid_samples:
                return None
            
            print(f"Creating date formatter with samples: {valid_samples[:3]} ...")
            
            # Step 1: Define SQLite-supported and regex-handleable formats
            supported_formats = [
                # SQLite native date formats
                (r'^\d{4}-\d{2}-\d{2}$', '%Y-%m-%d', lambda x: x),  # 2024-03-15
                (r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', '%Y-%m-%d %H:%M:%S', lambda x: x),  # 2024-03-15 14:30:00
                (r'^\d{4}-\d{2}$', '%Y-%m', lambda x: x + '-01'),  # 2024-03 -> 2024-03-01
                (r'^\d{4}$', '%Y', lambda x: x + '-01-01'),  # 2024 -> 2024-01-01
                
                # Common regex-handleable formats
                (r'^\d{4}/\d{2}/\d{2}$', '%Y/%m/%d', lambda x: datetime.strptime(x, '%Y/%m/%d').strftime('%Y-%m-%d')),  # 2024/03/15
                (r'^\d{4}/\d{1,2}$', '%Y/%m', lambda x: datetime.strptime(x + '/01', '%Y/%m/%d').strftime('%Y-%m-%d')),  # 2024/3
                (r'^\d{2}/\d{2}/\d{4}$', '%d/%m/%Y', lambda x: datetime.strptime(x, '%d/%m/%Y').strftime('%Y-%m-%d')),  # 15/03/2024
                (r'^\d{1,2}/\d{1,2}/\d{4}$', '%m/%d/%Y', lambda x: datetime.strptime(x, '%m/%d/%Y').strftime('%Y-%m-%d')),  # 3/15/2024
            ]
            
            # Step 2: Categorize all valid samples by format
            format_matches = {}
            unmatched_samples = []
            
            for sample in valid_samples:
                matched = False
                for i, (pattern, strp_format, converter) in enumerate(supported_formats):
                    if re.match(pattern, sample):
                        if i not in format_matches:
                            format_matches[i] = []
                        format_matches[i].append(sample)
                        matched = True
                        break
                
                if not matched:
                    unmatched_samples.append(sample)
            
            # Step 3: Check if all samples belong to ONE supported format
            if len(format_matches) == 1 and len(unmatched_samples) == 0:
                # All samples match exactly one supported format
                format_idx = list(format_matches.keys())[0]
                pattern, strp_format, converter = supported_formats[format_idx]
                
                print(f"All samples match supported format {format_idx}: {pattern}")
                
                # Create simple formatter function
                def _format_date(content):
                    content = str(content).strip()
                    if not content:
                        return None
                    
                    if re.match(pattern, content):
                        try:
                            return converter(content)
                        except Exception:
                            return None
                    return None
                
                return _format_date
            
            # Step 4: If not all samples match one format, use LLM
            print(f"Samples match multiple formats or have unmatched samples. Format matches: {len(format_matches)}, Unmatched: {len(unmatched_samples)}")
            
            # Prepare samples for LLM - one example from each matched format + unmatched ones
            llm_samples = []
            for format_idx, samples in format_matches.items():
                llm_samples.append(samples[0])  # Take first sample from each format
            
            llm_samples.extend(unmatched_samples)
            
            # If we have less than 10 samples, randomly add more
            import random
            while len(llm_samples) < 10 and len(valid_samples) > len(llm_samples):
                remaining = [s for s in valid_samples if s not in llm_samples]
                if remaining:
                    llm_samples.append(random.choice(remaining))
                else:
                    break
            
            # Use LLM with more complex example
            print(f"Using LLM to create date formatter with samples: {llm_samples[:10]} ...")
            prompt = f"""
Analyze the following date samples and create a Python function to parse them into a database-compatible date format.

Date samples:
{llm_samples[:10]}

Important guidelines:
1. Preserve the level of detail present in the original data
2. If samples only have YYYY-MM format, output should be YYYY-MM-DD with day=01
3. If samples have full dates, preserve the full date
4. If samples have time information, preserve it
5. Only handle the format pattern you see in these specific samples
6. Convert to database-compatible date string for SQLite
7. You do not need too much reasoning steps, just focus on handling the formats in the samples above

Return a Python function definition that converts the sample format to a database-compatible date string:

```python
def _format_date(content):
    from datetime import datetime
    import re
    
    content = str(content).strip()
    if not content:
        return None
    
    # Based on the samples above, add your specific parsing logic here
    # Example: if samples are mixed Chinese format like "25年12月", "25年1月", "2024年03月":
    # # Handle 2-digit year format like "25年12月"
    # if re.match(r'^\\d{{2}}年\\d{{1,2}}月$', content):
    #     try:
    #         year = int(content.split('年')[0])
    #         month = int(content.split('年')[1].replace('月', ''))
    #         # Assume 2000s for 2-digit years
    #         full_year = 2000 + year if year < 50 else 1900 + year
    #         return f"{{full_year:04d}}-{{month:02d}}-01"
    #     except ValueError:
    #         pass
    # 
    # # Handle 4-digit year format like "2024年03月"
    # if re.match(r'^\\d{{4}}年\\d{{1,2}}月$', content):
    #     try:
    #         year = int(content.split('年')[0])
    #         month = int(content.split('年')[1].replace('月', ''))
    #         return f"{{year:04d}}-{{month:02d}}-01"
    #     except ValueError:
    #         pass
    
    # Add your logic based on the actual samples above
    # Return None if format doesn't match the samples
    return None
```

Only return the complete function definition, no explanation.
"""
            
            response = self.model([{"role": "user", "content": prompt}])
            
            # Extract content from response
            if hasattr(response, 'content'):
                content = response.content
            else:
                content = str(response)

            # print(f"LLM response for date formatter:\n{content}")
            
            # Extract function definition
            if "def _format_date" in content:
                # Execute the function definition
                local_vars = {}
                exec(content, {"datetime": datetime, "re": re}, local_vars)
                return local_vars.get("_format_date")
            
            return None
            
        except Exception as e:
            print(f"Error creating date formatter: {e}")
            return None
    
    def _transform_complex(self, value: Any, transform_spec: str) -> Any:
        """Handle complex transformations using LLM"""
        try:
            prompt = f"""
Transform the following value according to the specification:

Value: {value}
Transform specification: {transform_spec}

Return only the transformed value, no explanation.
"""
            
            response = self.model([{"role": "user", "content": prompt}])
            
            if hasattr(response, 'content'):
                return response.content.strip()
            else:
                return str(response).strip()
                
        except Exception as e:
            print(f"Error in complex transformation: {e}")
            return value

def create_data_transformer() -> DataTransformer:
    """Factory function to create DataTransformer instance"""
    return DataTransformer()