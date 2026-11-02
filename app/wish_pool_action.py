"""许愿池工具箱入口。"""
import argparse
import wish_pool_run as run

def main():
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--claim', action='store_true')
    actions.add_argument('--wish', type=int)
    args = parser.parse_args()
    flow = run.connect()
    try:
        info = run.entry(flow)
        if args.claim or args.wish is not None:
            ok, message, _ = (run.claim_prev(flow, info) if args.claim else run.wish_one(flow, info, args.wish))
            print(('[OK] ' if ok else '[--] ') + message)
        run._print_status(run.get_status(flow, run.entry(flow)))
    finally:
        flow.disconnect()

if __name__ == '__main__':
    main()
