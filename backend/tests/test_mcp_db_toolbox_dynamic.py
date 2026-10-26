# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Comprehensive test suite for the Dynamic MCP Database Toolbox, SchemaCatalog,
5-Stage SqlAstSandbox firewall, and 2-Stage DB Query Planner/Executor Subgraph.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from yarvelle_core.db.base import Base, ensure_metadata_comments
import yarvelle_core.db.models  # noqa: F401
from yarvelle_core.db.schema_catalog import (
    SYSTEM_DENYLIST_TABLES,
    SchemaCatalog,
    get_schema_catalog,
    register_table_scope,
)
from yarvelle_core.db.session import (
    create_db_engine,
    normalize_database_url,
)
from yarvelle_core.loaders.agent_loader import load_agent
from yarvelle_core.scope.context import ScopeContext
from yarvelle_core.tools.mcp_db_toolbox import (
    McpDatabaseToolbox,
    get_db_toolbox,
    get_db_tools_for_agent,
)
from yarvelle_core.tools.sql_ast_sandbox import (
    SqlSecurityError,
    SqlValidationError,
    validate_and_rewrite_sql,
)
from yarvelle_core.workflows.subgraphs.db_toolbox import build_db_toolbox_subgraph


@pytest.fixture
async def db_session(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    """Create an isolated in-memory/temp SQLite database session with all core tables."""
    db_file = tmp_path / "test_dynamic_toolbox.db"
    engine = create_db_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker

    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as session:
        yield session

    await engine.dispose()


class TestSchemaCommentsAndMschemaCatalog:
    """Verify table, column, and index comments across all models and M-Schema rendering."""

    def test_all_tables_columns_and_indexes_have_comments(self) -> None:
        ensure_metadata_comments(Base.metadata)
        assert len(Base.metadata.tables) >= 25

        for table_name, table in Base.metadata.tables.items():
            assert table.comment and table.comment.strip(), (
                f"Table '{table_name}' is missing a table-level comment"
            )
            for col in table.columns:
                assert col.comment and col.comment.strip(), (
                    f"Column '{table_name}.{col.name}' is missing Column.comment"
                )
                assert col.doc and col.doc.strip(), (
                    f"Column '{table_name}.{col.name}' is missing Column.doc"
                )
            for idx in table.indexes:
                idx_comment = idx.info.get("comment") or getattr(idx, "comment", None)
                assert idx_comment and str(idx_comment).strip(), (
                    f"Index '{idx.name}' on '{table_name}' is missing an index comment"
                )

    def test_m_schema_excludes_denylisted_tables_and_renders_comments(self) -> None:
        catalog = get_schema_catalog()
        accessible = catalog.get_accessible_tables()

        for denied in SYSTEM_DENYLIST_TABLES:
            assert denied not in accessible, f"Denylisted table '{denied}' leaked into accessible tables"

        m_schema = catalog.get_m_schema(table_names=["notes", "reminders"], dialect="postgres")
        assert "【DB_ENGINE】 dialect=postgres" in m_schema
        assert "【TABLE】 notes" in m_schema
        assert "【TABLE】 reminders" in m_schema
        assert "# Comment:" in m_schema
        assert "# Indexes:" in m_schema
        assert "ix_reminders_profile_status_due" in m_schema

    def test_domain_scope_filtering_in_schema_catalog(self) -> None:
        catalog = SchemaCatalog()
        register_table_scope("custom_pack_items", "pack_alpha")

        ctx_alpha = ScopeContext(
            profile_id="prof-1",
            scope="pack_alpha.main",
            granted_scopes=("pack_alpha", "pack_alpha.*"),
        )
        ctx_beta = ScopeContext(
            profile_id="prof-1",
            scope="pack_beta.main",
            granted_scopes=("pack_beta", "pack_beta.*"),
        )
        # Core table 'notes' is accessible in both scopes (row-isolated via scope column)
        assert catalog.is_table_accessible("notes", scope_ctx=ctx_alpha, mode="write")
        assert catalog.is_table_accessible("notes", scope_ctx=ctx_beta, mode="write")


class TestMultiDialectSupport:
    """Verify multi-database URL normalization and dialect transpilation."""

    def test_normalize_database_url_all_dialects(self) -> None:
        assert normalize_database_url(":memory:") == "sqlite+aiosqlite:///:memory:"
        assert normalize_database_url("sqlite:///local.db") == "sqlite+aiosqlite:///local.db"
        assert normalize_database_url("postgres://u:p@host/db") == "postgresql+asyncpg://u:p@host/db"
        assert normalize_database_url("postgresql+psycopg2://u:p@host/db") == "postgresql+asyncpg://u:p@host/db"
        assert normalize_database_url("mysql://u:p@host/db") == "mysql+aiomysql://u:p@host/db"
        assert normalize_database_url("mariadb://u:p@host/db") == "mariadb+aiomysql://u:p@host/db"
        assert normalize_database_url("mssql://u:p@host/db") == "mssql+aioodbc://u:p@host/db"
        assert normalize_database_url("sqlserver://u:p@host/db") == "mssql+aioodbc://u:p@host/db"

    @pytest.mark.parametrize("dialect", ["sqlite", "postgres", "mysql", "tsql", "duckdb"])
    def test_transpile_parameterized_select_across_dialects(self, dialect: str) -> None:
        ctx = ScopeContext(
            profile_id="prof-1",
            scope="general",
            granted_scopes=("general", "general.*"),
        )
        plan = validate_and_rewrite_sql(
            "SELECT id, slug, title FROM notes WHERE slug = :slug",
            {"slug": "my-note"},
            scope_ctx=ctx,
            target_dialect=dialect,
        )
        assert plan.operation == "SELECT"
        assert plan.dialect == dialect
        assert ":slug" in plan.rewritten_sql
        assert ":__ctx_profile_id" in plan.rewritten_sql
        assert ":__ctx_scope" in plan.rewritten_sql
        assert plan.bound_params["__ctx_profile_id"] == "prof-1"
        assert plan.bound_params["__ctx_scope"] == "general"


class TestSqlAstSandboxSecurityFirewall:
    """Adversarial penetration tests against the 5-Stage SqlAstSandbox."""

    @pytest.mark.parametrize(
        "ddl_or_admin_sql",
        [
            "CREATE TABLE hacked (id INT)",
            "ALTER TABLE notes ADD COLUMN hacked TEXT",
            "DROP TABLE notes",
            "DROP INDEX ix_notes_slug",
            "TRUNCATE TABLE notes",
            "RENAME TABLE notes TO hacked",
            "GRANT ALL ON notes TO public",
            "REVOKE ALL ON notes FROM public",
            "PRAGMA table_info(notes)",
            "ATTACH DATABASE 'other.db' AS other",
            "DETACH DATABASE other",
            "VACUUM",
            "BEGIN TRANSACTION",
            "COMMIT",
            "ROLLBACK",
            "SET search_path TO public",
            "SHOW TABLES",
            "COPY notes TO '/tmp/leak.csv'",
        ],
    )
    def test_blocks_all_ddl_dcl_tcl_and_admin_statements(self, ddl_or_admin_sql: str) -> None:
        ctx = ScopeContext(
            profile_id="prof-1",
            scope="general",
            granted_scopes=("general", "general.*"),
        )
        with pytest.raises(SqlSecurityError):
            validate_and_rewrite_sql(ddl_or_admin_sql, scope_ctx=ctx)

    @pytest.mark.parametrize(
        "attack_sql",
        [
            # Stacked queries
            "SELECT id FROM notes; DROP TABLE notes;",
            "SELECT id FROM notes; DELETE FROM notes WHERE 1=1;",
            # Writable CTE inside SELECT
            "WITH deleted AS (DELETE FROM notes RETURNING *) SELECT * FROM deleted",
            # SELECT INTO table creation
            "SELECT id, title INTO new_notes_table FROM notes",
            # Dangerous SQL functions
            "SELECT load_extension('/tmp/evil.so') FROM notes",
            "SELECT pg_read_file('/etc/passwd') FROM notes",
            "SELECT pg_sleep(10) FROM notes",
            "SELECT randomblob(100000000) FROM notes",
            # System & vault denylisted tables
            "SELECT * FROM users",
            "SELECT * FROM sessions",
            "SELECT * FROM password_resets",
            "SELECT * FROM credentials",
            "SELECT * FROM profile_keys",
            "SELECT * FROM audit_events",
            "SELECT * FROM approvals",
            "SELECT * FROM system_settings",
            "SELECT * FROM sqlite_master",
            "SELECT * FROM information_schema.tables",
            # Read-only table mutation attempt
            "DELETE FROM profiles WHERE id = :id",
            "UPDATE agent SET title = 'hacked' WHERE id = :id",
            # Immutable column mutation attempt
            "UPDATE notes SET profile_id = 'victim' WHERE slug = :slug",
            "UPDATE notes SET scope = 'other_scope' WHERE slug = :slug",
            "UPDATE notes SET id = 'new-id' WHERE slug = :slug",
            # Unfiltered or tautological UPDATE / DELETE
            "DELETE FROM notes",
            "DELETE FROM notes WHERE 1=1",
            "DELETE FROM notes WHERE 'a' = 'a'",
            "DELETE FROM notes WHERE slug = :slug OR 1=1",
            "UPDATE notes SET title = 'wiped'",
            "UPDATE notes SET title = 'wiped' WHERE 1=1",
        ],
    )
    def test_blocks_stacked_queries_ctes_system_tables_and_unfiltered_mutations(
        self, attack_sql: str
    ) -> None:
        ctx = ScopeContext(
            profile_id="prof-1",
            scope="general",
            granted_scopes=("general", "general.*"),
        )
        with pytest.raises(SqlSecurityError):
            validate_and_rewrite_sql(
                attack_sql,
                {"id": "123", "slug": "test"},
                scope_ctx=ctx,
            )

    def test_hallucinated_column_raises_validation_error_with_column_hints(self) -> None:
        ctx = ScopeContext(
            profile_id="prof-1",
            scope="general",
            granted_scopes=("general", "general.*"),
        )
        with pytest.raises(SqlValidationError) as exc_info:
            validate_and_rewrite_sql(
                "SELECT id, nonexistent_column_xyz FROM notes",
                scope_ctx=ctx,
            )
        err_text = str(exc_info.value)
        assert "Unknown column 'nonexistent_column_xyz'" in err_text
        assert "content" in err_text
        assert "title" in err_text


class TestDynamicExecutionAndSelfCorrectionEndToEnd:
    """End-to-end execution tests for McpDatabaseToolbox, Subgraph, and tenant isolation."""

    async def test_declarative_and_dynamic_crud_with_strict_tenant_isolation(
        self, db_session: AsyncSession
    ) -> None:
        toolbox = McpDatabaseToolbox()
        ctx_p1 = ScopeContext(
            profile_id="profile-alpha",
            scope="general",
            granted_scopes=("general", "general.*"),
        )
        ctx_p2 = ScopeContext(
            profile_id="profile-beta",
            scope="general",
            granted_scopes=("general", "general.*"),
        )

        # 1. Insert a note for profile-alpha via dynamic INSERT
        ins_res = await toolbox.execute_dynamic_mutation(
            operation="INSERT",
            statement="INSERT INTO notes (slug, title, content, type) VALUES (:slug, :title, :content, :type)",
            parameters={
                "slug": "alpha-note",
                "title": "Alpha Secret Plan",
                "content": "Confidential alpha content",
                "type": "prep",
            },
            profile_id="profile-alpha",
            scope_ctx=ctx_p1,
            session=db_session,
        )
        assert ins_res["status"] == "ok"
        assert ins_res["operation"] == "INSERT"

        # 2. Insert a note for profile-beta via declarative tool
        await toolbox.execute(
            "upsert_workspace_note",
            {
                "slug": "beta-note",
                "title": "Beta Note",
                "content": "Beta content",
                "type": "scratchpad",
            },
            profile_id="profile-beta",
            scope="general",
            session=db_session,
        )

        # 3. Attempt cross-tenant tautology attack from profile-alpha (`OR 1=1`)
        q_res = await toolbox.execute_dynamic_query(
            statement="SELECT slug, title, profile_id FROM notes WHERE profile_id = 'profile-beta' OR 1=1",
            profile_id="profile-alpha",
            scope_ctx=ctx_p1,
            session=db_session,
        )
        assert q_res["status"] == "ok"
        assert q_res["count"] == 1
        assert q_res["records"][0]["slug"] == "alpha-note"
        assert q_res["records"][0]["profile_id"] == "profile-alpha"

        # 4. Dynamic UPDATE on profile-alpha's note
        upd_res = await toolbox.execute_dynamic_mutation(
            operation="UPDATE",
            statement="UPDATE notes SET title = :new_title WHERE slug = :slug",
            parameters={"new_title": "Alpha Updated Title", "slug": "alpha-note"},
            profile_id="profile-alpha",
            scope_ctx=ctx_p1,
            session=db_session,
        )
        assert upd_res["status"] == "ok"
        assert upd_res["affected_rows"] == 1

        # 5. Self-correction loop on hallucinated column name (`body` -> `content`) via subgraph
        subgraph = build_db_toolbox_subgraph(session=db_session)
        sub_state = await subgraph.ainvoke(
            {
                "request": "Get the note body and title for alpha-note",
                "statement": "SELECT slug, title, body FROM notes WHERE slug = :slug",
                "parameters": {"slug": "alpha-note"},
                "profile_id": "profile-alpha",
                "scope_ctx": ctx_p1,
                "max_retries": 2,
            }
        )
        assert sub_state["status"] == "completed"
        assert sub_state["attempts"] == 2
        assert sub_state["result"]["count"] == 1
        assert sub_state["result"]["records"][0]["title"] == "Alpha Updated Title"
        assert sub_state["result"]["records"][0]["content"] == "Confidential alpha content"

        # 6. Dynamic DELETE on profile-alpha's note
        del_res = await toolbox.execute_dynamic_mutation(
            operation="DELETE",
            statement="DELETE FROM notes WHERE slug = :slug",
            parameters={"slug": "alpha-note"},
            profile_id="profile-alpha",
            scope_ctx=ctx_p1,
            session=db_session,
        )
        assert del_res["status"] == "ok"
        assert del_res["risk_tier"] == "irreversible"
        assert del_res["affected_rows"] == 1

        # Verify profile-beta's note is completely untouched
        beta_check = await toolbox.execute_dynamic_query(
            statement="SELECT slug FROM notes",
            profile_id="profile-beta",
            scope_ctx=ctx_p2,
            session=db_session,
        )
        assert beta_check["count"] == 1
        assert beta_check["records"][0]["slug"] == "beta-note"

    def test_db_operator_system_agent_manifest_and_tools(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        agent_dir = repo_root / "agents" / "_system" / "db-operator"
        loaded = load_agent(agent_dir)
        manifest = loaded[0] if isinstance(loaded, tuple) else loaded
        assert manifest.id == "db-operator"
        assert "db_inspect_schema" in manifest.tools
        assert "db_execute_query" in manifest.tools
        assert "db_mutate_records" in manifest.tools

        lc_tools = get_db_tools_for_agent(
            "db-operator",
            profile_id="prof-1",
        )
        tool_names = {t.name for t in lc_tools}
        assert "db_inspect_schema" in tool_names
        assert "db_execute_query" in tool_names
        assert "db_mutate_records" in tool_names
        assert "upsert_workspace_note" in tool_names

        toolbox = get_db_toolbox()
        specs = {s.name: s for s in toolbox.to_tool_specs()}
        assert "db_inspect_schema" in specs
        assert "db_execute_query" in specs
        assert "db_mutate_records" in specs
