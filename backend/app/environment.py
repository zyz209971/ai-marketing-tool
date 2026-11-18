"""Private config: process environment > explicit file > .env.local > .env."""
import os
from pathlib import Path
from dotenv import dotenv_values


def load_environment(backend_dir: Path | None = None, explicit_file: str | None = None):
    root = backend_dir or Path(__file__).resolve().parent.parent
    selected = explicit_file or os.getenv('APP_ENV_FILE')
    files = [root/'.env', root/'.env.local']
    if selected:
        external = Path(selected).expanduser().resolve()
        if not external.is_file():
            raise ValueError('指定的私有配置文件不存在，请检查 -EnvFile / APP_ENV_FILE 路径。')
        files.append(external)
    merged, loaded = {}, []
    for file in files:
        if file.is_file():
            merged.update({k: v for k, v in dotenv_values(file, interpolate=False).items() if v is not None})
            loaded.append(str(file))
    for key, value in merged.items():
        os.environ.setdefault(key, value)
    return loaded
