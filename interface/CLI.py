import json
import os
import re
import subprocess
import time

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from LLM_Handling import (
    BANNER,
    add_model,
    create_llm_client,
    get_llm_settings,
    list_models,
    read_model_config,
    switch_model,
)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

SHOW_TOOL_DEBUG = os.environ.get("FTCCODE_SHOW_TOOL_DEBUG", "").lower() in {"1", "true", "yes"}

from prompt_toolkit import Application
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea


def gradient_text(text, start_color=(30, 144, 255), end_color=(46, 204, 113)):
    text_obj = Text()
    visible_chars = [char for char in text if char != "\n"]
    visible_index = -1

    for char in text:
        if char == "\n":
            text_obj.append("\n")
            continue

        visible_index += 1
        if len(visible_chars) == 1:
            ratio = 0
        else:
            ratio = visible_index / (len(visible_chars) - 1)

        r = int(start_color[0] + (end_color[0] - start_color[0]) * ratio)
        g = int(start_color[1] + (end_color[1] - start_color[1]) * ratio)
        b = int(start_color[2] + (end_color[2] - start_color[2]) * ratio)
        color = f"#{r:02x}{g:02x}{b:02x}"
        text_obj.append(char, style=f"bold {color}")

    return text_obj


def build_box_style(mode):
    color = "#1E90FF" if mode == "build" else "#FFA500"
    return Style.from_dict(
        {
            "frame.border": f"fg:{color}",
            "frame.label": f"fg:{color} bold",
            "text-area": "fg:#ffffff",
            "cursor": "reverse",
            "tag": "fg:#FFD700 bold",
        }
    )


def format_prompt_tags(text):
    styled = Text()
    last = 0
    for match in re.finditer(r'/([A-Za-z_][A-Za-z0-9_]*)', text):
        if match.start() > last:
            styled.append(text[last:match.start()])
        styled.append(match.group(1), style="bold goldenrod1")
        last = match.end()
    styled.append(text[last:])
    return styled

SUPPORTED_FUNCTIONS = [
    {
        "name": "read",
        "description": "Read a file from the local repository.",
        "parameters": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string", "description": "Path of the file to read."}
            },
            "required": ["filePath"],
        },
    },
    {
        "name": "write",
        "description": "Write content to a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["filePath", "content"],
        },
    },
    {
        "name": "edit",
        "description": "Edit a file by replacing exact text.",
        "parameters": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string"},
                "find": {"type": "string"},
                "replace": {"type": "string"},
            },
            "required": ["filePath", "find", "replace"],
        },
    },
    {
        "name": "commands",
        "description": "Execute a shell command.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "listFiles",
        "description": "List files in a directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "recursive": {"type": "boolean"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "writeFile",
        "description": "Write a new file or replace an existing file.",
        "parameters": {
            "type": "object",
            "properties": {
                "filePath": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["filePath", "content"],
        },
    },
    {
        "name": "subagent",
        "description": "Run a subagent for specialized tasks.",
        "parameters": {
            "type": "object",
            "properties": {
                "agentType": {"type": "string"},
                "task": {"type": "string"},
                "context": {"type": "object"},
            },
            "required": ["agentType", "task"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web using Chromium and return a concise summary of results.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query to run in the browser."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory",
        "description": "Store valuable information in memory for future reference.",
        "parameters": {
            "type": "object",
            "properties": {
                "memory": {"type": "string", "description": "Information to store in memory."},
            },
            "required": ["memory"],
        },

    }
]


def boxed_input(title=None):
    kb = KeyBindings()
    mode = "build"

    text_area = TextArea(
        multiline=False,
        wrap_lines=False,
        prompt="> ",
        style="class:text-area",
    )

    def toggle_mode(event):
        nonlocal mode
        mode = "plan" if mode == "build" else "build"
        event.app.style = build_box_style(mode)
        event.app.invalidate()

    @kb.add("enter")
    def _submit(event):
        mode_tag = "/build-mode" if mode == "build" else "/plan-mode"
        event.app.exit(result=f"{mode_tag} {text_area.text}".strip())

    @kb.add("c-s")
    def _toggle_mode(event):
        toggle_mode(event)

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event):
        event.app.exit(result=None)

    frame = Frame(text_area, title=title)
    layout = Layout(HSplit([frame]), focused_element=text_area.control)

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=build_box_style(mode),
        full_screen=False,
        mouse_support=False,
        cursor=CursorShape.BLINKING_BLOCK,
    )

    return app.run()


def parse_tool_calls(text):
    tool_pattern = r'(\w+)\s*\(\s*([^)]*)\s*\)'
    matches = re.finditer(tool_pattern, text)

    tools = []
    for match in matches:
        tool_name = match.group(1)
        if tool_name in ['read', 'write', 'edit', 'commands', 'listFiles', 'writeFile', 'subagent', 'web_search', 'memory']:
            tools.append(tool_name)

    return tools


def display_tool_progress(console, tool_name):
    messages = {
        'read': ('Reading file...', 'white'),
        'listFiles': ('Listing files...', 'white'),
        'write': ('Building...', 'white'),
        'writeFile': ('Building...', 'white'),
        'edit': ('Refactoring...', 'white'),
        'commands': ('Executing...', 'yellow'),
        'subagent': ('Delegating to specialist...', 'cyan'),
        'memory': ('Storing in memory...', 'white'),
    }

    if tool_name in messages:
        msg, color = messages[tool_name]
        console.print(f'[{color}]{msg}[/{color}]')


def load_system_prompt(filepath="Agents.md"):
    # Merge Agents.md (or provided filepath) with a local memories file when available.
    parts = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            parts.append(f.read())
    except FileNotFoundError:
        print(f"Warning: {filepath} not found.")

    # Prefer lowercase 'memories.md' but accept 'Memories.md' too.
    memories_candidates = ["memories.md", "Memories.md"]
    for mem in memories_candidates:
        try:
            if os.path.isfile(mem):
                with open(mem, "r", encoding="utf-8") as f:
                    parts.append("\n\n# Memories\n\n")
                    parts.append(f.read())
                break
        except Exception as e:
            print(f"Warning: failed to read {mem}: {e}")

    if parts:
        return "\n\n".join(parts)

    # Fallback default prompt
    print(f"Warning: neither {filepath} nor memories.md found. Using default system prompt.")
    return (
        "You are a helpful assistant for code development for First Tech "
        "Challenge (FTC) robotics teams. You are an expert in Java coding "
        "and provide optimal solutions to any and all problems"
    )


def extract_text_content(response_text):
    cleaned = re.sub(r'\w+\s*\(\s*[^)]*\s*\)', '', response_text)
    cleaned = cleaned.strip()
    return cleaned if cleaned else None


def get_tool_calls_from_response(response):
    tool_calls = []
    for choice in getattr(response, "choices", []):
        msg = getattr(choice, "message", None)
        if not msg:
            continue
        function_call = getattr(msg, "function_call", None)
        if function_call:
            tool_calls.append({
                "name": function_call.name,
                "arguments": function_call.arguments,
            })
        tool_loop = getattr(msg, "tool_calls", None)
        if tool_loop:
            for call in tool_loop:
                tool_calls.append(call)
    return tool_calls


def execute_tool_call(tool_name, arguments):
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as e:
            return f"Invalid tool arguments: {e}"

    if tool_name == "read":
        file_path = arguments.get("filePath")
        if not file_path:
            return "Missing filePath for read()"
        if not os.path.isfile(file_path):
            return f"File not found: {file_path}"
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
        
    if tool_name == "memory":
        memory = arguments.get("memory")
        if not memory:
            return "Missing memory for memory()"
        else:
        # Store the memory in Memories.md 
          with open("Memories.md", "a", encoding="utf-8") as f:
                f.write(f"{memory}\n")
        return f"Stored in memory: {memory}"

    if tool_name in ["write", "writeFile"]:
        file_path = arguments.get("filePath")
        content = arguments.get("content", "")
        if not file_path:
            return "Missing filePath for write()"
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote file: {file_path}"

    if tool_name == "edit":
        file_path = arguments.get("filePath")
        find = arguments.get("find", "")
        replace = arguments.get("replace", "")
        if not file_path:
            return "Missing filePath for edit()"
        if not os.path.isfile(file_path):
            return f"File not found: {file_path}"
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
        if find not in text:
            return f"Pattern not found in {file_path}."
        new_text = text.replace(find, replace, 1)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_text)
        return f"Edited file: {file_path}"

    if tool_name == "commands":
        command = arguments.get("command", "")
        if not command:
            return "Missing command for commands()"
        result = subprocess.run(
            command,
            shell=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        output = result.stdout.strip() or result.stderr.strip()
        if not output:
            output = f"Command completed with exit code {result.returncode}."
        return output

    if tool_name == "listFiles":
        path = arguments.get("path", ".")
        recursive = arguments.get("recursive", False)
        if not os.path.exists(path):
            return f"Path not found: {path}"
        if recursive:
            items = []
            for root, dirs, files in os.walk(path):
                for name in dirs + files:
                    items.append(os.path.relpath(os.path.join(root, name), path))
            return "\n".join(sorted(items))
        return "\n".join(sorted(os.listdir(path)))

    if tool_name == "web_search":
        query = arguments.get("query", "")
        if not query:
            return "Missing query for web_search()"
        if sync_playwright is None:
            return "Web search is unavailable because Playwright is not installed."
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(f"https://www.google.com/search?q={query}", wait_until="domcontentloaded", timeout=120000)
                page.wait_for_timeout(3000)
                snippets = []
                for element in page.locator("div.g").all()[:4]:
                    try:
                        title = element.locator("h3").first.inner_text()
                    except Exception:
                        title = ""
                    try:
                        text = element.locator(".VwiC3b, .IsZvec").first.inner_text()
                    except Exception:
                        text = ""
                    if title or text:
                        snippets.append(f"{title}\n{text}".strip())
                browser.close()
                if snippets:
                    return "\n\n".join(snippets[:4])
                return page.locator("body").inner_text()[:4000]
        except Exception as e:
            return f"Web search failed: {e}"

    if tool_name == "subagent":
        return "Subagent execution is not supported in this CLI."

    return f"Unknown tool: {tool_name}"


def append_function_message(conversation_history, name, arguments):
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments)
    conversation_history.append(
        {
            "role": "assistant",
            "content": "",
            "function_call": {"name": name, "arguments": arguments},
        }
    )


def completion_token_count(response, fallback_text=""):
    usage = getattr(response, "usage", None)
    for attr in ("completion_tokens", "output_tokens"):
        value = getattr(usage, attr, None) if usage else None
        if isinstance(value, int) and value > 0:
            return value

    if isinstance(usage, dict):
        for key in ("completion_tokens", "output_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and value > 0:
                return value

    words = re.findall(r"\S+", fallback_text or "")
    return max(1, int(len(words) * 1.35)) if words else 0


def print_response_stats(console, response, elapsed_seconds, assistant_reply):
    tokens = completion_token_count(response, assistant_reply)
    if tokens:
        tps = tokens / max(elapsed_seconds, 0.001)
        console.print(f"[dim]Stats: {tokens} output tokens in {elapsed_seconds:.2f}s | {tps:.1f} TPS[/dim]")
    else:
        console.print(f"[dim]Stats: {elapsed_seconds:.2f}s | TPS unavailable[/dim]")


def thinking_summary():
    return (
        "Hidden chain-of-thought is not exposed. Summary: I used the current prompt, "
        "conversation context, available tool results, and active model settings to produce the answer."
    )


def strip_mode_prefix(text):
    for prefix in ("/build-mode ", "/plan-mode "):
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text.strip()


def print_model_list(console):
    models = list_models()
    active = get_llm_settings().id
    console.print("\n[bold cyan]Models[/bold cyan]")
    for model in models:
        marker = "*" if model["id"] == active else " "
        console.print(
            f"{marker} [bold]{model['id']}[/bold] "
            f"[dim]({model['provider']} / {model['model']}, temp {model['temperature']})[/dim]"
        )
    console.print("[dim]Use /model <id> to switch, or /model add to add another model.[/dim]\n")


def handle_cli_command(user_input, console):
    command = strip_mode_prefix(user_input)
    if not command.startswith("/"):
        return None

    lowered = command.lower()
    if lowered in {"/help", "/?"}:
        console.print(
            "\n[bold cyan]Commands[/bold cyan]\n"
            "[dim]/models[/dim] - list configured models\n"
            "[dim]/model <id>[/dim] - switch active model\n"
            "[dim]/model add[/dim] - add a new model\n"
            "[dim]/thinking[/dim] - show a short reasoning summary note\n"
        )
        return "handled"

    if lowered == "/models":
        print_model_list(console)
        return "handled"

    if lowered == "/thinking":
        console.print(f"\n[bold yellow]Thinking Summary[/bold yellow]\n{thinking_summary()}\n")
        return "handled"

    if lowered == "/model add":
        model_config = read_model_config()
        settings = add_model(model_config, make_active=True)
        console.print(f"[green]Active model changed to {settings.id} ({settings.label} / {settings.model}).[/green]")
        return settings

    if lowered.startswith("/model "):
        model_id = command.split(" ", 1)[1].strip()
        try:
            settings = switch_model(model_id)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            print_model_list(console)
            return "handled"
        console.print(f"[green]Active model changed to {settings.id} ({settings.label} / {settings.model}).[/green]")
        return settings

    console.print("[yellow]Unknown command. Type /help for CLI commands.[/yellow]")
    return "handled"


def main():
    console = Console()
    console.clear()

    settings = get_llm_settings()
    client = create_llm_client(settings)
    banner = (
       "██████╗  ██████╗  █████╗      ██████╗  ██████╗ ██████╗ ███████╗\n"
       "██╔══██╗██╔════╝ ██╔══██╗    ██╔════╝ ██╔═══██╗██╔══██╗██╔════╝\n"
       "██████╔╝██║      ███████║    ██║      ██║   ██║██║  ██║█████╗  \n"
       "██╔══██╗██║      ██╔══██║    ██║      ██║   ██║██║  ██║██╔══╝  \n"
       "██║  ██║╚██████╗ ██║  ██║    ╚██████╗ ╚██████╔╝██████╔╝███████╗\n"
       "╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝     ╚═════╝  ╚═════╝ ╚═════╝ ╚══════╝\n"
        "\n [RCA CODING AGENT CLI V1.0.0]"
    )
    console.print(gradient_text(BANNER))
    console.print(f"Provider: [cyan]{settings.label}[/cyan]")
    console.print(f"Model: [cyan]{settings.id}[/cyan] [dim]({settings.model})[/dim]")
    console.print("Type [bold yellow]'exit'[/bold yellow], [bold yellow]'quit'[/bold yellow], [bold yellow]'/help'[/bold yellow], or press Esc/Ctrl+C to stop.\n")

    system_prompt = load_system_prompt()
    conversation_history = [{"role": "system", "content": system_prompt}]

    while True:
        try:
            user_input = boxed_input(title=None)

            if user_input is None:
                console.print("\n[bold blue]Goodbye![/bold blue]")
                break

            clean_input = strip_mode_prefix(user_input)

            if clean_input.lower() in ["exit", "quit"]:
                console.print("\n[bold blue]Goodbye![/bold blue]")
                break

            if not clean_input:
                continue

            command_result = handle_cli_command(user_input, console)
            if command_result is not None:
                if command_result != "handled":
                    settings = command_result
                    client = create_llm_client(settings)
                    console.print(f"[dim]Now using {settings.id} ({settings.model}).[/dim]\n")
                continue

            console.print("[bold cyan]You:[/bold cyan]", format_prompt_tags(user_input))
            conversation_history.append({"role": "user", "content": user_input})

            while True:
                with console.status(
                    "[white]Thinking...[/white]",
                    spinner="dots",
                    spinner_style="white",
                ):
                    started_at = time.perf_counter()
                    response = client.chat_completion(
                        messages=conversation_history,
                        functions=SUPPORTED_FUNCTIONS,
                    )
                    elapsed = time.perf_counter() - started_at
                choice = response.choices[0]
                assistant_message = getattr(choice, "message", None)
                function_call = getattr(assistant_message, "function_call", None)
                assistant_reply = getattr(assistant_message, "content", None) or ""

                if not function_call:
                    narrative = extract_text_content(assistant_reply)
                    if narrative:
                        console.print("\n[bold magenta]AI >[/bold magenta]")
                        console.print(Markdown(narrative))
                    elif assistant_reply:
                        console.print("\n[bold magenta]AI >[/bold magenta]")
                        console.print(Markdown(assistant_reply))
                    print_response_stats(console, response, elapsed, assistant_reply)
                    console.print("[dim]Thinking: hidden. Type /thinking for a short reasoning summary.[/dim]\n")
                    conversation_history.append({"role": "assistant", "content": assistant_reply})
                    break

                tool_name = function_call.name
                tool_arguments = function_call.arguments
                display_tool_progress(console, tool_name)
                if SHOW_TOOL_DEBUG:
                    console.print(f"[dim]{tool_name} arguments: {tool_arguments}[/dim]\n")

                tool_result = execute_tool_call(tool_name, tool_arguments)
                if SHOW_TOOL_DEBUG:
                    console.print(f"[green]{tool_result}[/green]\n")
                else:
                    console.print(f"[green]Done: {tool_name}[/green]\n")

                append_function_message(conversation_history, tool_name, tool_arguments)
                conversation_history.append(
                    {"role": "function", "name": tool_name, "content": tool_result}
                )

        except (KeyboardInterrupt, EOFError):
            console.print("\n[bold blue]Goodbye![/bold blue]")
            break
        except Exception as e:
            console.print(f"\n[bold red]API Error:[/bold red] {e}")


if __name__ == "__main__":
    main()
