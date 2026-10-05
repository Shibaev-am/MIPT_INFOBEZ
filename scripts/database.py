"""SQLite backup and offline restore. Uses only the Python standard library."""
import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def connect_readonly(path):
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)

def validate(path):
    with closing(connect_readonly(path)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Database integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Database contains invalid foreign keys")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"auth_user", "finance_category", "finance_transaction", "finance_budgetlimit", "django_migrations"}
        if not required.issubset(tables):
            raise ValueError("This is not a migrated Personal Budget database")

def backup(source, target):
    if not source.is_file():
        raise ValueError("Database does not exist; run migrations first")
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    # Never overwrite an existing backup.
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        with closing(connect_readonly(source)) as src, closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
        validate(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise

def restore(source, database, backups):
    validate(source)
    if source.resolve() == database.resolve():
        raise ValueError("Source and destination must be different")
    for suffix in ["-wal", "-journal"]:
        if Path(str(database) + suffix).exists():
            raise ValueError("Stop the application and close SQLite connections before restore")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    if database.exists():
        safety = backups / f"before-restore-{stamp}.sqlite3"
        backup(database, safety)
        print(f"Safety backup: {safety}")
    database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="restore-", suffix=".sqlite3", dir=database.parent)
    os.close(fd)
    temporary = Path(tmp_name)
    try:
        with closing(connect_readonly(source)) as src, closing(sqlite3.connect(temporary)) as dst:
            src.backup(dst)
        validate(temporary)
        os.replace(temporary, database)
    finally:
        temporary.unlink(missing_ok=True)

def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("DATA_DIR", ROOT / "data")) / "budget.sqlite3")
    parser.add_argument("--file", type=Path, help="Backup destination or restore source")
    parser.add_argument("--backups-dir", type=Path, default=ROOT / "backups")
    parser.add_argument("--confirm-stopped", action="store_true", help="Confirm the application is stopped before restoring")
    args = parser.parse_args()
    try:
        if args.action == "backup":
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            target = args.file or args.backups_dir / f"budget-{stamp}.sqlite3"
            backup(args.db, target)
            print(f"Backup saved: {target}")
        else:
            if not args.file or not args.confirm_stopped:
                parser.error("restore requires --file and --confirm-stopped")
            restore(args.file, args.db, args.backups_dir)
            print("Database restored. You can start the application.")
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Error: {error}\n")

if __name__ == "__main__":
    main()
