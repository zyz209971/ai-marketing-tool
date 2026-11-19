import importlib.util
from pathlib import Path
from unittest.mock import patch
import os
import pytest

spec=importlib.util.spec_from_file_location('deployment_config',Path(__file__).parents[1]/'scripts'/'deployment_config.py')
config=importlib.util.module_from_spec(spec);spec.loader.exec_module(config)
BASE={'AUTH_MODE':'session','DB_PASSWORD':'test:pass/@ with spaces','APP_DATA_DIR':'/data',
      'BRAND_STORAGE_DIR':'/data/brand-files','WORKSPACE_LOCAL_ONLY':'false'}


def test_deployment_builds_driver_specific_urls_without_exposing_password():
    from sqlalchemy.engine import make_url
    from psycopg.conninfo import conninfo_to_dict
    with patch.dict(os.environ,BASE,clear=True),patch('app.environment.load_environment',return_value=[]):
        assert config.configure()==8000
        assert make_url(os.environ['BRAND_DATABASE_URL']).password==BASE['DB_PASSWORD']
        assert conninfo_to_dict(os.environ['AGENT_CHECKPOINT_URL'])['password']==BASE['DB_PASSWORD']


@pytest.mark.parametrize('change',[
    {'AUTH_MODE':'local'}, {'DB_PASSWORD':''}, {'BRAND_STORAGE_DIR':''},
    {'WORKSPACE_LOCAL_ONLY':'true'}, {'COOKIE_SECURE':'false'}, {'APP_ACCESS_KEY':'old-shared-secret'},
])
def test_insecure_or_incomplete_deployment_is_rejected(change):
    with patch.dict(os.environ,{**BASE,**change},clear=True),patch('app.environment.load_environment',return_value=[]):
        with pytest.raises(ValueError):config.configure()
