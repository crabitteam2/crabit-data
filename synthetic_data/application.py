"""Actual local PREPARE/APPLY/INSPECT/RESTORE against an owned disposable DB."""
from contextlib import contextmanager
from pathlib import Path
import json
import os
import subprocess
import tempfile
import time
from .bundle import file_digest, verify_package, write_json
from .policy import digest
from .replay import run_java
from .runtime import java_environment
from .validate import read_json, require


@contextmanager
def local_target(root,backend,output):
    output.mkdir(parents=True,exist_ok=False)
    environment=java_environment(root,output,os.environ)
    command=['./gradlew','--quiet','--console=plain','--init-script',str(root/'scripts/demo/diagnostics/classpath.gradle'),'simulationDiagnosticClasspath']
    classpath=subprocess.check_output(command,cwd=backend,env=environment,text=True).strip()
    with tempfile.TemporaryDirectory(prefix='crabit-local-target-') as private:
        ready=Path(private)/'ready.json'
        subprocess.run([str(Path(environment['JAVA_HOME'])/'bin/javac'),'--class-path',classpath,'-d',private,str(root/'scripts/demo/LocalTarget.java')],cwd=backend,env=environment,check=True)
        classpath=private+os.pathsep+classpath
        with (output/'target.log').open('x') as log:
            process=subprocess.Popen([str(Path(environment['JAVA_HOME'])/'bin/java'),'--class-path',classpath,'com.crabit.backend.simulation.LocalTarget',str(ready)],cwd=backend,env=environment,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT)
            try:
                until=time.monotonic()+120
                while not ready.is_file():
                    require(process.poll() is None and time.monotonic()<until,'local-target-ready',detail=str(output/'target.log'))
                    time.sleep(.2)
                value=read_json(ready)
                environment.update(CRABIT_SIMULATION_TARGET_JDBC_URL=value['url'],CRABIT_SIMULATION_TARGET_DB_USER=value['user'],CRABIT_SIMULATION_TARGET_DB_PASSWORD=value['password'])
                write_json(output/'target.json',dict(kind='OWNED_DISPOSABLE_LOCAL_POSTGRES',localRuntimeDirectory=output.name,externalConsoleVerified=False,existingOwnerBalance=23456,excludedAcademySentinel=True))
                yield environment
            finally:
                process.stdin.close()
                try:process.wait(timeout=60)
                except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=30)


def verify_applied(before,after):
    old,new=before['tables'],after['tables'];owner='00000000-0000-0000-0000-000000000201';account='00000000-0000-0000-0000-000000000301'
    require(len(new['student'])==100,'applied-100')
    require(len(new['demo_simulation_account'])==100,'applied-accounts-100')
    for table,key,value in [('student','id',owner),('card_balance_account','id',account),('wish','account_id',account),('balance_observation','account_id',account),('ledger_event','account_id',account)]:
        require([r for r in old[table] if r[key]==value]==[r for r in new[table] if r[key]==value],'owner-preserved',detail=table)
    require([r for r in new['academy'] if r['id']=='00000000-0000-0000-0000-000000000102']==[r for r in old['academy'] if r['id']=='00000000-0000-0000-0000-000000000102'],'excluded-academy-preserved')
    observations=[r for r in new['balance_observation'] if r['account_id']!=account]
    require(observations and all(r['source_kind']=='SIMULATION' for r in observations),'synthetic-source')
    return dict(status='PASS',students=100,originalOwnerPreserved=True,syntheticAccounts=99,simulationObservations=len(observations),excludedAcademyPreserved=True,externalConsoleVerified=False)


def verify_restored(before,after):
    for table,rows in before['tables'].items():
        if table!='demo_simulation_dataset':require(after['tables'][table]==rows,'restored-table',detail=table)
    require(before['snapshot']['sequences']==after['snapshot']['sequences'],'restored-sequences')
    require(len(after['journal'])==2,'restored-audit-journal')
    return dict(status='PASS',originalDomainTablesRestored=True,sequencesRestored=True,journalEntries=2,externalConsoleVerified=False)


def application_cycle(package_root,backend,output,relational=None):
    root=Path(__file__).resolve().parents[1];backend=Path(backend).resolve();package_root=Path(package_root).resolve();output=Path(output).resolve()
    package=verify_package(package_root);output.mkdir(parents=True,exist_ok=False)
    from .provenance import stage_inventory
    stage_inventory(root,backend,output/'source-inventory.json','local-application')
    code=subprocess.check_output(['git','rev-parse','HEAD'],cwd=backend,text=True).strip()
    target_id='data-local-'+package['datasetId'][7:23]
    baseline=dict(kind='LOCAL_FIXTURE_ONLY',targetIdentity=target_id,externalConsoleVerified=False,ownerBalance=23456)
    write_json(output/'local-baseline.json',baseline);console=digest(baseline)
    write_json(output/'inspect-config.json',dict(targetIdentity=target_id))
    def call(operation,config,name,environment):
        folder=output/name;run_java(root,backend,'simulationImport',[operation,config,folder/'result'],folder,environment);return folder/'result'
    with local_target(root,backend,output/'target') as environment:
        before=read_json(call('INSPECT',output/'inspect-config.json','before',environment)/'inspection.json')
        write_json(output/'prepare-config.json',dict(schema=str(backend/'api/demo-simulation-v1.schema.json'),relational=str(Path(relational).resolve() if relational else package_root/'state/relational.json'),students=str(package_root/'bundle/students.json'),personas=str(package_root/'bundle/personas.json'),manifestDigest=package['manifestDigest'],targetIdentity=target_id,consoleBaselineDigest=console,codeSha=code))
        try:
            plan=call('PREPARE',output/'prepare-config.json','prepare',environment)
        except Exception:
            # PREPARE has no committed APPLY intent. Retain authoritative rollback
            # read-back on this owned test DB before its lifecycle ends.
            rejected=read_json(call('INSPECT',output/'inspect-config.json','after-rejected-prepare',environment)/'inspection.json')
            require(before['snapshot']==rejected['snapshot'] and before['journal']==rejected['journal'],
                    'rejected-prepare-rollback')
            write_json(output/'verification.json',dict(status='BLOCKED_BEFORE_APPLY',
                       manifestDigest=package['manifestDigest'],bundleAdmissionAtStart=package.get('backendAdmission','NOT_VERIFIED'),
                       prepareFailureLog='prepare/process.log',dryRunRollbackVerified=True,
                       beforeFingerprint=before['fingerprint'],afterRejectedPrepareFingerprint=rejected['fingerprint'],
                       originalDomainTablesUnchanged=True,applicationExecuted=False,restoreExecuted=False,
                       externalDemoApplied=False,externalConsoleVerified=False))
            raise
        dry_after=read_json(call('INSPECT',output/'inspect-config.json','after-dry-run',environment)/'inspection.json')
        require(before['snapshot']==dry_after['snapshot'],'dry-run-rollback')
        applied=read_json(call('APPLY',plan/'prepared-request.json','apply',environment)/'result.json')
        require(applied['status']=='APPLIED' and applied['authoritativeReadBack'] is True,'actual-apply-readback')
        after=read_json(call('INSPECT',output/'inspect-config.json','after-apply',environment)/'inspection.json')
        application=verify_applied(before,after);write_json(output/'application-verification.json',application)
        preparation=read_json(plan/'preparation.json')
        require(file_digest(plan/'backup.json')==preparation['backupDigest'],'backup-integrity')
        write_json(output/'restore-config.json',dict(backup=str(plan/'backup.json'),backupDigest=preparation['backupDigest'],consoleBaselineDigest=console,codeSha=code))
        restore=call('RESTORE_PREPARE',output/'restore-config.json','restore-prepare',environment)
        restored=read_json(call('APPLY',restore/'prepared-request.json','restore',environment)/'result.json')
        require(restored['status']=='RESTORED' and restored['authoritativeReadBack'] is True,'actual-restore-readback')
        final=read_json(call('INSPECT',output/'inspect-config.json','after-restore',environment)/'inspection.json')
        restoration=verify_restored(before,final);write_json(output/'restoration-verification.json',restoration)
    report=dict(status='PASS',manifestDigest=package['manifestDigest'],bundleAdmissionAtStart=package.get('backendAdmission','NOT_VERIFIED'),application=application,restoration=restoration,externalDemoApplied=False,externalConsoleVerified=False)
    write_json(output/'verification.json',report);return report
