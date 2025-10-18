"""
CLI wrapper utility for dockertree MCP server.

This module provides a wrapper for invoking dockertree CLI commands
with JSON output for MCP server integration.
"""

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


class DockertreeCLIWrapper:
    """Wrapper for dockertree CLI commands with JSON output."""
    
    def __init__(self, config):
        """Initialize CLI wrapper."""
        self.config = config
        self.dockertree_path = self._find_dockertree_executable()
    
    def _find_dockertree_executable(self) -> str:
        """Find the dockertree executable."""
        # Try to find dockertree in PATH
        import shutil
        dockertree_path = shutil.which("dockertree")
        if dockertree_path:
            return dockertree_path
        
        # Fallback to python -m dockertree
        return "python"
    
    async def run_command(self, args: List[str]) -> Dict[str, Any]:
        """Run a dockertree command and return JSON result."""
        try:
            # Build command
            if self.dockertree_path == "python":
                cmd = ["python", "-m", "dockertree"] + args
            else:
                cmd = [self.dockertree_path] + args
            
            # Run command
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.working_directory
            )
            
            stdout, stderr = await process.communicate()
            
            # Parse JSON output
            if process.returncode == 0:
                try:
                    result = json.loads(stdout.decode())
                    return result
                except json.JSONDecodeError:
                    # If JSON parsing fails, return the raw output
                    return {
                        "success": True,
                        "message": stdout.decode(),
                        "raw_output": stdout.decode()
                    }
            else:
                # Command failed
                error_msg = stderr.decode() if stderr else stdout.decode()
                return {
                    "success": False,
                    "error": error_msg,
                    "return_code": process.returncode
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to execute command: {str(e)}"
            }
    
    async def run_command_sync(self, args: List[str]) -> Dict[str, Any]:
        """Run a dockertree command synchronously (for compatibility)."""
        try:
            # Build command
            if self.dockertree_path == "python":
                cmd = ["python", "-m", "dockertree"] + args
            else:
                cmd = [self.dockertree_path] + args
            
            # Run command synchronously
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.config.working_directory
            )
            
            # Parse JSON output
            if result.returncode == 0:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {
                        "success": True,
                        "message": result.stdout,
                        "raw_output": result.stdout
                    }
            else:
                return {
                    "success": False,
                    "error": result.stderr,
                    "return_code": result.returncode
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to execute command: {str(e)}"
            }


