"""Dashboard tests use synthetic data only; never live generated answers."""
import json
from pathlib import Path
import pytest


def corpus(tmp_path):
    rows = [dict(chunk_id='c1', doc='week02', doc_title='week02_llm_fundamentals.pptx',
                 kind='slide', page_no=2, section='Tokens', text='Tokens are units of text.',
                 image_path='outputs/pages/slide.png'),
            dict(chunk_id='c2', doc='week02', doc_title='week02_llm_fundamentals.pptx',
                 kind='slide', page_no=2, section='Tokens', text='Another excerpt.', image_path='')]
    p = tmp_path / 'outputs/chunks.json'
    p.parent.mkdir()
    p.write_text(json.dumps(rows), encoding='utf-8')
    return rows


def test_catalog_reads_real_schema_and_handles_missing_file(tmp_path):
    from src.dashboard import Catalog
    corpus(tmp_path)
    cat = Catalog.load(tmp_path)
    assert cat.counts == (1, 1, 2)
    assert cat.choices == [('Week 02 · LLM Fundamentals', 'week02')]
    assert cat.topics(['week02']) == ['Tokens']
    assert Catalog.load(tmp_path / 'absent').counts == (0, 0, 0)
    assert 'No course materials' in Catalog.load(tmp_path / 'absent').notice


def test_answer_contract_sources_are_resolved_from_catalog(tmp_path):
    from src.dashboard import Catalog, Dashboard, Answer
    corpus(tmp_path)
    calls = []
    class FixtureBackend:
        def answer(self, question, docs, topic):
            calls.append((question, docs, topic))
            return Answer('A fixture answer.', ['c1'])
    ui = Dashboard(Catalog.load(tmp_path), FixtureBackend())
    result = ui.ask('What are tokens?', ['week02'], 'Tokens')
    assert result.answer == 'A fixture answer.'
    assert result.sources[0].excerpt == 'Tokens are units of text.'
    assert result.sources[0].location == 'Slide 2 · Tokens'
    assert result.sources[0].image is None
    assert calls == [('What are tokens?', ['week02'], 'Tokens')]
    assert 'Write a question' in ui.ask('', [], '').status
    assert 'Not connected yet' in Dashboard(ui.catalog).ask('Why?', [], '').status


def test_backend_failures_and_sensitive_evidence_are_not_exposed(tmp_path):
    from src.dashboard import Catalog, Dashboard, Answer
    rows = corpus(tmp_path)
    rows[0]['text'] = 'API key: DUMMY-NOT-A-SECRET'
    (tmp_path / 'outputs/chunks.json').write_text(json.dumps(rows), encoding='utf-8')
    class FixtureBackend:
        def answer(self, *args):
            return Answer('Safe answer', ['c1'])
    result = Dashboard(Catalog.load(tmp_path), FixtureBackend()).ask('Why?', [], '')
    assert 'DUMMY' not in str(result)
    assert not result.sources
    class BrokenBackend:
        def answer(self, *args):
            raise RuntimeError('DUMMY-INTERNAL-DETAILS')
    result = Dashboard(Catalog.load(tmp_path), BrokenBackend()).ask('Why?', [], '')
    assert 'DUMMY' not in str(result)
    assert 'try again' in result.status


def test_quiz_key_stays_server_side_and_score_is_frozen(tmp_path):
    from src.dashboard import Catalog, Dashboard, QuizItem
    corpus(tmp_path)
    class FixtureBackend:
        def quiz(self, docs, topic):
            return [QuizItem('What is a token?', ('Text unit', 'A server'), 0,
                             'FIXTURE-HIDDEN: text is split into units.', ('c1',))]
    ui = Dashboard(Catalog.load(tmp_path), FixtureBackend())
    view = ui.start_quiz('session-a', ['week02'], 'Tokens')
    assert view.questions == [('What is a token?', ('Text unit', 'A server'))]
    assert 'FIXTURE-HIDDEN' not in repr(view)
    assert 'correct' not in repr(view)
    assert 'Choose an answer' in ui.submit_quiz('session-a', [None]).status
    assert 'No quiz' in ui.submit_quiz('session-b', [0]).status
    result = ui.submit_quiz('session-a', [0])
    assert result.score == '1 / 1 correct'
    assert 'FIXTURE-HIDDEN' in result.explanations
    assert ui.submit_quiz('session-a', [1]).score == '1 / 1 correct'
    ui.clear_quiz('session-a')
    assert 'No quiz' in ui.submit_quiz('session-a', [0]).status
    assert 'Not connected yet' in Dashboard(ui.catalog).start_quiz('x', [], '').status


def test_requested_quiz_solutions_do_not_claim_a_score(tmp_path):
    from src.dashboard import Catalog, Dashboard, QuizItem
    corpus(tmp_path)
    class FixtureBackend:
        def quiz(self, *args):
            return [QuizItem('Fixture question', ('One', 'Two'), 1, 'Fixture explanation')]
    ui = Dashboard(Catalog.load(tmp_path), FixtureBackend())
    ui.start_quiz('a', [], '')
    result = ui.submit_quiz('a', [], reveal=True)
    assert result.score == 'Practice review · not scored'
    assert 'Two' in result.explanations
    assert ui.submit_quiz('a', [1]).score == result.score


@pytest.mark.skip(reason="Obsolete injected Dashboard interface; master callback coverage in test_mountain_integration.py")
def test_gradio_callbacks_render_answer_sources_and_keep_key_private(tmp_path):
    from src.dashboard import Catalog, Dashboard, QuizItem, Answer
    from src.app import build_app
    corpus(tmp_path)
    class FixtureBackend:
        def answer(self, *args):
            return Answer('FIXTURE ANSWER <script>not markup</script>', ['c1'])
        def quiz(self, *args):
            return [QuizItem('FIXTURE QUESTION', ('First', 'Second'), 1, 'HIDDEN-FIXTURE-SOLUTION')]
    app = build_app(Dashboard(Catalog.load(tmp_path), FixtureBackend()))
    config = app.get_config_file()
    assert [c['props']['label'] for c in config['components'] if c['type'] == 'tabitem'] == ['Q&A', 'Practice Quiz', 'Course Materials']
    assert 'HIDDEN-FIXTURE-SOLUTION' not in json.dumps(config)
    callbacks = app.dashboard_callbacks
    status, answer, sources = callbacks['ask']('Question', [], '')
    assert '&lt;script&gt;' in answer
    assert 'Tokens are units of text.' in sources
    assert 'Slide 2' in sources
    assert 'Original image unavailable' in sources
    import gradio as gr
    request = gr.Request(session_hash='fixture-session')
    output = callbacks['create']([], '', request)
    assert 'HIDDEN-FIXTURE-SOLUTION' not in repr(output)
    assert 'correct_index' not in repr(output)
    result = callbacks['submit'](request, 1, None, None, None, None)
    assert '1 / 1 correct' in repr(result)
    assert 'HIDDEN-FIXTURE-SOLUTION' in repr(result)


def test_qa_has_separate_filter_workspace_and_evidence_columns(tmp_path):
    from src.dashboard import Catalog, Dashboard
    from src.app import build_app
    corpus(tmp_path)
    config = build_app().get_config_file()
    components = {c['id']: c for c in config['components']}
    parents = {}
    def visit(node, ancestors=()):
        parents[node['id']] = ancestors
        for child in node.get('children', []):
            visit(child, (*ancestors, node['id']))
    visit(config['layout'])
    def in_column(label, column):
        item = next(c for c in components.values() if c['props'].get('label') == label)
        return any(components.get(i, {}).get('props', {}).get('elem_id') == column for i in parents[item['id']])
    assert in_column('Course materials', 'qa-filters')
    assert in_column('Your question', 'qa-workspace')
    evidence = next((c for c in components.values() if c['props'].get('elem_id') == 'qa-evidence'), None)
    assert evidence is not None
    assert evidence['type'] == 'column'


def test_accessible_theme_control_supports_persisted_light_and_dark(tmp_path):
    from src.dashboard import Catalog, Dashboard
    from src.app import build_app, THEME_JS
    corpus(tmp_path)
    config = build_app().get_config_file()
    control = next(c for c in config['components'] if c['props'].get('elem_id') == 'theme-mode')
    assert control['type'] == 'radio'
    assert control['props']['label'] == 'Appearance'
    assert [x[0] for x in control['props']['choices']] == ['Light', 'Dark']
    assert 'localStorage' in THEME_JS
    assert 'course-assistant-theme' in THEME_JS


def test_mountain_photo_is_bundled_and_embedded_without_file_routes():
    import base64
    import re
    from src.app import CSS, ROOT
    from PIL import Image
    photo = ROOT / 'src/assets/rocky-mountains.jpg'
    assert photo.is_file(), 'Decorative mountain photograph must be bundled locally'
    with Image.open(photo) as image:
        assert image.width >= 1920
        assert image.format == 'JPEG'
    embedded = re.search(r'data:image/jpeg;base64,([A-Za-z0-9+/=]+)', CSS)
    assert embedded, 'Backdrop must load without external URLs or broad file permissions'
    assert base64.b64decode(embedded.group(1)) == photo.read_bytes()
    assert 'clip-path:polygon' not in CSS
    assert 'Public domain' in (ROOT / 'src/assets/ATTRIBUTION.md').read_text()


def test_launcher_chooses_available_port_instead_of_reusing_stale_copy(monkeypatch):
    from src import app as module
    calls = {}
    class LocalApp:
        def queue(self, **kwargs):
            return self
        def launch(self, **kwargs):
            calls.update(kwargs)
    monkeypatch.setattr(module, 'build_app', lambda: LocalApp())
    module.main()
    assert calls['server_port'] is None
    assert calls['server_name'] == '127.0.0.1'
    assert calls['share'] is False


def test_original_image_bytes_and_no_path_escape(tmp_path):
    from src.dashboard import Catalog, Dashboard
    from src.app import source_html
    import base64
    rows = corpus(tmp_path)
    # Explicit test-only 1px PNG, not displayed by the live dashboard.
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1kAAAAASUVORK5CYII=')
    original = tmp_path / 'outputs/pages/slide.png'
    original.parent.mkdir()
    original.write_bytes(png)
    ui = Dashboard(Catalog.load(tmp_path))
    assert base64.b64encode(png).decode() in source_html(ui.sources(['c1']))
    rows[0]['image_path'] = '../../outside.png'
    (tmp_path / 'outputs/chunks.json').write_text(json.dumps(rows), encoding='utf-8')
    assert Dashboard(Catalog.load(tmp_path)).sources(['c1'])[0].image is None


def test_sensitive_document_does_not_expose_adjacent_page_image(tmp_path):
    from src.dashboard import Catalog, Dashboard
    rows = corpus(tmp_path)
    rows.append(dict(rows[0], chunk_id='private', page_no=9, text='Password: DUMMY-ONLY'))
    original = tmp_path / 'outputs/pages/slide.png'
    original.parent.mkdir()
    original.write_bytes(b'fixture image only')
    (tmp_path / 'outputs/chunks.json').write_text(json.dumps(rows), encoding='utf-8')
    # Images can contain sensitive details not captured by page OCR: conservative document-level check.
    assert Dashboard(Catalog.load(tmp_path)).sources(['c1'])[0].image is None


def test_catalog_malformed_file_has_friendly_notice(tmp_path):
    from src.dashboard import Catalog
    path = tmp_path / 'outputs/chunks.json'
    path.parent.mkdir()
    path.write_text('{not json', encoding='utf-8')
    assert 'could not be loaded' in Catalog.load(tmp_path).notice


@pytest.mark.skip(reason="Obsolete injected Dashboard interface; master callback coverage in test_mountain_integration.py")
def test_real_gradio_client_payload_never_contains_quiz_key_before_submit(tmp_path):
    from src.dashboard import Catalog, Dashboard, QuizItem, Answer
    from src.app import build_app
    from gradio_client import Client
    corpus(tmp_path)
    class FixtureBackend:
        def answer(self, question, docs, topic):
            return Answer('TEST FIXTURE: tokens are text units.', ['c1'])
        def quiz(self, docs, topic):
            return [QuizItem('TEST FIXTURE question', ('A', 'B'), 1, 'PRIVATE-TEST-EXPLANATION')]
    app = build_app(Dashboard(Catalog.load(tmp_path), FixtureBackend()))
    try:
        _, url, _ = app.launch(server_name='127.0.0.1', server_port=None, prevent_thread_lock=True, quiet=True, show_error=False)
        client = Client(url, verbose=False)
        answer = client.predict('What is a token?', [], '', api_name='/ask')
        assert 'TEST FIXTURE' in answer[1]
        assert 'Tokens are units of text.' in answer[2]
        created = client.predict([], '', api_name='/create_quiz')
        assert 'PRIVATE-TEST-EXPLANATION' not in repr(created)
        assert 'correct_index' not in repr(created)
        assert 'PRIVATE-TEST-EXPLANATION' not in json.dumps(client.config)
        other_session = Client(url, verbose=False)
        assert 'No quiz' in repr(other_session.predict(None, None, None, None, None, api_name='/submit_quiz'))
        result = client.predict('B', None, None, None, None, api_name='/submit_quiz')
        assert '1 / 1 correct' in repr(result)
        assert 'PRIVATE-TEST-EXPLANATION' in repr(result)
    finally:
        app.close()
