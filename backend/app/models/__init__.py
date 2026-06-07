"""ORM 模型聚合：确保 Base.metadata 能发现所有表。"""

from __future__ import annotations

from app.models.connection import DbConnection
from app.models.conversation import Conversation
from app.models.conversation_summary import ConversationSummary
from app.models.folder import Folder
from app.models.knowledge_document import KnowledgeDocument
from app.models.message import Message
from app.models.sql_feedback import SQLFeedback
from app.models.user_pattern import UserPattern

__all__ = [
    "DbConnection",
    "Conversation",
    "Folder",
    "ConversationSummary",
    "KnowledgeDocument",
    "Message",
    "SQLFeedback",
    "UserPattern",
]
