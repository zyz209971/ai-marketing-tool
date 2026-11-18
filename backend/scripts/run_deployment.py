"""One process / two agent threads. Scaling requires a distributed job owner first."""
from deployment_config import configure

if __name__ == '__main__':
    port = configure()
    from app.marketing_agent.runtime import checkpointer
    # Fail at startup rather than on the first user turn.
    with checkpointer():
        pass
    import uvicorn
    uvicorn.run('app.main:app',host='0.0.0.0',port=port,workers=1,proxy_headers=False)
