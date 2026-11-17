"""Compatibility exports for existing callers, including the chat router."""
from app.services.answer_generator import get_lecturer_contact_answer
import json
import logging
import os
import unicodedata
import re
from threading import Lock
from time import monotonic
from collections.abc import Iterator
from openai import OpenAI
from qdrant_client import QdrantClient, models

from app.services.common import (OPENAI_API_KEY, QDRANT_URL, COLLECTION_NAME, CHAT_MODEL, EMBEDDING_MODEL, DEFAULT_TOP_K, openai_client, qdrant, logger, normalize_lecturer_name, is_teaching_question, TEACHING_DATA_NOTE)
from app.services.query_analyzer import (RESEARCH_AREAS, MAJORS, ANALYZER_PROMPT, clean_research_areas, clean_major, clean_email, clean_phone_number, analyze_query)
from app.services.retrieval.lecturer_retriever import (build_search_filter, list_lecturers, resolve_lecturer_name, retrieve_context, get_all_lecturer_information)
from app.services.answer_generator import (ANSWER_PROMPT, format_lecturer_list, format_all_lecturer_information, compare_lecturer_count)
from app.services.chat_state import (PENDING_SELECTIONS, ACTIVE_LECTURERS, SELECTION_LOCK, SELECTION_TIMEOUT, remember_active_lecturer, get_active_lecturer, save_pending_selection, get_pending_selection, clear_pending_selection, choose_lecturer)
from app.services.chat_service import (get_lecturer_display_type, is_compare_lecturer_question, generate_answer_stream)
