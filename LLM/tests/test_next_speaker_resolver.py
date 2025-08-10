import asyncio
import os
import unittest

from LLM.next_speaker_resolver import resolve_next_speaker, NextPolicy


class ResolverTest(unittest.TestCase):
    def setUp(self):
        os.makedirs("LLM/logs", exist_ok=True)
        self.registry = [
            {"internal_id": "LUMINA", "display_name": "ルミナ", "short_name": "る"},
            {"internal_id": "CLARIS", "display_name": "クラリス", "short_name": "く"},
            {"internal_id": "NOX", "display_name": "ノクス", "short_name": "の"},
        ]
        self.oplog = "LLM/logs/operation_test.log"

    def test_tag_internal_id(self):
        text = "了解。[Next: LUMINA]"
        nid, reason, ext, norm = resolve_next_speaker(text, "CLARIS", self.registry, NextPolicy(), self.oplog)
        self.assertEqual(nid, "LUMINA")
        self.assertEqual(reason, "tag")

    def test_tag_display_name(self):
        text = "よろしく。[Next: ルミナ]"
        nid, reason, ext, norm = resolve_next_speaker(text, "CLARIS", self.registry, NextPolicy(), self.oplog)
        self.assertEqual(nid, "LUMINA")

    def test_tag_short_name(self):
        text = "次は任せた。[Next: る]"
        nid, reason, ext, norm = resolve_next_speaker(text, "CLARIS", self.registry, NextPolicy(), self.oplog)
        self.assertEqual(nid, "LUMINA")

    def test_self_nomination_blocked(self):
        text = "私が続けます。[Next: CLARIS]"
        nid, reason, ext, norm = resolve_next_speaker(text, "CLARIS", self.registry, NextPolicy(allow_self_nomination=False), self.oplog)
        self.assertNotEqual(reason, "tag")

    def test_round_robin(self):
        text = "タグなしです。"
        nid, reason, ext, norm = resolve_next_speaker(text, "LUMINA", self.registry, NextPolicy(fallback="round_robin"), self.oplog)
        self.assertEqual(nid, "CLARIS")
        self.assertEqual(reason, "round_robin")

    def test_fuzzy(self):
        text = "誤記あり。[Next: LUMlNA]"  # 小文字のl混入
        nid, reason, ext, norm = resolve_next_speaker(text, "CLARIS", self.registry, NextPolicy(fuzzy_threshold=0.8), self.oplog)
        self.assertEqual(nid, "LUMINA")
        self.assertIn(reason, ("tag", "fuzzy"))


if __name__ == "__main__":
    unittest.main()
