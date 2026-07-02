from __future__ import annotations

from dataclasses import dataclass


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

    def __str__(self) -> str:
        return self.markdown

    def to_markdown(self) -> str:
        return self.markdown

    def _repr_markdown_(self) -> str:
        return self.to_markdown()

    def show(self) -> None:
        print(self.markdown)

    def open(self) -> None:
        if self.url is None:
            raise ValueError(f"GuidePage has no public URL: {self.source}")
        import webbrowser

        webbrowser.open(self.url)
