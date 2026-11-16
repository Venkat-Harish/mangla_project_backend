"""Database-level SQL that the ORM's create_all can't express on its own.

Registered with SQLAlchemy DDL events, so it runs automatically when
Base.metadata.create_all(engine) creates the tables.

Note: SQLAlchemy runs DDL strings through Python %-formatting, so the SQL
below deliberately avoids the % character (mod() / quote_ident() instead).
"""

from sqlalchemy import DDL, Table, event

from .base import Base

# Random code: prefix + `len` chars from an alphabet without 0/O/1/I.
# Randomness comes from gen_random_uuid() bytes (cryptographically random);
# bytes 6 and 8 hold the UUID version/variant bits, so they are skipped.
GENERATE_ALNUM_CODE = DDL("""
CREATE OR REPLACE FUNCTION public.generate_alnum_code(prefix text, len integer DEFAULT 8)
RETURNS text
LANGUAGE plpgsql
VOLATILE
SET search_path = ''
AS $$
DECLARE
  alphabet constant text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  code text := '';
  b bytea;
  i integer;
BEGIN
  WHILE length(code) < len LOOP
    b := uuid_send(gen_random_uuid());
    FOR i IN 0..15 LOOP
      CONTINUE WHEN i IN (6, 8);
      EXIT WHEN length(code) >= len;
      code := code || substr(alphabet, mod(get_byte(b, i), 32) + 1, 1);
    END LOOP;
  END LOOP;
  RETURN prefix || code;
END
$$;
""")

# BEFORE INSERT trigger: TG_ARGV[0] = column name, TG_ARGV[1] = prefix.
# Fills the column when it's empty and retries until the code is unused.
SET_ALNUM_ID = DDL("""
CREATE OR REPLACE FUNCTION public.set_alnum_id()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
  col text := TG_ARGV[0];
  prefix text := TG_ARGV[1];
  code text;
  taken boolean;
BEGIN
  IF to_jsonb(NEW) ->> col IS NOT NULL THEN
    RETURN NEW;
  END IF;
  LOOP
    code := public.generate_alnum_code(prefix, 8);
    EXECUTE 'SELECT EXISTS (SELECT 1 FROM ' || quote_ident(TG_TABLE_SCHEMA) || '.'
            || quote_ident(TG_TABLE_NAME) || ' WHERE ' || quote_ident(col) || ' = $1)'
      INTO taken USING code;
    EXIT WHEN NOT taken;
  END LOOP;
  NEW := jsonb_populate_record(NEW, jsonb_build_object(col, code));
  RETURN NEW;
END
$$;
""")

event.listen(Base.metadata, "before_create", GENERATE_ALNUM_CODE)
event.listen(Base.metadata, "before_create", SET_ALNUM_ID)


def add_alnum_id_trigger(table: Table, column: str, prefix: str) -> None:
    """Auto-fill `column` with a unique code like PREFIX-XXXXXXXX on insert."""
    event.listen(table, "after_create", DDL(
        f"CREATE TRIGGER {table.name}_set_alnum_id BEFORE INSERT ON public.{table.name} "
        f"FOR EACH ROW EXECUTE FUNCTION public.set_alnum_id('{column}', '{prefix}')"
    ))


# BEFORE UPDATE trigger for all_reviews: stamp last_edited_time only when the
# review content changes (like/dislike count updates are not edits).
SET_REVIEW_LAST_EDITED = DDL("""
CREATE OR REPLACE FUNCTION public.set_review_last_edited()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
  IF NEW.rating IS DISTINCT FROM OLD.rating
     OR NEW.review_text IS DISTINCT FROM OLD.review_text
     OR NEW.images IS DISTINCT FROM OLD.images
     OR NEW.anonymous_flag IS DISTINCT FROM OLD.anonymous_flag THEN
    NEW.last_edited_time := now();
  END IF;
  RETURN NEW;
END
$$;
""")


def add_review_edit_trigger(table: Table) -> None:
    """Auto-set last_edited_time when a review's content changes."""
    event.listen(table, "before_create", SET_REVIEW_LAST_EDITED)
    event.listen(table, "after_create", DDL(
        f"CREATE TRIGGER {table.name}_set_last_edited BEFORE UPDATE ON public.{table.name} "
        f"FOR EACH ROW EXECUTE FUNCTION public.set_review_last_edited()"
    ))


def enable_rls(table: Table) -> None:
    """Turn on Row Level Security (no policies: blocks Supabase's public API)."""
    event.listen(table, "after_create", DDL(
        f"ALTER TABLE public.{table.name} ENABLE ROW LEVEL SECURITY"
    ))
