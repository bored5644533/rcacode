import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from types import SimpleNamespace


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

PROVIDERINFO_PATH = os.path.join(BASE_DIR, "providerinfo.json")
LEGACY_PROVIDERINFO_PATH = os.path.join(BASE_DIR, "providerinfo.txt")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

    BANNER = (
          "██████╗  ██████╗  █████╗      ██████╗  ██████╗ ██████╗ ███████╗\n"
          "██╔══██╗██╔════╝ ██╔══██╗    ██╔════╝ ██╔═══██╗██╔══██╗██╔════╝\n"
          "██████╔╝██║      ███████║    ██║      ██║   ██║██║  ██║█████╗  \n"
          "██╔══██╗██║      ██╔══██║    ██║      ██║   ██║██║  ██║██╔══╝  \n"
          "██║  ██║╚██████╗ ██║  ██║    ╚██████╗ ╚██████╔╝██████╔╝███████╗\n"
          "╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝     ╚═════╝  ╚═════╝ ╚═════╝ ╚══════╝\n"
          "\n [RCA CODING AGENT CLI V1.0.0]"
          )
PROVIDERS = {
    "anthropic": {
        "label": "Anthropic",
        "env": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4-20250514",
        "base_url": "https://api.anthropic.com/v1/messages",
        "kind": "anthropic",
    },
    "openai": {
        "label": "OpenAI",
        "env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "base_url": None,
        "kind": "openai_compatible",
    },
    "deepseek": {
        "label": "DeepSeek",
        "env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "kind": "openai_compatible",
    },
    "kimi": {
        "label": "Kimi",
        "env": "KIMI_API_KEY",
        "default_model": "kimi-k2-0711-preview",
        "base_url": "https://api.moonshot.ai/v1",
        "kind": "openai_compatible",
    },
    "openrouter": {
        "label": "OpenRouter",
        "env": "OPENROUTER_API_KEY",
        "default_model": "openai/gpt-4o-mini",
        "base_url": "https://openrouter.ai/api/v1",
        "kind": "openai_compatible",
    },
    "groq": {
        "label": "Groq",
        "env": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1",
        "kind": "openai_compatible",
    },
}


@dataclass
class ModelConfig:
    id: str
    provider: str
    model: str
    temperature: float
    api_key: str
    base_url: str | None = None

    @property
    def label(self):
        return PROVIDERS[self.provider]["label"]


@dataclass
class LLMSettings(ModelConfig):
    pass


def providerinfo_is_empty(path=PROVIDERINFO_PATH):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return not f.read().strip()
    if os.path.exists(LEGACY_PROVIDERINFO_PATH):
        with open(LEGACY_PROVIDERINFO_PATH, "r", encoding="utf-8") as f:
            return not f.read().strip()
    return True


def _normalize_provider(value):
    value = (value or "").strip().lower()
    aliases = {
        "1": "anthropic",
        "2": "openai",
        "3": "deepseek",
        "4": "kimi",
        "5": "openrouter",
        "6": "groq",
        "moonshot": "kimi",
    }
    return aliases.get(value, value)


def _normalize_api_key(provider, value):
    key = (value or "").strip().lstrip("\ufeff").strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in {"'", '"'}:
        key = key[1:-1].strip()
    if provider == "openrouter" and re.fullmatch(r"(?i)sk-or-v\d+-[0-9a-f]+", key):
        key = key.lower()
    return key


def _model_id(provider, model):
    safe_model = model.replace("/", "-").replace(":", "-").strip()
    return f"{provider}:{safe_model}"


def _read_float(prompt, default):
    while True:
        value = input(prompt).strip()
        if not value:
            return default
        try:
            number = float(value)
        except ValueError:
            print("Please enter a number like 0.2 or 0.7.")
            continue
        if 0 <= number <= 2:
            return number
        print("Temperature should be between 0 and 2.")


def _read_provider():
    options = list(PROVIDERS)
    print("Please choose your provider:")
    for index, key in enumerate(options, start=1):
        print(f" {index}. {PROVIDERS[key]['label']}")

    while True:
        selected = _normalize_provider(input("Provider number or name: "))
        if selected in PROVIDERS:
            return selected
        print("Unknown provider. Choose Anthropic, OpenAI, DeepSeek, Kimi, OpenRouter, or Groq.")


def read_model_config():
    provider = _read_provider()
    provider_data = PROVIDERS[provider]
    model = input(f"Model name [{provider_data['default_model']}]: ").strip() or provider_data["default_model"]
    temperature = _read_float("Temperature / creativity 0.0-2.0 [0.2]: ", 0.2)

    env_key = provider_data["env"]
    env_value = os.environ.get(env_key, "").strip()
    if env_value:
        api_key = _normalize_api_key(provider, env_value)
        print(f"Using API key from {env_key}.")
    else:
        api_key = _normalize_api_key(provider, input(f"API key for {provider_data['label']}: ").strip())

    custom_id = input(f"Short name [{_model_id(provider, model)}]: ").strip()
    return ModelConfig(
        id=custom_id or _model_id(provider, model),
        provider=provider,
        model=model,
        temperature=temperature,
        api_key=api_key,
        base_url=provider_data["base_url"],
    )


def run_introduction(path=PROVIDERINFO_PATH):
    print("Welcome to")
    print(BANNER)
    model_config = read_model_config()
    config = {"version": 1, "active_model": model_config.id, "models": [asdict(model_config)]}
    save_provider_config(config, path)
    return get_active_settings(path)


def _legacy_to_config(raw):
    if raw.startswith("{"):
        data = json.loads(raw)
    else:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) < 3:
            raise ValueError("providerinfo is incomplete. Delete it and run the CLI again.")
        data = {
            "provider": lines[0],
            "temperature": lines[1],
            "api_key": lines[2],
            "model": lines[3] if len(lines) > 3 else "",
        }

    if "models" in data:
        return _normalize_config(data)

    provider = _normalize_provider(data.get("provider"))
    if provider not in PROVIDERS:
        raise ValueError(f"Unsupported provider in providerinfo: {data.get('provider')}")
    provider_data = PROVIDERS[provider]
    model = (data.get("model") or provider_data["default_model"]).strip()
    model_config = ModelConfig(
        id=data.get("id") or _model_id(provider, model),
        provider=provider,
        model=model,
        temperature=float(data.get("temperature", 0.2)),
        api_key=_normalize_api_key(provider, data.get("api_key") or os.environ.get(provider_data["env"], "")),
        base_url=data.get("base_url") or provider_data["base_url"],
    )
    return {"version": 1, "active_model": model_config.id, "models": [asdict(model_config)]}


def _normalize_config(config):
    models = []
    for item in config.get("models", []):
        provider = _normalize_provider(item.get("provider"))
        if provider not in PROVIDERS:
            continue
        provider_data = PROVIDERS[provider]
        model = (item.get("model") or provider_data["default_model"]).strip()
        models.append(
            {
                "id": item.get("id") or _model_id(provider, model),
                "provider": provider,
                "model": model,
                "temperature": float(item.get("temperature", 0.2)),
                "api_key": _normalize_api_key(provider, item.get("api_key") or os.environ.get(provider_data["env"], "")),
                "base_url": item.get("base_url") or provider_data["base_url"],
            }
        )
    if not models:
        raise ValueError("providerinfo.json does not contain any usable models.")
    active_model = config.get("active_model")
    if active_model not in {model["id"] for model in models}:
        active_model = models[0]["id"]
    return {"version": 1, "active_model": active_model, "models": models}


def load_provider_config(path=PROVIDERINFO_PATH):
    if os.path.exists(path) and not providerinfo_is_empty(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "models" in data:
            return _normalize_config(data)
        config = _legacy_to_config(json.dumps(data))
        save_provider_config(config, path)
        return config

    if os.path.exists(LEGACY_PROVIDERINFO_PATH):
        with open(LEGACY_PROVIDERINFO_PATH, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if raw:
            config = _legacy_to_config(raw)
            save_provider_config(config, path)
            return config

    raise ValueError("providerinfo.json is empty.")


def save_provider_config(config, path=PROVIDERINFO_PATH):
    config = _normalize_config(config)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def get_active_settings(path=PROVIDERINFO_PATH):
    config = load_provider_config(path)
    for model in config["models"]:
        if model["id"] == config["active_model"]:
            return LLMSettings(**model)
    raise ValueError("Active model is missing from providerinfo.json.")


def get_llm_settings(path=PROVIDERINFO_PATH):
    if providerinfo_is_empty(path):
        return run_introduction(path)
    return get_active_settings(path)


def list_models(path=PROVIDERINFO_PATH):
    return load_provider_config(path)["models"]


def add_model(model_config, path=PROVIDERINFO_PATH, make_active=True):
    config = load_provider_config(path)
    config["models"] = [model for model in config["models"] if model["id"] != model_config.id]
    config["models"].append(asdict(model_config))
    if make_active:
        config["active_model"] = model_config.id
    save_provider_config(config, path)
    return get_active_settings(path)


def switch_model(model_id, path=PROVIDERINFO_PATH):
    config = load_provider_config(path)
    ids = {model["id"] for model in config["models"]}
    if model_id not in ids:
        raise ValueError(f"Unknown model id: {model_id}")
    config["active_model"] = model_id
    save_provider_config(config, path)
    return get_active_settings(path)


class OpenAICompatibleClient:
    def __init__(self, settings):
        from openai import OpenAI

        kwargs = {"api_key": settings.api_key}
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        if settings.provider == "openrouter":
            kwargs["default_headers"] = {
                "HTTP-Referer": "https://github.com/FTC-code/FTC-code",
                "X-Title": "FTC Code CLI",
            }
        self.settings = settings
        self.client = OpenAI(**kwargs)

    def chat_completion(self, messages, functions):
        tools = [{"type": "function", "function": function} for function in functions]
        try:
            response = self.client.chat.completions.create(
                model=self.settings.model,
                messages=messages,
                temperature=self.settings.temperature,
                tools=tools,
                tool_choice="auto",
            )
        except Exception as e:
            status = getattr(e, "status_code", None)
            if status == 401:
                env_key = PROVIDERS[self.settings.provider]["env"]
                raise RuntimeError(
                    f"{self.settings.label} rejected the API key stored in {PROVIDERINFO_PATH} "
                    f"(model {self.settings.model}). Check the key or re-add this model with "
                    f"/model add, or set {env_key}. Original error: {e}"
                ) from e
            raise
        return self._as_function_call_response(response)

    @staticmethod
    def _as_function_call_response(response):
        choice = response.choices[0]
        message = choice.message
        if getattr(message, "function_call", None) is not None:
            return response
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return response

        call = tool_calls[0].function
        legacy_message = SimpleNamespace(
            content=getattr(message, "content", ""),
            function_call=SimpleNamespace(name=call.name, arguments=call.arguments),
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=legacy_message)],
            usage=getattr(response, "usage", None),
        )


class AnthropicClient:
    def __init__(self, settings):
        self.settings = settings

    def chat_completion(self, messages, functions):
        payload = {
            "model": self.settings.model,
            "max_tokens": 4096,
            "temperature": self.settings.temperature,
            "messages": self._convert_messages(messages),
            "tools": self._convert_tools(functions),
        }
        system_prompt = self._system_prompt(messages)
        if system_prompt:
            payload["system"] = system_prompt

        request = urllib.request.Request(
            self.settings.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.settings.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Anthropic API error {e.code}: {body}") from e

        return self._normalize_response(data)

    @staticmethod
    def _system_prompt(messages):
        return "\n\n".join(m["content"] for m in messages if m.get("role") == "system" and m.get("content"))

    @staticmethod
    def _convert_messages(messages):
        converted = []
        for message in messages:
            role = message.get("role")
            content = message.get("content") or ""
            if role == "system":
                continue
            if role == "function":
                name = message.get("name", "tool")
                converted.append({"role": "user", "content": f"Tool result from {name}:\n{content}"})
            elif role in {"user", "assistant"} and content:
                converted.append({"role": role, "content": content})
        return converted or [{"role": "user", "content": "Hello"}]

    @staticmethod
    def _convert_tools(functions):
        return [
            {
                "name": function["name"],
                "description": function.get("description", ""),
                "input_schema": function.get("parameters", {"type": "object", "properties": {}}),
            }
            for function in functions
        ]

    @staticmethod
    def _usage(data):
        usage = data.get("usage", {})
        return SimpleNamespace(
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        )

    @classmethod
    def _normalize_response(cls, data):
        text_parts = []
        usage = cls._usage(data)
        for item in data.get("content", []):
            if item.get("type") == "tool_use":
                function_call = SimpleNamespace(
                    name=item.get("name"),
                    arguments=json.dumps(item.get("input", {})),
                )
                message = SimpleNamespace(content="", function_call=function_call)
                return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)
            if item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        message = SimpleNamespace(content="\n".join(text_parts).strip(), function_call=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def create_llm_client(settings):
    if not settings.api_key:
        env_key = PROVIDERS[settings.provider]["env"]
        raise ValueError(f"Missing API key. Set {env_key} or rerun setup with an API key.")
    if PROVIDERS[settings.provider]["kind"] == "anthropic":
        return AnthropicClient(settings)
    return OpenAICompatibleClient(settings)


def main():
    settings = run_introduction()
    print(f"Saved {settings.label} / {settings.model} to {PROVIDERINFO_PATH}.")


if __name__ == "__main__":
    main()
