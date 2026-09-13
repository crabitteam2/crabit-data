"""Build the strict backend bundle and a separately checksummed delivery package."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import csv
import hashlib
import json
import os
import shutil

from .policy import canonical, digest
from .validate import read_json, require, validate_discovery

LIMITS = dict(files=262144, manifestBytes=128*1024*1024, artifactBytes=128*1024*1024, aggregateBytes=8*1024**3)
ROLES = {'config.json':'CONFIG','students.json':'STUDENTS','personas.json':'PERSONAS','events.ndjson':'EVENTS',
         'id-map.json':'ID_MAP','state/export.json':'STATE','validation.json':'VALIDATION','normalized.json':'NORMALIZED',
         'demo-simulation-v1.schema.json':'SCHEMA','raw/index.json':'RAW_INDEX'}
NORMALIZED = ('normalized-backend.json','normalized-relational.json','normalized-responses.json','normalized-feed.json','normalized-recaps.json')


def file_digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            h.update(chunk)
    return 'sha256:'+h.hexdigest()


def immutable_copy(source,destination):
    source,destination=Path(source),Path(destination)
    require(source.is_file() and not source.is_symlink(),'regular-artifact',detail=str(source))
    destination.parent.mkdir(parents=True,exist_ok=True)
    # APFS/POSIX hardlinks preserve exact immutable bytes without duplicating large local RAW.
    try:
        os.link(source,destination)
    except OSError:
        with source.open('rb') as src,destination.open('xb') as dst:
            shutil.copyfileobj(src,dst)


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as file:
        file.write(canonical(value))


def projection_csv(replay,output):
    """Legacy columns project actual persisted rows, never fabricate balancing entries."""
    replay,output=Path(replay),Path(output);output.mkdir(parents=True,exist_ok=False)
    state=read_json(replay/'state/relational.json')['tables']
    mapping=read_json(replay/'id-map.json')['entries']
    reverse={(x['entityKind'],x['replayUuid']):x['logicalId'] for x in mapping}
    def logical(kind,value):
        return '' if value is None else reverse[(kind,value)]
    accounts={x['student_id']:x['id'] for x in state['card_balance_account']}
    roots={x['id']:x for x in state['ledger_event']}
    representative={x['wish_id'] for x in state['representative_wish_selection'] if x.get('wish_id') is not None}
    wishes_by_id={w['id']:w for w in state['wish']}
    tables={
        'users.csv':(['user_id','name','age'],[dict(user_id=logical('STUDENT',x['id']),name=x['nickname'],age=x['age']) for x in state['student']]),
        'card_accounts.csv':(['account_id','user_id','academy_id','created_at','closed_at'],[
            dict(account_id=logical('ACCOUNT',x['id']),user_id=logical('STUDENT',x['student_id']),academy_id=logical('ACADEMY',x['academy_id']),created_at=x['opened_at'],closed_at=x['closed_at']) for x in state['card_balance_account']]),
        'wishes.csv':(['wish_id','account_id','academy_id','title','target_amount','target_date','is_representative','status','created_at','closed_at','deleted_at','saved_amount'],[
            dict(wish_id=logical('WISH',x['id']),account_id=logical('ACCOUNT',x['account_id']),academy_id=logical('ACADEMY',x['academy_id']),title=x['purpose'],
                 target_amount=x['target_amount'],target_date=x['target_date'],is_representative='TRUE' if x['id'] in representative else 'FALSE',
                 status={'IN_PROGRESS':'진행중','AMOUNT_REACHED':'진행중','COMPLETED':'완료','ABANDONED':'포기'}[x['state']],
                 created_at=x['created_at'],closed_at=x['completed_at'] or x['abandoned_at'],deleted_at=x['deleted_at'],saved_amount=x['wish_amount']) for x in state['wish']]),
        'savings_transactions.csv':(['transaction_id','account_id','wish_id','amount','event_type','created_at'],[
            dict(transaction_id=logical('LEDGER_EFFECT',x['id']),account_id=logical('ACCOUNT',x['account_id']),wish_id=logical('WISH',x['wish_id']),
                 amount=x['wish_delta'],event_type=roots[x['event_id']]['event_type'],created_at=roots[x['event_id']]['occurred_at']) for x in state['ledger_wish_effect']]),
        'feed_posts.csv':(['feed_id','account_id','wish_id','kind','updated_at'],[
            dict(feed_id=logical('SHARED_CARD',x['id']),account_id=logical('ACCOUNT',wishes_by_id[x['wish_id']]['account_id']),wish_id=logical('WISH',x['wish_id']),
                 kind={'PROGRESS':'진행중','COMPLETION':'완료','ABANDONMENT':'포기'}[x['kind']],updated_at=x['updated_at']) for x in state['shared_card']]),
        'profile_visits.csv':(['visit_id','visited_account_id','visitor_account_id','created_at'],[
            dict(visit_id=logical('BEHAVIOR_EVENT',x['event_id']),visited_account_id=logical('ACCOUNT',accounts[x['target_id']]),
                 visitor_account_id=logical('ACCOUNT',accounts[x['actor_id']]),created_at=x['occurred_at'])
            for x in state['behavior_event'] if x['event_type']=='PROFILE_VISIT']),
    }
    report={}
    for name,(fields,rows) in tables.items():
        rows.sort(key=lambda row:tuple(str(row.get(field,'')) for field in fields))
        path=output/name
        with path.open('x',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        with path.open(encoding='utf-8-sig',newline='') as stream:
            require(len(list(csv.DictReader(stream)))==len(rows),'csv-roundtrip',detail=name)
        report[name]={'rows':len(rows),'sha256':file_digest(path),'byteLength':path.stat().st_size,'columns':fields}
    return report


def make_bundle(run,output,trusted_schema,*,retain_unadmitted=False):
    run,output,trusted_schema=Path(run).resolve(),Path(output).resolve(),Path(trusted_schema).resolve()
    validation=validate_discovery(run)
    replay=run/'discovery';config=read_json(run/'config.json');binding=read_json(run/'binding.json')
    # Preserve evidence of the known backend NOT_ELIGIBLE defect only when explicitly
    # requested. Missing Python bytes are never replaced with a fabricated response.
    missing=[]
    for line in (replay/'events.ndjson').read_text().splitlines():
        event=json.loads(line)
        for ref in event['artifactRefs']:
            if (replay/ref).is_file():continue
            result=read_json(replay/event['outcome']['resultRef'])
            legitimate=(event['kind'] in ('CLOSE_WEEK','CLOSE_MONTH') and ref==event['command']['responseRef']
                        and result.get('state')=='NOT_ELIGIBLE' and result.get('pythonInvoked') is False)
            require(retain_unadmitted and legitimate,'backend-unmaterialized-reference',event['eventId'],ref)
            missing.append(dict(eventId=event['eventId'],occurredAt=event['occurredAt'],path=ref,resultRef=event['outcome']['resultRef']))
    output.mkdir(parents=True,exist_ok=False);bundle=output/'bundle';bundle.mkdir()
    from .provenance import stage_inventory
    stage_inventory(Path(__file__).resolve().parents[1],trusted_schema.parent.parent,
                    output/'reports/package-source-inventory.json','package')
    dataset=digest(binding);schema_bytes=trusted_schema.read_bytes()
    require(len(schema_bytes)<=1024*1024,'schema-capacity')
    for name in ('config.json','students.json','personas.json'):
        immutable_copy(run/name,bundle/name)
    for name in ('id-map.json','state/export.json','raw/index.json'):
        immutable_copy(replay/name,bundle/name)
    (bundle/'demo-simulation-v1.schema.json').write_bytes(schema_bytes)
    raw=read_json(replay/'raw/index.json')
    refs={}
    for record in raw['records']:
        refs.setdefault(record['eventId'],[]).append(record['path'])
        immutable_copy(replay/record['path'],bundle/record['path'])
    events=[]
    with (bundle/'events.ndjson').open('xb') as target:
        for line in (replay/'events.ndjson').read_bytes().splitlines():
            event=json.loads(line)
            # Append only observed evidence links. Immutable request/result bytes are untouched.
            event['artifactRefs']=sorted(set(event['artifactRefs']) | set(refs[event['eventId']]))
            target.write(canonical(event)+b'\n');events.append(event)
    normalized=[]
    for name in NORMALIZED:
        immutable_copy(replay/name,output/'normalized'/name)
        normalized.append(dict(path='normalized/'+name,sha256=file_digest(replay/name)))
    # Strict canonical input accepts safe integers only. Exact float-bearing backend projections
    # stay intact outside the bundle, cryptographically committed by this ordered digest index.
    write_json(bundle/'normalized.json',normalized)
    rules=[dict(rule=name,status='PASS',checkedCount=count,errors=[],artifactRefs=refs_)
           for name,count,refs_ in [
               ('population-personas',100,['students.json','personas.json']),
               ('event-cash-allocation-access',len(events),['events.ndjson','state/export.json','id-map.json']),
               ('complete-periods',validation['periods'],['events.ndjson']),
               ('original-raw-integrity',validation['rawRecords'],['raw/index.json'])]]
    if missing:
        rules.append(dict(rule='backend-required-references',status='FAIL',checkedCount=len(events),
                          errors=[dict(code='UNMATERIALIZED_NOT_ELIGIBLE_RESPONSE',rule='backend-required-references',logicalId=x['eventId'],
                                       occurredAt=x['occurredAt'],message='Backend command requires responseRef although NOT_ELIGIBLE correctly produced no HTTP response.',
                                       artifactRefs=[x['resultRef']]) for x in missing],artifactRefs=['events.ndjson']))
    rules.append(dict(rule='two-fresh-fixed-replays',status='NOT_RUN',checkedCount=0,errors=[],artifactRefs=[]))
    write_json(bundle/'validation.json',dict(schemaVersion=1,schemaKind='demo-simulation-validation',datasetId=dataset,
               configDigest=binding['configDigest'],schemaDigest=digest(schema_bytes),ruleVersion='data-oracle-v1',rules=rules,
               counts=[dict(name=kind,value=count) for kind,count in sorted(validation['counts'].items())],
               independentAggregates=[dict(name='all-periods',value=validation['periods']),dict(name='causal-influence',value=validation['influenceCount'])]))
    files=[]
    for path in sorted(p for p in bundle.rglob('*') if p.is_file()):
        name=path.relative_to(bundle).as_posix();role=ROLES.get(name,'RAW')
        if role=='RAW':count=1
        elif role=='EVENTS':count=len(events)
        else:
            document=read_json(path);count=len(document) if isinstance(document,list) else 1
        files.append(dict(path=name,role=role,byteLength=path.stat().st_size,sha256=file_digest(path),recordCount=count))
    manifest=dict(**binding,schemaKind='demo-simulation-manifest',datasetId=dataset,schemaDigest=digest(schema_bytes),
                  runtimeVersions=config['runtimeVersions'],logicalDigest=digest(normalized),files=files)
    manifest_bytes=canonical(manifest)
    sizes=dict(files=len(files),manifestBytes=len(manifest_bytes),aggregateBytes=sum(f['byteLength'] for f in files),
               maxArtifactBytes=max(f['byteLength'] for f in files))
    capacity_violations=[dict(dimension=dimension,actual=sizes[key],limit=LIMITS[dimension])
                         for dimension,key in [('files','files'),('manifestBytes','manifestBytes'),
                                               ('artifactBytes','maxArtifactBytes'),('aggregateBytes','aggregateBytes')]
                         if sizes[key]>LIMITS[dimension]]
    # An explicitly UNADMITTED evidence package may retain an oversized manifest for
    # exact backend rejection/read-back and independent local import verification.
    # Never silently prune RAW, raise backend limits, or claim admission from this option.
    require(retain_unadmitted or not capacity_violations,'bundle-capacity',detail=str(capacity_violations))
    (bundle/'manifest.json').write_bytes(manifest_bytes)
    for path in sorted((replay/'state').glob('*.json')):
        immutable_copy(path,output/'state'/path.name)
    csv_report=projection_csv(replay,output/'csv')
    write_json(output/'reports/discovery-validation.json',validation)
    write_json(output/'reports/csv-projection.json',csv_report)
    for source in sorted((run/'source-snapshot').rglob('*')):
        if source.is_file():immutable_copy(source,output/'source-snapshot'/source.relative_to(run/'source-snapshot'))
    for name in ('source-snapshot-manifest.json','service-source-inventory.json'):
        if (run/name).is_file():immutable_copy(run/name,output/'reports'/name)
    for name in ('source-inventory.json','measurement.json','jvm-resource-usage.txt','generation-result.json'):
        immutable_copy(run/name,output/'reports'/name)
    package=dict(schemaVersion=1,schemaKind='demo-simulation-delivery-package',datasetId=dataset,
                 bundlePath='bundle',manifestDigest=digest(manifest_bytes),logicalDigest=manifest['logicalDigest'],
                 generationInputDigest=binding['configDigest'],ownerPolicy='LOCAL_100_APPLIED_ORIGINAL_OWNER_PLUS_99',
                 capacityLimits=LIMITS,measuredBundleSize=sizes,readyForApplication=False,
                 backendAdmission='BLOCKED_BACKEND_REQUIREMENTS' if capacity_violations else ('BLOCKED_MISSING_BACKEND_ARTIFACT' if missing else 'NOT_VERIFIED'),
                 unmaterializedBackendReferences=missing,capacityPassed=not capacity_violations,capacityViolations=capacity_violations,
                 files=[dict(path=p.relative_to(output).as_posix(),sha256=file_digest(p),byteLength=p.stat().st_size)
                        for p in sorted(output.rglob('*')) if p.is_file()])
    write_json(output/'package.json',package)
    return package


def verify_package(package_root):
    root=Path(package_root).resolve();package=read_json(root/'package.json')
    for entry in package['files']:
        relative=Path(entry['path'])
        require(not relative.is_absolute() and '..' not in relative.parts,'package-path')
        path=root/relative
        require(path.is_file() and not path.is_symlink() and path.stat().st_size==entry['byteLength'] and file_digest(path)==entry['sha256'],'package-checksum',detail=str(relative))
    require(file_digest(root/'bundle/manifest.json')==package['manifestDigest'],'manifest-checksum')
    return package
