"""Preserve every immutable evidence path/byte while sharing identical local copies."""
from pathlib import Path
import filecmp
import hashlib
import os
import stat
import uuid


def link_identical(original,duplicate):
    original,duplicate=Path(original),Path(duplicate)
    if not original.is_file() or not duplicate.is_file():return 0
    left,right=original.lstat(),duplicate.lstat()
    if not stat.S_ISREG(left.st_mode) or not stat.S_ISREG(right.st_mode):raise ValueError('evidence must be a regular file')
    if (left.st_dev,left.st_ino)==(right.st_dev,right.st_ino):return 0
    if left.st_size!=right.st_size or not filecmp.cmp(original,duplicate,shallow=False):raise ValueError('immutable source and indexed RAW differ')
    # Atomic replacement of this extra storage copy only; both named evidence paths remain.
    temporary=duplicate.with_name(duplicate.name+'.link-'+uuid.uuid4().hex)
    try:
        os.link(original,temporary)
        os.replace(temporary,duplicate)
    finally:
        if temporary.exists():temporary.unlink()
    return right.st_size


def deduplicate_completed(replay,events):
    """Caller supplies only backend-confirmed completed events, never the active command."""
    replay=Path(replay);saved=0;linked=0
    for event in events:
        sequence=event['sequence'];kind=event['kind'];command=event['command'];pairs=[]
        if kind=='FEED_QUERY':
            folder=replay/'feed-execution'/f'event-{sequence}'
            for source in folder.glob('*.json'):
                pairs.append((replay/'raw/feed'/f'event-{sequence}-{source.name}',source))
        elif kind in ('CLOSE_WEEK','CLOSE_MONTH'):
            base=replay/'recap-execution';folder=base/f'event-{sequence}'
            for part in ('source','input','verification'):
                name=f'event-{sequence}-period-{part}.json';pairs.append((replay/'raw/recap-period'/name,base/name))
            for name,key in [('request.json','requestRef'),('response.json','responseRef'),('stored-state.json','storedStateRef')]:
                pairs.append((replay/command[key],folder/name))
            pairs.extend([(replay/'raw/recap-http'/f'event-{sequence}.json',folder/'http.json'),(replay/'raw/recap-result'/f'event-{sequence}.json',folder/'result-verification.json')])
        for original,duplicate in pairs:
            amount=link_identical(original,duplicate)
            if amount:linked+=1;saved+=amount
    return dict(status='EXACT_BYTES_PRESERVED',linkedDuplicateFiles=linked,duplicateLogicalBytesShared=saved,evidencePathsRemoved=0)
