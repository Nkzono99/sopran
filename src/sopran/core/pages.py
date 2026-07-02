from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

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
    translations: Mapping[str, str] | None = None
    sources: Mapping[str, str] | None = None
    urls: Mapping[str, str | None] | None = None

    def __str__(self) -> str:
        return self.to_markdown()

    def to_markdown(self, *, language: str | None = None) -> str:
        markdown = self._markdown_for(language or self.language)
        if len(self.available_languages) > 1:
            return f"{self.language_switcher()}\n\n{markdown}"
        return markdown

    def with_language(self, language: str) -> GuidePage:
        return replace(
            self,
            language=language,
            markdown=self._markdown_for(language),
            source=self._source_for(language),
            url=self._url_for(language),
        )

    def with_schema(self, schema: object, *, heading: str = "Schema") -> GuidePage:
        translations = None
        if self.translations is not None:
            translations = {
                language: _markdown_with_schema_table(markdown, schema, heading=heading)
                for language, markdown in self.translations.items()
            }
        return replace(
            self,
            markdown=_markdown_with_schema_table(self.markdown, schema, heading=heading),
            translations=translations,
        )

    def language_switcher(self) -> str:
        languages = self.available_languages or (self.language,)
        labels = (_LANGUAGE_LABELS.get(language, language) for language in languages)
        return f"Lang: {'/'.join(labels)}"

    def _repr_markdown_(self) -> str:
        return self.to_markdown()

    def show(self) -> None:
        print(self.to_markdown())

    def open(self, *, language: str | None = None) -> None:
        selected_language = language or self.language
        url = self._url_for(selected_language)
        if url is None:
            raise ValueError(
                f"GuidePage has no public URL: {self._source_for(selected_language)}"
            )
        import webbrowser

        webbrowser.open(url)

    def _markdown_for(self, language: str) -> str:
        if language not in (self.available_languages or (self.language,)):
            raise ValueError(f"GuidePage language is not available: {language}")
        if language == self.language:
            return self.markdown
        if self.translations and language in self.translations:
            return self.translations[language]
        return self.markdown

    def _source_for(self, language: str) -> str:
        if language not in (self.available_languages or (self.language,)):
            raise ValueError(f"GuidePage language is not available: {language}")
        if language == self.language:
            return self.source
        if self.sources and language in self.sources:
            return self.sources[language]
        return self.source

    def _url_for(self, language: str) -> str | None:
        if language not in (self.available_languages or (self.language,)):
            raise ValueError(f"GuidePage language is not available: {language}")
        if language == self.language:
            return self.url
        if self.urls and language in self.urls:
            return self.urls[language]
        return self.url


def _markdown_with_schema_table(
    markdown: str,
    schema: object,
    *,
    heading: str,
) -> str:
    schema_markdown = schema.to_markdown()  # type: ignore[attr-defined]
    table_start = schema_markdown.find("| name |")
    schema_table = schema_markdown[table_start:] if table_start >= 0 else schema_markdown
    return f"{markdown.rstrip()}\n\n## {heading}\n\n{schema_table}\n"
