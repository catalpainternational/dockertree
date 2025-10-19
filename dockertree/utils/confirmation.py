"""
User confirmation utilities for dockertree CLI.

This module provides functions for prompting user confirmation with default values.
"""

import sys
from typing import List

from .logging import log_info, log_warning


def confirm_deletion(branches: List[str], operation: str = "delete") -> bool:
    """Prompt user for confirmation when deleting multiple branches/worktrees.
    
    Args:
        branches: List of branch names that will be deleted
        operation: The operation being performed ("delete" or "remove")
        
    Returns:
        True if user confirms, False if user cancels
    """
    if not branches:
        return False
    
    count = len(branches)
    branch_list = ', '.join(sorted(branches))
    
    # Show what will be deleted
    log_info(f"Found {count} matching branch(es): {branch_list}")
    
    # Create operation-specific message
    if operation == "delete":
        message = f"Delete {count} branch(es) and their worktrees?"
    else:  # remove
        message = f"Remove {count} worktree(s) (keep branches)?"
    
    # Prompt for confirmation with default 'Y'
    try:
        response = input(f"{message} [Y/n]: ").strip().lower()
        
        # Handle empty response (Enter key) as 'yes'
        if not response:
            return True
        
        # Handle explicit responses
        if response in ['y', 'yes']:
            return True
        elif response in ['n', 'no']:
            return False
        else:
            log_warning("Invalid response. Please enter 'y' for yes or 'n' for no.")
            return confirm_deletion(branches, operation)  # Retry
            
    except KeyboardInterrupt:
        log_info("\nOperation cancelled by user")
        return False
    except EOFError:
        # Handle case where stdin is not available (e.g., in automated scripts)
        log_warning("Cannot prompt for confirmation (no stdin available). Use --force to skip confirmation.")
        return False


def confirm_batch_operation(branches: List[str], operation: str = "delete") -> bool:
    """Confirm a batch operation with appropriate messaging.
    
    Args:
        branches: List of branch names that will be processed
        operation: The operation being performed ("delete" or "remove")
        
    Returns:
        True if user confirms, False if user cancels
    """
    if len(branches) <= 1:
        return True  # No confirmation needed for single branch
    
    return confirm_deletion(branches, operation)


def confirm_use_existing_worktree(branch_name: str) -> bool:
    """Prompt user for confirmation when a worktree already exists.
    
    Args:
        branch_name: Name of the branch/worktree that already exists
        
    Returns:
        True if user confirms to use existing worktree, False if user wants to use different name
    """
    log_warning(f"Branch/worktree '{branch_name}' already exists.")
    
    # Prompt for confirmation with default 'Y'
    try:
        response = input(f"Use existing worktree? [Y/n]: ").strip().lower()
        
        # Handle empty response (Enter key) as 'yes'
        if not response:
            return True
        
        # Handle explicit responses
        if response in ['y', 'yes']:
            return True
        elif response in ['n', 'no']:
            return False
        else:
            log_warning("Invalid response. Please enter 'y' for yes or 'n' for no.")
            return confirm_use_existing_worktree(branch_name)  # Retry
            
    except KeyboardInterrupt:
        log_info("\nOperation cancelled by user")
        return False
    except EOFError:
        # Handle case where stdin is not available (e.g., in automated scripts)
        log_warning("Cannot prompt for confirmation (no stdin available). Use --force to skip confirmation.")
        return False
