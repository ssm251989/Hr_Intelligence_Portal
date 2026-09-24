"""enable_rls() (docs/HRMS_COMPLETE_SPEC.txt section B + Part 2 section 2): every tenant
migration that creates a table calls this. FORCE (not just ENABLE) row level security
matters here specifically because this app's own connecting role owns every table it
creates -- Postgres exempts a table's owner from RLS by default, which would otherwise make
every policy below silently a no-op for this app's own queries.

current_setting('app.tenant_id', true) -- the second (missing_ok) argument -- returns NULL
instead of raising when a session hasn't run `SET app.tenant_id` at all (an admin psql
session, a one-off script, Alembic's own migration connection). tenant_id = NULL is never
true, so such a session sees zero rows rather than an error on every query: fails closed,
not broken.

NULLIF(..., '') around that matters for a DIFFERENT case than "never set": a pooled
connection that previously HAD app.tenant_id set (via plain SET, not SET LOCAL) and was
then rolled back reverts the custom GUC to '' (empty string), not NULL -- confirmed
directly against this app's own Postgres (a placeholder/custom GUC's rollback behavior,
unlike a built-in setting's). Casting '' to uuid raises, rather than failing closed like an
actual NULL does; NULLIF folds that '' case into NULL too, so both "never set" and
"set-then-rolled-back" fail closed the same way. app.core.database's own SET LOCAL (see its
comment) re-applies at the start of every real request's transaction regardless, so this
never bites normal request traffic -- it only matters for code taking a raw connection
directly, like a one-off script or a test.
"""


def _policy_expression() -> str:
    return "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def enable_rls(op, table_name: str) -> None:
    op.execute(f'ALTER TABLE "{table_name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" FORCE ROW LEVEL SECURITY')
    expr = _policy_expression()
    op.execute(f'CREATE POLICY "{table_name}_tenant_isolation" ON "{table_name}" USING ({expr}) WITH CHECK ({expr})')


def disable_rls(op, table_name: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS "{table_name}_tenant_isolation" ON "{table_name}"')
    op.execute(f'ALTER TABLE "{table_name}" NO FORCE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table_name}" DISABLE ROW LEVEL SECURITY')
