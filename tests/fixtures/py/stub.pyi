"""Type stub file — should be preferred over .py when present."""

VERSION: str

def connect(host: str, port: int = 5432) -> "Connection": ...

class Connection:
    """Database connection stub."""
    def query(self, sql: str) -> list: ...
    def close(self) -> None: ...
