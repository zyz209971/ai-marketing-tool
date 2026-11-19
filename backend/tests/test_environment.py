import os
from pathlib import Path
from unittest.mock import patch
import pytest
from app.environment import load_environment


def test_private_configuration_precedence(tmp_path):
    (tmp_path/'.env').write_text('WORD_API_KEY=base-test-value\nCOPY_MODEL=base-model\nQWEN_BASE_URL=https://example.invalid/v1\n',encoding='utf-8')
    (tmp_path/'.env.local').write_text('WORD_API_KEY=local-test-value\nCOPY_MODEL=local-model\n',encoding='utf-8')
    external=tmp_path/'private-config'
    external.write_text('WORD_API_KEY=external-test-value\nCOPY_MODEL=external-model\n',encoding='utf-8')
    with patch.dict(os.environ,{'WORD_API_KEY':'process-test-value'},clear=True):
        files=load_environment(tmp_path,str(external))
        assert len(files)==3
        assert os.environ['WORD_API_KEY']=='process-test-value'
        assert os.environ['COPY_MODEL']=='external-model'
        assert os.environ['QWEN_BASE_URL']=='https://example.invalid/v1'


def test_missing_explicit_file_is_not_silent(tmp_path):
    with patch.dict(os.environ,{},clear=True), pytest.raises(ValueError,match='不存在'):
        load_environment(tmp_path,str(tmp_path/'missing'))


def test_no_secret_in_loader_return(tmp_path):
    (tmp_path/'.env.local').write_text('WORD_API_KEY=local-test-value',encoding='utf-8')
    with patch.dict(os.environ,{},clear=True):
        returned=load_environment(tmp_path)
        assert 'local-test-value' not in str(returned)


def test_default_local_overrides_base(tmp_path):
    (tmp_path/'.env').write_text('COPY_MODEL=base',encoding='utf-8')
    (tmp_path/'.env.local').write_text('COPY_MODEL=local',encoding='utf-8')
    with patch.dict(os.environ,{},clear=True):
        load_environment(tmp_path)
        assert os.environ['COPY_MODEL']=='local'


def test_local_runtime_cannot_write_remote_checkpoints(tmp_path):
    import importlib.util
    spec=importlib.util.spec_from_file_location('local_launcher',Path(__file__).parents[1]/'scripts'/'run_agent_local.py')
    launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
    with patch.dict(os.environ,{'AGENT_CHECKPOINT_URL':'postgresql://example.invalid/remote'},clear=True):
        launcher.configure_runtime(tmp_path)
        assert os.environ['AGENT_CHECKPOINT_URL']==''
        assert os.environ['BRAND_DATABASE_URL']=='sqlite:///'+(tmp_path/'brand-knowledge.db').as_posix()
        assert os.environ['APP_DATA_DIR']==str(tmp_path)
