from __future__ import annotations

from dataclasses import dataclass

_LANGUAGE_LABELS = {
    "ja": "日本語",
    "en": "English",
}


@dataclass(frozen=True)
class InfoPage:
    title: str
    lines: tuple[str, ...]

    def __str__(self) -> str:
        return "\n".join((self.title, *self.lines))

    def to_markdown(self) -> str:
        body = "\n".join(f"- {line}" for line in self.lines)
        return f"## {self.title}\n\n{body}"

    def _repr_markdown_(self) -> str:
        return self.to_markdown()

    def show(self) -> None:
        print(str(self))


@dataclass(frozen=True)
class GuidePage:
    title: str
    markdown: str
    source: str
    url: str | None = None
    language: str = "en"
    available_languages: tuple[str, ...] = ("en",)

    def __str__(self) -> str:
        return self.to_markdown()

    def to_markdown(self) -> str:
        if len(self.available_languages) > 1:
            return f"{self.language_switcher()}\n\n{self.markdown}"
        return self.markdown

    def language_switcher(self) -> str:
        languages = self.available_languages or (self.language,)
        labels = (_LANGUAGE_LABELS.get(language, language) for language in languages)
        return f"Lang: {' / '.join(labels)}"

    def _repr_markdown_(self) -> str:
        return self.to_markdown()

    def show(self) -> None:
        print(self.markdown)

    def open(self) -> None:
        if self.url is None:
            raise ValueError(f"GuidePage has no public URL: {self.source}")
        import webbrowser

        webbrowser.open(self.url)
