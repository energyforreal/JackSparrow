import json
import subprocess

# Read the notebook JSON
with open('notebooks/JackSparrow_Trading_Colab_v3.ipynb', 'r', encoding='utf-8') as f:
    content = f.read()

# The file got corrupted, restore from git
result = subprocess.run(['git', 'checkout', 'HEAD', 'notebooks/JackSparrow_Trading_Colab_v3.ipynb'], 
                       capture_output=True, text=True)
if result.returncode == 0:
    print("✅ Restored notebook from git")
else:
    print(f"Git restore failed with: {result.stderr}")
    # Try manual restoration using the  backup approach
    print("Will need manual restoration")
