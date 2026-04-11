"""Aggregate and rank trending topics across all sources."""

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


def rank_topics(all_items: list[dict], limit: int = 20) -> list[dict]:
    """Rank and deduplicate topics from multiple sources.

    Items appearing in multiple sources get a relevance boost.
    Returns the top `limit` topics sorted by score.
    """
    # Group similar topics by simple keyword matching
    topic_groups: dict[str, list[dict]] = defaultdict(list)

    for item in all_items:
        topic_key = _normalize_topic(item.get("topic", ""))
        topic_groups[topic_key].append(item)

    ranked = []
    for key, items in topic_groups.items():
        # Best item from the group (highest relevance)
        best = max(items, key=lambda x: x.get("relevance_score", 0))

        # Boost score for topics appearing in multiple sources
        sources = set(item.get("source", "") for item in items)
        multi_source_boost = 0.1 * (len(sources) - 1)
        final_score = min(best.get("relevance_score", 0.5) + multi_source_boost, 1.0)

        ranked.append({
            **best,
            "relevance_score": final_score,
            "source_count": len(sources),
            "sources": list(sources),
        })

    ranked.sort(key=lambda x: x["relevance_score"], reverse=True)
    logger.info("Ranked %d unique topics from %d items", len(ranked), len(all_items))
    return ranked[:limit]


def _normalize_topic(topic: str) -> str:
    """Normalize a topic string for grouping similar topics."""
    # Lowercase, strip common words, take first 5 significant words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "and", "or", "but", "not", "this", "that", "it", "its",
        "how", "what", "why", "who", "when", "where",
    }

    words = topic.lower().split()
    significant = [w for w in words if w not in stop_words and len(w) > 2]
    return " ".join(significant[:5])
