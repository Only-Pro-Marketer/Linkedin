"""Data models for LinkedIn Post Research Tool."""

from dataclasses import dataclass, field
from typing import List
from enum import Enum
from datetime import datetime


class HookType(Enum):
    QUESTION = "question"
    BOLD_STATEMENT = "bold_statement"
    STORY_OPENER = "story_opener"
    STATISTIC = "statistic"
    CONTRARIAN = "contrarian"
    PERSONAL_FAILURE = "personal_failure"
    LISTICLE = "listicle"
    UNKNOWN = "unknown"


class BodyFormat(Enum):
    STORY = "story"
    LISTICLE = "listicle"
    FRAMEWORK = "framework"
    LESSON = "lesson"
    TIPS = "tips"
    UNKNOWN = "unknown"


class CTAType(Enum):
    ENGAGEMENT_QUESTION = "engagement_question"
    FOLLOW_FOR_MORE = "follow_for_more"
    LINK_IN_COMMENTS = "link_in_comments"
    SHARE_IF_AGREE = "share_if_agree"
    TAG_SOMEONE = "tag_someone"
    SOFT_SELL = "soft_sell"
    NONE = "none"


@dataclass
class LinkedInPost:
    content: str
    author: str = ""
    source_url: str = ""
    estimated_engagement: str = ""
    topic_tags: List[str] = field(default_factory=list)
    date_found: str = field(default_factory=lambda: datetime.now().isoformat())
    search_query_used: str = ""

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "author": self.author,
            "source_url": self.source_url,
            "estimated_engagement": self.estimated_engagement,
            "topic_tags": self.topic_tags,
            "date_found": self.date_found,
            "search_query_used": self.search_query_used,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LinkedInPost":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PostStructure:
    hook: str
    hook_type: HookType
    body: str
    body_format: BodyFormat
    cta: str
    cta_type: CTAType
    line_count: int
    word_count: int
    uses_line_breaks: bool
    uses_emoji: bool
    uses_hashtags: bool
    hashtags: List[str] = field(default_factory=list)
    whitespace_ratio: float = 0.0

    def to_dict(self) -> dict:
        return {
            "hook": self.hook,
            "hook_type": self.hook_type.value,
            "body": self.body,
            "body_format": self.body_format.value,
            "cta": self.cta,
            "cta_type": self.cta_type.value,
            "line_count": self.line_count,
            "word_count": self.word_count,
            "uses_line_breaks": self.uses_line_breaks,
            "uses_emoji": self.uses_emoji,
            "uses_hashtags": self.uses_hashtags,
            "hashtags": self.hashtags,
            "whitespace_ratio": self.whitespace_ratio,
        }


@dataclass
class PostTemplate:
    name: str
    hook_pattern: str
    body_pattern: str
    cta_pattern: str
    example_post: str
    fill_instructions: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "hook_pattern": self.hook_pattern,
            "body_pattern": self.body_pattern,
            "cta_pattern": self.cta_pattern,
            "example_post": self.example_post,
            "fill_instructions": self.fill_instructions,
        }


@dataclass
class PostRewrite:
    original_post: str
    rewritten_post: str
    target_niche: str
    tone: str
    changes_made: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "original_post": self.original_post,
            "rewritten_post": self.rewritten_post,
            "target_niche": self.target_niche,
            "tone": self.tone,
            "changes_made": self.changes_made,
        }
