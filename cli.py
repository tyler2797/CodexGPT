import sys


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print('Usage: python -m cli "your prompt"')
        raise SystemExit(2)
    prompt = " ".join(args)
    try:
        from core.logic import respond
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    try:
        result = respond(prompt)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if result is not None:
        print(result)


if __name__ == "__main__":
    main()
