"""Stage-specific code inventories; never pretend later packaging code ran at generation start."""
from pathlib import Path
import subprocess
from .bundle import file_digest, write_json
from .policy import digest


def backend_overlay(backend):
    """Hash the executable working tree delta, including new files and deletions."""
    backend=Path(backend)
    scope=['src/simulation','src/main','api','build.gradle.kts']
    modified=set(subprocess.check_output(['git','diff','--name-only','-z','HEAD','--',*scope],cwd=backend,text=True).split('\0'))
    modified.update(subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z','--',*scope],cwd=backend,text=True).split('\0'))
    modified.discard('')
    return {name:file_digest(backend/name) if (backend/name).is_file() else None for name in sorted(modified)}


def stage_inventory(root,backend,output,stage):
    root,backend,output=Path(root).resolve(),Path(backend).resolve(),Path(output)
    paths=set()
    for folder in ('synthetic_data','scripts/demo','feed','feed_service','recap_service'):
        paths.update(p for p in (root/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.java','.sh','.kts','.gradle'))
    paths.update(root/name for name in ('generate_data.py','monthly_batch.py','weekly_batch.py','monthly_recap.py','weekly_recap.py','recap_presenter.py','wish_category_classifier.py','api/demo-simulation-v1.schema.json','api/feed-ranking-v1.yaml'))
    sources={p.relative_to(root).as_posix():file_digest(p) for p in sorted(paths)}
    backend_sources=backend_overlay(backend)
    result=dict(schemaVersion=1,stage=stage,dataHeadSha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),backendHeadSha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=backend,text=True).strip(),dataSourceInventory=sources,dataSourceDigest=digest(sources),backendWorkingTreeOverlay=backend_sources,backendOverlayDigest=digest(backend_sources))
    write_json(output,result);return result
