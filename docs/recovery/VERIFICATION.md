# Verification boundary

Prepared: 2026-09-11. This is an implementation candidate, not a claim that the
user's GitHub repository or ModelScope space has been changed or deployed.

## Executed in the current environment

- 25 passing Python unittest cases.
- Real nginx configuration parsing and local HTTP integration, with MOCK auth
  and desktop upstreams: deny anonymous/bad cookies; allow a valid fixture cookie;
  fail closed if authorization fails; authorize WebSocket upgrade; block foreign
  WebSocket origins; protect assets; avoid forwarding Basic/Bearer headers.
- Python compilation and shell syntax checks.
- YAML structure checks and supervisor configuration parsing.
- Password hashing/idempotence, first-boot missing-password rejection, weak-password
  rejection and safe-write symlink rejection.

The root test output is bundled in LOCAL_TEST_RESULTS.txt. A passing nginx mock
integration test does not validate Authelia login or a real graphical desktop.

## Included but NOT executed here

The environment has no Docker daemon and cannot build/download the complete
upstream dependency tree. GitHub Actions will build the image and run
`tests/smoke_container.py` BEFORE publishing. This gate tests:

- Actual Authelia configuration validation and session login.
- Real Studio HTTP readiness and a running plasmashell process.
- Real noVNC WebSocket handshake and CLI import from outside the source directory.
- Sentinel persistence and re-login after a container restart.

The gate deliberately makes no paid LLM requests. If it fails, no deployment
artifact/image is published by the workflow. Studio tag availability, native Node
modules, OS packages and compatibility of the pinned upstream versions must pass
this build/run gate; they have not been independently proven in this environment.

## Still requires ModelScope acceptance

1. Actual public app hostname; do not infer it from the Studio identifier.
2. Correct Cookies, Set-Cookie, Origin, WebSocket forwarding and platform access
   controls through the real HTTPS ingress.
3. Writable /mnt/workspace subdirectories for uid 1001 and uid 1002. A community
   image author reports permission issues on some platform/base-image combinations;
   this must be checked, not dismissed. Do not blindly chmod everything to 777.
4. KDE rendering, keyboard/Chinese input, clipboard and the browser sandbox.
5. Provider access, exact model id, inference, streaming and actual Hermes tool use.
6. Restart/rebuild persistence, an off-site backup and an isolated restore rehearsal.
7. Actual allocated CPU/memory/storage and the account's current pause/idle policy.

No uptime, free inference quota, build duration, or 50-GB retention guarantee is
inferred from historical screenshots or community marketing text.


Additional protocol/install references:
https://tigervnc.org/doc/vncpasswd.html
https://nginx.org/en/docs/http/ngx_http_auth_basic_module.html
https://pip.pypa.io/en/stable/topics/local-project-installs/

Additional community architecture reference (not independently deployment-tested):
https://github.com/cybest2010/ai-infra-studio
