"""Connection-only helpers shared by core commands and the app bridge."""

from datetime import UTC, datetime

from sqlalchemy import Connection, text


def release_bridge_hide(conn: Connection, user_id: str, content_id: str) -> bool:
    """Release a bridge-owned hide; the unhide trigger clears its claim."""
    result = conn.execute(
        text("""UPDATE contents SET is_hidden=0, revision=revision+1, updated_at=:now
            WHERE user_id=:user AND id=:id AND is_hidden=1 AND EXISTS (
                SELECT 1 FROM app_content_links WHERE core_user_id=:user
                AND core_content_id=:id AND hid_core=1)"""),
        {"user": user_id, "id": content_id, "now": datetime.now(UTC).isoformat()},
    )
    return result.rowcount > 0
