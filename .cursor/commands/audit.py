#!/usr/bin/env python3
"""
Cursor command handler for /audit command.

This script is executed when the /audit command is used in Cursor.
It delegates to the audit script with proper error handling.
"""

import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import NoReturn


def setup_output_buffering() -> None:
    """Configure stdout and stderr for unbuffered, UTF-8 output."""
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(line_buffering=True, encoding='utf-8')
        except (AttributeError, ValueError):
            pass
    if hasattr(sys.stderr, 'reconfigure'):
        try:
            sys.stderr.reconfigure(line_buffering=True, encoding='utf-8')
        except (AttributeError, ValueError):
            pass


def get_project_root() -> Path:
    """Get the project root directory (parent of .cursor directory).
    
    Returns:
        Path to project root directory.
        
    Raises:
        RuntimeError: If project root cannot be determined.
    """
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent
    
    if not project_root.exists():
        raise RuntimeError(f"Project root does not exist: {project_root}")
    
    return project_root


def get_audit_script(project_root: Path) -> Path:
    """Get the path to the audit script based on platform.
    
    Args:
        project_root: Path to project root directory.
        
    Returns:
        Path to the audit script.
        
    Raises:
        FileNotFoundError: If script does not exist for current platform.
    """
    scripts_dir = project_root / "tools" / "commands"
    
    if platform.system() == "Windows":
        script_path = scripts_dir / "audit.ps1"
    else:
        script_path = scripts_dir / "audit.sh"
    
    if not script_path.exists():
        raise FileNotFoundError(
            f"Audit script not found at {script_path}. "
            "Please ensure the project structure is correct."
        )
    
    return script_path


def execute_audit_script(script_path: Path, project_root: Path) -> int:
    """Execute the audit script using subprocess.
    
    Args:
        script_path: Path to the audit script.
        project_root: Path to project root directory.
        
    Returns:
        Exit code from the script execution.
        
    Raises:
        subprocess.CalledProcessError: If script execution fails.
        OSError: If script cannot be executed.
    """
    # Change to project root
    original_cwd = os.getcwd()
    os.chdir(str(project_root))
    
    try:
        if platform.system() == "Windows":
            # Execute PowerShell script
            cmd = [
                "powershell.exe",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path)
            ]
        else:
            # Execute bash script
            cmd = ["bash", str(script_path)]
        
        # Execute script with real-time output
        process = subprocess.run(
            cmd,
            cwd=str(project_root),
            check=False,  # Don't raise on non-zero exit
            stdout=None,  # Inherit stdout
            stderr=None,  # Inherit stderr
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        return process.returncode
        
    finally:
        os.chdir(original_cwd)


def main() -> NoReturn:
    """Main entry point for the audit command handler.
    
    This function:
    1. Sets up output buffering
    2. Validates project structure
    3. Executes the audit script
    
    Exits with:
        0: Success
        1: Error during execution
    """
    try:
        # Setup output buffering
        setup_output_buffering()
        
        # Get project root
        project_root = get_project_root()
        
        # Get audit script path
        audit_script = get_audit_script(project_root)
        
        # Execute the audit script
        exit_code = execute_audit_script(audit_script, project_root)
        
        sys.exit(exit_code)
        
    except FileNotFoundError as e:
        print(f"\n\nERROR: {e}", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)
    except RuntimeError as e:
        print(f"\n\nERROR: {e}", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"\n\nERROR: Audit script failed with exit code {e.returncode}", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(e.returncode)
    except OSError as e:
        print(f"\n\nERROR: Failed to execute audit script: {e}", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nAudit interrupted by user.", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(130)
    except Exception as e:
        print(f"\n\nERROR: Unexpected error during audit: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()

