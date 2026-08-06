"""
Memory Intelligence Layer — natural retrieval, topics, timeline, learning graph,
roadmaps, concept capsules, duplicate knowledge, creators, and insights.

All insights are derived from stored user memories. No fabricated relationships.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import Settings, get_settings
from app.db.intelligence_store import IntelligenceStore, normalize_topic
from app.db.schema import get_connection, migrate
from app.db.video_registry import get_video_registry
from app.db.youtube_memory_store import YouTubeMemoryStore
from app.models.capsule import MemoryCapsule
from app.models.intelligence import (
    ConceptCapsule,
    ConceptCapsuleListResponse,
    CreatorListResponse,
    CreatorProfile,
    DuplicateKnowledgeItem,
    DuplicateKnowledgeResponse,
    ExplanationBlock,
    InsightsDashboard,
    IntelligenceHit,
    LearningEdge,
    LearningGraphResponse,
    LearningRelation,
    LearningRoadmap,
    NaturalRetrieveResponse,
    RoadmapLevel,
    RoadmapStep,
    TimelineEntry,
    TimelineMode,
    TimelineResponse,
    TopicCategory,
    TopicListResponse,
    TopicProfile,
)
from app.models.reflection import ReflectionInput
from app.models.video import SearchFilters, VideoMetadata
from app.services.enrichment_service import build_why_matched
from app.services.search_service import SearchService
from app.services.youtube_duplicate_service import YouTubeDuplicateDetector

_LANGUAGE_NAMES = frozenset(
    {"python", "javascript", "typescript", "rust", "go", "java", "ruby", "php", "c++", "c#", "swift", "kotlin"}
)
_FRAMEWORKS = frozenset(
    {"react", "django", "flask", "fastapi", "nextjs", "next.js", "vue", "angular", "rails", "spring"}
)
_TECH = frozenset(
    {
        "docker",
        "kubernetes",
        "k8s",
        "rag",
        "mcp",
        "llm",
        "gpu",
        "postgres",
        "redis",
        "chroma",
        "vector",
        "embedding",
        "langchain",
        "ollama",
    }
)
_BEGINNER_RE = re.compile(r"\b(beginner|intro|introduction|basics?|getting started|101|for beginners)\b", re.I)
_ADVANCED_RE = re.compile(r"\b(advanced|deep dive|internals?|production|expert|mastery)\b", re.I)
_CONTRADICT_RE = re.compile(r"\b(vs\.?|versus|myth|wrong|don't|do not|instead of|contrary|debate)\b", re.I)
_EXPAND_RE = re.compile(r"\b(advanced|deep|part\s*[2-9]|continued|beyond|next level)\b", re.I)


def load_capsule_json(settings: Settings, video_id: str) -> MemoryCapsule | None:
    migrate(settings)
    with get_connection(settings) as conn:
        row = conn.execute(
            "SELECT capsule_json FROM memory_capsules_json WHERE video_id = ?",
            (video_id,),
        ).fetchone()
    if not row:
        return None
    try:
        return MemoryCapsule.model_validate_json(row["capsule_json"])
    except Exception:
        return None


class MemoryIntelligenceService:
    """Facade over intelligence aggregates + AHME search."""

    def __init__(
        self,
        settings: Settings | None = None,
        store: IntelligenceStore | None = None,
        search: SearchService | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._store = store or IntelligenceStore(self._settings)
        self._search = search or SearchService(settings=self._settings)
        self._yt = YouTubeMemoryStore(self._settings)
        self._registry = get_video_registry(self._settings)
        self._dupes = YouTubeDuplicateDetector(self._yt)

    # ── Incremental ingest hook ─────────────────────────────────────────

    def on_memory_indexed(
        self,
        *,
        user_id: str,
        metadata: VideoMetadata,
        capsule: MemoryCapsule,
        reflection: ReflectionInput | None = None,
        memory_id: str | None = None,
    ) -> dict[str, int]:
        """Update topics, creators, edges, capsules incrementally after ingest."""
        counts = {"topics": 0, "edges": 0, "creators": 0, "capsules": 0}
        self._store.record_event(
            user_id=user_id,
            event_type="save",
            video_id=metadata.video_id,
            topic=(capsule.topics[0] if capsule.topics else None),
        )

        topic_names: list[str] = []
        for topic in capsule.topics:
            cat = self._classify_topic(topic)
            profile = self._store.upsert_topic(
                user_id=user_id,
                name=topic,
                category=cat,
                evidence=f"capsule topic on {metadata.video_id}: {metadata.title}",
                video_id=metadata.video_id,
                memory_id=memory_id,
                strength=1.0,
                summary_hint=capsule.short_summary or capsule.one_line_memory or metadata.title,
            )
            topic_names.append(profile.name)
            counts["topics"] += 1

        for entity in capsule.entities + capsule.tools_or_components:
            cat = self._classify_topic(entity)
            self._store.upsert_topic(
                user_id=user_id,
                name=entity,
                category=cat,
                evidence=f"entity on {metadata.video_id}",
                video_id=metadata.video_id,
                memory_id=memory_id,
                strength=0.8,
                summary_hint=metadata.title,
            )
            topic_names.append(entity)
            counts["topics"] += 1

        if reflection and reflection.goal:
            self._store.upsert_topic(
                user_id=user_id,
                name=reflection.goal,
                category=TopicCategory.PROJECT,
                evidence=f"user goal on save of {metadata.video_id}",
                video_id=metadata.video_id,
                memory_id=memory_id,
                strength=0.9,
            )
            counts["topics"] += 1

        text_blob = f"{metadata.title} {metadata.description} {capsule.short_summary}"
        beginner = bool(_BEGINNER_RE.search(text_blob)) or (
            reflection is not None and (reflection.difficulty or "").lower() == "beginner"
        )
        advanced = bool(_ADVANCED_RE.search(text_blob)) or (
            reflection is not None and (reflection.difficulty or "").lower() == "advanced"
        )

        if metadata.channel:
            # Recompute creator profile from all saved videos for this channel (idempotent).
            channel_videos = [
                m
                for m in self._yt.list_for_user(user_id, limit=500)
                if m.channel == metadata.channel
            ]
            if not any(m.video_id == metadata.video_id for m in channel_videos):
                # Current video may not be flushed yet — include metadata snapshot.
                pass
            topics_set: list[str] = list(dict.fromkeys(topic_names))[:20]
            total_dur = sum(float(m.duration_sec or 0) for m in channel_videos)
            # Ensure current video duration counted once
            if not any(m.video_id == metadata.video_id for m in channel_videos):
                total_dur += float(metadata.duration or 0)
                video_n = len(channel_videos) + 1
            else:
                video_n = max(len(channel_videos), 1)
            beg = sum(
                1
                for m in channel_videos
                if _BEGINNER_RE.search(f"{m.title} {m.description}")
            )
            adv = sum(
                1
                for m in channel_videos
                if _ADVANCED_RE.search(f"{m.title} {m.description}")
            )
            if beginner and not any(m.video_id == metadata.video_id for m in channel_videos):
                beg += 1
            if advanced and not any(m.video_id == metadata.video_id for m in channel_videos):
                adv += 1
            self._store.replace_creator_stats(
                user_id=user_id,
                name=metadata.channel,
                channel_id=metadata.channel_id or "",
                topics=topics_set,
                video_count=video_n,
                total_duration_sec=total_dur,
                beginner_count=beg,
                advanced_count=adv,
            )
            counts["creators"] += 1

        counts["edges"] += self._link_to_peers(
            user_id=user_id,
            metadata=metadata,
            capsule=capsule,
            topic_names=topic_names,
            beginner=beginner,
            advanced=advanced,
        )

        for name in list(dict.fromkeys(topic_names))[:12]:
            self._refresh_concept_capsule(user_id=user_id, topic_name=name)
            counts["capsules"] += 1

        return counts

    def _link_to_peers(
        self,
        *,
        user_id: str,
        metadata: VideoMetadata,
        capsule: MemoryCapsule,
        topic_names: list[str],
        beginner: bool,
        advanced: bool,
    ) -> int:
        created = 0
        peer_ids: set[str] = set()
        for name in topic_names[:8]:
            topic = self._store.find_topic_by_name(name, user_id=user_id)
            if not topic:
                continue
            for vid in topic.video_ids:
                if vid != metadata.video_id:
                    peer_ids.add(vid)

        source_topics = {normalize_topic(t) for t in topic_names}
        source_text = f"{metadata.title} {capsule.short_summary}".lower()

        for peer_id in list(peer_ids)[:30]:
            peer = self._yt.get(peer_id, user_id=user_id)
            peer_capsule = load_capsule_json(self._settings, peer_id)
            peer_topic_names = (
                list(peer_capsule.topics)
                if peer_capsule and peer_capsule.topics
                else [t.name for t in self._store.topics_for_video(peer_id, user_id=user_id)]
            )
            peer_topics = {normalize_topic(t) for t in peer_topic_names}
            shared = sorted(source_topics & peer_topics)
            if not shared and peer and peer.channel == metadata.channel:
                self._store.upsert_edge(
                    user_id=user_id,
                    source_video_id=metadata.video_id,
                    target_video_id=peer_id,
                    relation=LearningRelation.SAME_CREATOR,
                    strength=0.55,
                    evidence=f"Same creator '{metadata.channel}'",
                    evidence_refs=[metadata.channel],
                    source_title=metadata.title,
                    target_title=peer.title if peer else peer_id,
                )
                created += 1
                continue
            if not shared:
                continue

            shared_label = ", ".join(shared[:5])
            self._store.upsert_edge(
                user_id=user_id,
                source_video_id=metadata.video_id,
                target_video_id=peer_id,
                relation=LearningRelation.SAME_TOPIC,
                strength=min(1.0, 0.4 + 0.1 * len(shared)),
                evidence=f"Shared topics: {shared_label}",
                evidence_refs=shared[:5],
                source_title=metadata.title,
                target_title=peer.title if peer else (peer_capsule.title if peer_capsule else peer_id),
            )
            created += 1

            peer_text = (
                f"{peer.title if peer else ''} "
                f"{peer_capsule.short_summary if peer_capsule else ''}"
            ).lower()
            if _CONTRADICT_RE.search(source_text) or _CONTRADICT_RE.search(peer_text):
                self._store.upsert_edge(
                    user_id=user_id,
                    source_video_id=metadata.video_id,
                    target_video_id=peer_id,
                    relation=LearningRelation.CONTRADICTS,
                    strength=0.5,
                    evidence=f"Contrast language + shared topics ({shared_label})",
                    evidence_refs=shared[:3],
                )
                created += 1
            elif advanced and not beginner:
                self._store.upsert_edge(
                    user_id=user_id,
                    source_video_id=metadata.video_id,
                    target_video_id=peer_id,
                    relation=LearningRelation.EXPANDS,
                    strength=0.6,
                    evidence=f"Advanced language expands shared topic ({shared_label})",
                    evidence_refs=shared[:3],
                )
                created += 1
            elif beginner:
                self._store.upsert_edge(
                    user_id=user_id,
                    source_video_id=metadata.video_id,
                    target_video_id=peer_id,
                    relation=LearningRelation.EXPLAINS,
                    strength=0.55,
                    evidence=f"Introductory language explains shared topic ({shared_label})",
                    evidence_refs=shared[:3],
                )
                created += 1
            elif _EXPAND_RE.search(source_text):
                self._store.upsert_edge(
                    user_id=user_id,
                    source_video_id=metadata.video_id,
                    target_video_id=peer_id,
                    relation=LearningRelation.EXPANDS,
                    strength=0.5,
                    evidence=f"Expansion cues + shared topics ({shared_label})",
                    evidence_refs=shared[:3],
                )
                created += 1

            if advanced and any(_BEGINNER_RE.search(t) for t in peer_topic_names):
                self._store.upsert_edge(
                    user_id=user_id,
                    source_video_id=peer_id,
                    target_video_id=metadata.video_id,
                    relation=LearningRelation.ASSUMES,
                    strength=0.45,
                    evidence="Beginner peer topic may be assumed by advanced video",
                    evidence_refs=shared[:3],
                )
                created += 1

        return created

    def _refresh_concept_capsule(self, *, user_id: str, topic_name: str) -> ConceptCapsule | None:
        topic = self._store.find_topic_by_name(topic_name, user_id=user_id)
        if not topic or topic.memory_count < 1:
            return None
        creators: list[str] = []
        summaries: list[str] = []
        for vid in topic.video_ids[:20]:
            mem = self._yt.get(vid, user_id=user_id)
            if mem and mem.channel:
                creators.append(mem.channel)
            cap = load_capsule_json(self._settings, vid)
            if cap and (cap.short_summary or cap.one_line_memory):
                summaries.append(cap.short_summary or cap.one_line_memory)
            elif mem:
                summaries.append(mem.title)
        summary = topic.summary or "; ".join(summaries[:3])
        if not summary:
            summary = f"Saved memories about {topic.name}."
        return self._store.upsert_concept_capsule(
            user_id=user_id,
            name=topic.name,
            summary=summary[:1000],
            topic_ids=[topic.topic_id],
            video_ids=topic.video_ids,
            creators=list(dict.fromkeys(creators))[:12],
            progress_completed=len(topic.video_ids),
        )

    @staticmethod
    def _classify_topic(name: str) -> TopicCategory:
        n = normalize_topic(name)
        if n in _LANGUAGE_NAMES:
            return TopicCategory.LANGUAGE
        if n in _FRAMEWORKS or n.replace(" ", "") in {f.replace(".", "") for f in _FRAMEWORKS}:
            return TopicCategory.FRAMEWORK
        if n in _TECH or any(t in n for t in ("llm", "rag", "mcp", "docker", "kubern")):
            return TopicCategory.TECHNOLOGY
        if n.endswith(" inc") or n.endswith(" ltd") or "company" in n:
            return TopicCategory.COMPANY
        return TopicCategory.TOPIC

    # ── Feature 1+2: Natural retrieval + explainability ─────────────────

    def retrieve(
        self,
        query: str,
        *,
        user_id: str,
        limit: int = 5,
        filters: SearchFilters | None = None,
    ) -> NaturalRetrieveResponse:
        started = time.perf_counter()
        search_path = [
            "parse_natural_query",
            "ahme_hybrid_retrieve",
            "metadata_transcript_fusion",
            "enrich_why_matched",
            "attach_entities_related",
        ]
        self._store.record_event(user_id=user_id, event_type="search", query=query)

        base = self._search.search(
            query, limit=max(limit * 2, limit), user_id=user_id, filters=filters
        )
        hits: list[IntelligenceHit] = []
        for idx, item in enumerate(base.results[:limit]):
            entities = [t.name for t in self._store.topics_for_video(item.video_id, user_id=user_id)]
            related_ids = self._related_video_ids(item.video_id, user_id=user_id, limit=5)
            alternatives = [
                r.video_id
                for r in base.results
                if r.video_id != item.video_id
            ][:5]
            conf = item.confidence if item.confidence is not None else min(1.0, max(0.0, item.relevance_score))
            why = item.why_matched or build_why_matched(
                query=query,
                matched_text=item.matched_text,
                title=item.title,
                description="",
                relevance_score=item.relevance_score,
                start_time=item.start_time,
            )
            explanation = ExplanationBlock(
                why=why,
                matching_chunks=[item.matched_text] if item.matched_text else [],
                matching_metadata=list(item.matching_metadata),
                matched_entities=entities[:12],
                confidence=conf,
                alternative_video_ids=alternatives,
                related_video_ids=related_ids,
                search_path=search_path + [f"rank_position_{idx + 1}"],
                evidence_refs=[
                    f"video:{item.video_id}",
                    *(f"entity:{e}" for e in entities[:5]),
                ],
            )
            # Ensure every hit carries explanation on the nested result too
            enriched = item.model_copy(
                update={
                    "related_video_ids": related_ids or item.related_video_ids,
                    "confidence": conf,
                }
            )
            hits.append(IntelligenceHit(result=enriched, explanation=explanation))

        return NaturalRetrieveResponse(
            query=query,
            results=hits,
            search_path=search_path,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    def _related_video_ids(self, video_id: str, *, user_id: str, limit: int = 5) -> list[str]:
        """Related IDs from learning edges + shared topics (no embedding calls)."""
        scored: dict[str, float] = {}
        for edge in self._store.edges_for_video(video_id, user_id=user_id, limit=30):
            other = edge.target_video_id if edge.source_video_id == video_id else edge.source_video_id
            scored[other] = max(scored.get(other, 0.0), edge.strength)
        for topic in self._store.topics_for_video(video_id, user_id=user_id):
            for peer in topic.video_ids:
                if peer != video_id:
                    scored[peer] = max(scored.get(peer, 0.0), 0.4)
        return [vid for vid, _ in sorted(scored.items(), key=lambda kv: kv[1], reverse=True)[:limit]]

    # ── Feature 3: Topic discovery ──────────────────────────────────────

    def list_topics(self, *, user_id: str, limit: int = 50) -> TopicListResponse:
        topics = self._store.list_topics(user_id, limit=limit)
        return TopicListResponse(topics=topics, total=len(topics))

    def get_topic(self, topic_or_name: str, *, user_id: str) -> TopicProfile | None:
        topic = self._store.get_topic(topic_or_name, user_id=user_id)
        if topic:
            return topic
        return self._store.find_topic_by_name(topic_or_name, user_id=user_id)

    # ── Feature 4: Timeline ─────────────────────────────────────────────

    def timeline(
        self,
        *,
        user_id: str,
        mode: TimelineMode = TimelineMode.RECENTLY_SAVED,
        topic: str | None = None,
        limit: int = 30,
    ) -> TimelineResponse:
        memories = self._yt.list_for_user(user_id, limit=200)
        if topic:
            profile = self._store.find_topic_by_name(topic, user_id=user_id)
            allowed = set(profile.video_ids) if profile else set()
            memories = [m for m in memories if m.video_id in allowed]

        entries: list[TimelineEntry] = []
        for mem in memories:
            usage = self._registry.get_usage(mem.video_id)
            topics = [t.name for t in self._store.topics_for_video(mem.video_id, user_id=user_id)]
            entries.append(
                TimelineEntry(
                    video_id=mem.video_id,
                    title=mem.title,
                    channel=mem.channel,
                    url=mem.url,
                    saved_at=mem.saved_at,
                    published_at=mem.published_at,
                    topics=topics,
                    view_count=usage.view_count,
                    search_count=usage.search_count,
                    reason="",
                )
            )

        if mode == TimelineMode.RECENTLY_SAVED:
            entries.sort(key=lambda e: e.saved_at or "", reverse=True)
            for e in entries:
                e.reason = "Sorted by save timestamp (newest first)."
        elif mode == TimelineMode.FIRST_LEARNED:
            entries.sort(key=lambda e: e.saved_at or "")
            for e in entries:
                e.reason = "Sorted by first save timestamp (oldest first)."
        elif mode == TimelineMode.MOST_REVISITED:
            entries.sort(key=lambda e: (e.view_count + e.search_count), reverse=True)
            for e in entries:
                e.reason = f"Revisited via {e.view_count} views + {e.search_count} searches."
        elif mode == TimelineMode.RECENTLY_LEARNED:
            entries.sort(
                key=lambda e: (e.view_count > 0, e.saved_at or ""),
                reverse=True,
            )
            for e in entries:
                e.reason = "Prioritizes viewed memories, then recent saves."
        elif mode == TimelineMode.TOPIC_EVOLUTION:
            entries.sort(key=lambda e: e.saved_at or "")
            for e in entries:
                e.reason = f"Chronological topic evolution: {', '.join(e.topics[:4]) or 'untagged'}."

        return TimelineResponse(mode=mode, topic=topic, entries=entries[:limit])

    # ── Feature 5: Learning graph ───────────────────────────────────────

    def learning_graph(
        self,
        *,
        user_id: str,
        video_id: str | None = None,
        topic: str | None = None,
        limit: int = 50,
    ) -> LearningGraphResponse:
        if video_id:
            edges = self._store.edges_for_video(video_id, user_id=user_id, limit=limit)
            nodes = {video_id}
            for e in edges:
                nodes.add(e.source_video_id)
                nodes.add(e.target_video_id)
            return LearningGraphResponse(
                video_id=video_id, edges=self._annotate_edges(edges, user_id), node_count=len(nodes)
            )
        if topic:
            profile = self._store.find_topic_by_name(topic, user_id=user_id)
            vids = profile.video_ids if profile else []
            edges = self._store.edges_for_topic_videos(vids, user_id=user_id, limit=limit)
            return LearningGraphResponse(
                topic=topic,
                edges=self._annotate_edges(edges, user_id),
                node_count=len(vids),
            )
        # Global: top edges across recent memories
        all_edges: list[LearningEdge] = []
        for mem in self._yt.list_for_user(user_id, limit=40):
            all_edges.extend(self._store.edges_for_video(mem.video_id, user_id=user_id, limit=10))
        dedup: dict[str, LearningEdge] = {e.edge_id: e for e in all_edges}
        ranked = sorted(dedup.values(), key=lambda e: e.strength, reverse=True)[:limit]
        nodes: set[str] = set()
        for e in ranked:
            nodes.add(e.source_video_id)
            nodes.add(e.target_video_id)
        return LearningGraphResponse(
            edges=self._annotate_edges(ranked, user_id), node_count=len(nodes)
        )

    def _annotate_edges(self, edges: list[LearningEdge], user_id: str) -> list[LearningEdge]:
        out: list[LearningEdge] = []
        for e in edges:
            src = self._yt.get(e.source_video_id, user_id=user_id)
            tgt = self._yt.get(e.target_video_id, user_id=user_id)
            out.append(
                e.model_copy(
                    update={
                        "source_title": src.title if src else e.source_title,
                        "target_title": tgt.title if tgt else e.target_title,
                    }
                )
            )
        return out

    # ── Feature 6: Learning roadmap ─────────────────────────────────────

    def roadmap(self, topic: str, *, user_id: str) -> LearningRoadmap:
        profile = self._store.find_topic_by_name(topic, user_id=user_id)
        if not profile:
            return LearningRoadmap(
                topic=topic,
                missing_prerequisites=[f"No saved memories found for '{topic}'."],
            )

        steps: list[RoadmapStep] = []
        for vid in profile.video_ids:
            mem = self._yt.get(vid, user_id=user_id)
            if not mem:
                continue
            blob = f"{mem.title} {mem.description}".lower()
            cap = load_capsule_json(self._settings, vid)
            if cap:
                blob += f" {cap.short_summary}".lower()
            if _BEGINNER_RE.search(blob) or (mem.duration_sec or 0) < 600:
                level = RoadmapLevel.BEGINNER
                reason = "Intro keywords or short duration from saved metadata."
            elif _ADVANCED_RE.search(blob) or (mem.duration_sec or 0) > 1800:
                level = RoadmapLevel.ADVANCED
                reason = "Advanced keywords or long duration from saved metadata."
            else:
                level = RoadmapLevel.INTERMEDIATE
                reason = "Default intermediate: saved memory covers the topic."
            steps.append(
                RoadmapStep(
                    level=level,
                    video_id=vid,
                    title=mem.title,
                    channel=mem.channel,
                    url=mem.url,
                    duration_sec=mem.duration_sec,
                    reason=reason,
                    completed=True,
                    evidence=[f"topic:{profile.normalized_name}", f"video:{vid}"],
                )
            )

        beginner = [s for s in steps if s.level == RoadmapLevel.BEGINNER]
        intermediate = [s for s in steps if s.level == RoadmapLevel.INTERMEDIATE]
        advanced = [s for s in steps if s.level == RoadmapLevel.ADVANCED]
        # Stable watch order: beginner → intermediate → advanced, then duration asc
        ordered = sorted(
            steps,
            key=lambda s: (
                {"beginner": 0, "intermediate": 1, "advanced": 2}[s.level.value],
                s.duration_sec if s.duration_sec is not None else 10**9,
            ),
        )
        order_ids = [s.video_id for s in ordered]

        # Missing prerequisites: assumes edges pointing into topic videos from outside
        missing: list[str] = []
        edges = self._store.edges_for_topic_videos(profile.video_ids, user_id=user_id, limit=100)
        assumed_topics: set[str] = set()
        for e in edges:
            if e.relation == LearningRelation.ASSUMES:
                for ref in e.evidence_refs:
                    if ref and ref not in profile.normalized_name:
                        assumed_topics.add(ref)
        for name in sorted(assumed_topics):
            other = self._store.find_topic_by_name(name, user_id=user_id)
            if other is None or other.memory_count == 0:
                missing.append(name)

        suggested = ordered[-1:] if ordered else []
        if len(ordered) >= 2:
            suggested = [ordered[min(1, len(ordered) - 1)]]

        return LearningRoadmap(
            topic=profile.name,
            beginner=beginner,
            intermediate=intermediate,
            advanced=advanced,
            missing_prerequisites=missing,
            recommended_order=order_ids,
            already_completed=order_ids,
            suggested_next=suggested,
            evidence_only=True,
        )

    # ── Feature 7: Concept capsules ─────────────────────────────────────

    def list_capsules(self, *, user_id: str, limit: int = 50) -> ConceptCapsuleListResponse:
        # Ensure capsules exist for top topics
        for topic in self._store.list_topics(user_id, limit=20):
            self._refresh_concept_capsule(user_id=user_id, topic_name=topic.name)
        capsules = self._store.list_concept_capsules(user_id, limit=limit)
        return ConceptCapsuleListResponse(capsules=capsules, total=len(capsules))

    def get_capsule(self, capsule_id: str, *, user_id: str) -> ConceptCapsule | None:
        return self._store.get_concept_capsule(capsule_id, user_id=user_id)

    # ── Feature 8: Duplicate knowledge ──────────────────────────────────

    def duplicate_knowledge(self, *, user_id: str, limit: int = 40) -> DuplicateKnowledgeResponse:
        memories = self._yt.list_for_user(user_id, limit=100)
        items: list[DuplicateKnowledgeItem] = []
        seen_pairs: set[tuple[str, str]] = set()

        for mem in memories:
            # Exact / near video duplicates
            report = self._dupes.check_memory(mem, user_id=user_id)
            if report.is_duplicate and report.duplicate_of:
                pair = tuple(sorted([mem.video_id, report.duplicate_of]))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    other = self._yt.get(report.duplicate_of, user_id=user_id)
                    items.append(
                        DuplicateKnowledgeItem(
                            video_id_a=pair[0],
                            video_id_b=pair[1],
                            title_a=mem.title if mem.video_id == pair[0] else (other.title if other else ""),
                            title_b=mem.title if mem.video_id == pair[1] else (other.title if other else ""),
                            relationship=report.reason or "duplicate",
                            diversity_score=0.05,
                            evidence=report.reason or "Duplicate detector match",
                        )
                    )

            topics = {t.normalized_name for t in self._store.topics_for_video(mem.video_id, user_id=user_id)}
            for other in memories:
                if other.video_id <= mem.video_id:
                    continue
                pair = (mem.video_id, other.video_id)
                if pair in seen_pairs:
                    continue
                other_topics = {
                    t.normalized_name for t in self._store.topics_for_video(other.video_id, user_id=user_id)
                }
                shared = sorted(topics & other_topics)
                if len(shared) < 1:
                    continue
                # Diversity from title similarity + shared topic ratio
                title_sim = _token_jaccard(mem.title, other.title)
                topic_overlap = len(shared) / max(len(topics | other_topics), 1)
                if title_sim < 0.25 and topic_overlap < 0.4:
                    continue
                seen_pairs.add(pair)
                diversity = round(1.0 - (0.6 * title_sim + 0.4 * topic_overlap), 3)
                relationship = (
                    "nearly_identical_tutorial"
                    if title_sim > 0.7
                    else "repeated_concept"
                    if topic_overlap > 0.6
                    else "different_explanations_same_concept"
                )
                items.append(
                    DuplicateKnowledgeItem(
                        video_id_a=mem.video_id,
                        video_id_b=other.video_id,
                        title_a=mem.title,
                        title_b=other.title,
                        relationship=relationship,
                        diversity_score=max(0.0, min(1.0, diversity)),
                        shared_topics=shared[:8],
                        evidence=f"Shared topics {', '.join(shared[:5])}; title Jaccard={title_sim:.2f}",
                    )
                )
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break

        avg = sum(i.diversity_score for i in items) / len(items) if items else 0.0
        return DuplicateKnowledgeResponse(items=items[:limit], average_diversity=round(avg, 3))

    # ── Feature 9: Creator intelligence ─────────────────────────────────

    def list_creators(self, *, user_id: str, limit: int = 50) -> CreatorListResponse:
        # Refresh most-watched / most-useful from registry usage
        creators = self._store.list_creators(user_id, limit=limit)
        enriched: list[CreatorProfile] = []
        for c in creators:
            channel_memories = [
                m for m in self._yt.list_for_user(user_id, limit=200) if normalize_topic(m.channel) == c.normalized_name or m.channel == c.name
            ]
            most_watched = None
            most_useful = None
            best_views = -1
            best_helpful = -1
            overlap: set[str] = set()
            for m in channel_memories:
                usage = self._registry.get_usage(m.video_id)
                if usage.view_count > best_views:
                    best_views = usage.view_count
                    most_watched = m.video_id
                if usage.helpful_count > best_helpful:
                    best_helpful = usage.helpful_count
                    most_useful = m.video_id
                for t in self._store.topics_for_video(m.video_id, user_id=user_id):
                    overlap.add(t.name)
            # Related creators: share topics
            related: list[str] = list(c.related_creators)
            for other in creators:
                if other.creator_id == c.creator_id:
                    continue
                shared = set(c.topics_covered) & set(other.topics_covered)
                if shared and other.name not in related:
                    related.append(other.name)
            enriched.append(
                c.model_copy(
                    update={
                        "most_watched_video_id": most_watched,
                        "most_useful_video_id": most_useful,
                        "overlap_topics": sorted(overlap)[:20],
                        "related_creators": related[:12],
                    }
                )
            )
        return CreatorListResponse(creators=enriched, total=len(enriched))

    def get_creator(self, name_or_id: str, *, user_id: str) -> CreatorProfile | None:
        c = self._store.get_creator(name_or_id, user_id=user_id)
        if c:
            return c
        return self._store.find_creator_by_name(name_or_id, user_id=user_id)

    # ── Feature 10: Insights dashboard ──────────────────────────────────

    def insights(self, *, user_id: str) -> InsightsDashboard:
        topics = self._store.list_topics(user_id, limit=100)
        top_topics = topics[:10]

        # Most saved concepts = topic names by memory_count
        most_saved = [t.name for t in topics[:15]]

        # Most searched: agent_search_events + intelligence search events
        search_counts: dict[str, int] = {}
        for ev in self._store.recent_events(user_id, event_type="search", limit=300):
            q = (ev.get("query") or "").strip().lower()
            if not q:
                continue
            for t in topics:
                if t.normalized_name and t.normalized_name in q:
                    search_counts[t.name] = search_counts.get(t.name, 0) + 1
        # Also agent_search_events
        migrate(self._settings)
        with get_connection(self._settings) as conn:
            rows = conn.execute(
                """
                SELECT query FROM agent_search_events
                WHERE user_id = ? ORDER BY created_at DESC LIMIT 300
                """,
                (user_id,),
            ).fetchall()
        for row in rows:
            q = (row["query"] or "").lower()
            for t in topics:
                if t.normalized_name and t.normalized_name in q:
                    search_counts[t.name] = search_counts.get(t.name, 0) + 1
        most_searched = [
            name for name, _ in sorted(search_counts.items(), key=lambda kv: kv[1], reverse=True)[:15]
        ]

        # Forgotten: topics with last_seen older than 30 days and low search
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        forgotten = [
            t
            for t in topics
            if t.last_seen_at < cutoff and t.name not in most_searched[:5]
        ][:10]

        # Learning streak: consecutive calendar days with saves
        dates = self._store.save_dates(user_id)
        streak = _streak_days(dates)

        # Growth series
        memory_growth = _growth_series(
            [m.saved_at for m in self._yt.list_for_user(user_id, limit=500) if m.saved_at]
        )
        knowledge_growth = _growth_series([t.first_seen_at for t in topics if t.first_seen_at])

        creators = self._store.list_creators(user_id, limit=200)
        return InsightsDashboard(
            top_topics=top_topics,
            most_saved_concepts=most_saved,
            most_searched_concepts=most_searched,
            forgotten_topics=forgotten,
            learning_streak_days=streak,
            knowledge_growth=knowledge_growth,
            memory_growth=memory_growth,
            total_memories=len(self._yt.list_for_user(user_id, limit=5000)),
            total_topics=len(topics),
            total_creators=len(creators),
            total_learning_edges=self._store.count_edges(user_id),
        )


def _token_jaccard(a: str, b: str) -> float:
    ta = {t for t in re.findall(r"[a-z0-9]+", a.lower()) if len(t) > 2}
    tb = {t for t in re.findall(r"[a-z0-9]+", b.lower()) if len(t) > 2}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _streak_days(dates_desc: list[str]) -> int:
    if not dates_desc:
        return 0
    unique = sorted(set(dates_desc), reverse=True)
    today = datetime.now(timezone.utc).date()
    streak = 0
    expected = today
    for d in unique:
        try:
            day = datetime.fromisoformat(d).date() if "T" not in d else datetime.fromisoformat(d).date()
        except ValueError:
            try:
                day = datetime.strptime(d, "%Y-%m-%d").date()
            except ValueError:
                continue
        if day == expected or (streak == 0 and day == expected - timedelta(days=1)):
            if streak == 0 and day == expected - timedelta(days=1):
                expected = day
            streak += 1
            expected = expected - timedelta(days=1)
        elif day == expected:
            streak += 1
            expected = expected - timedelta(days=1)
        else:
            break
    return streak


def _growth_series(timestamps: list[str], *, max_points: int = 30) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for ts in timestamps:
        day = ts[:10]
        if len(day) == 10:
            counts[day] = counts.get(day, 0) + 1
    running = 0
    series: list[dict[str, Any]] = []
    for day in sorted(counts):
        running += counts[day]
        series.append({"date": day, "count": running})
    if len(series) > max_points:
        step = max(1, len(series) // max_points)
        series = series[::step][-max_points:]
    return series
