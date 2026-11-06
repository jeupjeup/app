"""Fixed category destinations; called inside the accepted-analysis transaction."""

from __future__ import annotations

import unicodedata
from uuid import uuid4

from sqlalchemy import Connection, text

from jupjup.domain.errors import AnalysisSchemaError

CATEGORY_COLLECTIONS = {
    "food_drink": "음식·음료",
    "place_travel": "장소·여행",
    "shopping": "쇼핑",
    "study_research": "학습·연구",
    "work": "업무",
    "news_issue": "뉴스·이슈",
    "howto_recipe": "방법·레시피",
    "culture_media": "문화·미디어",
    "health_fitness": "건강·운동",
    "finance": "금융",
    "tech": "기술",
    "life_tip": "생활 팁",
    "other": "기타",
}


def add_category_collection(
    conn: Connection,
    user_id: str,
    content_id: str,
    category: object,
    now: str | None,
) -> None:
    if not isinstance(category, str) or category not in CATEGORY_COLLECTIONS:
        raise AnalysisSchemaError("분석 결과에 유효한 컬렉션 category가 없습니다")
    name = CATEGORY_COLLECTIONS[category]
    key = unicodedata.normalize("NFC", name.casefold())
    conn.execute(
        text(
            "INSERT INTO collections(id,user_id,name,name_key,color,created_at,updated_at) "
            "VALUES (:id,:u,:name,:key,'#DDB8E5',:at,:at) ON CONFLICT(user_id,name_key) DO NOTHING"
        ),
        dict(id="col_" + uuid4().hex, u=user_id, name=name, key=key, at=now),
    )
    collection_id = conn.scalar(
        text("SELECT id FROM collections WHERE user_id=:u AND name_key=:key"), dict(u=user_id, key=key)
    )
    conn.execute(
        text(
            "INSERT INTO collection_contents(collection_id,content_id,user_id) VALUES (:c,:id,:u) "
            "ON CONFLICT(collection_id,content_id) DO NOTHING"
        ),
        dict(c=collection_id, id=content_id, u=user_id),
    )
