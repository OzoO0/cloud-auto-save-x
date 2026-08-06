from __future__ import annotations

import inspect
import logging
import re
import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Iterable, TypeVar
from zoneinfo import ZoneInfo

from natsort import natsorted
from treelib import Tree

from app.core.errors import bad_request
from app.core.settings import settings
from app.extensions.runtime.execution_log import ExecutionLog
from app.extensions.runtime.magic_rename import MagicRename
from app.extensions.runtime.retry_utils import RetryResult, retry_call, summarize_payload


logger = logging.getLogger(__name__)



class SkipTask(Exception):
    pass


T = TypeVar("T")


def _validate_code_status(action: str, resp: Any) -> RetryResult:
    if not isinstance(resp, dict):
        return RetryResult(value=resp, ok=True)
    status = resp.get("status")
    if status is not None and status not in (200, "200"):
        return RetryResult(
            value=resp,
            ok=False,
            error_message=f"{action} status={status} message={resp.get('message') or ''} resp={summarize_payload(resp)}",
        )
    code = resp.get("code")
    if code is not None and code not in (0, "0"):
        return RetryResult(
            value=resp,
            ok=False,
            error_message=f"{action} code={code} message={resp.get('message') or ''} resp={summarize_payload(resp)}",
        )
    return RetryResult(value=resp, ok=True)


def _parse_enddate(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _normalize_name(name: str, ignore_extension: bool) -> str:
    normalized = name.strip().lower()
    if not ignore_extension:
        return normalized
    if "." in normalized:
        return normalized.rsplit(".", 1)[0]
    return normalized


def _is_dir(payload: dict[str, Any]) -> bool:
    if payload.get("is_dir") is not None:
        return bool(payload.get("is_dir"))
    if payload.get("isdir") is not None:
        return str(payload.get("isdir")) in ("1", "true", "True")
    if payload.get("dir") is not None:
        return bool(payload.get("dir"))
    if payload.get("kind") in ("folder", "dir", "directory"):
        return True
    if payload.get("kind") in ("file",):
        return False
    if payload.get("type") in ("folder", "dir"):
        return True
    if payload.get("type") in ("file",):
        return False
    if payload.get("file_type") is not None:
        value = str(payload.get("file_type"))
        if value in ("0", "dir", "folder"):
            return True
        if value in ("1", "file"):
            return False
    return False


def _get_name(payload: dict[str, Any]) -> str:
    return str(
        payload.get("file_name")
        or payload.get("server_filename")
        or payload.get("fileName")
        or payload.get("name")
        or payload.get("title")
        or payload.get("fid")
        or payload.get("fs_id")
        or ""
    )


def _get_fid(payload: dict[str, Any]) -> str:
    return str(payload.get("fid") or payload.get("fs_id") or payload.get("file_id") or payload.get("id") or payload.get("fileId") or "")


def _get_fid_token(payload: dict[str, Any]) -> str | None:
    value = payload.get("fid_token") or payload.get("share_fid_token") or payload.get("token")
    if value is None:
        return None
    return str(value)


def _get_updated_at(payload: dict[str, Any]):
    return payload.get("updated_at") or payload.get("update_time") or payload.get("mtime") or payload.get("modified_at")


@dataclass(slots=True)
class DramaPlanItem:
    fid: str
    fid_token: str | None
    origin_name: str
    target_name: str


class DramaTaskExecutor:
    def __init__(self, *, adapter: Any, task_data: dict[str, Any], log: ExecutionLog | None = None):
        self.adapter = adapter
        self.task_data = task_data
        self.log = log
        self.transfer_count = 0

    def _set_stage(self, stage: str | None) -> None:
        if self.log:
            self.log.set_stage(stage)

    def _section(self, title: str) -> None:
        if self.log:
            self.log.section(title)

    def _line(self, text: str = "") -> None:
        if self.log:
            self.log.line(text)

    def _retry(
        self,
        *,
        action: str,
        fn: Callable[[], T],
        validate: Callable[[T], RetryResult] | None = None,
    ) -> T:
        return retry_call(
            action=action,
            fn=fn,
            validate=validate,
            attempts=int(getattr(settings, "drama_runtime_retry_max_attempts", 3) or 3),
            backoff_seconds=float(getattr(settings, "drama_runtime_retry_backoff_seconds", 1.0) or 1.0),
            max_backoff_seconds=float(getattr(settings, "drama_runtime_retry_max_backoff_seconds", 8.0) or 8.0),
            jitter_ratio=float(getattr(settings, "drama_runtime_retry_jitter_ratio", 0.2) or 0.2),
            emit=self._line,
            log=logger,
        )

    def _ls_dir(self, pdir_fid: str) -> dict[str, Any]:
        return self._retry(
            action="ls_dir",
            fn=lambda: self.adapter.ls_dir(pdir_fid, max_items=0) or {},
            validate=lambda r: _validate_code_status("ls_dir", r),
        )

    def _mkdir(self, savepath: str) -> dict[str, Any]:
        return self._retry(
            action="mkdir",
            fn=lambda: self.adapter.mkdir(savepath),
            validate=lambda r: _validate_code_status("mkdir", r),
        )

    def _query_task(self, job_id: str) -> dict[str, Any]:
        return self._retry(
            action="query_task",
            fn=lambda: self.adapter.query_task(str(job_id)) or {},
            validate=lambda r: _validate_code_status("query_task", r),
        )

    def _try_get_dir_fid(self, dir_path: str) -> str | None:
        fids = self._retry(action="get_fids", fn=lambda: self.adapter.get_fids([dir_path]) or [])
        for item in fids:
            if (item.get("file_path") or item.get("path")) == dir_path and item.get("fid"):
                return str(item["fid"])
        if fids and fids[0].get("fid"):
            return str(fids[0]["fid"])
        return None

    def _ensure_dest_dir_fid(self, savepath: str) -> str:
        existing = self._try_get_dir_fid(savepath)
        if existing:
            return existing
        response = self._mkdir(savepath)
        if not response:
            raise RuntimeError("创建目录失败")
        created = self._try_get_dir_fid(savepath)
        if created:
            return created
        raise RuntimeError("创建目录失败")

    def _list_dest_names(self, dest_fid: str, ignore_extension: bool) -> set[str]:
        listing = self._ls_dir(dest_fid)
        raw_items = (((listing or {}).get("data") or {}).get("list")) or []
        names: set[str] = set()
        for raw in raw_items:
            if _is_dir(raw):
                continue
            name = _get_name(raw)
            if not name:
                continue
            names.add(_normalize_name(name, ignore_extension))
        return names

    def _fetch_share_items(self, *, pwd_id: str, stoken: str, pdir_fid: str) -> list[dict[str, Any]]:
        def _validate(detail: dict[str, Any]) -> RetryResult:
            if not isinstance(detail, dict):
                return RetryResult(value=detail, ok=False, error_message=f"get_detail invalid response: {summarize_payload(detail)}")
            status = detail.get("status")
            if status is not None and status not in (200, "200"):
                return RetryResult(value=detail, ok=False, error_message=f"get_detail status={status} message={detail.get('message') or ''} resp={summarize_payload(detail)}")
            code = detail.get("code")
            if code is not None and code not in (0, "0"):
                return RetryResult(value=detail, ok=False, error_message=f"get_detail code={code} message={detail.get('message') or ''} resp={summarize_payload(detail)}")
            data = detail.get("data")
            if not isinstance(data, dict) or data.get("list") is None:
                return RetryResult(value=detail, ok=False, error_message=f"get_detail missing list: {summarize_payload(detail)}")
            return RetryResult(value=detail, ok=True)

        detail = self._retry(action="get_detail", fn=lambda: self.adapter.get_detail(pwd_id, stoken, pdir_fid or ""), validate=_validate)
        return (((detail or {}).get("data") or {}).get("list")) or []

    def _list_dest_dir_map(self, dest_fid: str) -> dict[str, str]:
        listing = self._ls_dir(dest_fid)
        raw_items = (((listing or {}).get("data") or {}).get("list")) or []
        result: dict[str, str] = {}
        for raw in raw_items:
            if not _is_dir(raw):
                continue
            name = _get_name(raw)
            fid = _get_fid(raw)
            if name and fid:
                result[name] = fid
        return result

    def _save_items(self, *, pwd_id: str, stoken: str, to_pdir_fid: str, items: list[dict[str, Any]]) -> None:
        plan: list[DramaPlanItem] = []
        for raw in items:
            fid = str(_get_fid(raw)).strip()
            token = _get_fid_token(raw)
            name = _get_name(raw)
            if not fid:
                continue
            if not token:
                raise RuntimeError("分享列表缺少 fid_token，无法转存")
            plan.append(
                DramaPlanItem(
                    fid=fid,
                    fid_token=str(token),
                    origin_name=str(name),
                    target_name=str(name),
                )
            )
        if not plan:
            return
        self._save_with_saved_fids(pwd_id=pwd_id, stoken=stoken, dest_root_fid=to_pdir_fid, plan=plan)

    def _call_save_file(
        self,
        *,
        fid_list: list[str],
        fid_token_list: list[str],
        to_pdir_fid: str,
        pwd_id: str,
        stoken: str,
        file_names: list[str],
    ) -> dict[str, Any]:
        try:
            params = inspect.signature(self.adapter.save_file).parameters
            if "file_names" in params:
                return self.adapter.save_file(fid_list, fid_token_list, to_pdir_fid, pwd_id, stoken, file_names=file_names)
        except Exception:
            pass
        try:
            return self.adapter.save_file(fid_list, fid_token_list, to_pdir_fid, pwd_id, stoken, file_names=file_names)
        except TypeError:
            return self.adapter.save_file(fid_list, fid_token_list, to_pdir_fid, pwd_id, stoken)

    def _extract_saved_fids(
        self,
        *,
        save_file_return: dict[str, Any] | None,
        query_task_return: dict[str, Any] | None,
    ) -> tuple[list[str], str]:
        data = (save_file_return or {}).get("data") or {}
        if data.get("_sync") and data.get("save_as_top_fids") is not None:
            fids = [str(x).strip() for x in (data.get("save_as_top_fids") or []) if str(x).strip()]
            return fids, "save_file.data.save_as_top_fids"

        drive_type = str(getattr(self.adapter, "DRIVE_TYPE", "") or "")
        qdata = (query_task_return or {}).get("data") or {}
        save_as = (qdata.get("save_as") or {}) if isinstance(qdata, dict) else {}
        if drive_type == "uc":
            if save_as.get("save_as_select_top_fids") is not None:
                fids = [str(x).strip() for x in (save_as.get("save_as_select_top_fids") or []) if str(x).strip()]
                return fids, "query_task.data.save_as.save_as_select_top_fids"
        if save_as.get("save_as_top_fids") is not None:
            fids = [str(x).strip() for x in (save_as.get("save_as_top_fids") or []) if str(x).strip()]
            return fids, "query_task.data.save_as.save_as_top_fids"
        return [], "missing"

    def _save_with_saved_fids(self, *, pwd_id: str, stoken: str, dest_root_fid: str, plan: list[DramaPlanItem]) -> list[str]:
        fid_list = [item.fid for item in plan]
        fid_token_list = [item.fid_token or "" for item in plan]
        file_names = [item.origin_name for item in plan]
        if any(not token for token in fid_token_list):
            raise RuntimeError("分享列表缺少 fid_token，无法转存")

        drive_type = str(getattr(self.adapter, "DRIVE_TYPE", "") or "")
        actual_save_fid = str(dest_root_fid)
        share_folder_fid = None
        if drive_type == "uc" and hasattr(self.adapter, "get_or_create_share_folder") and hasattr(self.adapter, "move_files_to_target"):
            share_folder_fid = self.adapter.get_or_create_share_folder()
            if share_folder_fid:
                actual_save_fid = str(share_folder_fid)
                self._line("使用中转目录: 来自：分享")
            else:
                self._line("获取中转目录失败，直接转存到目标目录")

        saved_fids: list[str] = []
        err_msg: str | None = None
        idx = 0
        while idx < len(fid_list):
            batch_fids = fid_list[idx : idx + 100]
            batch_tokens = fid_token_list[idx : idx + 100]
            batch_names = file_names[idx : idx + 100]
            idx += 100

            save_ret = self._call_save_file(
                fid_list=batch_fids,
                fid_token_list=batch_tokens,
                to_pdir_fid=actual_save_fid,
                pwd_id=str(pwd_id),
                stoken=str(stoken),
                file_names=batch_names,
            ) or {}
            if (save_ret.get("code") not in (0, "0", None)) or (save_ret.get("status") not in (200, "200", None)):
                err_msg = str(save_ret.get("message") or "转存失败")
                break

            qret = None
            job_id = (
                (save_ret.get("data") or {}).get("task_id")
                or (save_ret.get("data") or {}).get("taskId")
                or save_ret.get("task_id")
                or save_ret.get("taskId")
                or ""
            ).strip()
            if job_id:
                self._line(f"转存任务 id: {job_id}")
                qret = self._query_task(str(job_id))
                status = ((qret.get("data") or {}).get("status"))
                if status not in (2, "2", None):
                    err_msg = str((qret.get("data") or {}).get("message") or qret.get("message") or "转存任务失败")
                    break

            batch_saved, source = self._extract_saved_fids(save_file_return=save_ret, query_task_return=qret)
            self._line(f"saved_fids: {len(batch_saved)}（来源={source}）")
            saved_fids.extend(batch_saved)

        if err_msg:
            raise RuntimeError(err_msg)
        if not saved_fids:
            raise RuntimeError("转存任务完成但未返回转存后 fid 列表")

        if share_folder_fid and drive_type == "uc":
            self._set_stage("move_files")
            self._section("移动到目标目录")
            self._line(f"移动文件数: {len(saved_fids)}")
            move_ret = self.adapter.move_files_to_target(saved_fids, str(dest_root_fid)) or {}
            if move_ret.get("code") not in (0, "0", None):
                raise RuntimeError(str(move_ret.get("message") or "移动失败"))

        if len(saved_fids) != len(plan):
            self._line(f"提示: saved_fids={len(saved_fids)} 与计划数={len(plan)} 不一致，将仅对齐前 {min(len(saved_fids), len(plan))} 项")
        if saved_fids:
            self.transfer_count += len(saved_fids)
        return saved_fids

    def _sync_share_dir(
        self,
        *,
        pwd_id: str,
        stoken: str,
        share_dir_fid: str,
        share_dir_name: str,
        dest_dir_fid: str,
        dest_dir_name: str,
        ignore_extension: bool,
        tree: Tree,
        parent_node: str,
        depth: int,
    ) -> None:
        if depth > 3:
            return
        share_items = self._fetch_share_items(pwd_id=pwd_id, stoken=stoken, pdir_fid=share_dir_fid)
        dest_dir_map = self._list_dest_dir_map(dest_dir_fid)
        dest_file_names = self._list_dest_names(dest_dir_fid, ignore_extension)

        for raw in natsorted(share_items, key=lambda x: _get_name(x)):
            name = _get_name(raw)
            fid = _get_fid(raw)
            if not name or not fid:
                continue
            if _is_dir(raw):
                existing_dest_fid = dest_dir_map.get(name)
                if existing_dest_fid:
                    node_id = f"dir-{dest_dir_name}-{fid}"
                    tree.create_node(f"📁{name}", node_id, parent=parent_node)
                    self._sync_share_dir(
                        pwd_id=pwd_id,
                        stoken=stoken,
                        share_dir_fid=fid,
                        share_dir_name=name,
                        dest_dir_fid=existing_dest_fid,
                        dest_dir_name=name,
                        ignore_extension=ignore_extension,
                        tree=tree,
                        parent_node=node_id,
                        depth=depth + 1,
                    )
                    continue
                self._save_items(pwd_id=pwd_id, stoken=stoken, to_pdir_fid=dest_dir_fid, items=[raw])
                tree.create_node(f"📁{name}", f"dir-new-{dest_dir_name}-{fid}", parent=parent_node)
                continue
            if _normalize_name(name, ignore_extension) in dest_file_names:
                continue
            self._save_items(pwd_id=pwd_id, stoken=stoken, to_pdir_fid=dest_dir_fid, items=[raw])
            tree.create_node(f"{name} -> {name}", f"file-{dest_dir_name}-{fid}", parent=parent_node)

    def _iter_files(self, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for raw in items:
            if _is_dir(raw):
                continue
            fid = _get_fid(raw)
            name = _get_name(raw)
            if not fid or not name:
                continue
            result.append(raw)
        return result

    def _plan_transfer(self, *, share_files: list[dict[str, Any]], dest_file_list: list[dict[str, Any]]) -> list[DramaPlanItem]:
        taskname = str(self.task_data.get("taskname") or "")
        pattern = str(self.task_data.get("pattern") or "")
        replace = str(self.task_data.get("replace") or "")
        ignore_extension = bool(self.task_data.get("ignore_extension"))
        update_subdir = str(self.task_data.get("update_subdir") or "").strip()
        startfid = str(self.task_data.get("startfid") or "").strip()
        try:
            start_index = int(self.task_data.get("sort_index") or 1)
        except (TypeError, ValueError):
            start_index = 1

        mr = MagicRename(magic_regex=(self.task_data.get("magic_regex") if isinstance(self.task_data.get("magic_regex"), dict) else None))
        mr.set_taskname(taskname)
        pattern, replace = mr.magic_regex_conv(pattern, replace)
        compiled_search = re.compile(pattern) if pattern else None
        compiled_subdir = re.compile(update_subdir) if update_subdir else None
        disable_guessit_fallback = bool(self.task_data.get("disable_guessit_tmdb_fallback_rename") or False)
        tmdb_series_title = str(self.task_data.get("tmdb_series_title") or "").strip() or None
        tmdb_tv_seasons = self.task_data.get("tmdb_tv_seasons") if isinstance(self.task_data.get("tmdb_tv_seasons"), list) else None
        tmdb_year = int(self.task_data.get("tmdb_year")) if isinstance(self.task_data.get("tmdb_year"), int) else None
        tmdb_media_type = str(self.task_data.get("tmdb_media_type") or "").strip().lower()

        def _to_ts(v):
            try:
                return float(v)
            except Exception:
                return None

        start_ts = None
        fid_keep = None
        if startfid:
            start_item = next((f for f in share_files if str(_get_fid(f)).strip() == startfid), None)
            if start_item:
                start_ts = _to_ts(_get_updated_at(start_item))
                if start_ts is None:
                    sorted_list = sorted(share_files, key=lambda x: _to_ts(_get_updated_at(x)) or 0, reverse=True)
                    kept: list[str] = []
                    for f in sorted_list:
                        fid = str(_get_fid(f)).strip()
                        if fid == startfid:
                            break
                        if fid:
                            kept.append(fid)
                    fid_keep = set(kept)

        dest_filename_list = []
        for raw in dest_file_list:
            if _is_dir(raw):
                continue
            name = _get_name(raw)
            if name:
                dest_filename_list.append(name)

        candidates: list[dict[str, Any]] = []
        for raw in share_files:
            fid = _get_fid(raw)
            origin_name = _get_name(raw)
            fid_token = _get_fid_token(raw)
            updated_at = _get_updated_at(raw)
            if not fid or not origin_name:
                continue
            if startfid:
                if start_ts is not None:
                    if (_to_ts(updated_at) or 0) <= start_ts:
                        continue
                elif fid_keep is not None and fid not in fid_keep:
                    continue
            search_re = compiled_subdir if (compiled_subdir and _is_dir(raw)) else compiled_search
            if search_re and not search_re.search(origin_name):
                continue
            file_name_re = origin_name
            if not _is_dir(raw):
                if (not disable_guessit_fallback) and (not pattern.strip()) and (not replace.strip()) and bool(tmdb_series_title):
                    try:
                        from app.extensions.runtime.guessit_fallback import guessit_media_target

                        target = guessit_media_target(
                                origin_name,
                                media_type=tmdb_media_type,
                                tmdb_title=tmdb_series_title,
                                tmdb_year=tmdb_year,
                                tv_seasons=tmdb_tv_seasons,
                                tv_rename_template=str(self.task_data.get("guessit_tmdb_tv_rename_template") or "").strip() or None,
                                movie_rename_template=str(self.task_data.get("guessit_tmdb_movie_rename_template") or "").strip() or None,
                                trace_tag="drama_plan",
                            )
                        if not target:
                            continue
                        file_name_re = target
                    except Exception:
                        continue
                else:
                    file_name_re = mr.sub(pattern, replace, origin_name)
            if mr.is_exists(file_name_re, dest_filename_list, ignore_extension and not _is_dir(raw)):
                continue
            candidates.append(
                {
                    "fid": fid,
                    "fid_token": fid_token,
                    "file_name": origin_name,
                    "file_name_re": file_name_re,
                    "updated_at": updated_at,
                    "size": raw.get("size"),
                    "dir": False,
                }
            )

        def _to_size(v):
            try:
                return int(v)
            except Exception:
                return None

        best: dict[str, tuple[tuple[float, float], int]] = {}
        for idx, f in enumerate(candidates):
            target = str(f.get("file_name_re") or "")
            if not target:
                continue
            key = os.path.splitext(target)[0] if ignore_extension else target
            sz = _to_size(f.get("size"))
            ts = _to_ts(f.get("updated_at"))
            score = (float(sz) if sz is not None else float("-inf"), ts if ts is not None else float("-inf"))
            prev = best.get(key)
            if prev is None or score > prev[0] or (score == prev[0] and idx > prev[1]):
                best[key] = (score, idx)
        keep_idx = set(v[1] for v in best.values())
        candidates = [f for idx, f in enumerate(candidates) if idx in keep_idx]

        if re.search(r"\{I+\}", replace or ""):
            dest_for_index = [{"file_name": _get_name(raw), "dir": _is_dir(raw)} for raw in dest_file_list if _get_name(raw)]
            mr.set_dir_file_list(dest_for_index, replace, start_index=start_index)
            mr.sort_file_list(candidates, start_index=start_index)

        plan: list[DramaPlanItem] = []
        for f in candidates:
            plan.append(
                DramaPlanItem(
                    fid=str(f["fid"]),
                    fid_token=(str(f.get("fid_token")) if f.get("fid_token") is not None else None),
                    origin_name=str(f["file_name"]),
                    target_name=str(f["file_name_re"]),
                )
            )
        return plan

    def _rename_one(self, *, fid: str, origin: str, target: str) -> bool:
        fid = str(fid or "").strip()
        origin = str(origin or "")
        target = str(target or "")
        if not fid or not origin or not target or origin == target:
            return True
        try:
            self._retry(
                action="rename",
                fn=lambda: self.adapter.rename(fid, target),
                validate=lambda r: _validate_code_status("rename", r),
            )
            return True
        except Exception as exc:
            self._line(f"FAIL: 重命名失败 {origin} → {target} err={str(exc).strip() or type(exc).__name__}")
            return False

    def _rename_by_fids(self, *, saved_fids: list[str], plan: list[DramaPlanItem], dest_root_fid: str) -> None:
        dest_root_fid = str(dest_root_fid or "").strip()
        attempted: list[tuple[str, str, str]] = []
        failed: set[str] = set()

        limit = min(len(saved_fids), len(plan))
        for i in range(limit):
            fid = str(saved_fids[i] or "").strip()
            if not fid:
                continue
            origin = str(plan[i].origin_name or "")
            target = str(plan[i].target_name or "")
            if not origin or not target or origin == target:
                continue
            attempted.append((fid, origin, target))
            self._line(f"重命名：{origin} → {target}")
            if not self._rename_one(fid=fid, origin=origin, target=target):
                failed.add(fid)

        if not attempted or not dest_root_fid:
            return

        fid_name: dict[str, str] = {}
        try:
            listing = self._ls_dir(dest_root_fid)
            items = (((listing or {}).get("data") or {}).get("list")) or []
            for raw in items:
                if _is_dir(raw):
                    continue
                fid = str(_get_fid(raw) or "").strip()
                if not fid:
                    continue
                fid_name[fid] = str(_get_name(raw) or "")
        except Exception as exc:
            self._line(f"INFO: 重命名校验失败，无法读取目标目录 err={str(exc).strip() or type(exc).__name__}")
            fid_name = {}

        need_retry: list[tuple[str, str, str]] = []
        for fid, origin, target in attempted:
            current = fid_name.get(fid)
            if current == target:
                continue
            need_retry.append((fid, origin, target))

        retry_success = 0
        retry_failed = 0
        if need_retry:
            self._line(f"二次校验：待重试 {len(need_retry)}/{len(attempted)}")
            for fid, origin, target in need_retry:
                self._line(f"重试重命名：{origin} → {target}")
                if self._rename_one(fid=fid, origin=origin, target=target):
                    retry_success += 1
                else:
                    retry_failed += 1

        final_ok = 0
        final_failed = 0
        try:
            listing = self._ls_dir(dest_root_fid)
            items = (((listing or {}).get("data") or {}).get("list")) or []
            fid_name = {}
            for raw in items:
                if _is_dir(raw):
                    continue
                fid = str(_get_fid(raw) or "").strip()
                if not fid:
                    continue
                fid_name[fid] = str(_get_name(raw) or "")
            for fid, _origin, target in attempted:
                if fid_name.get(fid) == target:
                    final_ok += 1
                else:
                    final_failed += 1
        except Exception:
            final_ok = len(attempted) - len(failed)
            final_failed = len(failed)

        self._line(
            f"重命名摘要: total={len(attempted)} ok={final_ok} failed={final_failed} retry_ok={retry_success} retry_failed={retry_failed}"
        )



    def execute(self) -> Tree:
        extra = self.task_data.get("extra") or {}
        allow_once = bool(extra.get("allow_once"))
        runweek_mode = str(extra.get("runweek_mode") or "manual").strip().lower()
        runweek = extra.get("runweek") or []
        enddate = _parse_enddate(self.task_data.get("enddate"))
        now = datetime.now()
        self._set_stage("validate_schedule")
        self._section("验证调度条件")
        self._line(f"执行时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        if enddate and now.date() > enddate:
            self._line(f"跳过: 已超过截止日期 {enddate.isoformat()}")
            raise SkipTask("已超过截止日期")
        if allow_once:
            self._line("运行一次: 忽略按星期运行限制")
        elif runweek_mode == "auto":
            tmdb_id = int(self.task_data.get("tmdb_id") or 0)
            tmdb_media_type = str(self.task_data.get("tmdb_media_type") or "").strip().lower()
            if tmdb_id <= 0 or tmdb_media_type != "tv":
                self._line("跳过: 自动识别运行星期需要绑定 TMDB TV")
                raise SkipTask("未绑定 TMDB TV")
            if not bool(self.task_data.get("tmdb_configured")):
                self._line("跳过: TMDB 未配置，无法自动识别运行星期")
                raise SkipTask("TMDB 未配置")
            days = self.task_data.get("tmdb_episode_weekdays") or self.task_data.get("tmdb_update_weekdays") or []
            try:
                week = set(int(x) for x in (days or []))
            except Exception:
                week = set()
            week = {int(x) for x in week if 1 <= int(x) <= 7}
            if not week:
                self._line("跳过: 无法自动识别运行星期")
                raise SkipTask("无法自动识别运行星期")
            if now.isoweekday() not in week:
                self._line(f"跳过: 星期 {now.isoweekday()} 不在 {sorted(list(week))}")
                raise SkipTask("不在允许运行的星期范围内")
        else:
            if not runweek:
                self._line("未配置运行星期: 默认允许运行")
            else:
                try:
                    week = set(int(x) for x in runweek)
                except Exception:
                    week = set()
                week = {int(x) for x in week if 1 <= int(x) <= 7}
                if not week:
                    self._line("跳过: 未配置运行星期")
                    raise SkipTask("未配置运行星期")
                if now.isoweekday() not in week:
                    self._line(f"跳过: 星期 {now.isoweekday()} 不在 {sorted(list(week))}")
                    raise SkipTask("不在允许运行的星期范围内")

        self._set_stage("share_parse")
        self._section("解析分享链接")
        pwd_id, passcode, extracted_pdir_fid, _ = self.adapter.extract_url(self.task_data.get("shareurl") or "")
        if not pwd_id:
            raise bad_request("TASK_SHAREURL_INVALID", "无法解析分享链接")
        self._line(f"pwd_id: {pwd_id}")
        self._line(f"pdir_fid: {extracted_pdir_fid or ''}")

        self._set_stage("get_stoken")
        self._section("获取分享 token")
        def _validate_stoken(resp: dict[str, Any]) -> RetryResult:
            st = ((resp or {}).get("data") or {}).get("stoken")
            if st:
                return RetryResult(value=resp, ok=True)
            msg = (resp or {}).get("message") or "获取分享 token 失败"
            return RetryResult(value=resp, ok=False, error_message=f"{msg} resp={summarize_payload(resp)}")

        token_response = self._retry(action="get_stoken", fn=lambda: self.adapter.get_stoken(pwd_id, passcode or ""), validate=_validate_stoken)
        stoken = ((token_response or {}).get("data") or {}).get("stoken")
        if not stoken:
            message = (token_response or {}).get("message") or "获取分享 token 失败"
            raise RuntimeError(str(message))
        self._line("OK: stoken 获取成功")

        pdir_fid = str(extracted_pdir_fid or "")

        savepath = str(self.task_data.get("savepath") or "").rstrip("/")
        self._set_stage("ensure_dest_dir")
        self._section("准备保存目录")
        self._line(f"保存路径: {savepath}")
        dest_root_fid = self._ensure_dest_dir_fid(savepath)
        self._line(f"目标目录 fid: {dest_root_fid}")
        try:
            normalized_savepath = re.sub(r"/{2,}", "/", f"/{savepath}")
            if not hasattr(self.adapter, "savepath_fid") or not isinstance(getattr(self.adapter, "savepath_fid"), dict):
                setattr(self.adapter, "savepath_fid", {"/": "0"})
            self.adapter.savepath_fid[normalized_savepath] = str(dest_root_fid)
            if str(savepath).strip() and savepath != normalized_savepath:
                self.adapter.savepath_fid[str(savepath)] = str(dest_root_fid)
        except Exception:
            pass
        ignore_extension = bool(self.task_data.get("ignore_extension"))
        dest_listing = self._ls_dir(dest_root_fid)
        dest_file_list = (((dest_listing or {}).get("data") or {}).get("list")) or []
        dest_dir_map = {}
        dest_names = set()
        for raw in dest_file_list:
            name = _get_name(raw)
            if not name:
                continue
            if _is_dir(raw):
                fid = _get_fid(raw)
                if fid:
                    dest_dir_map[name] = fid
                continue
            dest_names.add(_normalize_name(name, ignore_extension))

        self._set_stage("fetch_share_items")
        self._section("读取分享列表")
        share_items = self._fetch_share_items(pwd_id=str(pwd_id), stoken=str(stoken), pdir_fid=pdir_fid)
        self._line(f"分享列表项数: {len(share_items)}")

        tree = Tree()
        tree.create_node(str(self.task_data.get("taskname") or ""), "root")

        update_subdir = (self.task_data.get("update_subdir") or "").strip()
        mode = str((extra.get("update_subdir_resave_mode") or "none")).strip()
        compiled_subdir = re.compile(update_subdir) if update_subdir else None

        root_files = [raw for raw in share_items if not _is_dir(raw)]
        self._set_stage("plan_transfer")
        self._section("生成转存计划")
        plan = self._plan_transfer(share_files=self._iter_files(root_files), dest_file_list=dest_file_list)
        self._line(f"待转存文件数: {len(plan)}")
        if plan:
            self._set_stage("save_file")
            self._section("执行转存")
            saved_fids = self._save_with_saved_fids(pwd_id=str(pwd_id), stoken=str(stoken), dest_root_fid=dest_root_fid, plan=plan)
            self._set_stage("rename")
            self._section("重命名")
            self._rename_by_fids(saved_fids=saved_fids, plan=plan, dest_root_fid=dest_root_fid)
            limit = min(len(plan), len(saved_fids))
            for i in range(limit):
                item = plan[i]
                saved_fid = str(saved_fids[i] or "").strip()
                data = {
                    "fid": saved_fid,
                    "file_name": item.origin_name,
                    "file_name_re": item.target_name,
                    "is_dir": False,
                }
                tree.create_node(f"{i + 1}. {item.origin_name} -> {item.target_name}", f"item-{i + 1}", parent="root", data=data)

        if compiled_subdir:
            self._set_stage("subdir_sync")
            self._section("子目录转存")
            startfid = str(self.task_data.get("startfid") or "").strip()
            start_ts = None
            fid_keep = None
            if startfid:
                def _to_ts(v):
                    try:
                        return float(v)
                    except Exception:
                        return None

                start_item = next((f for f in share_items if str(_get_fid(f)).strip() == startfid), None)
                if start_item:
                    start_ts = _to_ts(_get_updated_at(start_item))
                    if start_ts is None:
                        sorted_list = sorted(share_items, key=lambda x: _to_ts(_get_updated_at(x)) or 0, reverse=True)
                        kept: list[str] = []
                        for f in sorted_list:
                            fid = str(_get_fid(f)).strip()
                            if fid == startfid:
                                break
                            if fid:
                                kept.append(fid)
                        fid_keep = set(kept)
            for raw in natsorted(share_items, key=lambda x: _get_name(x)):
                if not _is_dir(raw):
                    continue
                name = _get_name(raw)
                fid = _get_fid(raw)
                if not name or not fid:
                    continue
                if startfid:
                    if start_ts is not None:
                        if (_to_ts(_get_updated_at(raw)) or 0) <= start_ts:
                            continue
                    elif fid_keep is not None and str(fid).strip() not in fid_keep:
                        continue
                if not compiled_subdir.search(name):
                    continue
                if mode == "delete_then_resave":
                    existing_dest_fid = dest_dir_map.get(name)
                    if existing_dest_fid:
                        self.adapter.delete([existing_dest_fid])
                    self._save_items(pwd_id=str(pwd_id), stoken=str(stoken), to_pdir_fid=dest_root_fid, items=[raw])
                    tree.create_node(f"📁{name}（重存）", f"dir-resave-{fid}", parent="root")
                    continue
                existing_dest_fid = dest_dir_map.get(name)
                if existing_dest_fid:
                    node_id = f"dir-sync-{fid}"
                    tree.create_node(f"📁{name}（检查）", node_id, parent="root")
                    self._sync_share_dir(
                        pwd_id=str(pwd_id),
                        stoken=str(stoken),
                        share_dir_fid=fid,
                        share_dir_name=name,
                        dest_dir_fid=existing_dest_fid,
                        dest_dir_name=name,
                        ignore_extension=ignore_extension,
                        tree=tree,
                        parent_node=node_id,
                        depth=0,
                    )
                    continue
                self._save_items(pwd_id=str(pwd_id), stoken=str(stoken), to_pdir_fid=dest_root_fid, items=[raw])
                tree.create_node(f"📁{name}", f"dir-new-{fid}", parent="root")

        if tree.size() <= 1:
            tree.create_node("无可转存文件", "empty", parent="root")
            self._line("无可转存文件")
        self._set_stage("end")
        return tree
