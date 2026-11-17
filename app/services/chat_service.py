from app.services.retrieval.lecturer_retriever import find_contact_owner_names, get_lecturer_research_points
from app.services.answer_generator import stream_context_answer, stream_research_answer, get_lecturer_contact_answer
import re
from collections.abc import Iterator

from app.services.common import DEFAULT_TOP_K, TEACHING_DATA_NOTE, is_teaching_question, logger, normalize_lecturer_name
from app.services.retrieval.lecturer_retriever import get_all_lecturer_information, list_lecturers, resolve_lecturer_name, retrieve_context
from app.services.answer_generator import compare_lecturer_count, format_all_lecturer_information, format_lecturer_list
from app.services.chat_state import (choose_lecturer, clear_pending_selection, get_active_lecturer, get_pending_selection, remember_active_lecturer, save_pending_selection)

def get_lecturer_display_type(query):
    text = normalize_lecturer_name(query)

    full_info_keywords = [
        "toan bo thong tin",
        "day du thong tin",
        "thong tin chi tiet",
        "thong tin day du",
        "chi tiet tat ca"
    ]

    for keyword in full_info_keywords:
        if keyword in text:
            return "full"

    name_keywords = [
        "toan bo ten",
        "tat ca ten",
        "danh sach",
        "liet ke",
        "ke ten",
        "nhung giang vien nao",
        "nhung giao vien nao",
        "ten giao vien",
        "ten giang vien"
    ]

    for keyword in name_keywords:
        if keyword in text:
            return "name"

    return None


def is_compare_lecturer_question(query):
    text = normalize_lecturer_name(query)

    compare_keywords = [
        "nganh nao co nhieu giang vien hon",
        "nganh nao nhieu giang vien hon",
        "nganh nao co it giang vien hon",
        "nganh nao it giang vien hon",
        "nganh nao dong giang vien hon",
        "so sanh so luong giang vien",
        "so sanh so giang vien",
        "moi nganh co bao nhieu giang vien",
        "moi nganh trong khoa co bao nhieu giang vien",
        "so luong giang vien cua tung nganh",
        "tung nganh co bao nhieu giang vien",
        "so giang vien cua moi nganh",
        "so giang vien tung nganh",
        "thong ke so luong giang vien theo nganh",
        "thong ke giang vien theo nganh",
        "hai nganh co bao nhieu giang vien",
        "ca hai nganh co bao nhieu giang vien"
    ]

    return any(
        keyword in text
        for keyword in compare_keywords
    )


def generate_answer_stream(
    query: str,
    filters: dict | None = None,
    top_k: int = DEFAULT_TOP_K,
    session_id: str | None = None,
) -> Iterator[str]:
    """Retrieve relevant context and stream an academic advising answer."""
    query = query.strip()

    if not query:
        yield "Bạn vui lòng nhập câu hỏi cần hỗ trợ."
        return

    try:
        filters = filters or {}


        # XU LY CAU HOI SO SANH SO LUONG GIANG VIEN
        if is_compare_lecturer_question(query):

            answer = compare_lecturer_count()

            yield answer
            return


        # EXACT-MATCH RETRIEVAL: TIM CHU SO HUU EMAIL / SO DIEN THOAI
        email = (filters.get("email") or "").strip().lower()
        phone = (
            filters.get("phone_number")
            or filters.get("phone")
            or ""
        ).strip()

        normalized_question = normalize_lecturer_name(query)

        asks_info_owner = any(
            phrase in normalized_question
            for phrase in (
                "cua ai",
                "cua thay co nao",
                "cua giang vien nao",
                "thuoc ve ai",
                "thuoc giang vien nao",
            )
        )

        if (email or phone) and asks_info_owner:
            names = find_contact_owner_names(email, phone)

            field_name = (
                "Email và số điện thoại" if email and phone
                else "Email" if email
                else "Số điện thoại"
            )

            if len(names) == 1:
                clear_pending_selection(session_id)
                remember_active_lecturer(session_id, names[0])

                yield f"{field_name} thuộc về giảng viên {names[0]}."

            elif len(names) == 0:
                yield (
                    f"Không tìm thấy giảng viên sở hữu "
                    f"{field_name.lower()} này trong dữ liệu."
                )

            else:
                yield (
                    f"{field_name} khớp với nhiều giảng viên: "
                    + ", ".join(names)
                    + ". Cần kiểm tra lại dữ liệu."
                )

            return


        # Explicit Entity Override
        # Tên giảng viên mới được ưu tiên hơn ngữ cảnh cũ.
        explicit_name = filters.get("lecturer_name")

        if explicit_name:
            matches = resolve_lecturer_name(explicit_name)

            if len(matches) == 1:
                resolved_name = matches[0]

                filters["lecturer_name"] = resolved_name
                clear_pending_selection(session_id)
                remember_active_lecturer(session_id, resolved_name)


        # ghi nhớ phiên trả lời để trả đúng kết quả của phiên đó
        pending = get_pending_selection(session_id)

        normalized_query = normalize_lecturer_name(query)

        is_followup = bool(re.search(
            r"\btrong\s+(?:hai|2|nhung|cac|danh sach|so)\b"
            r"|\b(?:hai|2)\s+(?:thay|co|giang vien)\b.*\bdo\b",
            normalized_query
        ))

        if pending and is_followup:
            research_areas = filters.get("research_areas") or []
            major = filters.get("major")

            if not research_areas and not major:
                yield "Bạn muốn tìm thông tin gì về những giảng viên vừa nêu?"
                return

            matching_lecturers = list_lecturers(
                major=major,
                research_areas=research_areas,
            )

            matching_names = {
                lecturer["name"]
                for lecturer in matching_lecturers
            }

            selected = [
                lecturer
                for lecturer in pending["candidates"]
                if lecturer["name"] in matching_names
            ]

            if len(selected) == 1:
                # ghi nhớ giảng viên đã lựa chọn
                remember_active_lecturer(session_id, selected[0]["name"])

            if not selected:
                yield (
                    "Trong danh sách giảng viên vừa nêu, "
                    "không có ai phù hợp với lĩnh vực hoặc chuyên ngành được hỏi."
                )
                return

            lines = [
                f"Trong {len(pending['candidates'])} giảng viên vừa nêu, "
                f"có {len(selected)} người phù hợp:"
            ]

            for index, lecturer in enumerate(selected, 1):
                lines.append(f"{index}. {lecturer['name']}")

            yield "\n".join(lines)
            return

        normalized_query = normalize_lecturer_name(query)

        # SỬA NGỮ CẢNH BẰNG CÁCH THÊM TỪ KHÓA CỦA CÂU HỎI MỚI
        refers_to_previous = bool(re.search(
            r"\b(?:thay|co|giang vien|nguoi)\s+(?:do|nay|ay)\b"
            r"|\b(?:cua|ve)\s+(?:thay|co|giang vien)\s*$"
            r"|\b(?:cua|ve)\s+(?:thay|co|giang vien)\s+la\s+gi\b"
            r"|\b(?:thong tin|email|lien he)\s+(?:cua\s+)?(?:thay|co)\s*$"
            r"|\b(?:thay|co|giang vien|nguoi)\s+(?:co|dang|tung|phu trach|huong dan)\b"
            r"|\b(?:thay|co|giang vien|nguoi)\s+(?:chuyen|gioi|nghien cuu|linh vuc)\b",
            normalized_query,
))

        if (
            refers_to_previous
            and not filters.get("lecturer_name")
            and filters.get("query_type") not in ("list", "list_all")
        ):
            # lấy lại giảng viên đó cho câu hỏi liên quan tiếp theo
            active_name = get_active_lecturer(session_id)

            if not active_name:
                yield (
                    "Bạn đang muốn hỏi về giảng viên nào? "
                    "Vui lòng cho biết tên giảng viên."
                )
                return

            filters = {
                "query_type": "other",
                "lecturer_name": active_name,
            }

            query = f"{query}\nGiảng viên được nhắc đến: {active_name}"

        # cho sinh viên lựa chọn nếu trả về nhiều kết quả
        pending = get_pending_selection(session_id)

        if pending:
            selected, attempted = choose_lecturer(
                query, pending["candidates"]
            )

            if attempted:
                if selected is None:
                    yield (
                        "Lựa chọn chưa xác định được. "
                        "Bạn vui lòng chọn số thứ tự hợp lệ "
                        "hoặc cung cấp họ tên đầy đủ trong danh sách."
                    )
                    return

                original_question = pending["question"]
                lecturer_name = selected["name"]

                # giúp ghi nhớ người được chọn để tiếp tục phiên đó
                remember_active_lecturer(session_id, lecturer_name)

                clear_pending_selection(session_id)

                filters = {
                    "query_type": "other",
                    "lecturer_name": lecturer_name,
                }
                query = (
                    f"{original_question}\n"
                    f"Giảng viên được chọn: {lecturer_name}"
                )
            else:
                clear_pending_selection(session_id)
        
        # HIEN THI DANH SACH HOAC THONG TIN GIANG VIEN THEO NGANH
        display_type = get_lecturer_display_type(query)
        selected_major = filters.get("major")

        if selected_major and display_type in ("name", "full"):

            if display_type == "name":
                lecturers = list_lecturers(major=selected_major)

                answer = format_lecturer_list(
                    lecturers,
                    major=selected_major
                )

            else:
                lecturers = get_all_lecturer_information(
                    selected_major
                )

                answer = format_all_lecturer_information(
                    lecturers,
                    selected_major
                )

            yield answer
            return


        # Exhaustive questions ("Có bao nhiêu...") are answered by code, others by top-k RAG.
        query_type = filters.get("query_type")
        major = filters.get("major") if query_type == "list" else None
        research_areas = filters.get("research_areas") if query_type == "list" else None

        # A plain list question needs a filter; only list_all may scan every lecturer.
        if query_type == "list_all" or major or research_areas:
            lecturers = list_lecturers(major, research_areas)
            logger.info("Found %d lecturers.", len(lecturers))
            answer = format_lecturer_list(lecturers, research_areas, major)

            if is_teaching_question(query):
                answer = f"{answer}\n\n{TEACHING_DATA_NOTE}"

            yield answer
            return

        lecturer_name = filters.get("lecturer_name")

        if lecturer_name:
            matches = resolve_lecturer_name(lecturer_name)

            if len(matches) > 1:
                candidates = [
                    item for item in list_lecturers()
                    if item["name"] in matches
                ]

                save_pending_selection(session_id, query, candidates)

                lines = [
                    f"Tôi tìm thấy {len(candidates)} giảng viên "
                    f"phù hợp với tên '{lecturer_name}':"
                ]

                for index, item in enumerate(candidates, start=1):
                    major = item.get("major") or "Chưa có thông tin ngành"
                    lines.append(
                        f"{index}. {item['name']} - Ngành {major}"
                    )

                if session_id:
                    lines.append(
                        "\nBạn muốn xem giảng viên nào? "
                        "Hãy trả lời bằng số thứ tự hoặc họ tên."
                    )
                else:
                    lines.append(
                        "\nBạn vui lòng cung cấp họ tên đầy đủ."
                    )

                yield "\n".join(lines)
                return

            if len(matches) == 1:
                lecturer_name = matches[0]
                remember_active_lecturer(session_id, lecturer_name)

        if lecturer_name:
            contact_answer = get_lecturer_contact_answer(
                lecturer_name=lecturer_name,
                query=query,
            )

            if contact_answer is not None:
                remember_active_lecturer(session_id, lecturer_name)
                yield contact_answer
                return


        # XÁC ĐỊNH CHÍNH XÁC LĨNH VỰC NGHIÊN CỨU CỦA GIẢNG VIÊN
        requested_areas = filters.get("research_areas") or []

        if lecturer_name and requested_areas:
            points = get_lecturer_research_points(lecturer_name)

            if points:
                yield from stream_research_answer(lecturer_name, requested_areas, points)
                return


        context = retrieve_context(
            query,
            lecturer_name=lecturer_name,
            major_id=filters.get("major_id"),
            major=filters.get("major"),
            research_areas=filters.get("research_areas"),
            top_k=top_k,
            lecturer_id=filters.get("lecturer_id"),
            email=filters.get("email"),
            phone_number=filters.get("phone_number"),
        )

        if not context:
            yield (
                "Hiện mình chưa tìm thấy thông tin phù hợp trong dữ liệu "
                "của hệ thống. Bạn có thể cung cấp thêm tên giảng viên, "
                "chuyên ngành hoặc lĩnh vực nghiên cứu cần tìm không?"
            )
            return

        # https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create
        yield from stream_context_answer(query, context)

    except Exception:
        # Let the router return HTTP 500, or abort the connection once streaming started.
        logger.exception("Answer generation failed.")
        raise


