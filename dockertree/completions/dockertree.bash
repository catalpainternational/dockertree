#!/bin/bash
# Bash completion script for dockertree CLI
# This script provides tab completion for dockertree commands, worktree names, and options

_dockertree_completion() {
    local cur prev words cword
    _init_completion || return
    
    # Main commands (including aliases)
    local commands="start-proxy stop-proxy start stop create up down delete remove remove-all delete-all list prune volumes setup help completion -D -r"
    
    # Commands that need worktree names
    local worktree_cmds="create up down delete remove"
    
    # Volume subcommands
    local volume_subcmds="list size backup restore clean"
    
    # Completion subcommands
    local completion_cmds="install uninstall status"
    
    # Shell options for completion install
    local shells="bash zsh"
    
    # Flags
    local flags="--force -d --detach --help -h"
    
    # Handle main command completion
    if [[ $cword -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
        return
    fi
    
    # Handle command-specific completion
    case "${words[1]}" in
        create)
            # For create, we can complete with existing git branches or suggest new names
            local git_branches=$(dockertree _completion git 2>/dev/null)
            COMPREPLY=( $(compgen -W "$git_branches" -- "$cur") )
            ;;
        up)
            # For 'up' command, complete with worktree names or flags
            if [[ "$cur" == -* ]]; then
                COMPREPLY=( $(compgen -W "-d --detach" -- "$cur") )
            else
                local worktrees=$(dockertree _completion worktrees 2>/dev/null)
                COMPREPLY=( $(compgen -W "$worktrees" -- "$cur") )
            fi
            ;;
        down|delete|remove|-D|-r)
            # For down/delete/remove (including aliases), complete with worktree names and flags
            if [[ "$cur" == -* ]]; then
                COMPREPLY=( $(compgen -W "--force" -- "$cur") )
            else
                local worktrees=$(dockertree _completion worktrees 2>/dev/null)
                COMPREPLY=( $(compgen -W "$worktrees" -- "$cur") )
            fi
            ;;
        volumes)
            # Handle volumes subcommands
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "$volume_subcmds" -- "$cur") )
            elif [[ $cword -eq 3 ]]; then
                # For backup, restore, clean - complete with worktree names
                case "${words[2]}" in
                    backup|restore|clean)
                        local worktrees=$(dockertree _completion worktrees 2>/dev/null)
                        COMPREPLY=( $(compgen -W "$worktrees" -- "$cur") )
                        ;;
                    *)
                        # For list, size - no additional completion needed
                        COMPREPLY=()
                        ;;
                esac
            else
                COMPREPLY=()
            fi
            ;;
        completion)
            # Handle completion subcommands
            if [[ $cword -eq 2 ]]; then
                COMPREPLY=( $(compgen -W "$completion_cmds" -- "$cur") )
            elif [[ $cword -eq 3 && "${words[2]}" == "install" ]]; then
                COMPREPLY=( $(compgen -W "$shells" -- "$cur") )
            else
                COMPREPLY=()
            fi
            ;;
        remove-all|delete-all)
            # For remove-all/delete-all, only complete with flags
            COMPREPLY=( $(compgen -W "--force" -- "$cur") )
            ;;
        setup)
            # For setup, complete with flags
            if [[ "$cur" == -* ]]; then
                COMPREPLY=( $(compgen -W "--project-name" -- "$cur") )
            else
                COMPREPLY=()
            fi
            ;;
        *)
            # For other commands, complete with flags
            COMPREPLY=( $(compgen -W "$flags" -- "$cur") )
            ;;
    esac
}

# Register the completion function
complete -F _dockertree_completion dockertree

# Also register for dockertree if it's used as an alias
complete -F _dockertree_completion dockertree
