import os

DEFAULT_ENV_PATH = "~/.polymarket.env"


def load_env_file(path=None):
    env_path = path or os.getenv("POLYMARKET_ENV_FILE") or DEFAULT_ENV_PATH
    env_path = os.path.expanduser(env_path)
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"'").strip()
                if key and value:
                    # Allow file to override existing env values for automation
                    os.environ[key] = value
    except Exception:
        # Silent failure to avoid leaking secrets in error output
        pass


def env_int(name):
    val = os.getenv(name)
    if val is None or val == "":
        return None
    try:
        return int(val)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
