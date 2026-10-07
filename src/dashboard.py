"""Dashboard-only state and contracts. No backend imports or endpoint calls."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Protocol


# Do not echo operational secrets from course setup guides or backend exceptions.
SENSITIVE = re.compile(r'api[ _-]?key|password|bearer\s|secret|access[ _-]?token|https?://[^\s]+:\d+', re.I)


@dataclass(frozen=True)
class Answer:
    text: str
    source_ids: list[str]


class Backend(Protocol):
    def answer(self, question: str, docs: list[str], topic: str) -> Answer: ...
    def quiz(self, docs: list[str], topic: str) -> list[QuizItem]: ...


@dataclass(frozen=True)
class Source:
    title: str
    location: str
    excerpt: str
    image: str | None


@dataclass
class AnswerView:
    status: str
    answer: str = ''
    sources: list[Source] = field(default_factory=list)


@dataclass(frozen=True)
class QuizItem:
    question: str
    options: tuple[str, ...]
    correct_index: int
    explanation: str
    source_ids: tuple[str, ...] = ()


@dataclass
class QuizView:
    status: str
    questions: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)


@dataclass
class QuizResult:
    status: str
    score: str = ''
    explanations: str = ''
    sources: list[Source] = field(default_factory=list)


class Dashboard:
    def __init__(self, catalog: Catalog, backend: Backend | None = None):
        self.catalog = catalog
        self.backend = backend
        # Keys/explanations never enter gr.State, component props or event outputs.
        self._quizzes: dict[str, tuple[QuizItem, ...]] = {}
        self._results: dict[str, QuizResult] = {}

    def clear_quiz(self, session: str) -> None:
        self._quizzes.pop(session, None)
        self._results.pop(session, None)

    def start_quiz(self, session: str, docs: list[str] | None, topic: str | None) -> QuizView:
        self.clear_quiz(session)
        if not self.catalog.chunks:
            return QuizView(self.catalog.notice)
        if self.backend is None:
            return QuizView('Not connected yet. Practice questions will appear when the course team connects the quiz service.')
        try:
            items = tuple(self.backend.quiz(docs or [], topic or ''))
            if not 1 <= len(items) <= 5:
                raise ValueError('Quiz size')
            for item in items:
                if not isinstance(item, QuizItem) or not 2 <= len(item.options) <= 6 or not 0 <= item.correct_index < len(item.options):
                    raise ValueError('Quiz format')
                if SENSITIVE.search(' '.join([item.question, *item.options, item.explanation])):
                    raise ValueError('Unsafe quiz')
                if len(set(item.options)) != len(item.options):
                    raise ValueError('Duplicate options')
            self._quizzes[session] = items
            return QuizView('Choose one answer per question, then submit. Solutions stay hidden until you submit or request them.', [(i.question, i.options) for i in items])
        except Exception:
            return QuizView('We could not create a quiz. Please try again in a moment.')

    def submit_quiz(self, session: str, answers: list[int | None], reveal: bool = False) -> QuizResult:
        if session in self._results:
            return self._results[session]
        items = self._quizzes.get(session)
        if not items:
            return QuizResult('No quiz is active. Create a practice quiz first.')
        if not reveal and (len(answers) < len(items) or any(type(a) is not int or not 0 <= a < len(item.options) for a, item in zip(answers, items))):
            return QuizResult('Choose an answer for every question before submitting.')
        score = 'Practice review · not scored' if reveal else f'{sum(a == i.correct_index for a, i in zip(answers, items))} / {len(items)} correct'
        explanations = '\n\n'.join(f'{n}. {i.options[i.correct_index]}\n{i.explanation}' for n, i in enumerate(items, 1))
        sources = self.sources([c for i in items for c in i.source_ids])
        result = QuizResult('Review complete. Create a new quiz to practice again.', score, explanations, sources)
        self._results[session] = result
        return result

    def sources(self, ids: list[str]) -> list[Source]:
        result = []
        for chunk_id in dict.fromkeys(ids):
            c = next((c for c in self.catalog.chunks if c['chunk_id'] == chunk_id), None)
            if not c:
                continue
            page = [r for r in self.catalog.chunks if (r['doc'], r.get('page_no')) == (c['doc'], c.get('page_no'))]
            if any(SENSITIVE.search(r['text']) for r in page):
                continue
            title = material_title(c.get('doc_title') or c['doc'])
            location = f"{str(c.get('kind', 'page')).title()} {c.get('page_no', '—')}"
            if c.get('section'):
                location += ' · ' + str(c['section'])
            image = None
            document_sensitive = any(SENSITIVE.search(r['text']) for r in self.catalog.chunks if r['doc'] == c['doc'])
            if c.get('image_path') and not document_sensitive:
                candidate = (self.catalog.root / c['image_path']).resolve()
                allowed = (self.catalog.root / 'outputs/pages').resolve()
                # Exact catalog provenance + restrictive image directory; no arbitrary files.
                if candidate.is_relative_to(allowed) and candidate.suffix.lower() in ('.png', '.jpg', '.jpeg') and candidate.is_file():
                    image = str(candidate)
            result.append(Source(title, location, c['text'], image))
        return result

    def ask(self, question: str, docs: list[str] | None, topic: str | None) -> AnswerView:
        if not question or not question.strip():
            return AnswerView('Write a question to get started.')
        if not self.catalog.chunks:
            return AnswerView(self.catalog.notice)
        if self.backend is None:
            return AnswerView('Not connected yet. Your materials are ready; answers will be available when the course team connects the answer service.')
        try:
            answer = self.backend.answer(question.strip(), docs or [], topic or '')
            if not isinstance(answer, Answer) or not answer.text.strip() or SENSITIVE.search(answer.text):
                return AnswerView('This answer could not be safely displayed. Please try a different question.')
            sources = self.sources(answer.source_ids)
            return AnswerView('Answer ready. Check the original evidence below.' if sources else 'Answer ready. No shareable source evidence was returned.', answer.text, sources)
        except Exception:
            return AnswerView('We could not get an answer. Please try again in a moment.')


def material_title(value: str) -> str:
    title = Path(value).stem.replace('_', ' ').replace('-', ' ').title()
    title = re.sub(r'Week\s*(\d+)\s*', r'Week \1 · ', title)
    return title.replace('Llm', 'LLM').replace('Rag', 'RAG')


@dataclass
class Catalog:
    root: Path
    chunks: list[dict] = field(default_factory=list)
    notice: str = ''

    @classmethod
    def load(cls, root: Path) -> Catalog:
        try:
            rows = json.loads((root / 'outputs/chunks.json').read_text(encoding='utf-8'))
            if not isinstance(rows, list) or any(not isinstance(c, dict) or not all(k in c for k in ('chunk_id', 'doc', 'text')) for c in rows):
                raise ValueError('Invalid catalog')
            return cls(root.resolve(), rows, '' if rows else 'No course materials are available yet.')
        except FileNotFoundError:
            return cls(root.resolve(), notice='No course materials are available yet. Ask your course team to add them.')
        except (OSError, ValueError):
            return cls(root.resolve(), notice='Course materials could not be loaded. Ask your course team to refresh them.')

    @property
    def counts(self) -> tuple[int, int, int]:
        return (len({c['doc'] for c in self.chunks}),
                len({(c['doc'], c.get('page_no')) for c in self.chunks}), len(self.chunks))

    @property
    def choices(self) -> list[tuple[str, str]]:
        docs = {c['doc']: material_title(c.get('doc_title') or c['doc']) for c in self.chunks}
        return sorted(((label, doc) for doc, label in docs.items()))

    def topics(self, docs: list[str] | None) -> list[str]:
        return sorted({str(c['section']) for c in self.chunks if c.get('section') and (not docs or c['doc'] in docs)})
