#!/usr/bin/python3
"""Explicit cloud API smoke test. May consume quota; never run automatically at startup."""
import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--chat', action='store_true', help='Make one small, potentially billable chat request')
    args = parser.parse_args()
    base = os.environ.get('OPENAI_BASE_URL', '').rstrip('/')
    key = os.environ.get('OPENAI_API_KEY', '')
    model = os.environ.get('HERMES_MODEL', '')
    parts = urlsplit(base)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or not key:
        raise SystemExit('Set an HTTPS OPENAI_BASE_URL and the OPENAI_API_KEY secret first.')
    payload = None
    if args.chat:
        if not model:
            raise SystemExit('Set HERMES_MODEL to an exact model id available to this account.')
        payload = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': 'Reply with OK.'}],
                              'max_tokens': 64}).encode()
    request = Request(base + ('/chat/completions' if args.chat else '/models'), data=payload,
                      headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=90) as response:
            data = json.load(response)
    except HTTPError as exc:
        # Do not print raw error bodies: providers may echo request metadata/secrets.
        raise SystemExit(f'Provider returned HTTP {exc.code}; check endpoint, quota, model access and key.')
    except (URLError, TimeoutError, ValueError):
        raise SystemExit('Provider connection or JSON decoding failed.')
    if args.chat:
        if not data.get('choices'):
            raise SystemExit('Provider response has no choices. Model-specific handling is required.')
        print('Chat transport succeeded. This is NOT a Hermes tool-use or reasoning acceptance test.')
    else:
        for item in data.get('data', []):
            if isinstance(item, dict) and 'id' in item:
                print(item['id'])
        if not data.get('data'):
            print('No model ids returned; this provider may not support the standard /models endpoint.')


if __name__ == '__main__':
    main()
