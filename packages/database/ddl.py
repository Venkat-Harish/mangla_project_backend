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


# Generic BEFORE UPDATE trigger: stamp last_edited_time when any of the columns
# passed as trigger arguments (TG_ARGV) change. The table needs a last_edited_time column.
SET_LAST_EDITED_ON_CHANGE = DDL("""
CREATE OR REPLACE FUNCTION public.set_last_edited_on_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
  new_row jsonb := to_jsonb(NEW);
  old_row jsonb := to_jsonb(OLD);
  i integer;
BEGIN
  FOR i IN 0..TG_NARGS - 1 LOOP
    IF new_row -> TG_ARGV[i] IS DISTINCT FROM old_row -> TG_ARGV[i] THEN
      NEW.last_edited_time := now();
      EXIT;
    END IF;
  END LOOP;
  RETURN NEW;
END
$$;
""")


def add_last_edited_trigger(table: Table, *columns: str) -> None:
    """Auto-set last_edited_time when any of `columns` change."""
    args = ", ".join(f"'{c}'" for c in columns)
    event.listen(table, "before_create", SET_LAST_EDITED_ON_CHANGE)
    event.listen(table, "after_create", DDL(
        f"CREATE TRIGGER {table.name}_set_last_edited BEFORE UPDATE ON public.{table.name} "
        f"FOR EACH ROW EXECUTE FUNCTION public.set_last_edited_on_change({args})"
    ))


# BEFORE INSERT OR UPDATE trigger for posts: post_deleted_time follows post_deleted_flag.
# Set to now() when the flag turns on (kept if it was already on), cleared when it turns off.
SET_POST_DELETED_TIME = DDL("""
CREATE OR REPLACE FUNCTION public.set_post_deleted_time()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
  IF NOT NEW.post_deleted_flag THEN
    NEW.post_deleted_time := NULL;
  ELSIF TG_OP = 'INSERT' THEN
    NEW.post_deleted_time := coalesce(NEW.post_deleted_time, now());
  ELSIF NOT OLD.post_deleted_flag THEN
    NEW.post_deleted_time := now();
  ELSE
    NEW.post_deleted_time := OLD.post_deleted_time;
  END IF;
  RETURN NEW;
END
$$;
""")


def add_post_deleted_time_trigger(table: Table) -> None:
    """Auto-set/clear post_deleted_time from post_deleted_flag."""
    event.listen(table, "before_create", SET_POST_DELETED_TIME)
    event.listen(table, "after_create", DDL(
        f"CREATE TRIGGER {table.name}_set_deleted_time BEFORE INSERT OR UPDATE ON public.{table.name} "
        f"FOR EACH ROW EXECUTE FUNCTION public.set_post_deleted_time()"
    ))


# AFTER INSERT OR UPDATE OF kitchen_id on all_dishes: every dish has an average_ratings row
# (zero counts) and its kitchen_id follows the dish. The counts themselves are kept up to
# date by the backend.
SYNC_AVERAGE_RATING_ROW = DDL("""
CREATE OR REPLACE FUNCTION public.sync_average_rating_row()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO public.average_ratings (dish_id, kitchen_id)
    VALUES (NEW.dish_id, NEW.kitchen_id)
    ON CONFLICT (dish_id) DO NOTHING;
  ELSE
    UPDATE public.average_ratings SET kitchen_id = NEW.kitchen_id WHERE dish_id = NEW.dish_id;
  END IF;
  RETURN NEW;
END
$$;
""")


def add_average_rating_rows(table: Table) -> None:
    """When average_ratings is created: backfill a row per existing dish and keep one per new dish."""
    event.listen(table, "after_create", SYNC_AVERAGE_RATING_ROW)
    event.listen(table, "after_create", DDL(
        f"INSERT INTO public.{table.name} (dish_id, kitchen_id) "
        f"SELECT dish_id, kitchen_id FROM public.all_dishes ON CONFLICT (dish_id) DO NOTHING"
    ))
    event.listen(table, "after_create", DDL(
        "CREATE TRIGGER all_dishes_sync_average_rating AFTER INSERT OR UPDATE OF kitchen_id "
        "ON public.all_dishes FOR EACH ROW EXECUTE FUNCTION public.sync_average_rating_row()"
    ))


def enable_rls(table: Table) -> None:
    """Turn on Row Level Security (no policies: blocks Supabase's public API)."""
    event.listen(table, "after_create", DDL(
        f"ALTER TABLE public.{table.name} ENABLE ROW LEVEL SECURITY"
    ))
