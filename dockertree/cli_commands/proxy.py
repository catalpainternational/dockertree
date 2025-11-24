"""
Proxy-related Dockertree CLI commands.
"""

from __future__ import annotations

import click

from dockertree.cli.helpers import add_json_option, add_verbose_option, command_wrapper
from dockertree.commands.caddy import CaddyManager
from dockertree.exceptions import DockertreeCommandError
from dockertree.utils.json_output import JSONOutput
from dockertree.utils.logging import log_info, log_success


def register_commands(cli) -> None:
    """Register proxy management commands."""

    @cli.command("start-proxy")
    @click.option("--non-interactive", is_flag=True, default=False, help="Run non-interactively", hidden=True)
    @add_json_option
    @add_verbose_option
    @command_wrapper()
    def start_proxy(non_interactive: bool, json: bool):
        """Start the global Caddy proxy container."""
        log_info("Starting global Caddy proxy")
        caddy_manager = CaddyManager()
        success = caddy_manager.start_global_caddy()
        if not success:
            raise DockertreeCommandError("Failed to start global Caddy container")
        log_success("Global Caddy proxy started successfully")
        if json:
            return JSONOutput.success("Global Caddy proxy started successfully")

    @cli.command("stop-proxy")
    @click.option("--non-interactive", is_flag=True, default=False, help="Run non-interactively", hidden=True)
    @add_json_option
    @add_verbose_option
    @command_wrapper()
    def stop_proxy(non_interactive: bool, json: bool):
        """Stop the global Caddy proxy container."""
        log_info("Stopping global Caddy proxy")
        caddy_manager = CaddyManager()
        success = caddy_manager.stop_global_caddy()
        if not success:
            raise DockertreeCommandError("Failed to stop global Caddy container")
        log_success("Global Caddy proxy stopped successfully")
        if json:
            return JSONOutput.success("Global Caddy proxy stopped successfully")

    @cli.command("start")
    @add_verbose_option
    @command_wrapper()
    def start():
        """Start the global Caddy proxy container (alias)."""
        caddy_manager = CaddyManager()
        success = caddy_manager.start_global_caddy()
        if not success:
            raise DockertreeCommandError("Failed to start global Caddy container")
        log_success("Global Caddy proxy started successfully")

    @cli.command("stop")
    @add_verbose_option
    @command_wrapper()
    def stop():
        """Stop the global Caddy proxy container (alias)."""
        caddy_manager = CaddyManager()
        success = caddy_manager.stop_global_caddy()
        if not success:
            raise DockertreeCommandError("Failed to stop global Caddy container")
        log_success("Global Caddy proxy stopped successfully")


