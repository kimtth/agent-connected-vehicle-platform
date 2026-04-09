from models.base import BaseSchemaModel
from typing import List, Union, Optional


class AskAIRequest(BaseSchemaModel):
    messages: Optional[Union[str, dict, List[Union[str, dict]]]] = None
    system: Optional[str] = None
    language_code: Optional[str] = None
    temperature: float = 0.7
    maxTokens: int = 512

    def normalized_messages_text(self) -> str:
        """Flatten messages into a single prompt string for Agent Framework."""
        if not self.messages:
            return ""
        raw = self.messages if isinstance(self.messages, list) else [self.messages]

        parts: List[str] = []
        for item in raw:
            if isinstance(item, dict) and item.get("content"):
                parts.append(str(item["content"]).strip())
            elif isinstance(item, str) and item.strip():
                parts.append(item.strip())
        return "\n".join(parts)