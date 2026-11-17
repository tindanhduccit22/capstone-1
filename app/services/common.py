import logging
import os
import unicodedata
from openai import OpenAI
from qdrant_client import QdrantClient


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")


COLLECTION_NAME = "cit_chatbot_collection"


CHAT_MODEL = "gpt-4o-mini"


EMBEDDING_MODEL = "text-embedding-3-small"


DEFAULT_TOP_K = 3


openai_client = OpenAI(api_key=OPENAI_API_KEY)


qdrant = QdrantClient(url=QDRANT_URL, api_key=os.getenv("QDRANT_API_KEY"))


logger = logging.getLogger("app.services.rag_service")


def normalize_lecturer_name(name : str) -> str:
    normalized = unicodedata.normalize("NFD", name.casefold())
    normalized = "".join(
        char for char in normalized
        if unicodedata.category(char) != "Mn"
    )
    return " ".join(normalized.replace("đ", "d").split())


def is_teaching_question(query: str) -> bool:
    """Tell whether the question asks about teaching, which the data does not cover."""
    return "dạy" in unicodedata.normalize("NFC", query).lower()


TEACHING_DATA_NOTE = (
    "Lưu ý: dữ liệu hiện chỉ có lĩnh vực nghiên cứu, chưa có phân công giảng dạy."
)


