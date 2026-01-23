from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class Architecture:
    id: str
    cmd: List[str]  # comando base, ej: ["C:\\path\\to\\venv\\python.exe","-m","tu_cli_modulo"]
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    env_file: Optional[str] = None