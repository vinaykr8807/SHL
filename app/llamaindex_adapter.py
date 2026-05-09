from app.catalog import Catalog


class OptionalLlamaIndex:
    def __init__(self, catalog: Catalog):
        self.enabled = False
        self.index = None
        try:
            from llama_index.core import Document, VectorStoreIndex

            documents = [
                Document(
                    text=item.searchable_text,
                    metadata={"name": item.name, "url": item.url, "test_type": item.test_type},
                )
                for item in catalog.items
            ]
            self.index = VectorStoreIndex.from_documents(documents)
            self.enabled = True
        except Exception:
            self.enabled = False

    def status(self) -> str:
        return "enabled" if self.enabled else "not-installed"
