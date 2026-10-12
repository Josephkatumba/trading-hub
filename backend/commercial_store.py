"""User persistence, explicit schema migration, optimistic journal writes and opaque sessions."""
import hashlib
import secrets
import time
import uuid
from sqlalchemy import (create_engine, MetaData, Table, Column, String, Integer, BigInteger, JSON,
                        ForeignKey, UniqueConstraint, CheckConstraint, select, insert, update, delete)
from sqlalchemy.exc import IntegrityError

metadata = MetaData()
users = Table("users", metadata, Column("id", String(36), primary_key=True),
    Column("issuer", String(512), nullable=False), Column("subject", String(255), nullable=False),
    UniqueConstraint("issuer", "subject", name="uq_oidc_identity"))
entitlements = Table("entitlements", metadata, Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("plan", String(16), nullable=False), Column("expires_at", BigInteger, nullable=False),
    CheckConstraint("plan IN ('free', 'pro')", name="valid_plan"))
sessions = Table("user_sessions", metadata, Column("token_hash", String(64), primary_key=True),
    Column("user_id", ForeignKey("users.id"), nullable=False), Column("csrf", String(64), nullable=False),
    Column("expires_at", BigInteger, nullable=False))
journal = Table("journal_records", metadata, Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("kind", String(16), primary_key=True), Column("record_id", String(160), primary_key=True),
    Column("payload", JSON, nullable=False), Column("version", Integer, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    CheckConstraint("kind IN ('trade', 'account', 'review')", name="valid_journal_kind"),
    CheckConstraint("version >= 1", name="positive_version"))
migrations = Table("schema_migrations", metadata, Column("version", Integer, primary_key=True))


class Conflict(Exception):
    pass


class CommercialStore:
    def __init__(self, url):
        self.engine = create_engine(url, pool_pre_ping=True, **({"connect_args": {"check_same_thread": False}}
                                    if url.startswith("sqlite") else {}))

    def migrate(self):
        # Explicit initial migration; runtime never silently initializes production schemas.
        with self.engine.begin() as connection:
            metadata.create_all(connection)
            if not connection.execute(select(migrations.c.version)).first():
                connection.execute(insert(migrations).values(version=1))

    def login(self, issuer, subject):
        if not issuer or not subject:
            raise ValueError("OIDC identity required")
        with self.engine.begin() as connection:
            uid = connection.execute(select(users.c.id).where(users.c.issuer == issuer, users.c.subject == subject)).scalar()
            if not uid:
                # Concurrent callbacks for the same identity must share one account.
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                identity_insert = sqlite_insert if self.engine.dialect.name == "sqlite" else pg_insert
                connection.execute(identity_insert(users).values(id=str(uuid.uuid4()), issuer=issuer, subject=subject)
                                   .on_conflict_do_nothing(index_elements=["issuer", "subject"]))
                uid = connection.execute(select(users.c.id).where(users.c.issuer == issuer, users.c.subject == subject)).scalar_one()
            connection.execute(delete(sessions).where(sessions.c.expires_at < int(time.time())))
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            connection.execute(insert(sessions).values(token_hash=self.hash(token), user_id=uid,
                csrf=csrf, expires_at=int(time.time()) + 8 * 3600))
        return token, csrf

    @staticmethod
    def hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def identity(self, token):
        if not token:
            return None
        with self.engine.connect() as connection:
            row = connection.execute(select(sessions).where(sessions.c.token_hash == self.hash(token),
                sessions.c.expires_at > int(time.time()))).mappings().first()
            if not row:
                return None
            grant = connection.execute(select(entitlements).where(entitlements.c.user_id == row["user_id"])).mappings().first()
        return {"id": row["user_id"], "csrf": row["csrf"],
                "plan": "pro" if grant and grant["plan"] == "pro" and grant["expires_at"] > time.time() else "free"}

    def logout(self, token):
        with self.engine.begin() as connection:
            connection.execute(delete(sessions).where(sessions.c.token_hash == self.hash(token)))

    def records(self, uid, kind, cursor="", limit=200):
        with self.engine.connect() as connection:
            rows = connection.execute(select(journal).where(journal.c.user_id == uid,
                journal.c.kind == kind, journal.c.record_id > cursor).order_by(journal.c.record_id).limit(limit + 1)).mappings().all()
        return {"records": [{"id": r["record_id"], "payload": r["payload"], "version": r["version"]} for r in rows[:limit]],
                "next_cursor": rows[limit-1]["record_id"] if len(rows) > limit else None}

    def put(self, uid, kind, rid, payload, version):
        values = dict(payload=payload, version=version + 1, updated_at=int(time.time()))
        try:
            with self.engine.begin() as connection:
                if version == 0:
                    connection.execute(insert(journal).values(user_id=uid, kind=kind, record_id=rid, **values))
                elif connection.execute(update(journal).where(journal.c.user_id == uid,
                        journal.c.kind == kind, journal.c.record_id == rid, journal.c.version == version).values(**values)).rowcount != 1:
                    raise Conflict("Record changed; reload before saving")
        except IntegrityError as exc:
            raise Conflict("Record exists; reload before saving") from exc
        return {"id": rid, "payload": payload, "version": version + 1}

    def remove(self, uid, kind, rid, version):
        with self.engine.begin() as connection:
            if connection.execute(delete(journal).where(journal.c.user_id == uid,
                    journal.c.kind == kind, journal.c.record_id == rid, journal.c.version == version)).rowcount != 1:
                raise Conflict("Record changed or not owned by this user")


if __name__ == "__main__":
    import os
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("migrate", "grant-pro", "schema"))
    parser.add_argument("--user-id")
    parser.add_argument("--expires-at", type=int)
    args = parser.parse_args()
    if args.action == "schema":
        from sqlalchemy.schema import CreateTable
        from sqlalchemy.dialects.postgresql import dialect
        print("-- Initial commercial schema, version 1. Generated from commercial_store.metadata.\nBEGIN;")
        for table in metadata.sorted_tables:
            ddl = str(CreateTable(table).compile(dialect=dialect())).strip()
            print("\n".join(line.rstrip() for line in ddl.splitlines()) + ";")
        print("INSERT INTO schema_migrations(version) VALUES (1);\nCOMMIT;")
        raise SystemExit(0)
    store = CommercialStore(os.environ["TRADING_HUB_DATABASE_URL"])
    if args.action == "migrate":
        store.migrate()
    else:
        if not args.user_id or not args.expires_at or args.expires_at <= time.time():
            parser.error("grant-pro requires an existing user UUID and future Unix expiry")
        with store.engine.begin() as connection:
            if not connection.execute(select(users.c.id).where(users.c.id == args.user_id)).scalar():
                parser.error("unknown user")
            connection.execute(delete(entitlements).where(entitlements.c.user_id == args.user_id))
            connection.execute(insert(entitlements).values(user_id=args.user_id, plan="pro", expires_at=args.expires_at))
