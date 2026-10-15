import unittest

from pydantic import ValidationError

from app.config import Settings


class RagConfigTest(unittest.TestCase):
    def make_config(self, **kwargs):
        return Settings(_env_file=None, DATABASE_URL="sqlite://", JWT_SECRET_KEY="test-only", JWT_EXPIRE_HOURS=24, JWT_ALGORITHM="HS256", **kwargs)

    def test_rag_is_optional_and_secrets_are_masked(self):
        config = self.make_config(DASHSCOPE_API_KEY="private-test-value")
        self.assertFalse(config.RAG_ENABLED)
        self.assertEqual(config.EMBEDDING_MODEL, "text-embedding-v4")
        self.assertEqual(config.EMBEDDING_DIMENSIONS, 1024)
        self.assertNotIn("private-test-value", repr(config))

    def test_rejects_invalid_dimensions_ports_and_chunk_overlap(self):
        for params in ({"EMBEDDING_DIMENSIONS": 1}, {"CHROMA_PORT": 0}, {"RAG_CHUNK_SIZE": 100, "RAG_CHUNK_OVERLAP": 100}):
            with self.subTest(params=params), self.assertRaises(ValidationError):
                self.make_config(**params)


if __name__ == "__main__":
    unittest.main()
