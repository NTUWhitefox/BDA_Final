"""Core recommendation engine.

Implements the hybrid design from PLAN.md section 4.3 at proof-of-concept scale:

  1. Tag-rarity weighting   : games x tags count matrix -> TF-IDF (rare tags matter
                              more, so generic tags like "Indie" don't dominate).
  2. Game->game similarity  : cosine similarity over the TF-IDF tag vectors.
  3. Tag co-occurrence graph: tags linked when they appear together on games;
                              Louvain community detection -> micro-niches.
  4. PageRank on the game   : centrality over the game-similarity graph identifies
     similarity graph         "hub" games where an audience concentrates.

At 10x/100x scale the same steps map onto Spark (TF-IDF/matrix ops), GraphFrames
(community detection / PageRank) and a vector index (FAISS) for nearest neighbours;
here we keep everything in-memory with scikit-learn + networkx.
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MultiLabelBinarizer


def _split_tags(s: str) -> list:
    return [t.strip() for t in str(s).split("|") if t.strip()]


@dataclass
class GameHit:
    appid: int
    name: str
    score: float
    niche: int
    developer: str = ""


class RecommenderEngine:
    """Builds the model in memory and answers discovery queries."""

    def __init__(self, games: pd.DataFrame):
        if games is None or len(games) < 2:
            n = 0 if games is None else len(games)
            raise ValueError(
                f"RecommenderEngine needs >= 2 tagged games, got {n}. The input "
                "dataset is empty or untagged - check data collection (SteamSpy "
                "'all'/'top' endpoints need per-app tag enrichment)."
            )
        self.games = games.reset_index(drop=True)
        self._fit()

    # ------------------------------------------------------------------ build
    def _fit(self) -> None:
        tag_lists = [_split_tags(t) for t in self.games["tags"]]

        # (1) games x tags binary matrix, then TF-IDF for tag-rarity weighting
        self.mlb = MultiLabelBinarizer()
        counts = self.mlb.fit_transform(tag_lists)            # n_games x n_tags
        self.tags = list(self.mlb.classes_)
        self.tfidf = TfidfTransformer()
        self.vectors = self.tfidf.fit_transform(counts)        # sparse, weighted

        # (2) full game->game cosine similarity (fine at POC scale)
        self.sim = cosine_similarity(self.vectors)
        np.fill_diagonal(self.sim, 0.0)

        self.idx_by_appid = {int(a): i for i, a in enumerate(self.games["appid"])}

        self._build_tag_graph(counts)
        self._build_game_graph()
        self._assign_niches(tag_lists)

    def _build_tag_graph(self, counts: np.ndarray) -> None:
        """Tag co-occurrence graph + Louvain communities (micro-niches)."""
        co = counts.T @ counts                                 # n_tags x n_tags
        g = nx.Graph()
        g.add_nodes_from(range(len(self.tags)))
        n = len(self.tags)
        for i in range(n):
            for j in range(i + 1, n):
                w = int(co[i, j])
                if w > 0:
                    g.add_edge(i, j, weight=w)
        self.tag_graph = g
        communities = nx.community.louvain_communities(g, weight="weight", seed=42)
        self.tag_community = {}
        for cid, members in enumerate(communities):
            for t in members:
                self.tag_community[t] = cid
        self.n_niches = len(communities)

    def _build_game_graph(self, threshold: float = 0.15) -> None:
        """PageRank over the game-similarity graph -> audience-hub score."""
        g = nx.Graph()
        g.add_nodes_from(range(len(self.games)))
        n = len(self.games)
        for i in range(n):
            for j in range(i + 1, n):
                w = float(self.sim[i, j])
                if w >= threshold:
                    g.add_edge(i, j, weight=w)
        self.game_graph = g
        pr = nx.pagerank(g, weight="weight") if g.number_of_edges() else {}
        self.pagerank = np.array([pr.get(i, 0.0) for i in range(n)])

    def _assign_niches(self, tag_lists: list) -> None:
        """Each game's niche = the dominant Louvain community among its tags."""
        tag_to_col = {t: i for i, t in enumerate(self.tags)}
        niches = []
        for tags in tag_lists:
            votes = {}
            for t in tags:
                col = tag_to_col.get(t)
                if col is None:
                    continue
                cid = self.tag_community.get(col, -1)
                votes[cid] = votes.get(cid, 0) + 1
            niches.append(max(votes, key=votes.get) if votes else -1)
        self.games["niche"] = niches

    # ------------------------------------------------------------------ query
    def _hit(self, i: int, score: float) -> GameHit:
        row = self.games.iloc[i]
        return GameHit(int(row["appid"]), str(row["name"]), round(float(score), 4),
                       int(row["niche"]), str(row.get("developer", "")))

    def search(self, query: str, limit: int = 10) -> list:
        q = query.strip().lower()
        mask = self.games["name"].str.lower().str.contains(q, na=False)
        return [self._hit(i, 1.0) for i in self.games[mask].index[:limit]]

    def similar(self, appid: int, k: int = 5) -> list:
        """'Games like X' - top-k by tag-vector cosine similarity."""
        i = self.idx_by_appid.get(int(appid))
        if i is None:
            return []
        order = np.argsort(self.sim[i])[::-1][:k]
        return [self._hit(int(j), self.sim[i, j]) for j in order]

    def competitors(self, appid: int, k: int = 5) -> list:
        """Closest games within the same niche - a developer's direct rivals."""
        i = self.idx_by_appid.get(int(appid))
        if i is None:
            return []
        niche = int(self.games.iloc[i]["niche"])
        same = [j for j in range(len(self.games))
                if j != i and int(self.games.iloc[j]["niche"]) == niche]
        same.sort(key=lambda j: self.sim[i, j], reverse=True)
        return [self._hit(j, self.sim[i, j]) for j in same[:k]]

    def niche_profile(self, appid: int) -> dict:
        """The game's niche: defining tags, sibling games, and audience hubs."""
        i = self.idx_by_appid.get(int(appid))
        if i is None:
            return {}
        niche = int(self.games.iloc[i]["niche"])
        members = [j for j in range(len(self.games))
                   if int(self.games.iloc[j]["niche"]) == niche]
        defining = [self.tags[c] for c, cid in self.tag_community.items() if cid == niche]
        hubs = sorted(members, key=lambda j: self.pagerank[j], reverse=True)[:5]
        return {
            "appid": int(appid),
            "name": str(self.games.iloc[i]["name"]),
            "niche_id": int(niche),
            "niche_size": int(len(members)),
            "defining_tags": defining[:12],
            "audience_hubs": [self._hit(j, self.pagerank[j]).__dict__ for j in hubs],
        }

    def niche_gaps(self, appid: int, top: int = 8) -> list:
        """Tags common elsewhere but absent from this niche = positioning angles."""
        i = self.idx_by_appid.get(int(appid))
        if i is None:
            return []
        niche = int(self.games.iloc[i]["niche"])
        in_niche = self.games[self.games["niche"] == niche]
        niche_tags = set("|".join(in_niche["tags"]).split("|"))
        all_tag_freq = {}
        for t in "|".join(self.games["tags"]).split("|"):
            if t:
                all_tag_freq[t] = all_tag_freq.get(t, 0) + 1
        candidates = [(t, f) for t, f in all_tag_freq.items() if t not in niche_tags]
        candidates.sort(key=lambda x: x[1], reverse=True)
        return [t for t, _ in candidates[:top]]

    def graph_data(self, threshold: float = 0.2, max_edges_per_node: int = 4) -> dict:
        """Nodes (games, coloured by niche, sized by PageRank) + top similarity
        edges, ready for a force-directed network visualisation."""
        nodes = []
        for i in range(len(self.games)):
            row = self.games.iloc[i]
            nodes.append({
                "id": int(row["appid"]),
                "label": str(row["name"]),
                "group": int(row["niche"]),
                "value": round(float(self.pagerank[i]) * 1000 + 1, 3),
            })
        edges, seen = [], set()
        n = len(self.games)
        for i in range(n):
            kept = 0
            for j in np.argsort(self.sim[i])[::-1]:
                if j == i or self.sim[i, j] < threshold:
                    continue
                a, b = sorted((int(self.games.iloc[i]["appid"]),
                               int(self.games.iloc[j]["appid"])))
                if (a, b) in seen:
                    continue
                seen.add((a, b))
                edges.append({"from": a, "to": b,
                              "value": round(float(self.sim[i, j]), 3)})
                kept += 1
                if kept >= max_edges_per_node:
                    break
        return {"nodes": nodes, "edges": edges, "n_niches": int(self.n_niches)}
