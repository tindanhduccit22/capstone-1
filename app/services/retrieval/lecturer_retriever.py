import unicodedata
from qdrant_client import models

from app.services.common import (COLLECTION_NAME, DEFAULT_TOP_K, EMBEDDING_MODEL, logger, normalize_lecturer_name, openai_client, qdrant)

def build_search_filter(
    lecturer_name: str | None = None,
    major_id: int | None = None,
    major: str | None = None,
    research_areas: list[str] | None = None,
    lecturer_id: int | None = None,
    email: str | None = None,
    phone_number: str | None = None,
) -> models.Filter | None:
    conditions = []

    # Each chunk stores the lecturer ID as parent_doc_id and the phone number as phone.
    if lecturer_id is not None:
        conditions.append(
            models.FieldCondition(
                key="parent_doc_id",
                match=models.MatchValue(value=lecturer_id),
            )
        )

    if email:
        conditions.append(
            models.FieldCondition(
                key="email",
                match=models.MatchValue(value=email),
            )
        )

    if phone_number:
        conditions.append(
            models.FieldCondition(
                key="phone",
                match=models.MatchValue(value=phone_number),
            )
        )

    if lecturer_name:
        conditions.append(
            models.FieldCondition(
                key="lecturer_name",
                match=models.MatchValue(value=lecturer_name),
            )
        )

    if major_id is not None:
        conditions.append(
            models.FieldCondition(
                key="major_id",
                match=models.MatchValue(value=major_id),
            )
        )

    if major is not None:
        conditions.append(
            models.FieldCondition(
                key="major",
                match=models.MatchValue(value=major),
            )
        )

    if research_areas:
        conditions.append(
            models.FieldCondition(
                key="research_areas",
                match=models.MatchAny(any=research_areas),
            )
        )
    return models.Filter(must=conditions) if conditions else None


def list_lecturers(
    major: str | None = None, research_areas: list[str] | None = None
) -> list[dict]:
    """Return matching lecturers without duplicates, most matched areas first."""
    search_filter = build_search_filter(major=major, research_areas=research_areas)
    requested_areas = research_areas or []
    lecturers = {}
    offset = None

    while True:
        # Fetch one page of points and the offset of the next page.
        points, offset = qdrant.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=search_filter,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        # Each lecturer may have several chunks, so parent_doc_id removes duplicates.
        for point in points:
            payload = point.payload or {}
            lecturer_name = payload.get("lecturer_name")

            # Skip incomplete points so an unfiltered scan cannot break sorting.
            if not lecturer_name:
                continue

            lecturer_areas = payload.get("research_areas") or []
            lecturers[payload.get("parent_doc_id")] = {
                "name": lecturer_name,
                "major": payload.get("major"),
                "matched_areas": [
                    area for area in requested_areas if area in lecturer_areas
                ],
            }

        # A next offset of None means there are no more pages.
        if offset is None:
            break

    return sorted(
        lecturers.values(),
        key=lambda lecturer: (-len(lecturer["matched_areas"]), lecturer["name"]),
    )


def resolve_lecturer_name(short_name: str) -> list[str]:
    target = " ".join(short_name.casefold().split())

    if not target:
        return []

    lecturers = list_lecturers()

    def matches_name(full_name: str, name: str) -> bool:
        return (
            full_name == name
            or full_name.endswith(" " + name)
            or full_name.startswith(name + " ")
        )

    # Priority 1: Match the ending of the name with accents preserved.
    exact_matches = [
        lecturer["name"]
        for lecturer in lecturers
        if matches_name(
            " ".join(lecturer["name"].casefold().split()),
            target,
        )
    ]

    if exact_matches:
        return list(dict.fromkeys(exact_matches))

    # Do not confuse an accented name with another name.
    has_accent = (
        "đ" in target
        or any(
            unicodedata.combining(char)
            for char in unicodedata.normalize("NFD", target)
        )
    )

    if has_accent:
        return []

    # Priority 2: Support names typed without Vietnamese accents.
    normalized_target = normalize_lecturer_name(target)

    matches = [
        lecturer["name"]
        for lecturer in lecturers
        if matches_ending(
            normalize_lecturer_name(lecturer["name"]),
            normalized_target,
        )
    ]

    return list(dict.fromkeys(matches))


def retrieve_context(
    query: str,
    lecturer_name: str | None = None,
    major_id: int | None = None,
    major: str | None = None,
    research_areas: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    lecturer_id: int | None = None,
    email: str | None = None,
    phone_number: str | None = None,
) -> str:
    """Retrieve lecturer context using vector search and optional filters."""
    query = query.strip()

    if not query:
        raise ValueError("Query must not be blank.")

    if top_k < 1:
        raise ValueError("top_k must be greater than zero.")

    try:
        # Convert the question into a vector for similarity search.
        embedding_response = openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=query,
            encoding_format="float",
        )
        query_vector = embedding_response.data[0].embedding

        # Build payload filter conditions from the provided fields.
        search_filter = build_search_filter(
            lecturer_name=lecturer_name,
            major_id=major_id,
            major=major,
            research_areas=research_areas,
            lecturer_id=lecturer_id,
            email=email,
            phone_number=phone_number,
        )
        search_results = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=search_filter,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )

        formatted_contexts = []

        for point in search_results.points:
            payload = point.payload or {}
            logger.info(
                "Hit: %s | score=%.3f", payload.get("lecturer_name"), point.score
            )
            content = payload.get("content")

            if not isinstance(content, str) or not content.strip():
                continue

            formatted_contexts.append(f"[THÔNG TIN GIẢNG VIÊN]\n{content.strip()}")

        logger.info(
            "Retrieved %d points; retained %d context chunks.",
            len(search_results.points),
            len(formatted_contexts),
        )

        return "\n\n==============================\n\n".join(formatted_contexts)

    except Exception:
        logger.exception("Context retrieval failed.")
        raise


def get_all_lecturer_information(major):
    search_filter = build_search_filter(major=major)

    lecturers = {}
    offset = None

    while True:
        points, offset = qdrant.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=search_filter,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False
        )

        for point in points:
            data = point.payload or {}

            lecturer_id = data.get("parent_doc_id")
            name = data.get("lecturer_name")

            if not name:
                continue

            if lecturer_id not in lecturers:
                lecturers[lecturer_id] = {
                    "name": name,
                    "email": data.get("email"),
                    "phone": data.get("phone"),
                    "major": data.get("major"),
                    "research_areas": data.get("research_areas", []),
                    "content": []
                }

            content = data.get("content")

            if content and content not in lecturers[lecturer_id]["content"]:
                lecturers[lecturer_id]["content"].append(content)

        if offset is None:
            break

    return sorted(
        lecturers.values(),
        key=lambda item: item["name"]
    )





def find_contact_owner_names(email, phone):
    conditions = []

    if email:
        conditions.append(
            models.FieldCondition(
                key="email",
                match=models.MatchValue(value=email),
            )
        )

    if phone:
        conditions.append(
            models.FieldCondition(
                key="phone",
                match=models.MatchValue(value=phone),
            )
        )

    search_filter = models.Filter(must=conditions)

    points, _ = qdrant.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=search_filter,
        limit=100,
        with_payload=True,
        with_vectors=False,
    )

    names = sorted({
        point.payload["lecturer_name"]
        for point in points
        if point.payload and point.payload.get("lecturer_name")
    })

    return names

def get_lecturer_research_points(lecturer_name):
    lecturer_filter = build_search_filter(
        lecturer_name=lecturer_name
    )

    points, _ = qdrant.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=lecturer_filter,
        limit=100,
        with_payload=True,
        with_vectors=False,
    )

    return points

def get_lecturer_contact_points(lecturer_name):
    search_filter = build_search_filter(
        lecturer_name=lecturer_name
    )

    points, _ = qdrant.scroll(
        collection_name=COLLECTION_NAME,
        scroll_filter=search_filter,
        limit=1,
        with_payload=True,
        with_vectors=False,
    )

    return points
