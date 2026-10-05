"""Repository text containing tokenizer markers remains ordinary source data."""
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/retrieval'))
from live import LiveIndex
from planning import plan_query


class SpecialTokenTests(unittest.TestCase):
    def test_index_search_and_restart_preserve_literal_special_tokens(self):
        markers = ['<|endoftext|>', '<|fim_prefix|>', '<|fim_middle|>', '<|fim_suffix|>', '<|endofprompt|>']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'repo'
            root.mkdir()
            (root / 'tokens.py').write_text('def token_markers():\n    return ' + repr(markers) + '\n')
            config = {'root': str(root), 'state': str(Path(directory) / 'state'),
                      'embeddingIdentity': 'test', 'embeddingUrl': 'http://test/v1',
                      'embeddingDimensions': 4, 'pollSeconds': .05, 'debounceSeconds': 0,
                      'reranker': {'baseUrl': 'http://rank', 'model': 'test', 'apiKey': 'test', 'api': 'rerank-batch'}}
            embedded = []

            def embed(url, body, *args, **kwargs):
                embedded.extend(body['input'])
                return {'data': [{'index': i, 'embedding': [1., 0., 0., 0.]} for i in range(len(body['input']))]}

            def model(url, body, *args, **kwargs):
                if 'input' in body:
                    return {'data': [{'index': i, 'embedding': [1., 0., 0., 0.]} for i in range(len(body['input']))]}
                return {'results': [{'index': i, 'query_index': q, 'document_index': d, 'relevance_score': .99}
                                    for i, (q, d) in enumerate(body['pairs'])]}

            for restart in (False, True):
                manager = LiveIndex(config, embed=embed).start()
                try:
                    generation = manager.current(5)
                    engine = generation.engine
                    with patch('evidence.post', side_effect=model):
                        context, debug = engine.search(plan_query('Find the token marker implementation'), budget=512)
                    for marker in markers:
                        self.assertIn(marker, context)
                    self.assertEqual(debug['tokens'], len(engine.encoding.encode_ordinary(context)))
                    self.assertLessEqual(debug['tokens'], 512)
                    self.assertEqual(len(embedded), 1, 'Restart must restore the existing vectors')
                finally:
                    manager.close()


if __name__ == '__main__':
    unittest.main()
