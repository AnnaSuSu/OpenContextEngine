"""Shared intent scoring with dense facet affinity and scored graph expansion.

Every candidate is scored against the complete question, so fragments containing
pronouns never lose their context. Facet affinity distributes its packing value.
"""
import numpy as np
from batched import BatchedEngine

VERSION = 'shared-intent-v4'


class RoutedEngine(BatchedEngine):
    version = VERSION
    # Shared-intent values are lower than independently maximized facet scores.
    # Only fill the remaining budget after all v2 selections; never displace them.
    min_gain = .005

    def scoring_policy(self, cache, queries, second_wave):
        confidence = max((value for (query, _), value in cache.items() if query == queries[0]), default=0)
        return {'fullFacets': second_wave and len(set(queries)) > 1 and confidence < .1}

    def scoring_pairs(self, requested, queries, dense, policy):
        if policy['fullFacets']:
            return requested
        return [(queries[0], uid) for _, uid in requested]

    def pair_score(self, cache, query, uid, queries, dense, policy):
        if policy['fullFacets']:
            return cache[(query, uid)]
        score = cache[(queries[0], uid)]
        if query == queries[0]:
            return score
        col = queries.index(query)
        affinity = np.exp(min(0, dense[uid, col] - max(dense[uid, 1:])) / .06)
        return score * (.35 + .65 * float(affinity))
