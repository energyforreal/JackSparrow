#!/usr/bin/env python3
"""Direct execution with explicit file output."""
import sys
import os
from pathlib import Path

# Ensure unbuffered output
sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)

project_root = Path(__file__).parent
output_file = project_root / "direct_output.txt"

print(f"Starting execution...", file=sys.stderr, flush=True)
print(f"Python: {sys.executable}", file=sys.stderr, flush=True)
print(f"Project root: {project_root}", file=sys.stderr, flush=True)

with open(output_file, 'w', encoding='utf-8') as f:
    f.write("=== STARTUP OUTPUT ===\n")
    f.flush()
    
    # Change to project root
    os.chdir(str(project_root))
    
    # Import and run the script
    script_path = project_root / "tools" / "commands" / "start_parallel.py"
    f.write(f"Script path: {script_path}\n")
    f.write(f"Script exists: {script_path.exists()}\n")
    f.flush()
    
    if script_path.exists():
        # Read and execute
        with open(script_path, 'r', encoding='utf-8') as script_file:
            code = script_file.read()
        
        # Redirect stdout/stderr temporarily to capture output
        import io
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        
        try:
            # Create a custom writer that writes to both file and original stdout
            class TeeWriter:
                def __init__(self, file, original):
                    self.file = file
                    self.original = original
                
                def write(self, text):
                    self.file.write(text)
                    self.file.flush()
                    self.original.write(text)
                    self.original.flush()
                
                def flush(self):
                    self.file.flush()
                    self.original.flush()
            
            sys.stdout = TeeWriter(f, old_stdout)
            sys.stderr = TeeWriter(f, old_stderr)
            
            # Execute the script
            exec(code)
        except Exception as e:
            import traceback
            error_msg = f"Error: {e}\n{traceback.format_exc()}\n"
            f.write(error_msg)
            old_stderr.write(error_msg)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
    
    f.write("\n=== END ===\n")
    f.flush()

print(f"Output written to: {output_file}", file=sys.stderr, flush=True)
