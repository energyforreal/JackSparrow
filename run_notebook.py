#!/usr/bin/env python3
"""Execute notebook with error handling and reporting."""

import subprocess
import sys
import json
import os
from pathlib import Path

notebook_path = r'd:\ATTRAL\Projects\Trading Agent 2\notebooks\JackSparrow_v38_reworked(1).ipynb'
output_path = r'd:\ATTRAL\Projects\Trading Agent 2\notebooks\JackSparrow_v38_output.ipynb'

print("=" * 80)
print("EXECUTING NOTEBOOK: JackSparrow_v38_reworked(1).ipynb")
print("=" * 80)

try:
    # Execute notebook using nbconvert
    result = subprocess.run(
        [
            sys.executable, '-m', 'nbconvert',
            '--to', 'notebook',
            '--execute',
            '--output', output_path,
            '--ExecutePreprocessor.timeout=3600',
            notebook_path
        ],
        cwd=str(Path(notebook_path).parent),
        capture_output=True,
        text=True,
        timeout=3700
    )
    
    print("EXECUTION OUTPUT:")
    print(result.stdout)
    
    if result.stderr:
        print("\nSTDERR:")
        print(result.stderr)
    
    print(f"\nReturn Code: {result.returncode}")
    
    if result.returncode == 0:
        print("\n✅ NOTEBOOK EXECUTED SUCCESSFULLY")
    else:
        print("\n❌ NOTEBOOK EXECUTION FAILED")
        print("Checking output notebook for error details...")
        
        # Parse output notebook to find error cells
        if os.path.exists(output_path):
            with open(output_path, 'r', encoding='utf-8') as f:
                nb = json.load(f)
            
            print("\nERROR DETAILS:")
            for i, cell in enumerate(nb.get('cells', [])):
                outputs = cell.get('outputs', [])
                for output in outputs:
                    if output.get('output_type') == 'error':
                        print(f"\nCell {i}: {cell.get('source', '')[:100]}")
                        print(f"Error: {output.get('ename')} - {output.get('evalue')}")
                        print(f"Traceback:\n{''.join(output.get('traceback', []))}")
    
except subprocess.TimeoutExpired:
    print("❌ NOTEBOOK EXECUTION TIMED OUT (exceeded 60 minutes)")
except Exception as e:
    print(f"❌ ERROR RUNNING NOTEBOOK: {e}")
    import traceback
    traceback.print_exc()
