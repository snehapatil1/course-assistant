"""Synthetic upload fixtures; never ingested or used as live evidence."""
from pathlib import Path
import json
import zipfile
import pytest


def pdf(tmp_path, name='lecture.pdf', data=b'%PDF-1.4\nTEST FIXTURE ONLY\n%%EOF'):
    folder = tmp_path / 'incoming'
    folder.mkdir(exist_ok=True)
    p = folder / name
    p.write_bytes(data)
    return p


def test_upload_persists_lists_after_restart_without_claiming_searchable(tmp_path):
    from src.material_library import MaterialLibrary
    from src.dashboard import Catalog
    lib = MaterialLibrary(tmp_path)
    result = lib.upload([str(pdf(tmp_path))])
    assert '1 added' in result
    rows = MaterialLibrary(tmp_path).rows(Catalog.load(tmp_path))
    assert len(rows) == 1
    assert rows[0][0] == 'Lecture'
    assert rows[0][1] == 'PDF'
    assert 'Awaiting processing' in rows[0][3]
    assert Catalog.load(tmp_path).choices == []
    assert (tmp_path / 'data/materials/lecture.pdf').read_bytes().startswith(b'%PDF')


def test_upload_duplicates_and_collisions_preserve_originals(tmp_path):
    from src.material_library import MaterialLibrary
    from src.dashboard import Catalog
    lib = MaterialLibrary(tmp_path)
    p = pdf(tmp_path)
    lib.upload([str(p)])
    assert '1 already saved' in lib.upload([str(p)])
    p.write_bytes(b'%PDF-1.4\nDIFFERENT TEST FIXTURE\n%%EOF')
    assert '1 added' in lib.upload([str(p)])
    files = list((tmp_path / 'data/materials').glob('*.pdf'))
    assert len(files) == 2
    assert files[0].read_bytes() != files[1].read_bytes()
    assert len(lib.rows(Catalog.load(tmp_path))) == 2


def test_upload_rejects_unsupported_disguised_large_and_unsafe_names(tmp_path):
    from src.material_library import MaterialLibrary
    lib = MaterialLibrary(tmp_path, max_bytes=100)
    assert 'not accepted' in lib.upload([str(pdf(tmp_path, 'note.txt'))])
    assert 'not accepted' in lib.upload([str(pdf(tmp_path, 'fake.pdf', b'not a PDF'))])
    assert 'too large' in lib.upload([str(pdf(tmp_path, 'big.pdf', b'%PDF-' + b'x'*101))])
    assert lib.safe_name('../outside.pdf') == 'outside.pdf'
    assert lib.safe_name('C:\\private\\lecture.pdf') == 'lecture.pdf'
    assert lib.safe_name('CON.pdf') != 'CON.pdf'
    assert not (tmp_path / 'outside.pdf').exists()


def test_pptx_and_prepared_catalog_status(tmp_path):
    from src.material_library import MaterialLibrary
    from src.dashboard import Catalog
    p = tmp_path / 'slides.pptx'
    with zipfile.ZipFile(p, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('ppt/presentation.xml', '<presentation/>')
    lib = MaterialLibrary(tmp_path)
    assert '1 added' in lib.upload([str(p)])
    out = tmp_path/'outputs'
    out.mkdir()
    (out/'chunks.json').write_text(json.dumps([dict(chunk_id='fixture',doc='slides',doc_title='slides.pptx',source_file='slides.pptx',text='TEST FIXTURE')]))
    rows = lib.rows(Catalog.load(tmp_path))
    assert len(rows) == 1
    assert 'Text prepared' in rows[0][3]
    assert Catalog.load(tmp_path).choices == [('Slides', 'slides')]


@pytest.mark.skip(reason="Obsolete save-only upload interface; master ingests uploads immediately, covered in test_mountain_integration.py")
def test_upload_callback_refreshes_only_prepared_selectors(tmp_path):
    from src.dashboard import Catalog, Dashboard
    from src.app import build_app
    app = build_app(Dashboard(Catalog.load(tmp_path)))
    result = app.dashboard_callbacks['upload']([str(pdf(tmp_path))])
    assert '1 added' in result[0]
    assert len(result[1]) == 1
    assert result[2]['choices'] == []
    assert result[3]['choices'] == []
    out = tmp_path/'outputs'
    out.mkdir()
    (out/'chunks.json').write_text(json.dumps([dict(chunk_id='fixture',doc='lecture',doc_title='lecture.pdf',text='FIXTURE')]))
    refreshed = app.dashboard_callbacks['refresh']()
    assert refreshed[1]['choices'] == [('Lecture', 'lecture')]
    # Refresh must also update the header and clear an obsolete empty-catalog notice.
    assert '<strong>1</strong> materials' in refreshed[3]
    assert 'passages available' in refreshed[3]
    assert refreshed[4] == ''


@pytest.mark.skip(reason="Obsolete save-only upload interface; master ingests uploads immediately, covered in test_mountain_integration.py")
def test_real_client_upload_duplicate_refresh_and_original_persistence(tmp_path):
    from src.app import build_app
    from src.dashboard import Catalog, Dashboard
    from src.material_library import MaterialLibrary
    from gradio_client import Client, handle_file
    original = pdf(tmp_path)
    app = build_app(Dashboard(Catalog.load(tmp_path)))
    try:
        _, url, _ = app.launch(server_name='127.0.0.1', server_port=None,
                             prevent_thread_lock=True, quiet=True, show_error=False)
        client = Client(url, verbose=False)
        added = client.predict([handle_file(str(original))], api_name='/save_materials')
        assert '1 added' in added[0]
        assert 'Awaiting processing' in repr(added[1])
        assert added[2]['choices'] == []
        assert added[3]['choices'] == []
        duplicate = client.predict([handle_file(str(original))], api_name='/save_materials')
        assert '1 already saved' in duplicate[0]
        refreshed = client.predict(api_name='/refresh_library')
        assert 'lecture.pdf' in repr(refreshed[0])
        assert len(MaterialLibrary(tmp_path).rows(Catalog.load(tmp_path))) == 1
        assert (tmp_path/'data/materials/lecture.pdf').read_bytes() == original.read_bytes()
    finally:
        app.close()
