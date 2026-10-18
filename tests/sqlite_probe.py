"""Safe lock timing for disposable multi-process tests; no SQL values or paths."""
import atexit
import json
import sqlite3
import time
import traceback
from pathlib import Path


def install(path):
    connect = sqlite3.connect
    events = []

    def flush():
        Path(path).write_text(json.dumps(events), encoding="utf-8")

    atexit.register(flush)

    class ObservedConnection(sqlite3.Connection):
        database_label = "database"
        held_since = None

        def observe(self, operation, method, *args, **kwargs):
            started = time.monotonic()
            before = self.in_transaction
            error_name = None
            try:
                return method(*args, **kwargs)
            except sqlite3.Error as error:
                error_name = getattr(error, "sqlite_errorname", type(error).__name__)
                raise
            finally:
                ended = time.monotonic()
                after = self.in_transaction
                held = 0
                if before and not after and self.held_since is not None:
                    held = ended - self.held_since
                    self.held_since = None
                if not before and after:
                    self.held_since = ended
                if error_name or ended - started > 0.025 or held > 0.025:
                    events.append({
                        "database": self.database_label,
                        "operation": operation,
                        "error": error_name,
                        "start": round(started, 6),
                        "elapsed": round(ended - started, 6),
                        "held": round(held, 6),
                        "transaction_before": before,
                        "transaction_after": after,
                        "functions": [f.name for f in traceback.extract_stack(limit=6)[:-1]],
                    })

        def execute(self, sql, *args, **kwargs):
            return self.observe(" ".join(sql.split()[:2]), super().execute, sql, *args, **kwargs)

        def executescript(self, sql):
            return self.observe("script", super().executescript, sql)

        def __exit__(self, *args):
            return self.observe("transaction-exit", super().__exit__, *args)

    def observed_connect(*args, **kwargs):
        kwargs.setdefault("factory", ObservedConnection)
        connection = connect(*args, **kwargs)
        connection.database_label = Path(str(args[0])).name
        return connection

    sqlite3.connect = observed_connect
