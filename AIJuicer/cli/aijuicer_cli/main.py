"""aijuicer CLI（spec § 8.3）。

典型用法：
    aijuicer workflow submit --name demo --input '{"topic":"hi"}'
    aijuicer workflow list
    aijuicer workflow show <wf_id>
    aijuicer workflow approve <wf_id> --step requirement
    aijuicer workflow rerun <wf_id> --step requirement --input @revised.json
    aijuicer workflow logs <wf_id> --follow
    aijuicer agents list
"""

from __future__ import annotations

import json
import os
import sys
from typing import Annotated

import httpx
import typer

app = typer.Typer(help="AI 榨汁机 CLI", no_args_is_help=True)
workflow_app = typer.Typer(help="管理 workflow", no_args_is_help=True)
agents_app = typer.Typer(help="管理 agent", no_args_is_help=True)
app.add_typer(workflow_app, name="workflow")
app.add_typer(agents_app, name="agents")


def _server() -> str:
    return os.environ.get("AIJUICER_SERVER", "http://localhost:8000").rstrip("/")


def _load_input(raw: str | None) -> dict:
    if raw is None:
        return {}
    if raw.startswith("@"):
        with open(raw[1:]) as f:
            return json.load(f)
    return json.loads(raw)


def _fmt(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


@workflow_app.command("submit")
def submit(
    name: Annotated[str, typer.Option(..., help="workflow 名")],
    project_name: Annotated[
        str,
        typer.Option(
            "--project-name",
            help="项目 slug（小写英文 + 短横线）；撞名时 scheduler 会自动加 4 位随机后缀",
        ),
    ],
    input: Annotated[str, typer.Option("--input", help="JSON 或 @file.json")] = "{}",
    approval_policy: Annotated[
        str, typer.Option("--policy", help='如 {"requirement":"auto"}')
    ] = "{}",
) -> None:
    r = httpx.post(
        f"{_server()}/api/workflows",
        json={
            "name": name,
            "project_name": project_name,
            "input": _load_input(input),
            "approval_policy": _load_input(approval_policy),
        },
        timeout=30.0,
    )
    r.raise_for_status()
    typer.echo(_fmt(r.json()))


@workflow_app.command("list")
def list_wfs(
    q: Annotated[str | None, typer.Option("--q", help="name 模糊搜索")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    status_group: Annotated[
        str | None,
        typer.Option("--group", help="running/awaiting/manual/completed/aborted/active"),
    ] = None,
    page: Annotated[int, typer.Option("--page")] = 1,
    page_size: Annotated[int, typer.Option("--page-size")] = 20,
) -> None:
    params: dict = {"page": page, "page_size": page_size}
    if q:
        params["q"] = q
    if status:
        params["status"] = status
    if status_group:
        params["status_group"] = status_group
    r = httpx.get(f"{_server()}/api/workflows", params=params, timeout=30.0)
    r.raise_for_status()
    body = r.json()
    items = body["items"]
    for it in items:
        typer.echo(
            f"{it['id']}  {it['status']:<30}  {it.get('current_step') or '-':<14}  {it['name']}"
        )
    typer.echo(f"-- 共 {body['total']} 条 · 第 {body['page']} 页 · 每页 {body['page_size']} --")


@workflow_app.command("show")
def show(wf_id: str) -> None:
    r = httpx.get(f"{_server()}/api/workflows/{wf_id}", timeout=30.0)
    r.raise_for_status()
    typer.echo(_fmt(r.json()))


def _decision(wf_id: str, decision: str, **body: object) -> None:
    payload: dict = {"decision": decision}
    payload.update({k: v for k, v in body.items() if v is not None})
    r = httpx.post(f"{_server()}/api/workflows/{wf_id}/approvals", json=payload, timeout=30.0)
    if r.status_code >= 400:
        typer.echo(f"[{r.status_code}] {r.text}", err=True)
        raise typer.Exit(code=1)
    typer.echo(_fmt(r.json()))


@workflow_app.command("approve")
def approve(
    wf_id: str,
    step: Annotated[str, typer.Option(..., help="待审批的 step")],
    comment: Annotated[str | None, typer.Option("--comment")] = None,
) -> None:
    _decision(wf_id, "approve", step=step, comment=comment)


@workflow_app.command("reject")
def reject(
    wf_id: str,
    step: Annotated[str, typer.Option(..., help="被拒的 step")],
    comment: Annotated[str | None, typer.Option("--comment")] = None,
) -> None:
    _decision(wf_id, "reject", step=step, comment=comment)


@workflow_app.command("abort")
def abort(
    wf_id: str,
    comment: Annotated[str | None, typer.Option("--comment")] = None,
) -> None:
    _decision(wf_id, "abort", comment=comment)


@workflow_app.command("rerun")
def rerun(
    wf_id: str,
    step: Annotated[str, typer.Option(..., help="要重跑的 step")],
    input: Annotated[str | None, typer.Option("--input", help="JSON 或 @file.json")] = None,
    comment: Annotated[str | None, typer.Option("--comment")] = None,
) -> None:
    _decision(
        wf_id,
        "rerun",
        step=step,
        comment=comment,
        modified_input=_load_input(input) if input else None,
    )


@workflow_app.command("skip")
def skip(
    wf_id: str,
    comment: Annotated[str | None, typer.Option("--comment")] = None,
) -> None:
    _decision(wf_id, "skip", comment=comment)


@workflow_app.command("logs")
def logs(
    wf_id: str,
    follow: Annotated[bool, typer.Option("--follow/--no-follow", "-f")] = True,
) -> None:
    """订阅 workflow 的 SSE 事件流。"""
    url = f"{_server()}/api/workflows/{wf_id}/events"
    try:
        with httpx.stream("GET", url, timeout=httpx.Timeout(None, read=None)) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    typer.echo(line[5:].strip())
                elif line.startswith("event:"):
                    typer.echo(f"-- {line[6:].strip()} --")
                if not follow:
                    return
    except KeyboardInterrupt:
        sys.exit(0)


@workflow_app.command("artifacts")
def artifacts(wf_id: str) -> None:
    r = httpx.get(f"{_server()}/api/workflows/{wf_id}/artifacts", timeout=30.0)
    r.raise_for_status()
    for a in r.json():
        typer.echo(f"{a['step']:<12}  {a['key']:<30}  {a['size_bytes']:>8}B  {a['id']}")


@agents_app.command("list")
def agents_list() -> None:
    r = httpx.get(f"{_server()}/api/agents", timeout=30.0)
    r.raise_for_status()
    for a in r.json():
        typer.echo(
            f"{a['step']:<12}  {a['status']:<8}  {a['name']:<24}  last_seen={a['last_seen_at']}"
        )
