"""Owned loopback processes, persistent STEP transport, and exact JVM resource measurement."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import os
import queue
import secrets
import subprocess
import sys
import threading


def java_environment(root, output, environment):
    env = environment.copy()
    java_home = env.get('JAVA_HOME')
    if not java_home:
        java_home = subprocess.check_output(['/usr/libexec/java_home', '-v', '21'], text=True).strip()
    java = Path(java_home) / 'bin/java'
    if not java.is_file():
        raise ValueError('Java 21 executable is unavailable')
    env.update(
        JAVA_HOME=str(java_home),
        CRABIT_SIMULATION_REAL_JAVA=str(java),
        CRABIT_SIMULATION_MEASURED_JAVA=str(root / 'scripts/demo/measured-java.sh'),
        CRABIT_SIMULATION_JVM_METRICS=str(output / 'jvm-resource-usage.txt'),
    )
    return env


def java_command(root, task, args):
    if task not in ('simulationSession', 'simulationRun', 'simulationImport', 'simulationInspect'):
        raise ValueError('unsupported local simulation task')
    if any(any(c.isspace() for c in str(x)) or any(c in str(x) for c in ['"', "'"]) for x in args):
        raise ValueError('Gradle simulation arguments must be paths without whitespace or quotes')
    return ['./gradlew', '--quiet', '--console=plain', '--init-script',
            str(root / 'scripts/demo/simulation-runtime.gradle.kts'), task,
            '--args=' + ' '.join(str(x) for x in args)]


@contextmanager
def services(root, output):
    env = os.environ.copy()
    token = secrets.token_urlsafe(32)
    env.update(FEED_RANKING_CREDENTIAL=token, CRABIT_RECAP_TOKEN=token,
               CRABIT_RECAP_HOST='127.0.0.1', CRABIT_RECAP_PORT='0')
    processes, handles = [], []
    try:
        for module, key, path in [('feed_service', 'FEED', '/internal/v1/feed-rankings'),
                                  ('recap_service', 'RECAP', '/internal/v1/recap-generations')]:
            log = open(output / f'{module}.log', 'w')
            handles.append(log)
            args = [sys.executable, '-u', '-m', module]
            if key == 'FEED':
                args += ['--host', '127.0.0.1', '--port', '0']
            process = subprocess.Popen(args, cwd=root, env=env, stdout=subprocess.PIPE, stderr=log, text=True)
            processes.append(process)
            ready_queue = queue.Queue()
            threading.Thread(target=lambda p=process, q=ready_queue: q.put(p.stdout.readline()), daemon=True).start()
            line = ready_queue.get(timeout=30)
            if not line:
                raise RuntimeError(f'{module} failed before ready; see {output / (module + ".log")}')
            ready = json.loads(line)
            if ready.get('event') != module.replace('_', '-') + '-ready' or ready.get('host') != '127.0.0.1':
                raise ValueError('unexpected service ready message')
            env[f'CRABIT_SIMULATION_{key}_URL'] = f"http://127.0.0.1:{ready['port']}{path}"
            env[f'CRABIT_SIMULATION_{key}_TOKEN'] = token
        yield env
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for handle in handles:
            handle.close()


class Session:
    def __init__(self, backend, config, output, env, logs):
        self.root = Path(__file__).resolve().parents[1]
        self.command = java_command(self.root, 'simulationSession',
                                    [backend / 'api/demo-simulation-v1.schema.json', config, output])
        self.log = open(logs / 'backend-session.log', 'w')
        self.protocol = open(logs / 'protocol.ndjson', 'w')
        self.intents = open(logs / 'intents.ndjson', 'w')
        self.queue = queue.Queue()
        self.process = subprocess.Popen(self.command, cwd=backend,
                                        env=java_environment(self.root, logs, env),
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.log, text=True, bufsize=1)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()
        try:
            self.receive('READY')
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                if line.startswith('CRABIT_SIMULATION_V1 '):
                    self.queue.put(json.loads(line.split(' ', 1)[1]))
                else:
                    self.log.write(line)
                    self.log.flush()
        finally:
            self.queue.put({'status': 'PROCESS_EXITED', 'exitCode': self.process.wait()})

    def receive(self, expected):
        result = self.queue.get(timeout=900)
        self.protocol.write(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n')
        self.protocol.flush()
        if result['status'] != expected:
            raise RuntimeError(f'backend protocol expected {expected}: {result}; command={self.command}')
        return result

    def send(self, value, expected):
        line = json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n'
        self.intents.write(line)
        self.intents.flush()
        self.process.stdin.write(line)
        self.process.stdin.flush()
        return self.receive(expected)

    def step(self, event):
        return self.send({'operation': 'STEP', 'event': event}, 'STEPPED')

    def finish(self):
        result = self.send({'operation': 'FINISH'}, 'DISCOVERY_COMPLETED')
        self.process.stdin.close()
        if self.process.wait(timeout=60) != 0:
            raise RuntimeError('backend process failed after FINISH')
        return result

    def close(self):
        if not self.process.stdin.closed:
            self.process.stdin.close()
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=30)
        self.thread.join(timeout=10)
        self.log.close()
        self.protocol.close()
        self.intents.close()
