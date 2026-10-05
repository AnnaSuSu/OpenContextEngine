"""Deterministic behavior facets; every facet retains its full query context in retrieval."""
import re


def plan_query(query):
    # Keep conditions in the intent, but do not spend a facet on a condition
    # such as "when a user reopens a chat" without its requested behavior.
    parts = [part.strip() for part in re.split(
        r'[:：;；，]|,\s+(?=how|which|why|where|what)|\s+and\s+(?=how|which|why|where|what|preserve|restore|validate|enforce|handle|load|save|reject|filter|check|merge|retain|stop)',
        query, flags=re.I) if len(part.strip()) > 7]
    actionable = [part for part in parts if not re.match(r'^(when|if|after|before|unless|given)\b', part, re.I)
                  and not (part.endswith('时') and not re.search(r'如何|怎么|哪里|怎样', part))]
    facets = actionable if 1 < len(actionable) <= 4 else [query]
    return {'intent': query, 'facets': [{'question': part, 'terms': re.findall(r'[A-Za-z][A-Za-z0-9_]*', part)}
                                      for part in facets]}
