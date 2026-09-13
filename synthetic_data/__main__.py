"""Reproducible local simulation entry points; no external target is accepted."""
import argparse
import json
from pathlib import Path
from .generate import generate
from .validate import validate_discovery
from .bundle import make_bundle, write_json
from .replay import fixed_replays
from .application import application_cycle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='operation',required=True)
    generation=sub.add_parser('generate',help='100 people, actual STEP/result/FINISH; new local DB')
    generation.add_argument('--output',required=True);generation.add_argument('--backend',required=True);generation.add_argument('--seed',type=int,default=20260910)
    validation=sub.add_parser('validate',help='Independent oracle over a completed discovery run')
    validation.add_argument('--run',required=True);validation.add_argument('--output')
    bundle=sub.add_parser('bundle',help='Strict manifest bundle, exact RAW, six CSV projections')
    bundle.add_argument('--run',required=True);bundle.add_argument('--output',required=True);bundle.add_argument('--schema',required=True)
    bundle.add_argument('--retain-unadmitted',action='store_true',help='Retain known NOT_ELIGIBLE missing-response or capacity failures as an explicitly UNADMITTED evidence package; never invent bytes or claim backend admission')
    replay=sub.add_parser('replay',help='Two fixed replays, separate fresh local DBs')
    replay.add_argument('--package',required=True);replay.add_argument('--backend',required=True);replay.add_argument('--output',required=True)
    application=sub.add_parser('verify-application',help='Actual backup/apply/restore on a NEW disposable local target')
    application.add_argument('--package',required=True);application.add_argument('--backend',required=True);application.add_argument('--output',required=True);application.add_argument('--relational')
    args=parser.parse_args()
    if args.operation=='generate':
        generate(args.output,args.backend,args.seed);return
    if args.operation=='validate':
        result=validate_discovery(args.run)
        if args.output:write_json(args.output,result)
    elif args.operation=='bundle':result=make_bundle(args.run,args.output,args.schema,retain_unadmitted=args.retain_unadmitted)
    elif args.operation=='replay':result=fixed_replays(args.package,args.backend,args.output)
    else:result=application_cycle(args.package,args.backend,args.output,args.relational)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))

if __name__=='__main__':main()
