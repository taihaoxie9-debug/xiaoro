# Task 1 RED Evidence

## Scope

- Frozen HEAD: `7d54c58fe35f1425227e55ba07b9d896b43c5ecc`
- Audit key: `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`
- Formal full-file audit invocations: `1`
- RED owner: `tests/guide/runtime/test_import_boundary.py`
- Production configuration changed: `no`
- Additional formal audit invoked: `no`

## Command

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/runtime/test_import_boundary.py::test_dockerfile_defaults_to_guide_runtime \
  tests/guide/runtime/test_import_boundary.py::test_compose_database_password_matches_all_client_urls
```

Result: exit code `1`; `2 failed in 0.09s`.

## Expected Failures

### Default Docker Entry

Node:
`tests/guide/runtime/test_import_boundary.py::test_dockerfile_defaults_to_guide_runtime`

Earliest failing layer: `deployment/runtime composition`.

Exact failure:

```text
E       assert 'CMD ["uvicorn", "app.guide_runtime.app:app"' in '# ==================== 基础镜像 ====================\nFROM python:3.11-slim\n\n# 设置工作目录\nWORKDIR /app\n\n# ==============...================== 启动命令 ====================\nCMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]\n'
```

Reason: `Dockerfile` still defaults to `app.main:app` instead of
`app.guide_runtime.app:app`.

### Compose Database Password

Node:
`tests/guide/runtime/test_import_boundary.py::test_compose_database_password_matches_all_client_urls`

Earliest failing layer: `deployment/configuration`.

Exact failure:

```text
E       AssertionError: DATABASE_URL passwords must match production POSTGRES_PASSWORD: expected '${POSTGRES_PASSWORD}', got {'app': 'postgres123', 'celery_worker': 'postgres123'}
E       assert {'app': 'post...'postgres123'} == {}
E
E         Left contains 2 more items:
E         {'app': 'postgres123', 'celery_worker': 'postgres123'}
E         Use -v to get more diff
```

Reason: the production PostgreSQL service uses `${POSTGRES_PASSWORD}`, while
the `app` and `celery_worker` client URLs each use the different literal
password `postgres123`.

## Disposition

Both failures are intentional Task 1 RED nodes. No `Dockerfile`,
`docker-compose.yml`, or `docker-compose.prod.yml` fix is included in this
checkpoint.
