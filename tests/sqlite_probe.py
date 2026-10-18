"""Safe SQL failure labels for disposable multi-process concurrency tests only."""
import json
import sqlite3
import time
import traceback


def install(path):
    connect = sqlite3.connect

    class ObservedConnection(sqlite3.Connection):
        def observe(self, operation, method, *args, **kwargs):
            started = time.monotonic()
            try:
                return method(*args, **kwargs)
            except sqlite3.Error as error:
                event = {
                    "operation": operation,
                    "error": getattr(error, "sqlite_errorname", type(error).__name__),
                    "elapsed": round(time.monotonic() - started, 3),
                    "functions": [frame.name for frame in traceback.extract_stack(limit=6)[:-1]],
                }
                with open(path, "a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event) + "\n")
                raise

        def execute(self, sql, *args, **kwargs):
            return self.observe(" ".join(sql.split()[:2]), super().execute, sql, *args, **kwargs)

        def executescript(self, sql):
            return self.observe("script", super().executescript, sql)

        def __exit__(self, *args):
            return self.observe("transaction-exit", super().__exit__, *args)

    def observed_connect(*args, **kwargs):
        kwargs.setdefault("factory", ObservedConnection)
        return connect(*args, **kwargs)

    sqlite3.connect = observed_connect
