import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.models import Recommendation


TEST_TYPE_CODES = {
    "Ability & Aptitude": "A",
    "Assessment Exercises": "E",
    "Biodata & Situational Judgment": "B",
    "Competencies": "C",
    "Development & 360": "D",
    "Knowledge & Skills": "K",
    "Personality & Behavior": "P",
    "Simulations": "S",
}


@dataclass(frozen=True)
class CatalogItem:
    entity_id: str
    name: str
    url: str
    description: str
    keys: tuple[str, ...]
    job_levels: tuple[str, ...]
    languages: tuple[str, ...]
    duration: str
    remote: str
    adaptive: str

    @property
    def test_type(self) -> str:
        codes = [TEST_TYPE_CODES.get(key, "") for key in self.keys]
        return ",".join(code for code in codes if code)

    @property
    def searchable_text(self) -> str:
        return " ".join(
            [
                self.name,
                self.description,
                " ".join(self.keys),
                " ".join(self.job_levels),
                " ".join(self.languages),
                self.duration,
            ]
        )

    def recommendation(self) -> Recommendation:
        return Recommendation(name=self.name, url=self.url, test_type=self.test_type)


def normalize_text(text: str) -> str:
    text = text.lower()
    text = text.replace("&", " and ")
    return re.sub(r"[^a-z0-9+#.]+", " ", text).strip()


class Catalog:
    def __init__(self, path: Path):
        raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        self.items = [
            CatalogItem(
                entity_id=str(row.get("entity_id", "")),
                name=row.get("name", ""),
                url=row.get("link", ""),
                description=row.get("description", "") or "",
                keys=tuple(row.get("keys", []) or []),
                job_levels=tuple(row.get("job_levels", []) or []),
                languages=tuple(row.get("languages", []) or []),
                duration=row.get("duration", "") or "",
                remote=row.get("remote", "") or "",
                adaptive=row.get("adaptive", "") or "",
            )
            for row in raw
            if row.get("name") and row.get("link")
        ]
        self.by_name = {normalize_text(item.name): item for item in self.items}
        self.by_url = {item.url: item for item in self.items}

    def find_by_name_contains(self, name_fragment: str) -> CatalogItem | None:
        needle = normalize_text(name_fragment)
        exact = self.by_name.get(needle)
        if exact:
            return exact
        for item in self.items:
            if needle and needle in normalize_text(item.name):
                return item
        return None

    def require(self, name_fragment: str) -> CatalogItem | None:
        return self.find_by_name_contains(name_fragment)

    def from_recommendations_in_text(self, text: str) -> list[CatalogItem]:
        found: list[CatalogItem] = []
        seen: set[str] = set()
        normalized = normalize_text(text)
        for item in self.items:
            item_name = normalize_text(item.name)
            if len(item_name) > 5 and item_name in normalized and item.url not in seen:
                found.append(item)
                seen.add(item.url)
        return found


class VectorIndex:
    def __init__(self, catalog: Catalog, embedding_model: str, enable_sentence_transformer: bool = False):
        self.catalog = catalog
        self.embedding_model_name = embedding_model
        self.enable_sentence_transformer = enable_sentence_transformer
        self.mode = "keyword"
        self._vectorizer = None
        self._matrix = None
        self._faiss_index = None
        self._embedder = None
        self._build()

    def _build(self) -> None:
        texts = [item.searchable_text for item in self.catalog.items]
        if self.enable_sentence_transformer:
            try:
                from sentence_transformers import SentenceTransformer
                import faiss

                self._embedder = SentenceTransformer(self.embedding_model_name)
                embeddings = self._embedder.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
                embeddings = embeddings.astype("float32")
                index = faiss.IndexFlatIP(embeddings.shape[1])
                index.add(embeddings)
                self._faiss_index = index
                self._matrix = embeddings
                self.mode = "sentence-transformer-faiss"
                return
            except Exception:
                pass

        try:
            from sklearn.feature_extraction.text import HashingVectorizer
            import faiss

            self._vectorizer = HashingVectorizer(
                alternate_sign=False,
                norm="l2",
                n_features=4096,
                ngram_range=(1, 2),
                stop_words="english",
            )
            embeddings = self._vectorizer.transform(texts).astype("float32").toarray()
            index = faiss.IndexFlatIP(embeddings.shape[1])
            index.add(embeddings)
            self._faiss_index = index
            self._matrix = embeddings
            self.mode = "hashing-faiss"
            return
        except Exception:
            pass

        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=20000)
        self._matrix = self._vectorizer.fit_transform(texts)
        self.mode = "tfidf-fallback"

    def search(self, query: str, top_k: int = 20) -> list[tuple[CatalogItem, float]]:
        if self.mode == "sentence-transformer-faiss" and self._embedder and self._faiss_index:
            vector = self._embedder.encode([query], convert_to_numpy=True, normalize_embeddings=True).astype("float32")
            scores, indices = self._faiss_index.search(vector, min(top_k, len(self.catalog.items)))
            return [
                (self.catalog.items[int(idx)], float(score))
                for idx, score in zip(indices[0], scores[0])
                if int(idx) >= 0
            ]
        if self.mode == "hashing-faiss" and self._vectorizer and self._faiss_index:
            vector = self._vectorizer.transform([query]).astype("float32").toarray()
            scores, indices = self._faiss_index.search(vector, min(top_k, len(self.catalog.items)))
            return [
                (self.catalog.items[int(idx)], float(score))
                for idx, score in zip(indices[0], scores[0])
                if int(idx) >= 0
            ]

        query_vector = self._vectorizer.transform([query])
        scores = (self._matrix @ query_vector.T).toarray().ravel()
        order = np.argsort(scores)[::-1][:top_k]
        return [(self.catalog.items[int(i)], float(scores[int(i)])) for i in order]


def dedupe_items(items: list[CatalogItem], limit: int = 10) -> list[CatalogItem]:
    out: list[CatalogItem] = []
    seen: set[str] = set()
    for item in items:
        if item.url in seen:
            continue
        seen.add(item.url)
        out.append(item)
        if len(out) >= limit:
            break
    return out
