"""Two actual fresh-DB fixed replays and immutable normalized comparison."""
from pathlib import Path
import os
import resource
import subprocess
import time
from .bundle import NORMALIZED, file_digest, verify_package, write_json
from .runtime import java_command, java_environment, services
from .validate import read_json, require


def run_java(root, backend, task, args, output, environment):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    command=java_command(root,task,args)
    started=time.monotonic()
    with (output/'process.log').open('x') as log:
        process=subprocess.run(command,cwd=backend,env=java_environment(root,output,environment),stdout=log,stderr=subprocess.STDOUT)
    write_json(output/'execution.json',dict(command=command,exitCode=process.returncode,elapsedSeconds=round(time.monotonic()-started,3),jvmResourceUsageRef='jvm-resource-usage.txt'))
    require(process.returncode==0,'java-process',detail=f'{task}: {output}/process.log')


def compare_replays(first,second,*,expected_manifest_digest=None):
    first,second=Path(first).resolve(),Path(second).resolve()
    require(first!=second,'distinct-replay-directories')
    observations=[]
    databases=[]
    for root in (first,second):
        observation=read_json(root/'replay-observation.json')
        require(observation.get('status')=='REPLAYED_PARTIAL_VALIDATION','fixed-replay-finished',detail=str(root))
        requested=observation.get('requestedEvents')
        require(type(requested) is int and requested>0 and observation.get('completedEvents')==requested,
                'fixed-replay-complete',detail=str(root))
        require(observation.get('localDisposableDatabaseOnly') is True and observation.get('validationDatabaseUnchanged') is True,
                'fixed-replay-database-preservation',detail=str(root))
        before=observation.get('validationPreservationBefore',{})
        after=observation.get('validationPreservationAfter',{})
        database=before.get('database')
        require(isinstance(database,str) and database and after.get('database')==database,
                'fixed-replay-database-identity',detail=str(root))
        require(before==after,'fixed-replay-database-preservation',detail=str(root))
        if expected_manifest_digest is not None:
            require(observation.get('manifestDigest')==expected_manifest_digest,
                    'fixed-replay-expected-manifest',detail=str(root))
        databases.append(database);observations.append(observation)
    require(databases[0]!=databases[1],'distinct-replay-databases')
    for key in ('datasetId','manifestDigest','requestedEvents'):
        require(observations[0].get(key) is not None and observations[0][key]==observations[1].get(key),
                'fixed-replay-input-binding',detail=key)
    results={}
    for name in NORMALIZED:
        a,b=first/name,second/name
        require(a.is_file() and b.is_file(),'normalized-required',detail=name)
        first_digest,second_digest=file_digest(a),file_digest(b)
        results[name]=dict(first=first_digest,second=second_digest,equal=first_digest==second_digest,byteLength=a.stat().st_size)
    require(all(x['equal'] for x in results.values()),'fixed-replay-equality',detail=str(results))
    return dict(status='PASS',freshDatabaseRuns=2,databaseIdentities=databases,
                manifestDigest=observations[0]['manifestDigest'],datasetId=observations[0]['datasetId'],
                completedEvents=observations[0]['completedEvents'],files=results,
                rawComparison='RAW_PRESERVED_LOGICAL_NORMALIZATION_ONLY',externalDemoApplied=False)


def fixed_replays(package_root,backend,output):
    root=Path(__file__).resolve().parents[1];backend=Path(backend).resolve();output=Path(output).resolve();package_root=Path(package_root).resolve()
    package=verify_package(package_root);output.mkdir(parents=True,exist_ok=False)
    from .provenance import stage_inventory
    stage_inventory(root,backend,output/'source-inventory.json','fixed-replays')
    with services(root,output) as environment:
        for name in ('first','second'):
            destination=output/name
            run_java(root,backend,'simulationRun',[package_root/'bundle',backend/'api/demo-simulation-v1.schema.json',package['manifestDigest'],destination/'replay'],destination,environment)
    comparison=compare_replays(output/'first/replay',output/'second/replay',expected_manifest_digest=package['manifestDigest'])
    comparison['manifestDigest']=package['manifestDigest']
    write_json(output/'comparison.json',comparison)
    return comparison
