"""Master callbacks in the retained Mountain UI; fixtures never touch live data."""
import json
from src import app


def test_mountain_layout_wires_master_callbacks():
    demo = app.build_app()
    cfg = demo.get_config_file()
    ids = {c['props'].get('elem_id') for c in cfg['components']}
    assert {'qa-filters', 'qa-workspace', 'qa-evidence', 'theme-mode'} <= ids
    functions = {f.fn for f in demo.fns.values()}
    assert app.generate_quiz_ui in functions
    assert app.grade_quiz in functions
    assert app.answer_dashboard in functions
    assert 'localStorage' in app.THEME_JS


def test_answer_dashboard_keeps_master_retrieval_and_separates_evidence(monkeypatch):
    from src.retrieve import Candidate
    calls = []
    monkeypatch.setattr(app.retrieve, 'endpoint_ready', lambda _: True)
    c = Candidate('c', 'doc', 'Lecture', 'slide', 2, 'Evidence text', 'missing.png')
    def retrieve(query, **kwargs):
        calls.append((query, kwargs))
        return [c]
    monkeypatch.setattr(app.retrieve, 'retrieve', retrieve)
    monkeypatch.setattr(app.qa, 'answer_question', lambda q, cs, include_images: dict(answer='Grounded fixture', valid=True, validation_errors=[], sources=[dict(doc='doc', page_no=2, excerpt='Evidence text')]))
    answer, sources, images = app.answer_dashboard('Why?', 'doc', 'Topic', False, False)
    assert 'Grounded fixture' in answer and 'Validation' in answer
    assert 'Evidence text' in sources and 'Grounded fixture' not in sources
    assert calls == [('Topic: Why?', {'docs': ['doc'], 'use_rerank': False})]
    assert images == []


def test_empty_library_quiz_is_readable_not_file_error(tmp_path, monkeypatch):
    monkeypatch.setattr(app.config, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(app.retrieve, 'endpoint_ready', lambda _: True)
    output = app.generate_quiz_ui('', '', 1)
    assert 'No chunks' in output[0]
    assert output[-1] == ''


def test_real_client_master_upload_dedupe_remove_and_quiz(tmp_path, monkeypatch, pdf_file):
    from gradio_client import Client, handle_file
    library_dir, out = tmp_path / 'library', tmp_path / 'outputs'
    add, remove, listing = app.library.add_document, app.library.remove_document, app.library.list_documents
    monkeypatch.setattr(app.library, 'add_document', lambda p: add(p, library_dir=library_dir, out_dir=out))
    monkeypatch.setattr(app.library, 'remove_document', lambda d: remove(d, library_dir=library_dir, out_dir=out))
    monkeypatch.setattr(app.library, 'list_documents', lambda: listing(out_dir=out))
    monkeypatch.setattr(app.config, 'PROJECT_ROOT', tmp_path)
    demo = app.build_app()
    try:
        _, url, _ = demo.launch(server_name='127.0.0.1', server_port=None, prevent_thread_lock=True, quiet=True)
        client = Client(url, verbose=False)
        added = client.predict([handle_file(str(pdf_file))], api_name='/save_materials')
        assert 'added' in added[0] and '2 pages/slides' in added[0]
        doc_id = listing(out)[0]['doc_id']
        assert all(doc_id in repr(added[i]) for i in [1, 2, 3])
        assert '<strong>1</strong> materials' in added[4]
        assert 'already in the library' in client.predict([handle_file(str(pdf_file))], api_name='/save_materials')[0]
        assert (out / 'chunks.json').exists() and list((out / 'pages').glob('*.png'))
        assert 'not configured' in client.predict('Why?', doc_id, '', False, False, api_name='/ask')[0]
        monkeypatch.setattr(app.retrieve, 'endpoint_ready', lambda _: True)
        original_generate = app.quiz.generate_quiz
        def generate(title, chunks, n, topic=''):
            payload = json.dumps({'questions': [dict(question='TEST FIXTURE ONLY', options=['A', 'B'], key=1, explain='PRIVATE-FIXTURE-EXPLANATION', chunk_ref=chunks[0]['chunk_id'])]})
            return original_generate(title, chunks, n, topic, chat_fn=lambda _: payload)
        monkeypatch.setattr(app.quiz, 'generate_quiz', generate)
        created = client.predict(doc_id, '', 1, api_name='/create_quiz')
        assert 'PRIVATE-FIXTURE' not in repr(created)
        assert 'PRIVATE-FIXTURE' not in json.dumps(client.config)
        other = Client(url, verbose=False)
        assert 'Generate a quiz first' in other.predict(None, None, None, None, None, api_name='/grade_quiz')
        assert 'Not all questions answered' in client.predict(None, None, None, None, None, api_name='/grade_quiz')
        graded = client.predict('B', None, None, None, None, api_name='/grade_quiz')
        assert 'Score: 1 / 1' in graded and 'PRIVATE-FIXTURE' in graded
        removed = client.predict(doc_id, api_name='/remove_material')
        assert 'purged' in removed[0]
        assert listing(out) == [] and not list(library_dir.glob('*.pdf'))
        assert not list((out / 'pages').glob('*.png'))
    finally:
        demo.close()
        app._QUIZ_STORE.clear()


def test_dashboard_reports_real_unconfigured_status():
    answer, sources, images = app.answer_dashboard('Why?', '', '', True, True)
    assert 'not configured' in answer
    assert images == []
