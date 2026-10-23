"""The Documents tab and folder auto-ingest: what the page asks the server for and what it promises the owner.
These are text checks on the page code (the dashboard rules in test_office.py still apply to it)."""
import pathlib

JS = (pathlib.Path(__file__).resolve().parent.parent / "core" / "office_static" / "app.js").read_text()


def test_the_documents_tab_reads_the_folder_status_and_posts_the_approval():
    assert 'api("GET", "/folder-ingest")' in JS
    assert 'api("POST", "/folder-ingest/approve", { grant: g.grant })' in JS


def test_the_owner_sees_the_cost_warning_before_the_first_read():
    assert "Nothing is read until you approve" in JS
    assert "can cost money" in JS and "Approve and start" in JS
    assert '"waiting_approval"' in JS


def test_folder_documents_are_labelled_and_not_deleted_from_the_page():
    assert '"from folder "' in JS and "kept up to date by the folder" in JS
    assert "folder ? h(\"span\", { class: \"sub\" }, \"kept up to date by the folder\") : del" in JS


def test_an_older_server_without_the_route_does_not_break_the_tab():
    # only a 401 is passed on (it locks the page); any other error from /folder-ingest just hides the panel
    assert 'catch (e) { if (String(e.message) === "unauthorized") throw e; }' in JS
    assert "if (!fi || !fi.enabled) return [];" in JS


def test_folder_names_go_in_as_text():
    start = JS.index("const folderCard")
    end = JS.index("const refreshDocuments")
    block = JS[start:end]
    assert "innerHTML" not in block and "textContent" in block
