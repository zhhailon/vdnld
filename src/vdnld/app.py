"""Application orchestration for vdnld."""

from __future__ import annotations

import functools

from vdnld.dependencies import require_ffmpeg
from vdnld.download.execute import DownloadExecutionError, clear_plan_cache, execute_plan
from vdnld.download.manager import DownloadPlan, plan_download
from vdnld.extractors.browser import capture_media_requests, interactive_capture_media_requests


def run(
    url: str,
    output: str | None,
    *,
    quality: str | None = None,
    ffmpeg_required: bool = True,
    browser_fallback: bool = False,
    interactive_browser: bool = False,
    plan_only: bool = False,
    resume: bool = True,
    clear_cache: bool = False,
    tor: bool = False,
) -> None:
    proxy_url: str | None = None
    if tor:
        from vdnld.net.proxy import enable_socks5_proxy, tor_proxy_url
        enable_socks5_proxy()
        proxy_url = tor_proxy_url()
        print(f"proxy: {proxy_url}")
        _print_tor_info()

    base_probe = interactive_capture_media_requests if interactive_browser else capture_media_requests
    browser_probe = functools.partial(base_probe, proxy_url=proxy_url) if proxy_url else base_probe
    plan = plan_download(
        url=url,
        output=output,
        browser_fallback=browser_fallback or interactive_browser,
        browser_probe=browser_probe,
        quality=quality,
    )
    _print_plan(plan)
    if clear_cache:
        target, cleared = clear_plan_cache(plan)
        print("status: cache cleared" if cleared else "status: no cache")
        print(f"target: {target}")
        return
    if plan_only:
        print("status: planned")
        return
    if ffmpeg_required and plan.executable:
        require_ffmpeg()
    if plan.executable:
        target = execute_plan_target(plan)
        print("status: downloading")
        print(f"target: {target}")
    try:
        output_path = execute_plan(plan, resume=resume)
    except DownloadExecutionError as exc:
        print(f"status: not executed")
        print(f"reason: {exc}")
        return
    print(f"status: downloaded")
    print(f"saved_to: {output_path}")


def _print_tor_info() -> None:
    import json
    from urllib.request import urlopen

    try:
        with urlopen("https://check.torproject.org/api/ip", timeout=10) as resp:
            data = json.loads(resp.read())
        is_tor = data.get("IsTor", False)
        ip = data.get("IP", "unknown")
        print(f"tor: {'yes' if is_tor else 'no (traffic may not be anonymized)'}")
        print(f"exit_node: {ip}")
        if ip and ip != "unknown":
            _print_ip_geo(ip)
    except Exception as exc:
        print(f"tor: could not verify ({exc})")


def _print_ip_geo(ip: str) -> None:
    import json
    from urllib.request import urlopen

    try:
        with urlopen(f"http://ip-api.com/json/{ip}?fields=country,countryCode,city", timeout=10) as resp:
            data = json.loads(resp.read())
        parts = [data.get("countryCode", ""), data.get("country", ""), data.get("city", "")]
        location = ", ".join(p for p in parts if p)
        if location:
            print(f"location: {location}")
    except Exception:
        pass


def _print_plan(plan: DownloadPlan) -> None:
    print(f"url: {plan.url}")
    print(f"output: {plan.output or '<auto>'}")
    if plan.title:
        print(f"title: {plan.title}")
    print(f"strategy: {plan.strategy}")
    print(f"extractor: {plan.extractor}")
    print(f"merge: {'yes' if plan.needs_merge else 'no'}")
    if plan.selected_url and plan.selected_url != plan.url:
        print(f"selected_url: {plan.selected_url}")
    if plan.notes:
        print(f"notes: {plan.notes}")


def execute_plan_target(plan: DownloadPlan) -> str:
    from vdnld.download.execute import resolve_output_path

    return str(resolve_output_path(plan))
