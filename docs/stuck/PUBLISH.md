# PR publication — STUCK

The user authorized one PR to `Chowdarichandu/order_flow`. The repository was
empty; the local source-only main baseline and T00 scaffold branch are committed.

Two distinct publication approaches failed:

1. Git push of main and codex/orderflow-zero-bootstrap, using the existing GitHub
   CLI credential helper: HTTP 403, permission denied to Chowdarichandu. Neither
   branch was created by this failed atomic push.
2. GitHub connector create_file of the source baseline: HTTP 403,
   `Resource not accessible by integration`. No remote file was created.

Read-only repository metadata reports admin/push permissions, but the actual
write requests are denied. Permission metadata is not proof of usable write
access. No credential was printed and no permission change was attempted.

PR creation cannot succeed without remote base/head branches. No PR was opened.
Do not retry either approach until the GitHub integration has write access.

The full PR body is in docs/PR_DESCRIPTION.md. A complete Git bundle is exported
as /workspace/orderflow-zero.bundle. From an authorized owner environment:

```bash
git clone -b codex/orderflow-zero-bootstrap /path/to/orderflow-zero.bundle order_flow
cd order_flow
git branch main origin/main
git remote rename origin bundle-source
git remote add origin https://github.com/Chowdarichandu/order_flow.git
git push --atomic origin main codex/orderflow-zero-bootstrap
gh pr create --repo Chowdarichandu/order_flow --draft --base main \
  --head codex/orderflow-zero-bootstrap \
  --title 'T00: bootstrap scaffold; offline verification blocked' \
  --body-file docs/PR_DESCRIPTION.md
```

These commands only publish the prepared source and draft PR. They do not solve
the missing offline test dependencies or make the recorder deployable.
