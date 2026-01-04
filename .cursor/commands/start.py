#!/usr/bin/env python3
"""
Cursor command handler for /start command.

This script is executed when the /start command is used in Cursor.
It delegates to the main startup script with proper error handling.
"""

import importlib.util
import os
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
    project_root = script_path.parent.parent.parent

    if not project_root.exists():
        raise RuntimeError(f"Project root does not exist: {project_root}")

    return project_root


def validate_startup_script(script_path: Path) -> None:
    """Validate that the startup script exists and is readable.
    
    Args:
        script_path: Path to the startup script.
        
    Raises:
        FileNotFoundError: If script does not exist.
        PermissionError: If script is not readable.
    """
    if not script_path.exists():
        raise FileNotFoundError(
            f"Startup script not found at {script_path}. "
            "Please ensure the project structure is correct."
        )
    
    if not os.access(script_path, os.R_OK):
        raise PermissionError(
            f"Startup script is not readable: {script_path}"
        )


def load_and_execute_module(script_path: Path, project_root: Path) -> None:
    """Load the startup script as a module and execute its main function.
    
    Args:
        script_path: Path to the startup script.
        project_root: Path to project root directory.
        
    Raises:
        ImportError: If module cannot be loaded.
        AttributeError: If module does not have a main function.
        RuntimeError: If main function execution fails.
    """
    # Add script directory to Python path for imports
    script_dir = script_path.parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    
    # Change to project root for proper working directory
    original_cwd = os.getcwd()
    try:
        os.chdir(str(project_root))
        
        # Load module using importlib
        module_name = script_path.stem
        spec = importlib.util.spec_from_file_location(module_name, str(script_path))
        
        if spec is None:
            raise ImportError(f"Could not create spec for {script_path}")
        
        if spec.loader is None:
            raise ImportError(f"Could not get loader for {script_path}")
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        
        # Execute the module
        spec.loader.exec_module(module)
        
        # Call main function if it exists
        if not hasattr(module, "main"):
            raise AttributeError(
                f"Module {module_name} does not have a 'main' function. "
                "Please ensure the startup script defines a main() function."
            )
        
        # Execute main function
        module.main()
        
    finally:
        os.chdir(original_cwd)


def main() -> NoReturn:
    """Main entry point for the start command handler.
    
    This function:
    1. Sets up output buffering
    2. Validates project structure
    3. Loads and executes the startup script
    
    Exits with:
        0: Success
        1: Error during execution
        130: Keyboard interrupt (Ctrl+C)
    """
    try:
        # Setup output buffering
        setup_output_buffering()
        
        # Get project root
        project_root = get_project_root()
        
        # Change to project root
        os.chdir(str(project_root))
        
        # Path to main startup script
        start_script = project_root / "tools" / "commands" / "start_parallel.py"
        
        # Validate script exists
        validate_startup_script(start_script)
        
        # Load and execute the module
        load_and_execute_module(start_script, project_root)
        
        # If we get here, main() returned normally
        sys.exit(0)
        
    except KeyboardInterrupt:
        print("\n\nStartup interrupted by user.", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(130)
    except FileNotFoundError as e:
        print(f"\n\nERROR: {e}", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)
    except PermissionError as e:
        print(f"\n\nERROR: {e}", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)
    except ImportError as e:
        print(f"\n\nERROR: Failed to import startup script: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)
    except AttributeError as e:
        print(f"\n\nERROR: {e}", file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: Failed to execute startup script: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()
