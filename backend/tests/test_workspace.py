from uuid import uuid4

import pytest

from app.repositories.workspace import path_for, prepare, remove


def test_path_for_joins_task_id_under_root(tmp_path):
    task_id = uuid4()
    assert path_for(task_id, tmp_path) == tmp_path / str(task_id)


def test_prepare_creates_parent_directories(tmp_path):
    dest = tmp_path / "workspaces" / str(uuid4())
    prepare(dest)
    assert dest.parent.is_dir()
    assert not dest.exists()


def test_prepare_allows_empty_existing_directory(tmp_path):
    dest = tmp_path / str(uuid4())
    dest.mkdir()
    prepare(dest)


def test_prepare_refuses_nonempty_path(tmp_path):
    dest = tmp_path / str(uuid4())
    dest.mkdir()
    (dest / "already-there").write_text("nope")
    with pytest.raises(FileExistsError):
        prepare(dest)


def test_remove_deletes_workspace_but_not_root(tmp_path):
    dest = path_for(uuid4(), tmp_path)
    dest.mkdir()
    (dest / "file.txt").write_text("cloned")
    remove(dest)
    assert not dest.exists()
    assert tmp_path.exists()


def test_remove_missing_path_is_a_noop(tmp_path):
    remove(tmp_path / "does-not-exist")
