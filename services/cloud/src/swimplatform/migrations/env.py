from alembic import context
from sqlalchemy import engine_from_config, event, pool
from swimplatform.models import Base

config = context.config

if context.is_offline_mode():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def manual_transactions(dbapi_connection, _record):
            # pysqlite 默认只对 DML 隐式 BEGIN，DDL 会逐条自动提交；
            # 改为显式事务后，建表与整表重建失败时才能整体回滚。
            dbapi_connection.isolation_level = None

    with engine.connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()

            @event.listens_for(engine, "begin")
            def begin_explicit(conn):
                conn.exec_driver_sql("BEGIN")

        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
