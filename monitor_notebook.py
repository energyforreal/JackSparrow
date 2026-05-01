#!/usr/bin/env python3
"""Monitor notebook execution with live progress updates."""

import json
import time
import os
from pathlib import Path

output_path = r'd:\ATTRAL\Projects\Trading Agent 2\notebooks\JackSparrow_v38_output.ipynb'

print("Monitoring notebook execution...\n")
print("Output will be saved to:", output_path)
print()

last_size = 0
check_interval = 5  # seconds

try:
    while True:
        if os.path.exists(output_path):
            current_size = os.path.getsize(output_path)
            if current_size != last_size:
                try:
                    with open(output_path, 'r', encoding='utf-8') as f:
                        nb = json.load(f)
                    
                    cell_count = len(nb.get('cells', []))
                    executed_count = 0
                    error_count = 0
                    
                    for cell in nb.get('cells', []):
                        if cell.get('execution_count') is not None:
                            executed_count += 1
                        
                        for output in cell.get('outputs', []):
                            if output.get('output_type') == 'error':
                                error_count += 1
                    
                    print(f"[{time.strftime('%H:%M:%S')}] Cells executed: {executed_count}/{cell_count} | Errors: {error_count} | File size: {current_size} bytes")
                    last_size = current_size
                    
                    # Show any error details
                    if error_count > 0:
                        for i, cell in enumerate(nb.get('cells', [])):
                            for output in cell.get('outputs', []):
                                if output.get('output_type') == 'error':
                                    print(f"\n  ⚠️  Error in cell {i}:")
                                    print(f"     {output.get('ename')}: {output.get('evalue')}")
                except json.JSONDecodeError:
                    print(f"[{time.strftime('%H:%M:%S')}] Output file still being written...")
        
        time.sleep(check_interval)

except KeyboardInterrupt:
    print("\n\nMonitoring stopped.")
