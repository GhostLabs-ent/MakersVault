"""Qualify supplied local image identities over disposable production HTTPS."""
import argparse
import json
from pathlib import Path
import tempfile

from verification_runtime import DisposableStack, image_identity, install_signal_handlers, smoke


def main():
    install_signal_handlers()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-image", required=True)
    parser.add_argument("--web-image", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    identities = {name: image_identity(image, args.version, args.revision)
                  for name, image in (("api", args.api_image), ("web", args.web_image))}
    with tempfile.TemporaryDirectory(prefix="makersvault-current-smoke-") as temporary:
        stack = DisposableStack(Path(temporary) / "stack", identities["api"], identities["web"])
        try:
            stack.start()
            result = smoke(stack, args.version, args.revision)
        finally:
            stack.close()
    print(json.dumps({"status": "passed", "revision": args.revision, "images": identities, **result}, sort_keys=True))


if __name__ == "__main__":
    main()
