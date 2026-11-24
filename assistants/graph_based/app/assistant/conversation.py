"""Conversation loop for interactive chat with the assistant."""

from rich.console import Console
from rich.markup import escape

from app.assistant.assistant import Assistant

console = Console()


def run_conversation(assistant: Assistant) -> None:
    """Run an interactive chat loop using the provided assistant instance."""
    while True:
        console.print("[bold green]You:[/bold green]", end=" ")
        user_input = input()
        if user_input.lower() in ["salir", "exit"]:
            break

        response = assistant.send_message(user_input)
        safe_response = escape(response) if response else "(no response)"
        console.print(f"[bold blue]Senpai:[/bold blue] {safe_response}")


def run_single_turn(assistant: Assistant, user_input: str) -> str:
    """Run a single assistant turn and return the response."""
    response = assistant.send_message(user_input)
    return response or "(no response)"
