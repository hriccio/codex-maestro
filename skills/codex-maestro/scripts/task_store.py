"""Local, transactional planned-work records. No network or third-party dependencies."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

SCHEMA = 1
STATES = {
    'backlog': {'ready', 'canceled'},
    'ready': {'backlog', 'in_progress', 'canceled'},
    'in_progress': {'ready', 'review', 'canceled'},
    'review': {'in_progress', 'done', 'canceled'},
    'done': {'backlog'}, 'canceled': {'backlog'},
}


def database_path():
    return Path.home() / '.local/share/codex-maestro/tasks.sqlite3'


def now():
    return datetime.now(timezone.utc).isoformat()


def number(value, prefix='TASK'):
    match = re.fullmatch(prefix + r'-([1-9][0-9]*)', value)
    if not match:
        raise ValueError(f'expected {prefix}-N identifier')
    return int(match[1])


class Store:
    def __init__(self, path=None):
        self.path = Path(path or database_path()).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        try:
            with self.write():
                version = self.db.execute('PRAGMA user_version').fetchone()[0]
                if version not in (0, SCHEMA):
                    raise ValueError(f'unsupported task schema {version}')
                if version == 0:
                    if self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                        raise ValueError('refusing unversioned nonempty database')
                    # Individual statements retain the surrounding initialization transaction.
                    for statement in (
                        'CREATE TABLE campaigns (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, body TEXT NOT NULL, owner TEXT NOT NULL)',
                        '''CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        repository TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                        acceptance TEXT NOT NULL, owner TEXT NOT NULL, campaign INTEGER REFERENCES campaigns(id),
                        external_refs TEXT NOT NULL, evidence TEXT NOT NULL DEFAULT '',
                        state TEXT NOT NULL DEFAULT 'backlog', revision INTEGER NOT NULL DEFAULT 1,
                        created TEXT NOT NULL, updated TEXT NOT NULL,
                        claim TEXT, recovery_path TEXT)''',
                        '''CREATE TABLE dependencies (consumer INTEGER REFERENCES tasks(id),
                        producer INTEGER REFERENCES tasks(id), PRIMARY KEY(consumer, producer))''',
                        '''CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task INTEGER REFERENCES tasks(id), time TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL)''',
                    ):
                        self.db.execute(statement)
                    self.db.execute(f'PRAGMA user_version={SCHEMA}')
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    @contextmanager
    def write(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def event(self, task, kind, data):
        self.db.execute('INSERT INTO events(task,time,kind,data) VALUES(?,?,?,?)',
                        (task, now(), kind, json.dumps(data)))

    def campaign(self, title, body='', owner=''):
        if not title.strip():
            raise ValueError('title is required')
        with self.write():
            ident = self.db.execute('INSERT INTO campaigns(title,body,owner) VALUES(?,?,?)',
                                    (title, body, owner)).lastrowid
        return {'id': f'CAM-{ident}', 'title': title, 'body': body, 'owner': owner}

    def campaigns(self):
        return [dict(row, id=f"CAM-{row['id']}") for row in self.db.execute('SELECT * FROM campaigns ORDER BY id')]

    def create(self, repository, title, body='', acceptance='', owner='', campaign=None, external_refs=None):
        if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository) or any(x in {'.', '..'} for x in repository.split('/')):
            raise ValueError('repository must be canonical owner/name')
        if not title.strip():
            raise ValueError('title is required')
        with self.write():
            ident = self.db.execute('''INSERT INTO tasks(repository,title,body,acceptance,owner,campaign,
                external_refs,created,updated) VALUES(?,?,?,?,?,?,?,?,?)''',
                (repository.lower(), title, body, acceptance, owner,
                 number(campaign, 'CAM') if campaign else None, json.dumps(external_refs or []), now(), now())).lastrowid
            self.event(ident, 'created', {'revision': 1})
        return self.get(f'TASK-{ident}')

    def get(self, ident):
        row = self.db.execute('SELECT * FROM tasks WHERE id=?', (number(ident),)).fetchone()
        if row is None:
            raise ValueError(f'unknown task {ident}')
        task = dict(row)
        task['id'] = ident
        task['campaign'] = f"CAM-{row['campaign']}" if row['campaign'] else None
        task['external_refs'] = json.loads(row['external_refs'])
        task['dependencies'] = [f'TASK-{r[0]}' for r in self.db.execute(
            'SELECT producer FROM dependencies WHERE consumer=? ORDER BY producer', (row['id'],))]
        task['blocked_by'] = [r for r in task['dependencies'] if self.db.execute(
            'SELECT state FROM tasks WHERE id=?', (number(r),)).fetchone()[0] != 'done']
        return task

    def tasks(self, ready=False):
        result = [self.get(f'TASK-{row[0]}') for row in self.db.execute('SELECT id FROM tasks ORDER BY id')]
        return [t for t in result if not ready or (t['state'] == 'ready' and not t['blocked_by'] and not t['claim'])]

    def checked(self, ident, revision, allow_claim=False):
        task = self.get(ident)
        if task['revision'] != revision:
            raise ValueError(f"stale revision; current revision is {task['revision']}")
        if task['claim'] and not allow_claim:
            raise ValueError('task is claimed; stop execution and release explicitly first')
        return task

    def bump(self, ident, kind, data):
        self.db.execute('UPDATE tasks SET revision=revision+1,updated=? WHERE id=?', (now(), number(ident)))
        self.event(number(ident), kind, data)

    def edit(self, ident, revision, **fields):
        allowed = {'title', 'body', 'acceptance', 'owner', 'external_refs', 'evidence', 'campaign'}
        if not fields or set(fields) - allowed:
            raise ValueError('expected editable task fields')
        if 'title' in fields and not fields['title'].strip():
            raise ValueError('title is required')
        with self.write():
            self.checked(ident, revision)
            values = dict(fields)
            if 'external_refs' in values:
                values['external_refs'] = json.dumps(values['external_refs'])
            if 'campaign' in values:
                values['campaign'] = number(values['campaign'], 'CAM') if values['campaign'] else None
            self.db.execute('UPDATE tasks SET ' + ','.join(f'{key}=?' for key in values) + ' WHERE id=?',
                            (*values.values(), number(ident)))
            self.bump(ident, 'edited', fields)
        return self.get(ident)

    def transition(self, ident, revision, state, evidence=''):
        with self.write():
            task = self.checked(ident, revision)
            if state not in STATES[task['state']]:
                raise ValueError(f"invalid transition {task['state']} -> {state}")
            if state in {'in_progress', 'done'} and task['blocked_by']:
                raise ValueError('dependencies are not done')
            if state == 'done' and not evidence.strip():
                raise ValueError('completion requires evidence')
            self.db.execute('UPDATE tasks SET state=?,evidence=? WHERE id=?', (state, evidence, number(ident)))
            self.bump(ident, 'transition', {'from': task['state'], 'to': state, 'evidence': evidence})
        return self.get(ident)

    def dependency(self, ident, revision, producer, remove=False):
        with self.write():
            task = self.checked(ident, revision)
            self.get(producer)
            if task['state'] in {'done', 'canceled'}:
                raise ValueError('reopen the consumer before changing dependencies')
            if not remove:
                cycle = self.db.execute('''WITH RECURSIVE ancestors(id) AS
                    (SELECT ? UNION SELECT d.producer FROM dependencies d JOIN ancestors a ON d.consumer=a.id)
                    SELECT 1 FROM ancestors WHERE id=?''', (number(producer), number(ident))).fetchone()
                if cycle:
                    raise ValueError('dependency cycle')
                self.db.execute('INSERT INTO dependencies VALUES(?,?)', (number(ident), number(producer)))
            else:
                self.db.execute('DELETE FROM dependencies WHERE consumer=? AND producer=?', (number(ident), number(producer)))
            self.bump(ident, 'dependency', {'producer': producer, 'removed': remove})
        return self.get(ident)

    def claim(self, ident, revision, recovery_path):
        with self.write():
            task = self.checked(ident, revision)
            if task['state'] != 'ready' or task['blocked_by']:
                raise ValueError('task must be ready with all dependencies done')
            token = uuid.uuid4().hex
            self.db.execute("UPDATE tasks SET claim=?,recovery_path=?,state='in_progress' WHERE id=?",
                            (token, str(recovery_path), number(ident)))
            self.bump(ident, 'claimed', {'token': token, 'recovery_path': str(recovery_path)})
            # Snapshot inside the claim transaction.
            snapshot = self.get(ident)
        return snapshot

    def release(self, ident, revision, token, reason):
        if not reason.strip():
            raise ValueError('release requires a recovery reason')
        with self.write():
            task = self.checked(ident, revision, allow_claim=True)
            if not task['claim'] or task['claim'] != token:
                raise ValueError('claim token mismatch')
            self.db.execute('UPDATE tasks SET claim=NULL,recovery_path=NULL WHERE id=?', (number(ident),))
            self.bump(ident, 'released', {'reason': reason, 'token': token})
        return self.get(ident)

    def history(self, ident):
        self.get(ident)
        return [dict(r, data=json.loads(r['data'])) for r in self.db.execute(
            'SELECT * FROM events WHERE task=? ORDER BY id', (number(ident),))]

    def export(self):
        self.db.execute('BEGIN')
        try:
            return {'schema': SCHEMA, 'campaigns': self.campaigns(), 'tasks': self.tasks(),
                    'events': [dict(r, data=json.loads(r['data'])) for r in self.db.execute('SELECT * FROM events ORDER BY id')]}
        finally:
            self.db.execute('ROLLBACK')

    def backup(self, destination):
        destination = Path(destination).expanduser().resolve()
        # Exclusive creation prevents accidental overwrite or backing up onto the live store.
        with destination.open('xb'):
            pass
        try:
            with sqlite3.connect(destination) as target:
                self.db.backup(target)
        except BaseException:
            destination.unlink()
            raise
        return {'backup': str(destination)}


def restore(source, destination=None):
    source = Path(source).expanduser().resolve()
    destination = Path(destination or database_path()).resolve()
    db = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    try:
        if db.execute('PRAGMA user_version').fetchone()[0] != SCHEMA:
            raise ValueError('unsupported backup schema')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('invalid backup integrity')
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with destination.open('xb'):
            pass
        try:
            with sqlite3.connect(destination) as target:
                db.backup(target)
            check = Store(destination)
            try:
                for task in check.tasks():
                    if task['state'] not in STATES or task['revision'] < 1:
                        raise ValueError('invalid task record')
                check.export()
            finally:
                check.close()
        except BaseException:
            destination.unlink()
            raise
    finally:
        db.close()
    return {'restored': str(destination)}


def markdown(task):
    return (f"# {task['id']}: {task['title']}\n\n"
            f"Repository: {task['repository']}\nRevision: {task['revision']}\n"
            f"State: {task['state']}\nOwner: {task['owner']}\n"
            f"Campaign: {task['campaign'] or ''}\n"
            f"Dependencies: {', '.join(task['dependencies'])}\n\n"
            f"## Scope\n\n{task['body']}\n\n## Acceptance\n\n{task['acceptance']}\n\n"
            f"## Evidence\n\n{task['evidence']}\n\n"
            f"External references: {', '.join(task['external_refs'])}\n")


def execute(args):
    try:
        if args.task_command == 'restore':
            result = restore(args.file)
        else:
            store = Store()
            try:
                command = args.task_command
                if command in {'create', 'edit'}:
                    fields = {key: getattr(args, key) for key in
                              ('title', 'owner', 'external_refs') if getattr(args, key) is not None}
                    for key in ('body', 'acceptance', 'evidence'):
                        file = getattr(args, key + '_file', None)
                        if file:
                            fields[key] = Path(file).read_text(encoding='utf-8')
                    result = (store.create(args.repository, **fields) if command == 'create'
                              else store.edit(args.id, args.revision, **fields))
                elif command in {'list', 'ready'}:
                    result = store.tasks(ready=command == 'ready')
                    if args.repository:
                        result = [t for t in result if t['repository'] == args.repository.lower()]
                elif command == 'show':
                    result = store.get(args.id)
                elif command == 'transition':
                    result = store.transition(args.id, args.revision, args.state, args.evidence or '')
                elif command == 'block':
                    result = store.dependency(args.id, args.revision, args.by, args.remove)
                elif command == 'release':
                    result = store.release(args.id, args.revision, args.token, args.reason)
                elif command == 'history':
                    result = store.history(args.id)
                elif command == 'export':
                    result = store.export()
                elif command == 'backup':
                    result = store.backup(args.file)
                elif command == 'campaign':
                    result = (store.campaign(args.title,
                              Path(args.body_file).read_text(encoding='utf-8') if args.body_file else '', args.owner)
                              if args.campaign_command == 'create' else store.campaigns())
                else:
                    raise ValueError('unsupported task command')
            finally:
                store.close()
        if getattr(args, 'markdown', False):
            print(markdown(result))
        else:
            print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise SystemExit(f'task: {exc}') from None


def add_parser(sub):
    parser = sub.add_parser('task', help='manage persistent offline tasks (JSON output)')
    commands = parser.add_subparsers(dest='task_command', required=True)
    for name in ('create', 'edit'):
        p = commands.add_parser(name)
        if name == 'create':
            p.add_argument('--repository', required=True, help='canonical owner/name')
        else:
            p.add_argument('id')
            p.add_argument('--revision', type=int, required=True)
        p.add_argument('--title', required=name == 'create')
        p.add_argument('--owner')
        p.add_argument('--external-ref', action='append', dest='external_refs', help='replaces the reference list on edit')
        p.add_argument('--body-file')
        p.add_argument('--acceptance-file')
        p.add_argument('--evidence-file')
    for name in ('list', 'ready'):
        p = commands.add_parser(name)
        p.add_argument('--repository')
    for name in ('show', 'history'):
        p = commands.add_parser(name)
        p.add_argument('id')
        if name == 'show':
            p.add_argument('--markdown', action='store_true')
    p = commands.add_parser('transition')
    p.add_argument('id')
    p.add_argument('state', choices=list(STATES))
    p.add_argument('--revision', type=int, required=True)
    p.add_argument('--evidence', help='required for done')
    p = commands.add_parser('block')
    p.add_argument('id', help='consumer task')
    p.add_argument('--by', required=True, help='producer task')
    p.add_argument('--remove', action='store_true')
    p.add_argument('--revision', type=int, required=True)
    p = commands.add_parser('release', help='release only after confirming worker execution has stopped')
    p.add_argument('id')
    p.add_argument('--revision', type=int, required=True)
    p.add_argument('--token', required=True)
    p.add_argument('--reason', required=True)
    for name in ('backup', 'restore'):
        p = commands.add_parser(name, help='restore requires an absent destination and stopped workers' if name == 'restore' else 'consistent SQLite backup')
        p.add_argument('file')
    parser.set_defaults(func=execute)
